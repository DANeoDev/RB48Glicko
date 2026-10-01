from datetime import datetime, timezone
from scripts.finances.database import (
    get_finances_connection,
    add_payment_allocation,
    get_allocations_for_match_date,
    get_allocations_for_period,
    get_allocations_for_player,
    get_transaction_by_id,
    get_all_player_membership_statuses,
    get_player_membership_status,
    set_player_membership_status,
)
from scripts.database.database import get_connection as get_rb48_connection
from scripts.database.db_players import get_players
from scripts.accounts.database import get_accounts_connection


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

                guest_entries.append({
                    "player_id": pid,
                    "name": name,
                    "aliases_str": ", ".join(pdata.get("aliases", [])),
                    "status": status,
                    "fee_required": GUEST_FEE_PER_KICK,
                    "amount_paid": paid_sum,
                    "payment_status": payment_status,
                    "allocations": p_allocs,
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


def manual_mark_match_guest_payment(
    match_date: str,
    player_id: int,
    payment_method: str,
    note: str | None = None,
    amount: float = GUEST_FEE_PER_KICK,
) -> int:
    """
    Manually mark a player's guest fee for a match date as cash, paypal direct, waived, or unpaid.
    """
    finances_conn = get_finances_connection()
    try:
        # Delete prior manual allocations for this player and date
        finances_conn.execute(
            """
            DELETE FROM payment_allocations
            WHERE match_date = ? AND player_id = ? AND transaction_id IS NULL AND fee_type = 'match_guest'
            """,
            (match_date, player_id),
        )
        finances_conn.commit()

        if payment_method == "unpaid":
            return 0

        alloc_amount = 0.0 if payment_method == "waived" else amount
        return add_payment_allocation(
            finances_conn,
            fee_type="match_guest",
            allocated_amount=alloc_amount,
            payment_method=payment_method,
            transaction_id=None,
            match_date=match_date,
            player_id=player_id,
            note=note or f"Manuelle Erfassung ({payment_method})",
        )
    finally:
        finances_conn.close()


def get_membership_dues_overview(period: str = "2026-H2") -> dict:
    """
    Get membership dues breakdown (48 € / Half-year) for all club members.
    """
    players = get_all_players_with_membership()
    members = [p for p in players if p["status"] == "member"]

    finances_conn = get_finances_connection()
    try:
        allocations = get_allocations_for_period(finances_conn, period)
        alloc_by_player: dict[int, list[dict]] = {}
        for a in allocations:
            pid = a.get("player_id")
            if pid:
                alloc_by_player.setdefault(pid, []).append(a)

        member_dues_list = []
        total_expected = len(members) * MEMBERSHIP_DUE_PER_HALFYEAR
        total_collected = 0.0

        for m in members:
            pid = m["player_id"]
            p_allocs = alloc_by_player.get(pid, [])
            paid_sum = sum(a["allocated_amount"] for a in p_allocs if a["payment_method"] != "waived")
            is_waived = any(a["payment_method"] == "waived" for a in p_allocs)

            total_collected += paid_sum

            if is_waived:
                pstatus = "waived"
            elif paid_sum >= MEMBERSHIP_DUE_PER_HALFYEAR:
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
                "fee_required": MEMBERSHIP_DUE_PER_HALFYEAR,
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

        # Match history guest kicks (3.50 €)
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
