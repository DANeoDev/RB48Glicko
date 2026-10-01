from datetime import datetime, timezone
from scripts.finances.database import (
    get_finances_connection,
    add_payment_allocation,
    get_allocations_for_match_date,
    get_allocations_for_period,
    get_allocations_for_player,
    get_transaction_by_id,
    update_transaction_assignment,
    save_or_update_identity,
    get_all_player_membership_statuses,
    get_player_membership_status,
    set_player_membership_status,
)
from scripts.database.database import get_connection as get_rb48_connection
from scripts.database.db_players import get_players
from scripts.accounts.database import get_accounts_connection
from scripts.finances.matcher import parse_guest_hints_from_note, normalize_text, find_player_match


GUEST_FEE_PER_KICK = 3.50
MEMBERSHIP_DUE_PER_HALFYEAR = 48.00


def resolve_player_membership_status(
    player_id: int,
    finances_conn=None,
    accounts_conn=None,
    explicit_statuses=None,
    linked_player_ids=None,
) -> str:
    """
    Determine if a player is 'member' or 'guest'.
    Rule:
    1. If explicitly set in `player_membership_status`, use that.
    2. Else if player is linked to an approved user account, default to 'member'.
    3. Else default to 'guest'.
    """
    if explicit_statuses is not None:
        if player_id in explicit_statuses:
            return explicit_statuses[player_id]
    elif finances_conn:
        exp = get_player_membership_status(finances_conn, player_id, default=None)
        if exp:
            return exp

    if linked_player_ids is not None:
        if player_id in linked_player_ids:
            return "member"
    elif accounts_conn:
        row = accounts_conn.execute(
            "SELECT 1 FROM users WHERE player_id = ?", (player_id,)
        ).fetchone()
        if row:
            return "member"

    return "guest"


def get_all_players_with_membership(
    finances_conn=None,
    rb48_conn=None,
    accounts_conn=None,
) -> list[dict]:
    """
    Get all players with their aliases, linked user accounts, and membership status ('member' | 'guest').
    """
    close_fin = False
    close_rb = False
    close_acc = False

    if finances_conn is None:
        finances_conn = get_finances_connection()
        close_fin = True
    if rb48_conn is None:
        rb48_conn = get_rb48_connection()
        close_rb = True
    if accounts_conn is None:
        accounts_conn = get_accounts_connection()
        close_acc = True

    try:
        players_dict = get_players(rb48_conn)
        explicit_statuses = get_all_player_membership_statuses(finances_conn)

        user_rows = accounts_conn.execute(
            "SELECT id, username, email, player_id, attendance_name FROM users WHERE player_id IS NOT NULL"
        ).fetchall()
        users_by_player_id = {u["player_id"]: dict(u) for u in user_rows}
        linked_player_ids = set(users_by_player_id.keys())

        result = []
        for pid, pdata in players_dict.items():
            primary_alias = pdata["aliases"][0] if pdata["aliases"] else f"Player #{pid}"
            all_aliases = ", ".join(pdata["aliases"])
            linked_user = users_by_player_id.get(pid)
            has_explicit = pid in explicit_statuses

            status = resolve_player_membership_status(
                pid,
                explicit_statuses=explicit_statuses,
                linked_player_ids=linked_player_ids,
            )

            result.append({
                "player_id": pid,
                "name": primary_alias,
                "aliases_str": all_aliases,
                "linked_user": linked_user,
                "status": status,
                "has_explicit": has_explicit,
            })

        result.sort(key=lambda x: (0 if x["status"] == "member" else 1, x["name"].lower()))
        return result
    finally:
        if close_fin:
            finances_conn.close()
        if close_rb:
            rb48_conn.close()
        if close_acc:
            accounts_conn.close()


def get_match_history_financial_overview() -> list[dict]:
    """
    Return all distinct match dates from Match History (`rb48.db`) with guest fee metrics.
    """
    rb48_conn = get_rb48_connection()
    finances_conn = get_finances_connection()
    accounts_conn = get_accounts_connection()

    try:
        # Query distinct match dates
        date_rows = rb48_conn.execute(
            """
            SELECT date, COUNT(DISTINCT match_id) as match_count, COUNT(DISTINCT player_id) as total_players
            FROM matches
            JOIN match_players USING(match_id)
            GROUP BY date
            ORDER BY date DESC
            """
        ).fetchall()

        explicit_statuses = get_all_player_membership_statuses(finances_conn)
        user_rows = accounts_conn.execute(
            "SELECT player_id FROM users WHERE player_id IS NOT NULL"
        ).fetchall()
        linked_player_ids = {u["player_id"] for u in user_rows}

        results = []
        for drow in date_rows:
            mdate = drow["date"]

            # Fetch distinct players for this date
            prows = rb48_conn.execute(
                """
                SELECT DISTINCT player_id
                FROM matches
                JOIN match_players USING(match_id)
                WHERE date = ?
                """,
                (mdate,),
            ).fetchall()

            guest_pids = [
                r["player_id"]
                for r in prows
                if resolve_player_membership_status(
                    r["player_id"],
                    explicit_statuses=explicit_statuses,
                    linked_player_ids=linked_player_ids,
                ) == "guest"
            ]

            guest_count = len(guest_pids)
            allocations = get_allocations_for_match_date(finances_conn, mdate)

            paid_pids = {
                a["player_id"]
                for a in allocations
                if a.get("player_id") and (a["payment_method"] == "waived" or a["allocated_amount"] >= GUEST_FEE_PER_KICK)
            }

            paid_count = len(set(guest_pids).intersection(paid_pids))
            unpaid_count = max(0, guest_count - paid_count)
            total_expected = guest_count * GUEST_FEE_PER_KICK
            total_collected = sum(
                a["allocated_amount"]
                for a in allocations
                if a.get("player_id") in guest_pids and a["payment_method"] != "waived"
            )

            results.append({
                "match_date": mdate,
                "match_count": drow["match_count"],
                "total_players": drow["total_players"],
                "guest_count": guest_count,
                "paid_count": paid_count,
                "unpaid_count": unpaid_count,
                "total_expected": total_expected,
                "total_collected": total_collected,
                "outstanding": max(0.0, total_expected - total_collected),
            })

        return results
    finally:
        rb48_conn.close()
        finances_conn.close()
        accounts_conn.close()


def get_all_unpaid_guest_entries() -> list[dict]:
    """
    Return all unpaid guest fee entries across all match dates.
    Each item contains: name, match_date, fee_required, amount_paid, payment_status, player_id.
    Ordered by match_date DESC, name ASC.
    """
    overview = get_match_history_financial_overview()
    unpaid_matches = [m for m in overview if m.get("unpaid_count", 0) > 0]
    all_unpaid = []
    for m in unpaid_matches:
        details = get_match_date_guest_status(m["match_date"])
        for g in details.get("guest_entries", []):
            if g.get("payment_status") in ("unpaid", "partial"):
                all_unpaid.append({
                    "name": g["name"],
                    "match_date": m["match_date"],
                    "fee_required": g["fee_required"],
                    "amount_paid": g["amount_paid"],
                    "payment_status": g["payment_status"],
                    "player_id": g["player_id"],
                })
    return all_unpaid


def get_match_date_guest_status(match_date: str) -> dict:
    """
    Get financial breakdown for all players on a specific match date from Match History.
    """
    rb48_conn = get_rb48_connection()
    finances_conn = get_finances_connection()
    accounts_conn = get_accounts_connection()

    try:
        players_dict = get_players(rb48_conn)
        explicit_statuses = get_all_player_membership_statuses(finances_conn)
        user_rows = accounts_conn.execute(
            "SELECT player_id, username, attendance_name FROM users WHERE player_id IS NOT NULL"
        ).fetchall()
        users_by_player_id = {u["player_id"]: dict(u) for u in user_rows}
        linked_player_ids = set(users_by_player_id.keys())

        prows = rb48_conn.execute(
            """
            SELECT DISTINCT player_id
            FROM matches
            JOIN match_players USING(match_id)
            WHERE date = ?
            ORDER BY player_id ASC
            """,
            (match_date,),
        ).fetchall()

        allocations = get_allocations_for_match_date(finances_conn, match_date)
        alloc_by_player: dict[int, list[dict]] = {}
        for a in allocations:
            pid = a.get("player_id")
            if pid:
                alloc_by_player.setdefault(pid, []).append(a)

        guest_entries = []
        member_entries = []
        total_guest_fees_expected = 0.0
        total_guest_fees_collected = 0.0

        for r in prows:
            pid = r["player_id"]
            pdata = players_dict.get(pid, {})
            name = pdata.get("aliases", [f"Player #{pid}"])[0]
            status = resolve_player_membership_status(
                pid,
                explicit_statuses=explicit_statuses,
                linked_player_ids=linked_player_ids,
            )

            p_allocs = alloc_by_player.get(pid, [])
            paid_sum = sum(a["allocated_amount"] for a in p_allocs if a["payment_method"] != "waived")
            is_waived = any(a["payment_method"] == "waived" for a in p_allocs)

            if status == "guest":
                total_guest_fees_expected += GUEST_FEE_PER_KICK
                total_guest_fees_collected += paid_sum

                if is_waived:
                    payment_status = "waived"
                elif paid_sum >= GUEST_FEE_PER_KICK:
                    pmethods = {a["payment_method"] for a in p_allocs}
                    if "cash" in pmethods and "paypal" not in pmethods:
                        payment_status = "cash"
                    elif "bank" in pmethods and "paypal" not in pmethods:
                        payment_status = "bank"
                    else:
                        payment_status = "paid"
                elif paid_sum > 0:
                    payment_status = "partial"
                else:
                    payment_status = "unpaid"

                # Check if someone else paid for this guest (proxy payment)
                paid_by_name = None
                paid_by_pid = None
                for a in p_allocs:
                    if a.get("paid_by_player_id") and a["paid_by_player_id"] != pid:
                        paid_by_pid = a["paid_by_player_id"]
                        pb_pdata = players_dict.get(paid_by_pid, {})
                        paid_by_name = pb_pdata.get("aliases", [f"Player #{paid_by_pid}"])[0]
                        break

                guest_entries.append({
                    "player_id": pid,
                    "name": name,
                    "aliases_str": ", ".join(pdata.get("aliases", [])),
                    "status": status,
                    "fee_required": GUEST_FEE_PER_KICK,
                    "amount_paid": paid_sum,
                    "payment_status": payment_status,
                    "allocations": p_allocs,
                    "paid_by_name": paid_by_name,
                    "paid_by_player_id": paid_by_pid,
                })
            else:
                member_entries.append({
                    "player_id": pid,
                    "name": name,
                    "aliases_str": ", ".join(pdata.get("aliases", [])),
                    "status": status,
                })

        return {
            "match_date": match_date,
            "guest_entries": guest_entries,
            "member_entries": member_entries,
            "total_guests": len(guest_entries),
            "total_members": len(member_entries),
            "total_expected": total_guest_fees_expected,
            "total_collected": total_guest_fees_collected,
            "outstanding": max(0.0, total_guest_fees_expected - total_guest_fees_collected),
        }
    finally:
        rb48_conn.close()
        finances_conn.close()
        accounts_conn.close()


def find_unconfirmed_transaction_for_player(
    finances_conn,
    player_id: int,
    match_date: str | None = None,
    amount: float = GUEST_FEE_PER_KICK,
) -> dict | None:
    """Find an unconfirmed imported transaction matching a player or their aliases/email."""
    # 1. Exact matched_player_id
    row = finances_conn.execute(
        """
        SELECT * FROM finance_transactions
        WHERE matched_player_id = ? AND status = 'imported' AND is_confirmed = 0 AND amount >= ?
        ORDER BY ABS(julianday(date) - julianday(?)) ASC, id DESC
        LIMIT 1
        """,
        (player_id, amount, match_date or "now"),
    ).fetchone()
    if row:
        return dict(row)

    # 2. Check unassigned transactions where find_player_match suggests this player
    unmatched_rows = finances_conn.execute(
        """
        SELECT * FROM finance_transactions
        WHERE matched_player_id IS NULL AND status = 'imported' AND is_confirmed = 0 AND amount >= ?
        ORDER BY ABS(julianday(date) - julianday(?)) ASC, id DESC
        """,
        (amount, match_date or "now"),
    ).fetchall()

    if not unmatched_rows:
        return None

    rb48_conn = get_rb48_connection()
    acc_conn = get_accounts_connection()
    try:
        for r in unmatched_rows:
            match = find_player_match(
                r["raw_payer_name"],
                r["raw_payer_email"],
                finances_conn=finances_conn,
                rb48_conn=rb48_conn,
                accounts_conn=acc_conn,
            )
            if match and match.get("player_id") == player_id and match.get("confidence", 0) >= 0.70:
                return dict(r)
    finally:
        rb48_conn.close()
        acc_conn.close()

    return None


def manual_mark_match_guest_payment(
    match_date: str,
    player_id: int,
    payment_method: str,
    note: str | None = None,
    amount: float = GUEST_FEE_PER_KICK,
) -> int:
    """
    Manually mark a player's guest fee for a match date as cash, paypal direct, waived, or unpaid.
    Automatically links to an unconfirmed imported transaction (e.g. PayPal) if available.
    """
    finances_conn = get_finances_connection()
    try:
        # Find any existing allocation for this match date and player
        existing_allocs = finances_conn.execute(
            """
            SELECT * FROM payment_allocations
            WHERE match_date = ? AND player_id = ? AND fee_type = 'match_guest'
            """,
            (match_date, player_id),
        ).fetchall()

        # If payment_method is "unpaid", reset any linked transactions back to 'imported' and delete allocations
        if payment_method == "unpaid":
            for ea in existing_allocs:
                if ea["transaction_id"]:
                    finances_conn.execute(
                        "UPDATE finance_transactions SET status = 'imported', is_confirmed = 0 WHERE id = ?",
                        (ea["transaction_id"],),
                    )
            finances_conn.execute(
                """
                DELETE FROM payment_allocations
                WHERE match_date = ? AND player_id = ? AND fee_type = 'match_guest'
                """,
                (match_date, player_id),
            )
            finances_conn.commit()
            return 0

        # Delete prior manual allocations (without transaction_id)
        finances_conn.execute(
            """
            DELETE FROM payment_allocations
            WHERE match_date = ? AND player_id = ? AND transaction_id IS NULL AND fee_type = 'match_guest'
            """,
            (match_date, player_id),
        )
        finances_conn.commit()

        # Check if an allocation with transaction_id already existed
        linked_tx_id = None
        for ea in existing_allocs:
            if ea["transaction_id"]:
                linked_tx_id = ea["transaction_id"]
                break

        # If no linked transaction yet and method is paypal or bank, auto-link matching imported transaction
        if not linked_tx_id and payment_method in ("paypal", "bank"):
            cand = find_unconfirmed_transaction_for_player(finances_conn, player_id, match_date, amount=amount)
            if cand:
                linked_tx_id = cand["id"]
                update_transaction_assignment(
                    finances_conn,
                    linked_tx_id,
                    player_id=player_id,
                    status="assigned",
                    is_confirmed=1,
                )

        alloc_amount = 0.0 if payment_method == "waived" else amount
        return add_payment_allocation(
            finances_conn,
            fee_type="match_guest",
            allocated_amount=alloc_amount,
            payment_method=payment_method,
            transaction_id=linked_tx_id,
            match_date=match_date,
            player_id=player_id,
            note=note or f"Erfassung ({payment_method})",
        )
    finally:
        finances_conn.close()


def get_membership_dues_overview(period: str = "2026-H2") -> dict:
    """
    Get membership dues breakdown (48 € / Half-year) for all club members.
    """
    finances_conn = get_finances_connection()
    try:
        players = get_all_players_with_membership()
        members = [p for p in players if p["status"] == "member"]

        is_full_year = len(str(period)) == 4 and str(period).isdigit()
        fee_required_per_member = (2 * MEMBERSHIP_DUE_PER_HALFYEAR) if is_full_year else MEMBERSHIP_DUE_PER_HALFYEAR

        if is_full_year:
            target_periods = [f"{period}-H1", f"{period}-H2"]
            allocations = []
            for tp in target_periods:
                allocations.extend(get_allocations_for_period(finances_conn, tp))
        elif period == "all":
            cursor = finances_conn.execute(
                "SELECT * FROM payment_allocations WHERE fee_type = 'membership_due' ORDER BY id ASC"
            )
            allocations = [dict(row) for row in cursor.fetchall()]
        else:
            allocations = get_allocations_for_period(finances_conn, period)

        alloc_by_player: dict[int, list[dict]] = {}
        for a in allocations:
            pid = a.get("player_id")
            if pid:
                alloc_by_player.setdefault(pid, []).append(a)

        member_dues_list = []
        total_expected = len(members) * fee_required_per_member
        total_collected = 0.0

        for m in members:
            pid = m["player_id"]
            p_allocs = alloc_by_player.get(pid, [])
            paid_sum = sum(a["allocated_amount"] for a in p_allocs if a["payment_method"] != "waived")
            is_waived = any(a["payment_method"] == "waived" for a in p_allocs)

            total_collected += paid_sum

            if is_waived:
                pstatus = "waived"
            elif paid_sum >= fee_required_per_member:
                pmethods = {a["payment_method"] for a in p_allocs}
                if "bank" in pmethods:
                    pstatus = "bank"
                elif "cash" in pmethods:
                    pstatus = "cash"
                else:
                    pstatus = "paid"
            elif paid_sum > 0:
                pstatus = "partial"
            else:
                pstatus = "unpaid"

            member_dues_list.append({
                "player_id": pid,
                "name": m["name"],
                "aliases_str": m["aliases_str"],
                "linked_user": m["linked_user"],
                "fee_required": fee_required_per_member,
                "amount_paid": paid_sum,
                "payment_status": pstatus,
                "allocations": p_allocs,
            })

        return {
            "period": period,
            "members": member_dues_list,
            "total_members": len(members),
            "total_expected": total_expected,
            "total_collected": total_collected,
            "outstanding": max(0.0, total_expected - total_collected),
        }
    finally:
        finances_conn.close()


def manual_mark_membership_due(
    period: str,
    player_id: int,
    payment_method: str,
    note: str | None = None,
    amount: float = MEMBERSHIP_DUE_PER_HALFYEAR,
) -> int:
    """Manually mark membership dues for a player and period."""
    finances_conn = get_finances_connection()
    try:
        finances_conn.execute(
            """
            DELETE FROM payment_allocations
            WHERE period = ? AND player_id = ? AND transaction_id IS NULL AND fee_type = 'membership_due'
            """,
            (period, player_id),
        )
        finances_conn.commit()

        if payment_method == "unpaid":
            return 0

        alloc_amount = 0.0 if payment_method == "waived" else amount
        return add_payment_allocation(
            finances_conn,
            fee_type="membership_due",
            allocated_amount=alloc_amount,
            payment_method=payment_method,
            transaction_id=None,
            period=period,
            player_id=player_id,
            note=note or f"Mitgliedsbeitrag ({payment_method})",
        )
    finally:
        finances_conn.close()


def auto_allocate_transaction_to_debts(
    transaction_id: int,
    player_id: int,
) -> int:
    """
    Allocate a confirmed transaction amount to the player's oldest unpaid match history guest kicks
    or membership dues. Returns number of debts/kicks covered.
    """
    finances_conn = get_finances_connection()
    rb48_conn = get_rb48_connection()
    accounts_conn = get_accounts_connection()

    try:
        tx = get_transaction_by_id(finances_conn, transaction_id)
        if not tx or tx["amount"] <= 0:
            return 0

        status = resolve_player_membership_status(player_id, finances_conn, accounts_conn)
        remaining_amount = float(tx["amount"])
        covered = 0

        # If 48.00 € (membership due), check membership dues first
        if remaining_amount >= MEMBERSHIP_DUE_PER_HALFYEAR and status == "member":
            # Check 2026-H2 and 2026-H1
            for per in ("2026-H1", "2026-H2"):
                if remaining_amount < MEMBERSHIP_DUE_PER_HALFYEAR:
                    break
                allocs = get_allocations_for_period(finances_conn, per)
                p_allocs = [a for a in allocs if a.get("player_id") == player_id]
                paid_sum = sum(a["allocated_amount"] for a in p_allocs if a["payment_method"] != "waived")
                if paid_sum >= MEMBERSHIP_DUE_PER_HALFYEAR:
                    continue

                add_payment_allocation(
                    finances_conn,
                    fee_type="membership_due",
                    allocated_amount=MEMBERSHIP_DUE_PER_HALFYEAR,
                    payment_method=tx["source"],
                    transaction_id=tx["id"],
                    period=per,
                    player_id=player_id,
                    note=f"PayPal {tx['tx_code'] or ''}".strip(),
                )
                remaining_amount -= MEMBERSHIP_DUE_PER_HALFYEAR
                covered += 1

        # Check if this is a proxy payment (member paying for guests)
        if remaining_amount >= GUEST_FEE_PER_KICK and status == 'member':
            # Member paying 3.50€ multiples -> likely paying for guests
            remainder_check = remaining_amount % GUEST_FEE_PER_KICK
            is_guest_fee_multiple = remainder_check < 0.01 or (GUEST_FEE_PER_KICK - remainder_check) < 0.01
            if is_guest_fee_multiple:
                proxy_covered = auto_allocate_proxy_guest_payment(
                    transaction_id, player_id,
                )
                covered += proxy_covered
                return covered  # Proxy allocation handled the rest

        # Match history guest kicks (3.50 €) -- for self-paying guests
        match_date_rows = rb48_conn.execute(
            """
            SELECT DISTINCT date
            FROM matches
            JOIN match_players USING(match_id)
            WHERE player_id = ?
            ORDER BY date ASC
            """,
            (player_id,),
        ).fetchall()

        for drow in match_date_rows:
            if remaining_amount < GUEST_FEE_PER_KICK:
                break

            mdate = drow["date"]
            allocs = get_allocations_for_match_date(finances_conn, mdate)
            p_allocs = [a for a in allocs if a.get("player_id") == player_id]
            paid_sum = sum(a["allocated_amount"] for a in p_allocs if a["payment_method"] != "waived")
            if paid_sum >= GUEST_FEE_PER_KICK:
                continue

            add_payment_allocation(
                finances_conn,
                fee_type="match_guest",
                allocated_amount=GUEST_FEE_PER_KICK,
                payment_method=tx["source"],
                transaction_id=tx["id"],
                match_date=mdate,
                player_id=player_id,
                note=f"PayPal {tx['tx_code'] or ''}".strip(),
            )
            remaining_amount -= GUEST_FEE_PER_KICK
            covered += 1

        return covered
    finally:
        finances_conn.close()
        rb48_conn.close()
        accounts_conn.close()


def find_member_guests_for_date(
    payer_player_id: int,
    match_date: str,
    finances_conn=None,
    rb48_conn=None,
    accounts_conn=None,
) -> list[dict]:
    """Find unpaid guest players associated with a member for a given match date.
    
    Uses two strategies:
    1. Planner data: guests registered by this member (via registered_by_user_id)
    2. Match history: all guest players who played on that date with unpaid fees
    
    Returns list of dicts with player_id, name, source ('planner' or 'match_history').
    """
    from scripts.planner.database import get_planner_connection
    from scripts.database.db_players import get_players
    
    close_fin = close_rb = close_acc = False
    if finances_conn is None:
        finances_conn = get_finances_connection()
        close_fin = True
    if rb48_conn is None:
        rb48_conn = get_rb48_connection()
        close_rb = True
    if accounts_conn is None:
        accounts_conn = get_accounts_connection()
        close_acc = True
    
    try:
        players_dict = get_players(rb48_conn)
        explicit_statuses = get_all_player_membership_statuses(finances_conn)
        user_rows = accounts_conn.execute(
            "SELECT player_id FROM users WHERE player_id IS NOT NULL"
        ).fetchall()
        linked_player_ids = {u["player_id"] for u in user_rows}
        
        # Find payer's user_id
        payer_user = accounts_conn.execute(
            "SELECT id FROM users WHERE player_id = ?", (payer_player_id,)
        ).fetchone()
        payer_user_id = payer_user["id"] if payer_user else None
        
        results = []
        seen_pids = set()
        
        # Strategy 1: Planner-based guest lookup
        if payer_user_id:
            try:
                planner_conn = get_planner_connection()
                # Find events on or near this date (within ±3 days)
                events = planner_conn.execute(
                    """
                    SELECT id, event_date FROM events
                    WHERE ABS(julianday(event_date) - julianday(?)) <= 3
                    ORDER BY ABS(julianday(event_date) - julianday(?)) ASC
                    """,
                    (match_date, match_date),
                ).fetchall()
                
                for event in events:
                    guests = planner_conn.execute(
                        """
                        SELECT id, name, user_id FROM attendees
                        WHERE event_id = ? AND registered_by_user_id = ? AND is_guest = 1 AND status = 'attending'
                        ORDER BY guest_index ASC
                        """,
                        (event["id"], payer_user_id),
                    ).fetchall()
                    
                    for g in guests:
                        # Try to find the guest's player_id by matching their name against aliases
                        guest_name = g["name"]
                        # Strip the "(MemberName +N)" suffix from guest names
                        import re as _re
                        clean_guest_name = _re.sub(r'\s*\([^)]+\)\s*$', '', guest_name).strip()
                        
                        # Match guest name to player_id via aliases
                        guest_match = _find_guest_player_id(clean_guest_name, rb48_conn, players_dict)
                        if guest_match and guest_match not in seen_pids:
                            # Check this player is actually a guest and has unpaid fees
                            status = resolve_player_membership_status(
                                guest_match, explicit_statuses=explicit_statuses,
                                linked_player_ids=linked_player_ids,
                            )
                            if status == 'guest':
                                allocs = get_allocations_for_match_date(finances_conn, match_date)
                                paid = sum(
                                    a["allocated_amount"] for a in allocs
                                    if a.get("player_id") == guest_match and a["payment_method"] != "waived"
                                )
                                if paid < GUEST_FEE_PER_KICK:
                                    pdata = players_dict.get(guest_match, {})
                                    results.append({
                                        "player_id": guest_match,
                                        "name": pdata.get("aliases", [clean_guest_name])[0],
                                        "source": "planner",
                                        "attendee_id": g["id"],
                                    })
                                    seen_pids.add(guest_match)
                planner_conn.close()
            except Exception:
                pass  # Planner DB may not exist
        
        # Strategy 2: All unpaid guests who played on this match date
        prows = rb48_conn.execute(
            """
            SELECT DISTINCT player_id
            FROM matches JOIN match_players USING(match_id)
            WHERE date = ?
            """,
            (match_date,),
        ).fetchall()
        
        for r in prows:
            pid = r["player_id"]
            if pid in seen_pids or pid == payer_player_id:
                continue
            
            status = resolve_player_membership_status(
                pid, explicit_statuses=explicit_statuses,
                linked_player_ids=linked_player_ids,
            )
            if status != 'guest':
                continue
            
            allocs = get_allocations_for_match_date(finances_conn, match_date)
            paid = sum(
                a["allocated_amount"] for a in allocs
                if a.get("player_id") == pid and a["payment_method"] != "waived"
            )
            if paid < GUEST_FEE_PER_KICK:
                pdata = players_dict.get(pid, {})
                results.append({
                    "player_id": pid,
                    "name": pdata.get("aliases", [f"Player #{pid}"])[0],
                    "source": "match_history",
                })
                seen_pids.add(pid)
        
        return results
    finally:
        if close_fin:
            finances_conn.close()
        if close_rb:
            rb48_conn.close()
        if close_acc:
            accounts_conn.close()


def _find_guest_player_id(guest_name: str, rb48_conn, players_dict: dict) -> int | None:
    """Try to match a guest name string to a player_id using aliases."""
    norm_guest = normalize_text(guest_name)
    if not norm_guest:
        return None
    
    alias_rows = rb48_conn.execute("SELECT alias, player_id FROM aliases").fetchall()
    for row in alias_rows:
        if normalize_text(row["alias"]) == norm_guest:
            return row["player_id"]
    
    # Fuzzy: check if any alias is a substring or starts-with
    guest_tokens = norm_guest.split()
    for row in alias_rows:
        norm_alias = normalize_text(row["alias"])
        if not norm_alias:
            continue
        for token in guest_tokens:
            if token == norm_alias or (len(token) >= 3 and token.startswith(norm_alias)):
                return row["player_id"]
    
    return None


def auto_allocate_proxy_guest_payment(
    transaction_id: int,
    payer_player_id: int,
    guest_allocations: list[dict] | None = None,
) -> int:
    """Allocate a member's payment to guest debts.
    
    Args:
        transaction_id: The finance_transactions.id
        payer_player_id: The member who paid
        guest_allocations: Optional pre-determined list of
            [{'player_id': int, 'match_date': str, 'amount': float, 'attendee_id': int|None}]
            If None, auto-detects guests based on payment date and amount.
    
    Returns number of guest debts covered.
    """
    finances_conn = get_finances_connection()
    rb48_conn = get_rb48_connection()
    accounts_conn = get_accounts_connection()
    
    try:
        tx = get_transaction_by_id(finances_conn, transaction_id)
        if not tx or tx["amount"] <= 0:
            return 0
        
        remaining = float(tx["amount"])
        covered = 0
        
        if guest_allocations:
            # Use explicit allocations from admin
            for alloc in guest_allocations:
                amount = float(alloc.get("amount", GUEST_FEE_PER_KICK))
                if remaining < amount:
                    break
                
                add_payment_allocation(
                    finances_conn,
                    fee_type="match_guest",
                    allocated_amount=amount,
                    payment_method=tx["source"],
                    transaction_id=transaction_id,
                    match_date=alloc.get("match_date"),
                    player_id=alloc["player_id"],
                    attendee_id=alloc.get("attendee_id"),
                    paid_by_player_id=payer_player_id,
                    note=f"Stellvertreter-Zahlung von Spieler #{payer_player_id}",
                )
                remaining -= amount
                covered += 1
        else:
            # Auto-detect: find match dates near the payment date
            tx_date = tx["date"]
            num_guests = int(remaining / GUEST_FEE_PER_KICK)
            if num_guests <= 0:
                return 0
            
            # Find nearby match dates (±3 days)
            date_rows = rb48_conn.execute(
                """
                SELECT DISTINCT date
                FROM matches
                WHERE ABS(julianday(date) - julianday(?)) <= 3
                ORDER BY ABS(julianday(date) - julianday(?)) ASC
                """,
                (tx_date, tx_date),
            ).fetchall()
            
            for drow in date_rows:
                if remaining < GUEST_FEE_PER_KICK:
                    break
                
                mdate = drow["date"]
                unpaid_guests = find_member_guests_for_date(
                    payer_player_id, mdate,
                    finances_conn=finances_conn,
                    rb48_conn=rb48_conn,
                    accounts_conn=accounts_conn,
                )
                
                for guest in unpaid_guests:
                    if remaining < GUEST_FEE_PER_KICK:
                        break
                    
                    add_payment_allocation(
                        finances_conn,
                        fee_type="match_guest",
                        allocated_amount=GUEST_FEE_PER_KICK,
                        payment_method=tx["source"],
                        transaction_id=transaction_id,
                        match_date=mdate,
                        player_id=guest["player_id"],
                        attendee_id=guest.get("attendee_id"),
                        paid_by_player_id=payer_player_id,
                        note=f"Stellvertreter-Zahlung von Spieler #{payer_player_id}",
                    )
                    remaining -= GUEST_FEE_PER_KICK
                    covered += 1
        
        return covered
    finally:
        finances_conn.close()
        rb48_conn.close()
        accounts_conn.close()


def get_proxy_payment_suggestion(
    transaction_id: int,
    payer_player_id: int,
) -> dict | None:
    """Generate a smart-split suggestion for a member's guest fee payment.
    
    Returns None if this doesn't look like a proxy payment.
    Returns dict with 'suggested_guests', 'match_date', 'num_kicks', 'total' if it does.
    """
    finances_conn = get_finances_connection()
    rb48_conn = get_rb48_connection()
    accounts_conn = get_accounts_connection()
    
    try:
        tx = get_transaction_by_id(finances_conn, transaction_id)
        if not tx or tx["amount"] <= 0:
            return None
        
        amount = float(tx["amount"])
        
        # Check if amount is a multiple of guest fee
        remainder = amount % GUEST_FEE_PER_KICK
        if remainder > 0.01 and (GUEST_FEE_PER_KICK - remainder) > 0.01:
            return None  # Not a clean multiple
        
        num_kicks = round(amount / GUEST_FEE_PER_KICK)
        if num_kicks <= 0:
            return None
        
        # Check if payer is a member
        status = resolve_player_membership_status(payer_player_id, finances_conn, accounts_conn)
        if status != 'member':
            return None  # Not a member, standard self-payment flow
        
        # Find nearby match dates
        tx_date = tx["date"]
        date_rows = rb48_conn.execute(
            """
            SELECT DISTINCT date
            FROM matches
            WHERE ABS(julianday(date) - julianday(?)) <= 3
            ORDER BY ABS(julianday(date) - julianday(?)) ASC
            """,
            (tx_date, tx_date),
        ).fetchall()
        
        all_guests = []
        best_date = None
        for drow in date_rows:
            mdate = drow["date"]
            guests = find_member_guests_for_date(
                payer_player_id, mdate,
                finances_conn=finances_conn,
                rb48_conn=rb48_conn,
                accounts_conn=accounts_conn,
            )
            if guests:
                if not best_date:
                    best_date = mdate
                all_guests.extend([{**g, 'match_date': mdate} for g in guests])
        
        # Also parse note hints
        note_hints = []
        tx_note = tx.get("note") or ""
        if tx_note:
            from scripts.finances.matcher import parse_guest_hints_from_note
            note_hints = parse_guest_hints_from_note(tx_note)
        
        return {
            "is_proxy_payment": True,
            "num_kicks": num_kicks,
            "total": amount,
            "match_date": best_date,
            "suggested_guests": all_guests[:num_kicks],  # Suggest up to num_kicks guests
            "all_available_guests": all_guests,
            "note_hints": note_hints,
        }
    finally:
        finances_conn.close()
        rb48_conn.close()
        accounts_conn.close()


def is_date_in_period(date_str: str, period: str) -> bool:
    """Check if a YYYY-MM-DD date string belongs to a period filter (YYYY, YYYY-H1, YYYY-H2, or 'all')."""
    if not date_str or period == "all":
        return True
    if len(period) == 4 and period.isdigit():
        return date_str.startswith(period)
    if period.endswith("-H1"):
        year = period[:4]
        return date_str.startswith(year) and "01-01" <= date_str[5:10] <= "06-30"
    if period.endswith("-H2"):
        year = period[:4]
        return date_str.startswith(year) and "07-01" <= date_str[5:10] <= "12-31"
    return True


def get_available_finance_periods(finances_conn=None, rb48_conn=None) -> list[dict]:
    """
    Return available period filters (half-years and full years, plus all time).
    Ordered descending by year.
    """
    current_year = datetime.now(timezone.utc).year
    years = {current_year}

    close_rb = False
    if rb48_conn is None:
        rb48_conn = get_rb48_connection()
        close_rb = True

    try:
        m_rows = rb48_conn.execute("SELECT DISTINCT SUBSTR(date, 1, 4) FROM matches").fetchall()
        for r in m_rows:
            if r[0] and str(r[0]).isdigit():
                years.add(int(r[0]))
    except Exception:
        pass
    finally:
        if close_rb:
            rb48_conn.close()

    close_fin = False
    if finances_conn is None:
        finances_conn = get_finances_connection()
        close_fin = True

    try:
        t_rows = finances_conn.execute("SELECT DISTINCT SUBSTR(date, 1, 4) FROM finance_transactions").fetchall()
        for r in t_rows:
            if r[0] and str(r[0]).isdigit():
                years.add(int(r[0]))
        p_rows = finances_conn.execute("SELECT DISTINCT SUBSTR(period, 1, 4) FROM payment_allocations WHERE period IS NOT NULL").fetchall()
        for r in p_rows:
            if r[0] and str(r[0]).isdigit():
                years.add(int(r[0]))
    except Exception:
        pass
    finally:
        if close_fin:
            finances_conn.close()

    sorted_years = sorted(list(years), reverse=True)
    periods = []
    for y in sorted_years:
        periods.append({"value": f"{y}-H2", "label": f"2. Halbjahr {y} ({y}-H2)", "type": "halfyear"})
        periods.append({"value": f"{y}-H1", "label": f"1. Halbjahr {y} ({y}-H1)", "type": "halfyear"})
        periods.append({"value": f"{y}", "label": f"Gesamtjahr {y}", "type": "year"})

    periods.append({"value": "all", "label": "Gesamter Zeitraum (Alle)", "type": "all"})
    return periods


def get_period_display_label(period: str) -> str:
    """Return a human-friendly label for a period identifier."""
    if period == "all":
        return "Gesamter Zeitraum (Alle)"
    if len(period) == 4 and period.isdigit():
        return f"Gesamtjahr {period}"
    if period.endswith("-H1"):
        return f"1. Halbjahr {period[:4]} ({period})"
    if period.endswith("-H2"):
        return f"2. Halbjahr {period[:4]} ({period})"
    return period


def get_finance_summary_metrics(
    period: str = "2026-H2",
    finances_conn=None,
    rb48_conn=None,
    accounts_conn=None,
) -> dict:
    """
    Compute financial overview metrics for the specified period:
    1. Offene Kleckerbeträge
    2. Offene Mitgliedsbeiträge
    3. Paypaleinnahmen (mit Aufschlüsselung: Mitgliedsbeiträge / Kleckerbeträge)
    4. Kontoeinnahmen (Aufschlüsselung: Mitgliedsbeiträge)
    """
    close_fin = False
    close_rb = False
    close_acc = False

    if finances_conn is None:
        finances_conn = get_finances_connection()
        close_fin = True
    if rb48_conn is None:
        rb48_conn = get_rb48_connection()
        close_rb = True
    if accounts_conn is None:
        accounts_conn = get_accounts_connection()
        close_acc = True

    try:
        available_periods = get_available_finance_periods(finances_conn=finances_conn, rb48_conn=rb48_conn)
        available_years = {int(p["value"][:4]) for p in available_periods if p["value"] != "all"}

        # 1. Offene Kleckerbeträge
        matches = get_match_history_financial_overview()
        filtered_matches = [m for m in matches if is_date_in_period(m["match_date"], period)]
        open_klecker_amount = sum(m.get("outstanding", 0.0) for m in filtered_matches)
        open_klecker_count = sum(m.get("unpaid_count", 0) for m in filtered_matches)
        total_klecker_expected = sum(m.get("total_expected", 0.0) for m in filtered_matches)
        total_klecker_collected = sum(m.get("total_collected", 0.0) for m in filtered_matches)

        # 2. Offene Mitgliedsbeiträge
        due_periods = []
        if period.endswith(("-H1", "-H2")):
            due_periods = [period]
        elif len(period) == 4 and period.isdigit():
            due_periods = [f"{period}-H1", f"{period}-H2"]
        elif period == "all":
            for y in sorted(available_years, reverse=True):
                due_periods.extend([f"{y}-H2", f"{y}-H1"])
        else:
            due_periods = [period]

        open_dues_amount = 0.0
        open_dues_count = 0
        total_dues_expected = 0.0
        total_dues_collected = 0.0

        for dp in due_periods:
            d_ov = get_membership_dues_overview(dp)
            open_dues_amount += d_ov.get("outstanding", 0.0)
            open_dues_count += sum(1 for mem in d_ov.get("members", []) if mem.get("payment_status") in ("unpaid", "partial"))
            total_dues_expected += d_ov.get("total_expected", 0.0)
            total_dues_collected += d_ov.get("total_collected", 0.0)

        # 3. Paypaleinnahmen & 4. Kontoeinnahmen
        tx_rows = finances_conn.execute(
            "SELECT * FROM finance_transactions WHERE amount > 0 AND status != 'ignored'"
        ).fetchall()
        period_txs = [t for t in tx_rows if is_date_in_period(t["date"], period)]
        paypal_tx_total = sum(t["amount"] for t in period_txs if (t["source"] == "paypal" or not t["source"]))

        alloc_rows = finances_conn.execute("SELECT * FROM payment_allocations").fetchall()

        paypal_membership_dues = 0.0
        paypal_guest_fees = 0.0
        bank_membership_dues = 0.0
        bank_guest_fees = 0.0

        for a in alloc_rows:
            pm = a["payment_method"]
            ftype = a["fee_type"]
            amount = float(a["allocated_amount"] or 0.0)

            in_period = False
            if ftype == "membership_due":
                in_period = (a["period"] in due_periods) or is_date_in_period(str(a["created_at"])[:10], period)
            elif ftype == "match_guest":
                in_period = is_date_in_period(a["match_date"], period)
            else:
                in_period = is_date_in_period(str(a["created_at"])[:10], period)

            if not in_period:
                continue

            if pm == "paypal":
                if ftype == "membership_due":
                    paypal_membership_dues += amount
                elif ftype == "match_guest":
                    paypal_guest_fees += amount
            elif pm == "bank":
                if ftype == "membership_due":
                    bank_membership_dues += amount
                elif ftype == "match_guest":
                    bank_guest_fees += amount

        total_paypal_income = max(paypal_tx_total, paypal_membership_dues + paypal_guest_fees)
        paypal_unassigned = max(0.0, total_paypal_income - (paypal_membership_dues + paypal_guest_fees))
        total_bank_income = bank_membership_dues + bank_guest_fees

        return {
            "period": period,
            "period_label": get_period_display_label(period),
            # 1. Offene Kleckerbeträge
            "open_klecker_amount": round(open_klecker_amount, 2),
            "open_klecker_count": open_klecker_count,
            "total_klecker_expected": round(total_klecker_expected, 2),
            "total_klecker_collected": round(total_klecker_collected, 2),
            # 2. Offene Mitgliedsbeiträge
            "open_dues_amount": round(open_dues_amount, 2),
            "open_dues_count": open_dues_count,
            "total_dues_expected": round(total_dues_expected, 2),
            "total_dues_collected": round(total_dues_collected, 2),
            # 3. Paypaleinnahmen
            "total_paypal_income": round(total_paypal_income, 2),
            "paypal_membership_dues": round(paypal_membership_dues, 2),
            "paypal_guest_fees": round(paypal_guest_fees, 2),
            "paypal_unassigned": round(paypal_unassigned, 2),
            # 4. Kontoeinnahmen
            "total_bank_income": round(total_bank_income, 2),
            "bank_membership_dues": round(bank_membership_dues, 2),
            "bank_guest_fees": round(bank_guest_fees, 2),
        }
    finally:
        if close_fin:
            finances_conn.close()
        if close_rb:
            rb48_conn.close()
        if close_acc:
            accounts_conn.close()


def settle_transaction_and_debts(
    transaction_id: int,
    payer_player_id: int | None = None,
    beneficiary_player_id: int | None = None,
    match_date: str | None = None,
    remember: bool = False,
    current_user_id: int | None = None,
    note: str | None = None,
) -> dict:
    """
    Settle a transaction directly, covering debts for either the payer themselves
    or on behalf of another guest player (e.g. Claudio paying for Paul).
    Also links any existing manual allocations for this player/date (e.g. Martin).
    """
    finances_conn = get_finances_connection()
    rb48_conn = get_rb48_connection()
    accounts_conn = get_accounts_connection()

    try:
        tx = get_transaction_by_id(finances_conn, transaction_id)
        if not tx:
            return {"success": False, "error": "Transaktion nicht gefunden"}

        # Resolve payer player ID
        payer_pid = payer_player_id
        if not payer_pid:
            payer_pid = tx.get("matched_player_id")
        if not payer_pid:
            match = find_player_match(
                tx.get("raw_payer_name"),
                tx.get("raw_payer_email"),
                finances_conn=finances_conn,
                rb48_conn=rb48_conn,
                accounts_conn=accounts_conn,
            )
            if match.get("player_id") and match.get("confidence", 0) >= 0.60:
                payer_pid = match["player_id"]

        # Beneficiary defaults to payer
        bene_pid = beneficiary_player_id or payer_pid

        # Remember identity if requested
        if remember and payer_pid:
            save_or_update_identity(
                finances_conn,
                player_id=payer_pid,
                payer_email=tx.get("raw_payer_email"),
                payer_name=tx.get("raw_payer_name"),
                confidence=1.0,
                created_by_user_id=current_user_id,
            )

        # Update transaction to assigned & confirmed
        update_transaction_assignment(
            finances_conn,
            transaction_id,
            player_id=payer_pid,
            status="assigned",
            is_confirmed=1,
        )

        remaining_amount = float(tx.get("amount", 0))
        covered_count = 0

        if bene_pid and remaining_amount > 0:
            players_dict = get_players(rb48_conn)
            payer_pdata = players_dict.get(payer_pid, {}) if payer_pid else {}
            payer_name = payer_pdata.get("aliases", [f"Spieler #{payer_pid}"])[0] if payer_pid else (tx.get("raw_payer_name") or "Zahler")

            alloc_note = note
            if not alloc_note:
                if payer_pid and bene_pid != payer_pid:
                    alloc_note = f"Bezahlt von {payer_name}"
                else:
                    alloc_note = f"PayPal {tx['tx_code'] or ''}".strip()

            # 1. Check existing manual allocations without transaction_id for the beneficiary
            if match_date:
                manual_rows = finances_conn.execute(
                    """
                    SELECT id, allocated_amount FROM payment_allocations
                    WHERE match_date = ? AND player_id = ? AND transaction_id IS NULL AND fee_type = 'match_guest'
                    """,
                    (match_date, bene_pid),
                ).fetchall()
            else:
                manual_rows = finances_conn.execute(
                    """
                    SELECT id, allocated_amount FROM payment_allocations
                    WHERE player_id = ? AND transaction_id IS NULL AND fee_type = 'match_guest'
                    ORDER BY match_date DESC
                    """,
                    (bene_pid,),
                ).fetchall()

            for mr in manual_rows:
                if remaining_amount < GUEST_FEE_PER_KICK:
                    break
                finances_conn.execute(
                    """
                    UPDATE payment_allocations
                    SET transaction_id = ?, payment_method = ?, paid_by_player_id = ?, note = ?
                    WHERE id = ?
                    """,
                    (
                        transaction_id,
                        tx["source"],
                        payer_pid if payer_pid != bene_pid else None,
                        alloc_note,
                        mr["id"],
                    ),
                )
                remaining_amount -= GUEST_FEE_PER_KICK
                covered_count += 1

            # 2. Check unpaid match guest fees for beneficiary
            if remaining_amount >= GUEST_FEE_PER_KICK:
                if match_date:
                    dates_to_check = [match_date]
                else:
                    match_date_rows = rb48_conn.execute(
                        """
                        SELECT DISTINCT date FROM matches
                        JOIN match_players USING(match_id)
                        WHERE player_id = ?
                        ORDER BY date ASC
                        """,
                        (bene_pid,),
                    ).fetchall()
                    dates_to_check = [r["date"] for r in match_date_rows]

                for mdate in dates_to_check:
                    if remaining_amount < GUEST_FEE_PER_KICK:
                        break
                    allocs = get_allocations_for_match_date(finances_conn, mdate)
                    p_allocs = [a for a in allocs if a.get("player_id") == bene_pid]
                    paid_sum = sum(a["allocated_amount"] for a in p_allocs if a["payment_method"] != "waived")
                    if paid_sum >= GUEST_FEE_PER_KICK:
                        continue

                    add_payment_allocation(
                        finances_conn,
                        fee_type="match_guest",
                        allocated_amount=GUEST_FEE_PER_KICK,
                        payment_method=tx["source"],
                        transaction_id=transaction_id,
                        match_date=mdate,
                        player_id=bene_pid,
                        paid_by_player_id=payer_pid if payer_pid != bene_pid else None,
                        note=alloc_note,
                    )
                    remaining_amount -= GUEST_FEE_PER_KICK
                    covered_count += 1

            # 3. If beneficiary is a member and remaining >= 48 €, allocate to membership dues
            status = resolve_player_membership_status(bene_pid, finances_conn, accounts_conn)
            if remaining_amount >= MEMBERSHIP_DUE_PER_HALFYEAR and status == "member":
                for per in ("2026-H1", "2026-H2"):
                    if remaining_amount < MEMBERSHIP_DUE_PER_HALFYEAR:
                        break
                    allocs = get_allocations_for_period(finances_conn, per)
                    p_allocs = [a for a in allocs if a.get("player_id") == bene_pid]
                    paid_sum = sum(a["allocated_amount"] for a in p_allocs if a["payment_method"] != "waived")
                    if paid_sum >= MEMBERSHIP_DUE_PER_HALFYEAR:
                        continue

                    add_payment_allocation(
                        finances_conn,
                        fee_type="membership_due",
                        allocated_amount=MEMBERSHIP_DUE_PER_HALFYEAR,
                        payment_method=tx["source"],
                        transaction_id=transaction_id,
                        period=per,
                        player_id=bene_pid,
                        paid_by_player_id=payer_pid if payer_pid != bene_pid else None,
                        note=alloc_note,
                    )
                    remaining_amount -= MEMBERSHIP_DUE_PER_HALFYEAR
                    covered_count += 1

        finances_conn.commit()
        return {
            "success": True,
            "transaction_id": transaction_id,
            "payer_player_id": payer_pid,
            "beneficiary_player_id": bene_pid,
            "covered_count": covered_count,
        }
    finally:
        finances_conn.close()
        rb48_conn.close()
        accounts_conn.close()


def reset_transaction_settlement(transaction_id: int):
    """Reset a transaction back to 'imported' (unconfirmed) and remove/detach allocations."""
    finances_conn = get_finances_connection()
    try:
        finances_conn.execute(
            "DELETE FROM payment_allocations WHERE transaction_id = ?",
            (transaction_id,),
        )
        finances_conn.execute(
            """
            UPDATE finance_transactions
            SET status = 'imported', is_confirmed = 0, matched_player_id = NULL, matched_user_id = NULL
            WHERE id = ?
            """,
            (transaction_id,),
        )
        finances_conn.commit()
    finally:
        finances_conn.close()

