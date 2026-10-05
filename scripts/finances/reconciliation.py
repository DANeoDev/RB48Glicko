import csv
from datetime import datetime, timezone
from scripts.utils.timezone import get_cologne_date_str, get_cologne_now
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
    get_all_player_membership_records,
    get_player_membership_status,
    set_player_membership_status,
    create_receivable,
    get_receivable_by_id,
    get_receivables,
    update_receivable,
    delete_receivable,
    get_allocations_for_receivable,
    create_special_receivables_group,
)
from scripts.database.database import get_connection as get_rb48_connection
from scripts.database.db_players import get_players, get_ignored_aliases, get_alias_lookup
from scripts.matches.match_entry import get_matches_dir
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
    as_of_date: str | None = None,
    explicit_records=None,
    user_created_dates=None,
) -> str:
    """
    Determine if a player is 'member' or 'guest'.
    Rule:
    1. If as_of_date is provided and player has a recorded 'match_guest' allocation for as_of_date,
       treat as 'guest' for that historical match.
    2. If explicitly set in `player_membership_status`:
       - If as_of_date is provided and status is 'member':
         Check member_since. If as_of_date < member_since, return 'guest'.
       - Else return explicit status.
    3. Else if player is linked to an approved user account:
       - If as_of_date is provided and user was created after as_of_date, return 'guest'.
       - Else default to 'member'.
    4. Else default to 'guest'.
    """
    # 1. Historical allocation check
    if as_of_date and finances_conn:
        try:
            row = finances_conn.execute(
                "SELECT 1 FROM payment_allocations WHERE match_date = ? AND player_id = ? AND fee_type = 'match_guest'",
                (as_of_date, player_id),
            ).fetchone()
            if row:
                return "guest"
        except Exception:
            pass

    # 2. Explicit membership record check
    rec = None
    if explicit_records is not None:
        rec = explicit_records.get(player_id)
    elif finances_conn:
        try:
            r = finances_conn.execute(
                "SELECT status, member_since FROM player_membership_status WHERE player_id = ?",
                (player_id,),
            ).fetchone()
            if r:
                rec = dict(r)
        except Exception:
            pass

    if rec:
        exp_status = rec.get("status")
        member_since = rec.get("member_since")
        if as_of_date and exp_status == "member" and member_since and as_of_date < member_since:
            return "guest"
        if exp_status:
            return exp_status

    if explicit_statuses is not None:
        if player_id in explicit_statuses:
            return explicit_statuses[player_id]
    elif finances_conn:
        exp = get_player_membership_status(finances_conn, player_id, default=None)
        if exp:
            return exp

    # 3. Linked user account check
    is_linked = False
    if linked_player_ids is not None:
        is_linked = player_id in linked_player_ids
    elif accounts_conn:
        urow = accounts_conn.execute(
            "SELECT 1 FROM users WHERE player_id = ?", (player_id,)
        ).fetchone()
        is_linked = bool(urow)

    if is_linked:
        return "member"

    return "guest"


def get_ignored_guests_for_match_date(match_date: str, rb48_conn=None) -> list[str]:
    """
    Scan match CSVs in get_matches_dir() for the given match date (YYYY-MM-DD)
    and find any participating player names that belong to ignored_aliases.
    Returns sorted list of distinct alias names.
    """
    close_rb = False
    if rb48_conn is None:
        rb48_conn = get_rb48_connection()
        close_rb = True

    try:
        ignored = get_ignored_aliases(rb48_conn)
        if not ignored:
            return []

        ignored_map = {a.casefold(): a for a in ignored}
        matches_dir = get_matches_dir()
        found = set()

        for p in matches_dir.glob(f"{match_date}*.csv"):
            for enc in ("utf-8", "latin-1", "cp1252"):
                try:
                    with open(p, "r", encoding=enc) as f:
                        for row in csv.reader(f):
                            if not row or len(row) < 6 or row[0].strip().casefold() == "match_id":
                                continue
                            team_a = [name.strip() for name in row[2].split(",") if name.strip()]
                            team_b = [name.strip() for name in row[3].split(",") if name.strip()]
                            for name in team_a + team_b:
                                if name.casefold() in ignored_map:
                                    found.add(ignored_map[name.casefold()])
                    break
                except Exception:
                    continue

        return sorted(list(found))
    finally:
        if close_rb:
            rb48_conn.close()


def get_all_match_dates_for_ignored_alias(alias: str, rb48_conn=None) -> list[str]:
    """
    Find all match dates (YYYY-MM-DD) where a given ignored alias participated in match CSVs.
    Ordered ascending.
    """
    clean_alias = alias.strip().casefold()
    matches_dir = get_matches_dir()
    dates = set()

    for p in matches_dir.glob("*.csv"):
        for enc in ("utf-8", "latin-1", "cp1252"):
            try:
                with open(p, "r", encoding=enc) as f:
                    for row in csv.reader(f):
                        if not row or len(row) < 6 or row[0].strip().casefold() == "match_id":
                            continue
                        m_id = row[0].strip()
                        m_date = m_id.rsplit("-", 1)[0]
                        team_a = [name.strip() for name in row[2].split(",") if name.strip()]
                        team_b = [name.strip() for name in row[3].split(",") if name.strip()]
                        for name in team_a + team_b:
                            if name.casefold() == clean_alias:
                                dates.add(m_date)
                break
            except Exception:
                continue

    return sorted(list(dates))


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
    Return all distinct match dates from Match History (`rb48.db`) with guest fee metrics,
    including both regular guest players and participating ignored aliases.
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

        explicit_records = get_all_player_membership_records(finances_conn)
        explicit_statuses = {pid: r["status"] for pid, r in explicit_records.items()}
        user_rows = accounts_conn.execute(
            "SELECT player_id, created_at FROM users WHERE player_id IS NOT NULL"
        ).fetchall()
        linked_player_ids = {u["player_id"] for u in user_rows}
        user_created_dates = {u["player_id"]: str(u["created_at"])[:10] for u in user_rows if u["created_at"]}
        players_dict = get_players(rb48_conn)

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
                    as_of_date=mdate,
                    explicit_records=explicit_records,
                    user_created_dates=user_created_dates,
                    finances_conn=finances_conn,
                ) == "guest"
            ]

            allocations = get_allocations_for_match_date(finances_conn, mdate)

            paid_pids = {
                a["player_id"]
                for a in allocations
                if a.get("player_id") and (a["payment_method"] == "waived" or a["allocated_amount"] >= GUEST_FEE_PER_KICK)
            }

            # Check ignored guests for this match date
            ignored_guests = get_ignored_guests_for_match_date(mdate, rb48_conn)
            present_aliases = set()
            for r in prows:
                pdata = players_dict.get(r["player_id"], {})
                for al in pdata.get("aliases", []):
                    present_aliases.add(al.casefold())

            unlinked_ignored_guests = [ign for ign in ignored_guests if ign.casefold() not in present_aliases]

            paid_ignored_count = 0
            collected_ignored = 0.0
            for ign in unlinked_ignored_guests:
                ign_allocs = [
                    a for a in allocations
                    if (a.get("guest_alias") and a["guest_alias"].casefold() == ign.casefold())
                    or (not a.get("player_id") and not a.get("guest_alias") and ign.casefold() in (a.get("note") or "").casefold())
                ]
                ign_paid_sum = sum(a["allocated_amount"] for a in ign_allocs if a["payment_method"] != "waived")
                ign_waived = any(a["payment_method"] == "waived" for a in ign_allocs)
                collected_ignored += ign_paid_sum
                if ign_waived or ign_paid_sum >= GUEST_FEE_PER_KICK:
                    paid_ignored_count += 1

            guest_count = len(guest_pids) + len(unlinked_ignored_guests)
            paid_count = len(set(guest_pids).intersection(paid_pids)) + paid_ignored_count
            unpaid_count = max(0, guest_count - paid_count)
            total_expected = guest_count * GUEST_FEE_PER_KICK
            total_collected = sum(
                a["allocated_amount"]
                for a in allocations
                if a.get("player_id") in guest_pids and a["payment_method"] != "waived"
            ) + collected_ignored

            results.append({
                "match_date": mdate,
                "match_count": drow["match_count"],
                "total_players": drow["total_players"] + len(unlinked_ignored_guests),
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


def get_match_date_guest_status(
    match_date: str,
    finances_conn=None,
    rb48_conn=None,
    accounts_conn=None,
) -> dict:
    """
    Get financial breakdown for all players on a specific match date from Match History,
    including both regular guest players and participating ignored aliases.
    """
    close_rb48 = False
    close_finances = False
    close_accounts = False

    if rb48_conn is None:
        rb48_conn = get_rb48_connection()
        close_rb48 = True
    if finances_conn is None:
        finances_conn = get_finances_connection()
        close_finances = True
    if accounts_conn is None:
        accounts_conn = get_accounts_connection()
        close_accounts = True

    try:
        players_dict = get_players(rb48_conn)
        explicit_records = get_all_player_membership_records(finances_conn)
        explicit_statuses = {pid: r["status"] for pid, r in explicit_records.items()}
        user_rows = accounts_conn.execute(
            "SELECT player_id, username, attendance_name, created_at FROM users WHERE player_id IS NOT NULL"
        ).fetchall()
        users_by_player_id = {u["player_id"]: dict(u) for u in user_rows}
        linked_player_ids = set(users_by_player_id.keys())
        user_created_dates = {u["player_id"]: str(u["created_at"])[:10] for u in user_rows if u["created_at"]}

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
                as_of_date=match_date,
                explicit_records=explicit_records,
                user_created_dates=user_created_dates,
                finances_conn=finances_conn,
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
                    "id_slug": f"p_{pid}",
                })
            else:
                member_entries.append({
                    "player_id": pid,
                    "name": name,
                    "aliases_str": ", ".join(pdata.get("aliases", [])),
                    "status": status,
                })

        # Process ignored guests participating on this match date
        ignored_guests = get_ignored_guests_for_match_date(match_date, rb48_conn)
        present_aliases = set()
        for r in prows:
            pdata = players_dict.get(r["player_id"], {})
            for al in pdata.get("aliases", []):
                present_aliases.add(al.casefold())

        for ign in ignored_guests:
            if ign.casefold() in present_aliases:
                continue

            ign_allocs = [
                a for a in allocations
                if (a.get("guest_alias") and a["guest_alias"].casefold() == ign.casefold())
                or (not a.get("player_id") and not a.get("guest_alias") and ign.casefold() in (a.get("note") or "").casefold())
            ]
            paid_sum = sum(a["allocated_amount"] for a in ign_allocs if a["payment_method"] != "waived")
            is_waived = any(a["payment_method"] == "waived" for a in ign_allocs)

            total_guest_fees_expected += GUEST_FEE_PER_KICK
            total_guest_fees_collected += paid_sum

            if is_waived:
                payment_status = "waived"
            elif paid_sum >= GUEST_FEE_PER_KICK:
                pmethods = {a["payment_method"] for a in ign_allocs}
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

            paid_by_name = None
            paid_by_pid = None
            for a in ign_allocs:
                if a.get("paid_by_player_id"):
                    paid_by_pid = a["paid_by_player_id"]
                    pb_pdata = players_dict.get(paid_by_pid, {})
                    paid_by_name = pb_pdata.get("aliases", [f"Player #{paid_by_pid}"])[0]
                    break

            ign_slug = f"ign_{abs(hash(ign)) % 10000000}"
            guest_entries.append({
                "player_id": f"ignored:{ign}",
                "name": ign,
                "aliases_str": f"{ign} (Extern)",
                "status": "guest",
                "fee_required": GUEST_FEE_PER_KICK,
                "amount_paid": paid_sum,
                "payment_status": payment_status,
                "allocations": ign_allocs,
                "paid_by_name": paid_by_name,
                "paid_by_player_id": paid_by_pid,
                "is_ignored_alias": True,
                "id_slug": ign_slug,
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
        if close_rb48:
            rb48_conn.close()
        if close_finances:
            finances_conn.close()
        if close_accounts:
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
    player_id: int | str | None,
    payment_method: str,
    note: str | None = None,
    amount: float = GUEST_FEE_PER_KICK,
    guest_alias: str | None = None,
) -> int:
    """
    Manually mark a player's guest fee for a match date as cash, paypal direct, waived, or unpaid.
    Supports regular player_ids and ignored aliases (via 'ignored:NAME' or guest_alias parameter).
    Automatically links to an unconfirmed imported transaction (e.g. PayPal) if available.
    """
    finances_conn = get_finances_connection()
    try:
        clean_alias = guest_alias
        real_pid = None
        if isinstance(player_id, str) and player_id.startswith("ignored:"):
            clean_alias = player_id.split(":", 1)[1]
        elif player_id is not None and not clean_alias:
            try:
                real_pid = int(player_id)
            except (ValueError, TypeError):
                clean_alias = str(player_id)

        if clean_alias:
            # Handle ignored alias guest
            existing_allocs = finances_conn.execute(
                """
                SELECT * FROM payment_allocations
                WHERE match_date = ? AND fee_type = 'match_guest'
                AND (guest_alias = ? OR (guest_alias IS NULL AND player_id IS NULL AND note LIKE ?))
                """,
                (match_date, clean_alias, f"%{clean_alias}%"),
            ).fetchall()

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
                    WHERE match_date = ? AND fee_type = 'match_guest'
                    AND (guest_alias = ? OR (guest_alias IS NULL AND player_id IS NULL AND note LIKE ?))
                    """,
                    (match_date, clean_alias, f"%{clean_alias}%"),
                )
                finances_conn.commit()
                return 0

            # Delete prior manual allocations (without transaction_id)
            finances_conn.execute(
                """
                DELETE FROM payment_allocations
                WHERE match_date = ? AND fee_type = 'match_guest' AND transaction_id IS NULL
                AND (guest_alias = ? OR (guest_alias IS NULL AND player_id IS NULL AND note LIKE ?))
                """,
                (match_date, clean_alias, f"%{clean_alias}%"),
            )
            finances_conn.commit()

            linked_tx_id = None
            for ea in existing_allocs:
                if ea["transaction_id"]:
                    linked_tx_id = ea["transaction_id"]
                    break

            alloc_amount = 0.0 if payment_method == "waived" else amount
            return add_payment_allocation(
                finances_conn,
                fee_type="match_guest",
                allocated_amount=alloc_amount,
                payment_method=payment_method,
                transaction_id=linked_tx_id,
                match_date=match_date,
                player_id=None,
                guest_alias=clean_alias,
                note=note or f"Gastbeitrag {clean_alias} ({payment_method})",
            )

        # Find any existing allocation for this match date and player
        existing_allocs = finances_conn.execute(
            """
            SELECT * FROM payment_allocations
            WHERE match_date = ? AND player_id = ? AND fee_type = 'match_guest'
            """,
            (match_date, real_pid),
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
                (match_date, real_pid),
            )
            finances_conn.commit()
            return 0

        # Delete prior manual allocations (without transaction_id)
        finances_conn.execute(
            """
            DELETE FROM payment_allocations
            WHERE match_date = ? AND player_id = ? AND transaction_id IS NULL AND fee_type = 'match_guest'
            """,
            (match_date, real_pid),
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
            cand = find_unconfirmed_transaction_for_player(finances_conn, real_pid, match_date, amount=amount)
            if cand:
                linked_tx_id = cand["id"]
                update_transaction_assignment(
                    finances_conn,
                    linked_tx_id,
                    player_id=real_pid,
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
            player_id=real_pid,
            note=note or f"Erfassung ({payment_method})",
        )
    finally:
        finances_conn.close()


def get_period_date_range(period: str) -> dict:
    """
    Return start date, end date, has_ended status, and display label for a period string.
    """
    today_str = get_cologne_date_str()
    is_full_year = len(str(period)) == 4 and str(period).isdigit()

    if str(period).endswith("-H1"):
        year = str(period)[:4]
        start_date = f"{year}-01-01"
        end_date = f"{year}-06-30"
        label = f"1. Halbjahr {year} ({period})"
    elif str(period).endswith("-H2"):
        year = str(period)[:4]
        start_date = f"{year}-07-01"
        end_date = f"{year}-12-31"
        label = f"2. Halbjahr {year} ({period})"
    elif is_full_year:
        year = str(period)
        start_date = f"{year}-01-01"
        end_date = f"{year}-12-31"
        label = f"Gesamtjahr {year}"
    else:  # "all" or other
        start_date = "1970-01-01"
        end_date = "2099-12-31"
        label = "Gesamter Zeitraum"

    has_ended = today_str > end_date
    return {
        "period": period,
        "start": start_date,
        "end": end_date,
        "has_ended": has_ended,
        "label": label,
    }


def get_membership_dues_overview(period: str = "2026-H2") -> dict:
    """
    Get membership dues breakdown (48 € / Half-year) for all club members,
    including actual match attendance (kicks count) during this period.
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

        # Query match attendance for each member during this period from rb48 database
        p_range = get_period_date_range(period)
        match_stats_by_player: dict[int, dict] = {}
        try:
            rb48_conn = get_rb48_connection()
            try:
                rows = rb48_conn.execute(
                    """
                    SELECT mp.player_id, COUNT(DISTINCT m.match_id) AS games_count, MAX(m.date) AS latest_match_date
                    FROM matches m
                    JOIN match_players mp ON m.match_id = mp.match_id
                    WHERE m.date >= ? AND m.date <= ?
                    GROUP BY mp.player_id
                    """,
                    (p_range["start"], p_range["end"]),
                ).fetchall()
                match_stats_by_player = {
                    r["player_id"]: {
                        "games_count": r["games_count"],
                        "latest_match_date": r["latest_match_date"],
                    }
                    for r in rows
                }
            finally:
                rb48_conn.close()
        except Exception:
            pass

        member_dues_list = []
        total_collected = 0.0

        count_paid = 0
        count_partial = 0
        count_unpaid_active = 0
        count_unpaid_inactive = 0
        count_inactive = 0

        for m in members:
            pid = m["player_id"]
            p_allocs = alloc_by_player.get(pid, [])
            paid_sum = sum(a["allocated_amount"] for a in p_allocs if a["payment_method"] != "waived")
            waived_allocs = [a for a in p_allocs if a["payment_method"] == "waived"]
            is_waived = len(waived_allocs) > 0
            is_explicitly_inactive = any(
                "inaktiv" in (a.get("note") or "").lower() for a in waived_allocs
            )

            p_stats = match_stats_by_player.get(pid, {"games_count": 0, "latest_match_date": None})
            games_count = p_stats["games_count"]
            latest_match_date = p_stats["latest_match_date"]
            was_present = games_count > 0

            # Inactive members: explicitly marked inactive or waived with 0 games
            is_inactive = is_explicitly_inactive or (is_waived and not was_present)

            # Inactive or waived members do not pay dues ("inaktive Mitglieder zahlen keinen Beitrag")
            if is_inactive:
                fee_required = 0.0
            elif is_waived:
                fee_required = 0.0
            else:
                fee_required = fee_required_per_member

            total_collected += paid_sum

            # Classify status
            if is_inactive:
                pstatus = "inactive"
                count_inactive += 1
            elif is_waived:
                pstatus = "waived"
                count_inactive += 1
            elif paid_sum >= fee_required_per_member:
                pmethods = {a["payment_method"] for a in p_allocs}
                if "bank" in pmethods:
                    pstatus = "bank"
                elif "cash" in pmethods:
                    pstatus = "cash"
                else:
                    pstatus = "paid"
                count_paid += 1
            elif paid_sum > 0:
                pstatus = "partial"
                count_partial += 1
            else:  # paid_sum == 0
                if was_present:
                    pstatus = "unpaid"  # Truly unpaid: player was there!
                    count_unpaid_active += 1
                else:
                    if p_range["has_ended"]:
                        pstatus = "unpaid_inactive_ended"  # 0 games and period ended -> de facto inactive!
                        count_unpaid_inactive += 1
                    else:
                        pstatus = "unpaid_inactive_ongoing"  # 0 games so far, period still ongoing
                        count_unpaid_inactive += 1

            member_dues_list.append({
                "player_id": pid,
                "name": m["name"],
                "aliases_str": m["aliases_str"],
                "linked_user": m["linked_user"],
                "fee_required": fee_required,
                "base_fee": fee_required_per_member,
                "amount_paid": paid_sum,
                "payment_status": pstatus,
                "allocations": p_allocs,
                "games_count": games_count,
                "latest_match_date": latest_match_date,
                "was_present": was_present,
                "is_inactive": is_inactive,
            })

        total_expected = sum(m["fee_required"] for m in member_dues_list)
        active_members_count = sum(1 for m in member_dues_list if m["fee_required"] > 0)
        outstanding = max(0.0, total_expected - total_collected)

        return {
            "period": period,
            "period_dates": p_range,
            "members": member_dues_list,
            "total_members": len(members),
            "active_members_count": active_members_count,
            "total_expected": total_expected,
            "total_collected": total_collected,
            "outstanding": outstanding,
            "count_paid": count_paid,
            "count_partial": count_partial,
            "count_unpaid_active": count_unpaid_active,
            "count_unpaid_inactive": count_unpaid_inactive,
            "count_inactive": count_inactive,
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

        alloc_amount = 0.0 if payment_method in ("waived", "inactive") else amount
        actual_method = "waived" if payment_method == "inactive" else payment_method
        actual_note = note or ("Inaktiv im Zeitraum" if payment_method == "inactive" else f"Mitgliedsbeitrag ({payment_method})")

        return add_payment_allocation(
            finances_conn,
            fee_type="membership_due",
            allocated_amount=alloc_amount,
            payment_method=actual_method,
            transaction_id=None,
            period=period,
            player_id=player_id,
            note=actual_note,
        )
    finally:
        finances_conn.close()


def bulk_set_inactive_members(period: str) -> int:
    """
    Bulk mark all members with 0 kicks in an ended (or specified) period as inactive/waived.
    Returns the count of members updated.
    """
    ov = get_membership_dues_overview(period)
    updated_count = 0
    for m in ov["members"]:
        if m["games_count"] == 0 and m["payment_status"] in ("unpaid", "unpaid_inactive_ended", "unpaid_inactive_ongoing"):
            manual_mark_membership_due(
                period=period,
                player_id=m["player_id"],
                payment_method="waived",
                note="Inaktiv im Zeitraum (0 Kicks)",
                amount=0.0,
            )
            updated_count += 1
    return updated_count


def get_membership_dues_matrix(finances_conn=None, rb48_conn=None) -> dict:
    """
    Build a cross-period matrix of all club members and their dues/attendance status
    across all available half-years (e.g. 2026-H2, 2026-H1, 2025-H2, etc.).
    """
    close_fin = False
    if finances_conn is None:
        finances_conn = get_finances_connection()
        close_fin = True

    try:
        available_periods = [
            p for p in get_available_finance_periods(finances_conn=finances_conn)
            if p["type"] == "halfyear"
        ]
        period_values = [p["value"] for p in available_periods]

        # Compute dues overview for each period
        period_overviews = {
            pv: get_membership_dues_overview(pv)
            for pv in period_values
        }

        players = get_all_players_with_membership()
        members = [p for p in players if p["status"] == "member"]

        matrix_rows = []
        for m in members:
            pid = m["player_id"]
            p_periods = {}
            total_paid_all = 0.0
            total_unpaid_active_count = 0

            for pv in period_values:
                ov = period_overviews[pv]
                m_info = next((item for item in ov["members"] if item["player_id"] == pid), None)
                if m_info:
                    p_periods[pv] = {
                        "payment_status": m_info["payment_status"],
                        "amount_paid": m_info["amount_paid"],
                        "fee_required": m_info["fee_required"],
                        "games_count": m_info["games_count"],
                        "latest_match_date": m_info["latest_match_date"],
                        "was_present": m_info["was_present"],
                        "has_ended": ov["period_dates"]["has_ended"],
                    }
                    total_paid_all += m_info["amount_paid"]
                    if m_info["payment_status"] == "unpaid":
                        total_unpaid_active_count += 1
                else:
                    p_periods[pv] = {
                        "payment_status": "unpaid_inactive_ended",
                        "amount_paid": 0.0,
                        "fee_required": 0.0,
                        "games_count": 0,
                        "latest_match_date": None,
                        "was_present": False,
                        "has_ended": True,
                    }

            matrix_rows.append({
                "player_id": pid,
                "name": m["name"],
                "aliases_str": m["aliases_str"],
                "linked_user": m["linked_user"],
                "periods": p_periods,
                "total_paid_all": total_paid_all,
                "total_unpaid_active_count": total_unpaid_active_count,
            })

        matrix_rows.sort(key=lambda x: (-x["total_unpaid_active_count"], x["name"].lower()))

        return {
            "periods": available_periods,
            "period_values": period_values,
            "members": matrix_rows,
            "total_members": len(members),
        }
    finally:
        if close_fin:
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

        # For members: Check membership dues (members can voluntarily choose lower amounts < 48 €)
        if status == "member" and remaining_amount > 0:
            is_bank = (tx.get("source") or "").lower() == "bank"
            tx_text = f"{tx.get('description') or ''} {tx.get('note') or ''}".lower()
            has_due_hint = any(k in tx_text for k in ("beitrag", "mitglied", "halbjahr", "h1", "h2", "vereinsbeitrag"))

            # Check if this is a proxy payment for guests (e.g. member paid 3.50€ multiples without due hint and not from bank)
            rem = remaining_amount % GUEST_FEE_PER_KICK
            is_guest_multiple = rem < 0.01 or (GUEST_FEE_PER_KICK - rem) < 0.01
            if is_guest_multiple and not is_bank and not has_due_hint and remaining_amount < 40.0:
                proxy_covered = auto_allocate_proxy_guest_payment(transaction_id, player_id)
                if proxy_covered > 0:
                    covered += proxy_covered
                    return covered

            # Allocate to membership dues using smart inferred period order
            inferred = infer_transaction_settlement_target(
                remaining_amount, tx.get("date"), tx.get("note"), tx.get("description"), player_id
            )
            for per in inferred.get("periods", ("2026-H1", "2026-H2")):
                if remaining_amount <= 0:
                    break
                allocs = get_allocations_for_period(finances_conn, per)
                p_allocs = [a for a in allocs if a.get("player_id") == player_id]
                paid_sum = sum(a["allocated_amount"] for a in p_allocs if a["payment_method"] != "waived")
                if paid_sum >= MEMBERSHIP_DUE_PER_HALFYEAR:
                    continue

                alloc_amt = min(remaining_amount, MEMBERSHIP_DUE_PER_HALFYEAR - paid_sum)
                if alloc_amt <= 0:
                    alloc_amt = remaining_amount

                source_label = "Konto" if tx.get("source") == "bank" else "PayPal"
                add_payment_allocation(
                    finances_conn,
                    fee_type="membership_due",
                    allocated_amount=alloc_amt,
                    payment_method=tx["source"],
                    transaction_id=tx["id"],
                    period=per,
                    player_id=player_id,
                    note=f"{source_label} {tx.get('tx_code') or ''}".strip(),
                )
                remaining_amount -= alloc_amt
                covered += 1

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
            m_status = resolve_player_membership_status(player_id, finances_conn, accounts_conn, as_of_date=mdate)
            if m_status != "guest":
                continue

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
    # 1. Exact match
    for row in alias_rows:
        if normalize_text(row["alias"]) == norm_guest:
            return row["player_id"]

    # 2. Match within parentheses e.g. 'Konsti+1 (Jens)' -> 'Jens'
    import re as _re
    for row in alias_rows:
        alias_raw = row["alias"]
        m = _re.search(r'\((.*?)\)', alias_raw)
        if m and normalize_text(m.group(1)) == norm_guest:
            return row["player_id"]
    
    # 3. Fuzzy: check if any alias is a substring or starts-with
    guest_tokens = norm_guest.split()
    for row in alias_rows:
        norm_alias = normalize_text(row["alias"])
        if not norm_alias:
            continue
        alias_tokens = norm_alias.split()
        for token in guest_tokens:
            if token in alias_tokens or token == norm_alias or (len(token) >= 3 and token.startswith(norm_alias)):
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
    """Generate a smart-split suggestion for a member's payment.
    Supports both:
    1. Combination payment: Membership due + guest fees (e.g. 69,00 € = 48€ Beitrag + 21€ Gäste)
    2. Proxy guest payment: Multiples of 3,50 € on behalf of guests.
    """
    finances_conn = get_finances_connection()
    rb48_conn = get_rb48_connection()
    accounts_conn = get_accounts_connection()
    
    try:
        tx = get_transaction_by_id(finances_conn, transaction_id)
        if not tx or tx["amount"] <= 0:
            return None
        
        amount = float(tx["amount"])
        status = resolve_player_membership_status(payer_player_id, finances_conn, accounts_conn)
        
        from scripts.finances.matcher import analyze_payment_note
        tx_note = tx.get("note") or ""
        note_analysis = analyze_payment_note(tx_note)
        has_due_hint = note_analysis.get("has_due_hint", False)
        period_hint = note_analysis.get("period_hint") or "2026-H2"
        note_guest_names = note_analysis.get("guest_names", [])

        is_combo_split = False
        due_amount = 0.0
        guest_amount = 0.0
        num_kicks = 0

        # Check if combination payment (Mitgliedsbeitrag + Gastbeiträge)
        if status == 'member':
            rem_after_due = round(amount - MEMBERSHIP_DUE_PER_HALFYEAR, 2)
            if rem_after_due >= 0:
                rem_mod = rem_after_due % GUEST_FEE_PER_KICK
                rem_is_mult = rem_mod < 0.01 or (GUEST_FEE_PER_KICK - rem_mod) < 0.01
                if rem_after_due > 0 and (rem_is_mult or has_due_hint or len(note_guest_names) > 0):
                    is_combo_split = True
                    due_amount = MEMBERSHIP_DUE_PER_HALFYEAR
                    guest_amount = rem_after_due
                    num_kicks = round(guest_amount / GUEST_FEE_PER_KICK)

        if not is_combo_split:
            remainder = amount % GUEST_FEE_PER_KICK
            if remainder <= 0.01 or (GUEST_FEE_PER_KICK - remainder) <= 0.01:
                guest_amount = amount
                num_kicks = round(amount / GUEST_FEE_PER_KICK)
            else:
                return None

        if num_kicks <= 0 and not is_combo_split:
            return None

        players_dict = get_players(rb48_conn)
        payer_pdata = players_dict.get(payer_player_id, {})
        payer_name = payer_pdata.get("aliases", [f"Spieler #{payer_player_id}"])[0]

        suggested_guests = []
        all_unpaid = get_all_unpaid_guest_entries()

        # Step 1: Match specifically mentioned guests in note
        if note_guest_names:
            for gname in note_guest_names:
                if len(suggested_guests) >= num_kicks:
                    break
                g_pid = _find_guest_player_id(gname, rb48_conn, players_dict)
                if g_pid:
                    g_name = players_dict.get(g_pid, {}).get("aliases", [gname])[0]
                    # Find open unpaid matches for this player
                    p_unpaid = [u for u in all_unpaid if u.get("player_id") == g_pid]
                    for entry in p_unpaid:
                        if len(suggested_guests) >= num_kicks:
                            break
                        suggested_guests.append({
                            "player_id": g_pid,
                            "name": g_name,
                            "match_date": entry.get("match_date"),
                            "amount": GUEST_FEE_PER_KICK,
                        })
                else:
                    # External / ignored alias
                    alias_unpaid = [u for u in all_unpaid if u.get("name", "").casefold() == gname.casefold()]
                    if alias_unpaid:
                        for entry in alias_unpaid:
                            if len(suggested_guests) >= num_kicks:
                                break
                            suggested_guests.append({
                                "player_id": None,
                                "guest_alias": gname,
                                "name": gname,
                                "match_date": entry.get("match_date"),
                                "amount": GUEST_FEE_PER_KICK,
                            })
                    else:
                        suggested_guests.append({
                            "player_id": None,
                            "guest_alias": gname,
                            "name": gname,
                            "match_date": None,
                            "amount": GUEST_FEE_PER_KICK,
                        })

        # Step 2: Nearby match dates / planner registered guests if still slots available
        if len(suggested_guests) < num_kicks:
            tx_date = tx["date"]
            date_rows = rb48_conn.execute(
                """
                SELECT DISTINCT date
                FROM matches
                WHERE ABS(julianday(date) - julianday(?)) <= 5
                ORDER BY ABS(julianday(date) - julianday(?)) ASC
                """,
                (tx_date, tx_date),
            ).fetchall()
            for drow in date_rows:
                if len(suggested_guests) >= num_kicks:
                    break
                mdate = drow["date"]
                mguests = find_member_guests_for_date(
                    payer_player_id, mdate,
                    finances_conn=finances_conn,
                    rb48_conn=rb48_conn,
                    accounts_conn=accounts_conn,
                )
                for mg in mguests:
                    if len(suggested_guests) >= num_kicks:
                        break
                    if not any(sg.get("player_id") == mg["player_id"] and sg.get("match_date") == mdate for sg in suggested_guests):
                        suggested_guests.append({
                            "player_id": mg["player_id"],
                            "name": mg["name"],
                            "match_date": mdate,
                            "amount": GUEST_FEE_PER_KICK,
                        })

        # Step 3: If still unfilled, fill with remaining unpaid entries
        if len(suggested_guests) < num_kicks:
            for entry in all_unpaid:
                if len(suggested_guests) >= num_kicks:
                    break
                if not any(sg.get("player_id") == entry.get("player_id") and sg.get("match_date") == entry.get("match_date") for sg in suggested_guests):
                    suggested_guests.append({
                        "player_id": entry.get("player_id"),
                        "guest_alias": entry.get("name") if not entry.get("player_id") else None,
                        "name": entry.get("name"),
                        "match_date": entry.get("match_date"),
                        "amount": GUEST_FEE_PER_KICK,
                    })

        # Build human-readable summary text and explicit date breakdown
        guest_counts = {}
        guest_by_person = {}
        for g in suggested_guests[:num_kicks]:
            gname = g.get("name") or "Gast"
            guest_counts[gname] = guest_counts.get(gname, 0) + 1
            mdate = g.get("match_date")
            guest_by_person.setdefault(gname, []).append(mdate)

        guest_summary_parts = [f"{cnt}× {name}" for name, cnt in guest_counts.items()]
        guest_summary_str = ", ".join(guest_summary_parts) if guest_summary_parts else f"{num_kicks}× Gastbeitrag"

        # Explicit date breakdown
        guest_details_parts = []
        for gname, mdates in guest_by_person.items():
            valid_dates = [d[5:].replace("-", ".") for d in mdates if d]
            if valid_dates:
                guest_details_parts.append(f"{len(mdates)}× {gname} ({', '.join(valid_dates)})")
            else:
                guest_details_parts.append(f"{len(mdates)}× {gname}")

        guest_details_str = ", ".join(guest_details_parts)

        if is_combo_split:
            due_str = f"{due_amount:.2f}".replace('.', ',')
            guest_str = f"{guest_amount:.2f}".replace('.', ',')
            summary_text = f"{due_str} € Beitrag ({payer_name}) + {guest_str} € Gäste ({guest_summary_str})"
            cleared_debts_summary = f"Mitgliedsbeitrag {period_hint} ({due_str} € für {payer_name}) + {guest_details_str}"
        else:
            amt_str = f"{amount:.2f}".replace('.', ',')
            summary_text = f"{amt_str} € Gäste ({guest_summary_str})"
            cleared_debts_summary = f"{amt_str} € ({guest_details_str})"

        return {
            "is_proxy_payment": True,
            "is_combo_split": is_combo_split,
            "num_kicks": num_kicks,
            "total": amount,
            "due_amount": due_amount,
            "guest_amount": guest_amount,
            "period": period_hint,
            "payer_player_id": payer_player_id,
            "payer_name": payer_name,
            "suggested_guests": suggested_guests[:num_kicks],
            "note_hints": note_guest_names,
            "summary_text": summary_text,
            "cleared_debts_summary": cleared_debts_summary,
        }
    finally:
        finances_conn.close()
        rb48_conn.close()
        accounts_conn.close()


def settle_smart_combo_transaction(
    transaction_id: int,
    payer_player_id: int | None = None,
    suggestion: dict | None = None,
) -> dict:
    """Execute settlement of a combination payment or proxy suggestion."""
    finances_conn = get_finances_connection()
    rb48_conn = get_rb48_connection()
    accounts_conn = get_accounts_connection()
    try:
        tx = get_transaction_by_id(finances_conn, transaction_id)
        if not tx:
            return {"success": False, "error": "Transaktion nicht gefunden"}

        if not payer_player_id:
            payer_player_id = tx.get("matched_player_id")

        if not suggestion:
            if not payer_player_id:
                match = find_player_match(tx.get("raw_payer_name"), tx.get("raw_payer_email"), finances_conn=finances_conn, rb48_conn=rb48_conn, accounts_conn=accounts_conn)
                payer_player_id = match.get("player_id")
            if payer_player_id:
                suggestion = get_proxy_payment_suggestion(transaction_id, payer_player_id)

        if not suggestion:
            return settle_transaction_and_debts(transaction_id, payer_player_id=payer_player_id)

        payer_pid = suggestion.get("payer_player_id") or payer_player_id
        payer_name = suggestion.get("payer_name") or tx.get("raw_payer_name") or "Zahler"

        # 1. Allocate membership due if combo split
        if suggestion.get("is_combo_split") and suggestion.get("due_amount", 0) > 0:
            due_per = suggestion.get("period") or "2026-H2"
            add_payment_allocation(
                finances_conn,
                fee_type="membership_due",
                allocated_amount=suggestion["due_amount"],
                payment_method=tx["source"],
                transaction_id=transaction_id,
                period=due_per,
                player_id=payer_pid,
                note=f"Vereinsbeitrag {due_per} ({payer_name})",
            )

        # 2. Allocate guest kicks
        for g in suggestion.get("suggested_guests", []):
            add_payment_allocation(
                finances_conn,
                fee_type="match_guest",
                allocated_amount=float(g.get("amount", GUEST_FEE_PER_KICK)),
                payment_method=tx["source"],
                transaction_id=transaction_id,
                match_date=g.get("match_date"),
                player_id=g.get("player_id"),
                guest_alias=g.get("guest_alias"),
                paid_by_player_id=payer_pid,
                note=f"Bezahlt von {payer_name}",
            )

        # 3. Mark transaction assigned and confirmed
        update_transaction_assignment(
            finances_conn,
            transaction_id,
            player_id=payer_pid,
            status="assigned",
            is_confirmed=1,
        )

        return {"success": True, "suggestion": suggestion}
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
    current_year = get_cologne_now().year
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

        partial_dues_count = 0
        for dp in due_periods:
            d_ov = get_membership_dues_overview(dp)
            open_dues_amount += d_ov.get("outstanding", 0.0)
            open_dues_count += sum(1 for mem in d_ov.get("members", []) if mem.get("payment_status") == "unpaid")
            partial_dues_count += sum(1 for mem in d_ov.get("members", []) if mem.get("payment_status") == "partial")
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
            "partial_dues_count": partial_dues_count,
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
    payer_player_id: int | str | None = None,
    beneficiary_player_id: int | str | None = None,
    match_date: str | None = None,
    remember: bool = False,
    current_user_id: int | None = None,
    note: str | None = None,
    beneficiary_alias: str | None = None,
    target_settlement: str | None = None,
) -> dict:
    """
    Settle a transaction directly, covering debts for either the payer themselves
    or on behalf of another guest player (e.g. Claudio paying for Paul, or Julian paying for Malte).
    Supports regular player IDs as well as ignored aliases (via 'ignored:NAME' or beneficiary_alias).
    Also links any existing manual allocations for this player/alias/date.
    """
    finances_conn = get_finances_connection()
    rb48_conn = get_rb48_connection()
    accounts_conn = get_accounts_connection()

    try:
        tx = get_transaction_by_id(finances_conn, transaction_id)
        if not tx:
            return {"success": False, "error": "Transaktion nicht gefunden"}

        # Resolve payer
        payer_pid = None
        payer_alias = None
        if isinstance(payer_player_id, str) and payer_player_id.startswith("ignored:"):
            payer_alias = payer_player_id.split(":", 1)[1]
        elif payer_player_id is not None:
            try:
                payer_pid = int(payer_player_id)
            except (ValueError, TypeError):
                payer_alias = str(payer_player_id)

        if not payer_pid and not payer_alias:
            payer_pid = tx.get("matched_player_id")
        if not payer_pid and not payer_alias:
            match = find_player_match(
                tx.get("raw_payer_name"),
                tx.get("raw_payer_email"),
                finances_conn=finances_conn,
                rb48_conn=rb48_conn,
                accounts_conn=accounts_conn,
            )
            if match.get("player_id") and match.get("confidence", 0) >= 0.60:
                payer_pid = match["player_id"]

        # Fallback: if payer is not registered in system, use raw payer name or email as alias
        if not payer_pid and not payer_alias:
            payer_alias = tx.get("raw_payer_name") or tx.get("raw_payer_email") or "Zahler"

        # Resolve beneficiary
        bene_pid = None
        bene_alias = beneficiary_alias
        if isinstance(beneficiary_player_id, str) and (beneficiary_player_id.startswith("ignored:") or not beneficiary_player_id.isdigit()):
            if beneficiary_player_id.startswith("ignored:"):
                bene_alias = beneficiary_player_id.split(":", 1)[1]
            elif beneficiary_player_id.strip():
                bene_alias = str(beneficiary_player_id).strip()
        elif beneficiary_player_id is not None and not bene_alias:
            try:
                bene_pid = int(beneficiary_player_id)
            except (ValueError, TypeError):
                bene_alias = str(beneficiary_player_id)

        if not bene_pid and not bene_alias:
            bene_pid = payer_pid
            bene_alias = payer_alias

        # Strictly remember identity only for payer_pid (never for beneficiary if proxy)
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
        if target_settlement == "credit_only":
            return {"success": True, "covered_count": 0, "status": "assigned"}

        remaining_amount = float(tx.get("amount", 0))
        covered_count = 0

        payer_name = "Zahler"
        if payer_pid:
            players_dict = get_players(rb48_conn)
            payer_pdata = players_dict.get(payer_pid, {})
            payer_name = payer_pdata.get("aliases", [f"Spieler #{payer_pid}"])[0]
        elif payer_alias:
            payer_name = payer_alias
        elif tx.get("raw_payer_name"):
            payer_name = tx["raw_payer_name"]

        alloc_note = note
        if not alloc_note:
            is_proxy = (bene_pid and payer_pid and bene_pid != payer_pid) or (bene_alias and bene_alias != payer_alias)
            if is_proxy:
                alloc_note = f"Bezahlt von {payer_name}"
            else:
                alloc_note = f"PayPal {tx['tx_code'] or ''}".strip()

        # Determine settlement target preference
        inferred = infer_transaction_settlement_target(
            remaining_amount, tx.get("date"), tx.get("note"), tx.get("description"), bene_pid
        )
        effective_target = target_settlement if (target_settlement and target_settlement != "auto") else None
        if not effective_target and (inferred.get("has_due_hint") or (inferred.get("target_settlement") or "").startswith("due:")):
            effective_target = inferred["target_settlement"]

        # Case A: Beneficiary is an ignored alias (external player)
        if bene_alias and remaining_amount > 0:
            # 1. Check existing manual allocations without transaction_id for this alias
            if match_date:
                manual_rows = finances_conn.execute(
                    """
                    SELECT id, allocated_amount FROM payment_allocations
                    WHERE match_date = ? AND fee_type = 'match_guest' AND transaction_id IS NULL
                    AND (guest_alias = ? OR (guest_alias IS NULL AND player_id IS NULL AND note LIKE ?))
                    """,
                    (match_date, bene_alias, f"%{bene_alias}%"),
                ).fetchall()
            else:
                manual_rows = finances_conn.execute(
                    """
                    SELECT id, allocated_amount FROM payment_allocations
                    WHERE fee_type = 'match_guest' AND transaction_id IS NULL
                    AND (guest_alias = ? OR (guest_alias IS NULL AND player_id IS NULL AND note LIKE ?))
                    ORDER BY match_date DESC
                    """,
                    (bene_alias, f"%{bene_alias}%"),
                ).fetchall()

            for mr in manual_rows:
                if remaining_amount < GUEST_FEE_PER_KICK:
                    break
                finances_conn.execute(
                    """
                    UPDATE payment_allocations
                    SET transaction_id = ?, payment_method = ?, paid_by_player_id = ?, guest_alias = ?, note = ?
                    WHERE id = ?
                    """,
                    (
                        transaction_id,
                        tx["source"],
                        payer_pid,
                        bene_alias,
                        alloc_note,
                        mr["id"],
                    ),
                )
                remaining_amount -= GUEST_FEE_PER_KICK
                covered_count += 1

            # 2. Check unpaid match guest fees for this alias
            if remaining_amount >= GUEST_FEE_PER_KICK:
                if match_date:
                    dates_to_check = [match_date]
                else:
                    dates_to_check = get_all_match_dates_for_ignored_alias(bene_alias, rb48_conn)

                for mdate in dates_to_check:
                    if remaining_amount < GUEST_FEE_PER_KICK:
                        break
                    allocs = get_allocations_for_match_date(finances_conn, mdate)
                    ign_allocs = [
                        a for a in allocs
                        if (a.get("guest_alias") and a["guest_alias"].casefold() == bene_alias.casefold())
                        or (not a.get("player_id") and not a.get("guest_alias") and bene_alias.casefold() in (a.get("note") or "").casefold())
                    ]
                    paid_sum = sum(a["allocated_amount"] for a in ign_allocs if a["payment_method"] != "waived")
                    if paid_sum >= GUEST_FEE_PER_KICK:
                        continue

                    add_payment_allocation(
                        finances_conn,
                        fee_type="match_guest",
                        allocated_amount=GUEST_FEE_PER_KICK,
                        payment_method=tx["source"],
                        transaction_id=transaction_id,
                        match_date=mdate,
                        player_id=None,
                        guest_alias=bene_alias,
                        paid_by_player_id=payer_pid,
                        note=alloc_note,
                    )
                    remaining_amount -= GUEST_FEE_PER_KICK
                    covered_count += 1

        # Case B: Beneficiary is a registered player (guest or member with historical guest fees)
        elif bene_pid and remaining_amount > 0:
            # B1. If membership dues are targeted (explicitly or inferred from text/amount/status), allocate dues FIRST
            if effective_target and effective_target.startswith("due:"):
                req_part = effective_target.split(":", 1)[1]
                if req_part.endswith("-year") or (len(req_part) == 4 and req_part.isdigit()):
                    yr = req_part[:4]
                    due_pers = [f"{yr}-H1", f"{yr}-H2"]
                else:
                    due_pers = [req_part]

                for per in due_pers:
                    if remaining_amount <= 0:
                        break
                    allocs = get_allocations_for_period(finances_conn, per)
                    p_allocs = [a for a in allocs if a.get("player_id") == bene_pid]
                    paid_sum = sum(a["allocated_amount"] for a in p_allocs if a["payment_method"] != "waived")
                    if paid_sum >= MEMBERSHIP_DUE_PER_HALFYEAR:
                        continue

                    alloc_amt = min(remaining_amount, max(0.0, MEMBERSHIP_DUE_PER_HALFYEAR - paid_sum))
                    if alloc_amt <= 0:
                        alloc_amt = min(remaining_amount, MEMBERSHIP_DUE_PER_HALFYEAR)

                    add_payment_allocation(
                        finances_conn,
                        fee_type="membership_due",
                        allocated_amount=alloc_amt,
                        payment_method=tx["source"],
                        transaction_id=transaction_id,
                        period=per,
                        player_id=bene_pid,
                        paid_by_player_id=payer_pid if payer_pid != bene_pid else None,
                        note=alloc_note or f"Mitgliedsbeitrag {per}",
                    )
                    remaining_amount -= alloc_amt
                    covered_count += 1

            # B2. Check existing manual allocations without transaction_id for the beneficiary (if kicks not skipped)
            if effective_target != "due_only" and remaining_amount >= GUEST_FEE_PER_KICK:
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

            # B3. Check unpaid match guest fees for beneficiary
            if effective_target != "due_only" and remaining_amount >= GUEST_FEE_PER_KICK:
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
                    m_status = resolve_player_membership_status(bene_pid, finances_conn, accounts_conn, as_of_date=mdate)
                    if m_status != "guest":
                        continue
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

            # B4. If beneficiary is a member and dues were NOT already allocated above, allocate to membership dues
            status = resolve_player_membership_status(bene_pid, finances_conn, accounts_conn)
            if remaining_amount > 0 and status == "member" and not (effective_target and effective_target.startswith("due:")):
                for per in inferred.get("periods", ("2026-H1", "2026-H2")):
                    if remaining_amount <= 0:
                        break
                    allocs = get_allocations_for_period(finances_conn, per)
                    p_allocs = [a for a in allocs if a.get("player_id") == bene_pid]
                    paid_sum = sum(a["allocated_amount"] for a in p_allocs if a["payment_method"] != "waived")
                    if paid_sum >= MEMBERSHIP_DUE_PER_HALFYEAR:
                        continue

                    alloc_amt = min(remaining_amount, max(0.0, MEMBERSHIP_DUE_PER_HALFYEAR - paid_sum))
                    if alloc_amt <= 0:
                        alloc_amt = remaining_amount

                    add_payment_allocation(
                        finances_conn,
                        fee_type="membership_due",
                        allocated_amount=alloc_amt,
                        payment_method=tx["source"],
                        transaction_id=transaction_id,
                        period=per,
                        player_id=bene_pid,
                        paid_by_player_id=payer_pid if payer_pid != bene_pid else None,
                        note=alloc_note or f"Mitgliedsbeitrag {per}",
                    )
                    remaining_amount -= alloc_amt
                    covered_count += 1

        # Fallback: if there is still remaining amount (e.g. advance payment, external player like Martin Wagener, etc.),
        # allocate remaining funds to the beneficiary / payer so the transaction is accounted for.
        if remaining_amount > 0 and (bene_alias or bene_pid):
            bene_status = resolve_player_membership_status(bene_pid, finances_conn, accounts_conn) if bene_pid else "guest"
            fee_t = "membership_due" if (bene_status == "member" or (not bene_alias and remaining_amount >= 15.0)) else "match_guest"
            add_payment_allocation(
                finances_conn,
                fee_type=fee_t,
                allocated_amount=remaining_amount,
                payment_method=tx.get("source", "paypal"),
                transaction_id=transaction_id,
                match_date=match_date or tx.get("date"),
                player_id=bene_pid,
                guest_alias=bene_alias,
                paid_by_player_id=payer_pid if payer_pid != bene_pid else None,
                note=alloc_note,
            )
            covered_count += 1
            remaining_amount = 0.0

        finances_conn.commit()
        return {
            "success": True,
            "transaction_id": transaction_id,
            "payer_player_id": payer_pid,
            "beneficiary_player_id": bene_pid,
            "beneficiary_alias": bene_alias,
            "covered_count": covered_count,
        }
    finally:
        finances_conn.close()
        rb48_conn.close()
        accounts_conn.close()


def sync_rule_based_receivables(finances_conn=None, rb48_conn=None, accounts_conn=None) -> dict:
    """
    Synchronize all rule-based membership dues and match guest kicks into finance_receivables.
    - Idempotent: does not create duplicate receivables.
    - Retroactively links existing payment_allocations to their matching receivable_id.
    - Calculates and updates receivable status ('open', 'partial', 'settled', 'waived').
    - Respects manual_settled=1 overrides (partial payments manually marked settled remain settled).
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

    created_dues = 0
    created_kicks = 0
    linked_allocations = 0

    try:
        # 1. Sync rule-based membership dues for all members across half-year periods
        try:
            pers = [p["value"] for p in get_available_finance_periods(finances_conn, rb48_conn) if p.get("type") == "halfyear"]
        except Exception:
            pers = ["2026-H1", "2026-H2"]

        members = [p for p in get_all_players_with_membership(finances_conn, rb48_conn, accounts_conn) if p.get("status") == "member"]

        for per in pers:
            p_range = get_period_date_range(per)
            due_date = p_range.get("end_date") or f"{per[:4]}-12-31"

            for m in members:
                pid = m["player_id"]
                existing = finances_conn.execute(
                    "SELECT id, status, manual_settled, note FROM finance_receivables WHERE kind = 'membership_due' AND player_id = ? AND period = ?",
                    (pid, per),
                ).fetchone()

                init_status = "open"
                init_note = None
                if p_range.get("has_ended"):
                    games_count = rb48_conn.execute(
                        "SELECT COUNT(DISTINCT m.match_id) as cnt FROM matches m JOIN match_players mp ON m.match_id = mp.match_id WHERE mp.player_id = ? AND m.date >= ? AND m.date <= ?",
                        (pid, p_range["start"], p_range["end"]),
                    ).fetchone()["cnt"] or 0
                    if games_count == 0:
                        init_status = "waived"
                        init_note = "De facto befreit (0 Kicks)"

                if not existing:
                    create_receivable(
                        finances_conn,
                        kind="membership_due",
                        amount=MEMBERSHIP_DUE_PER_HALFYEAR,
                        title=f"Mitgliedsbeitrag {per}",
                        player_id=pid,
                        period=per,
                        due_date=due_date,
                        status=init_status,
                        note=init_note,
                        source="rule",
                    )
                    created_dues += 1

        # 2. Sync match guest kicks
        match_dates = [
            row["date"] for row in rb48_conn.execute(
                "SELECT DISTINCT date FROM matches ORDER BY date ASC"
            ).fetchall()
        ]

        for mdate in match_dates:
            details = get_match_date_guest_status(mdate, finances_conn, rb48_conn, accounts_conn)
            for g in details.get("guest_entries", []):
                raw_pid = g.get("player_id")
                pid = None
                alias = None
                if raw_pid is not None and str(raw_pid).isdigit():
                    pid = int(raw_pid)
                elif isinstance(raw_pid, str) and raw_pid.startswith("ignored:"):
                    alias = raw_pid[8:]
                elif g.get("name"):
                    alias = g["name"]

                if not pid and not alias:
                    continue

                if pid:
                    existing = finances_conn.execute(
                        "SELECT id, status, manual_settled FROM finance_receivables WHERE kind = 'match_guest' AND player_id = ? AND match_date = ?",
                        (pid, mdate),
                    ).fetchone()
                else:
                    existing = finances_conn.execute(
                        "SELECT id, status, manual_settled FROM finance_receivables WHERE kind = 'match_guest' AND LOWER(guest_alias) = LOWER(?) AND match_date = ?",
                        (alias, mdate),
                    ).fetchone()

                if not existing:
                    create_receivable(
                        finances_conn,
                        kind="match_guest",
                        amount=GUEST_FEE_PER_KICK,
                        title=f"Gastbeitrag {mdate}",
                        player_id=pid,
                        guest_alias=alias,
                        match_date=mdate,
                        due_date=mdate,
                        status="open",
                        source="rule",
                    )
                    created_kicks += 1

        # 3. Link unlinked payment_allocations to matching receivables and update statuses
        all_recs = finances_conn.execute("SELECT * FROM finance_receivables").fetchall()
        for rec in all_recs:
            rid = rec["id"]
            r_kind = rec["kind"]
            r_pid = rec["player_id"]
            r_alias = rec["guest_alias"]
            r_per = rec["period"]
            r_mdate = rec["match_date"]
            r_amount = float(rec["amount"])
            manual_settled = int(dict(rec).get("manual_settled", 0) or 0)

            if r_kind == "membership_due" and r_pid and r_per:
                matching_allocs = finances_conn.execute(
                    "SELECT id, allocated_amount, payment_method, receivable_id FROM payment_allocations WHERE fee_type = 'membership_due' AND player_id = ? AND period = ?",
                    (r_pid, r_per),
                ).fetchall()
            elif r_kind == "match_guest" and r_mdate:
                if r_pid:
                    matching_allocs = finances_conn.execute(
                        "SELECT id, allocated_amount, payment_method, receivable_id FROM payment_allocations WHERE fee_type = 'match_guest' AND player_id = ? AND match_date = ?",
                        (r_pid, r_mdate),
                    ).fetchall()
                else:
                    matching_allocs = finances_conn.execute(
                        "SELECT id, allocated_amount, payment_method, receivable_id FROM payment_allocations WHERE fee_type = 'match_guest' AND (LOWER(guest_alias) = LOWER(?) OR note LIKE ?) AND match_date = ?",
                        (r_alias, f"%{r_alias}%", r_mdate),
                    ).fetchall()
            else:
                matching_allocs = finances_conn.execute(
                    "SELECT id, allocated_amount, payment_method, receivable_id FROM payment_allocations WHERE receivable_id = ?",
                    (rid,),
                ).fetchall()

            for ma in matching_allocs:
                if not ma["receivable_id"]:
                    finances_conn.execute(
                        "UPDATE payment_allocations SET receivable_id = ? WHERE id = ?",
                        (rid, ma["id"]),
                    )
                    linked_allocations += 1

            if manual_settled == 1:
                new_status = "settled"
            elif manual_settled == 2:
                new_status = "open"
            else:
                has_waived = any(ma["payment_method"] == "waived" for ma in matching_allocs)
                total_paid = sum(float(ma["allocated_amount"] or 0.0) for ma in matching_allocs if ma["payment_method"] != "waived")
                if total_paid >= r_amount:
                    new_status = "settled"
                elif total_paid > 0:
                    new_status = "partial"
                elif has_waived:
                    new_status = "waived"
                else:
                    # Check de facto waived for ended periods with 0 kicks
                    is_de_facto_waived = False
                    if r_kind == "membership_due" and r_per and r_pid:
                        p_range = get_period_date_range(r_per)
                        if p_range.get("has_ended"):
                            games_cnt = rb48_conn.execute(
                                "SELECT COUNT(DISTINCT m.match_id) as cnt FROM matches m JOIN match_players mp ON m.match_id = mp.match_id WHERE mp.player_id = ? AND m.date >= ? AND m.date <= ?",
                                (r_pid, p_range["start"], p_range["end"]),
                            ).fetchone()["cnt"] or 0
                            if games_cnt == 0:
                                is_de_facto_waived = True

                    if is_de_facto_waived:
                        new_status = "waived"
                        if not rec["note"] or "de facto" not in (rec["note"] or "").lower():
                            finances_conn.execute(
                                "UPDATE finance_receivables SET note = 'De facto befreit (0 Kicks)' WHERE id = ?",
                                (rid,),
                            )
                    else:
                        new_status = "open"

            if new_status != rec["status"]:
                finances_conn.execute(
                    "UPDATE finance_receivables SET status = ? WHERE id = ?",
                    (new_status, rid),
                )

        finances_conn.commit()
        return {
            "created_dues": created_dues,
            "created_kicks": created_kicks,
            "linked_allocations": linked_allocations,
            "total_receivables": len(all_recs) + created_dues + created_kicks,
        }
    finally:
        if close_fin:
            finances_conn.close()
        if close_rb:
            rb48_conn.close()
        if close_acc:
            accounts_conn.close()


def create_manual_due_receivables(
    period: str,
    player_ids: list[int] | None = None,
    finances_conn=None,
    rb48_conn=None,
    accounts_conn=None,
) -> int:
    """
    Manually create membership due receivables for a period (e.g. 2026-H1 or any historical period)
    where no match attendance exists. Can be for all active members or selected players.
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
        if player_ids is None:
            members = [p for p in get_all_players_with_membership(finances_conn, rb48_conn, accounts_conn) if p.get("status") == "member"]
            pids = [m["player_id"] for m in members]
        else:
            pids = player_ids

        p_range = get_period_date_range(period)
        due_date = p_range.get("end") or p_range.get("end_date") or f"{period[:4]}-06-30"

        created = 0
        for pid in pids:
            existing = finances_conn.execute(
                "SELECT id FROM finance_receivables WHERE kind = 'membership_due' AND player_id = ? AND period = ?",
                (pid, period),
            ).fetchone()
            if not existing:
                create_receivable(
                    finances_conn,
                    kind="membership_due",
                    amount=MEMBERSHIP_DUE_PER_HALFYEAR,
                    title=f"Mitgliedsbeitrag {period}",
                    player_id=pid,
                    period=period,
                    due_date=due_date,
                    status="open",
                    source="manual",
                )
                created += 1

        finances_conn.commit()
        return created
    finally:
        if close_fin:
            finances_conn.close()
        if close_rb:
            rb48_conn.close()
        if close_acc:
            accounts_conn.close()


def allocate_transaction_receivables(
    transaction_id: int,
    payer_player_id: int | str | None = None,
    allocations: list[dict] | None = None,
    remember: bool = False,
    current_user_id: int | None = None,
    note: str | None = None,
) -> dict:
    """
    Manually allocate a transaction to one or more specific receivables.
    Supports partial payments, marking a receivable as fully settled even on partial payment,
    and booking any remainder as credit/surplus.
    `allocations` is a list of dicts:
        [
            {"receivable_id": int, "amount": float, "mark_settled": bool (optional)},
            ...
        ]
    """
    finances_conn = get_finances_connection()
    rb48_conn = get_rb48_connection()
    accounts_conn = get_accounts_connection()
    try:
        tx = get_transaction_by_id(finances_conn, transaction_id)
        if not tx:
            return {"success": False, "error": "Transaktion nicht gefunden"}

        payer_pid = None
        payer_alias = None
        if isinstance(payer_player_id, str) and payer_player_id.startswith("ignored:"):
            payer_alias = payer_player_id.split(":", 1)[1]
        elif payer_player_id is not None:
            try:
                payer_pid = int(payer_player_id)
            except (ValueError, TypeError):
                payer_alias = str(payer_player_id)

        if not payer_pid and not payer_alias:
            payer_pid = tx.get("matched_player_id")
        if not payer_pid and not payer_alias:
            payer_alias = tx.get("raw_payer_name") or tx.get("raw_payer_email") or "Zahler"

        update_transaction_assignment(
            finances_conn,
            transaction_id,
            player_id=payer_pid,
            status="assigned",
            is_confirmed=1,
        )

        if remember and payer_pid:
            save_or_update_identity(
                finances_conn,
                player_id=payer_pid,
                payer_email=tx.get("raw_payer_email"),
                payer_name=tx.get("raw_payer_name"),
                confidence=1.0,
                created_by_user_id=current_user_id,
            )

        tx_amount = float(tx.get("amount", 0.0))
        remaining = tx_amount
        covered_count = 0

        alloc_list = allocations or []
        for item in alloc_list:
            rid = int(item["receivable_id"])
            amt = float(item["amount"])
            if amt <= 0:
                continue

            rec = get_receivable_by_id(finances_conn, rid)
            if not rec:
                continue

            mark_settled = bool(item.get("mark_settled", False))
            bene_pid = rec.get("player_id")
            bene_alias = rec.get("guest_alias")

            fee_type_to_save = rec["kind"] if rec["kind"] in ("match_guest", "membership_due") else "manual_adjustment"
            add_payment_allocation(
                finances_conn,
                fee_type=fee_type_to_save,
                allocated_amount=amt,
                payment_method=tx.get("source", "bank"),
                transaction_id=transaction_id,
                event_id=None,
                match_date=rec.get("match_date"),
                player_id=bene_pid,
                guest_alias=bene_alias,
                period=rec.get("period"),
                receivable_id=rid,
                paid_by_player_id=payer_pid if (payer_pid and payer_pid != bene_pid) else None,
                note=note or f"Begleicht {rec['title']}",
            )
            covered_count += 1
            remaining -= amt

            if mark_settled:
                update_receivable(finances_conn, rid, status="settled", manual_settled=1)
            else:
                allocs = get_allocations_for_receivable(finances_conn, rid)
                tot_paid = sum(float(a["allocated_amount"] or 0.0) for a in allocs if a["payment_method"] != "waived")
                if tot_paid >= float(rec["amount"]):
                    update_receivable(finances_conn, rid, status="settled")
                elif tot_paid > 0:
                    update_receivable(finances_conn, rid, status="partial")

        if remaining > 0.01:
            add_payment_allocation(
                finances_conn,
                fee_type="manual_adjustment",
                allocated_amount=remaining,
                payment_method=tx.get("source", "bank"),
                transaction_id=transaction_id,
                player_id=payer_pid,
                guest_alias=payer_alias,
                note=f"Guthaben / Überzahlung ({remaining:.2f} €)",
            )

        finances_conn.commit()
        return {
            "success": True,
            "transaction_id": transaction_id,
            "covered_count": covered_count,
            "remaining_credit": max(0.0, remaining),
        }
    finally:
        finances_conn.close()
        rb48_conn.close()
        accounts_conn.close()


def reset_transaction_settlement(transaction_id: int):
    """Reset a transaction back to 'imported' (unconfirmed) and remove/detach allocations."""
    finances_conn = get_finances_connection()
    try:
        aff_rows = finances_conn.execute(
            "SELECT DISTINCT receivable_id FROM payment_allocations WHERE transaction_id = ? AND receivable_id IS NOT NULL",
            (transaction_id,),
        ).fetchall()
        aff_rids = [r["receivable_id"] for r in aff_rows]

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

        for rid in aff_rids:
            rec = get_receivable_by_id(finances_conn, rid)
            if rec and not rec.get("manual_settled"):
                paid = finances_conn.execute(
                    "SELECT SUM(allocated_amount) as s FROM payment_allocations WHERE receivable_id = ? AND payment_method != 'waived'",
                    (rid,),
                ).fetchone()["s"] or 0.0
                if paid >= float(rec["amount"]):
                    n_st = "settled"
                elif paid > 0:
                    n_st = "partial"
                else:
                    n_st = "open"
                update_receivable(finances_conn, rid, status=n_st)

        finances_conn.commit()
    finally:
        finances_conn.close()


class OpenDebtsDict(dict):
    """
    Dictionary of open debts storing all internal keys as strings to ensure json.dumps/tojson
    with sort_keys=True succeeds without int vs str comparison TypeError in Python 3.10+,
    while transparently supporting int and str lookups, and ignored alias prefixing.
    """
    def __getitem__(self, key):
        s_key = str(key)
        if super().__contains__(s_key):
            return super().__getitem__(s_key)
        if s_key.startswith("ignored:"):
            trimmed = s_key[8:]
            if super().__contains__(trimmed):
                return super().__getitem__(trimmed)
        else:
            prefixed = f"ignored:{s_key}"
            if super().__contains__(prefixed):
                return super().__getitem__(prefixed)
        return super().__getitem__(s_key)

    def get(self, key, default=None):
        try:
            return self[key]
        except KeyError:
            return default

    def __contains__(self, key):
        s_key = str(key)
        if super().__contains__(s_key):
            return True
        if s_key.startswith("ignored:"):
            return super().__contains__(s_key[8:])
        return super().__contains__(f"ignored:{s_key}")


def get_all_players_open_debts(finances_conn=None, rb48_conn=None, accounts_conn=None) -> OpenDebtsDict:
    """
    Compute open debts for every player and external alias.
    Returns an OpenDebtsDict keyed by stringified player_id ('12') and 'ignored:<alias>' / '<alias>':
    {
        key: {
            "total_open": float,
            "guest_kicks_count": int,
            "guest_kicks": [ {"match_date": "2026-09-23", "amount": 3.50}, ... ],
            "dues": [ {"period": "2026-H2", "amount": 48.00}, ... ],
            "summary": "7,00 € offen (2 Kicks: 23.09., 30.09.)",
            "short_summary": "7,00 € (2 Kicks)",
            "is_member": bool,
        }
    }
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
        debts = OpenDebtsDict()

        # 1. Unpaid guest kicks across all match history
        all_unpaid_guests = get_all_unpaid_guest_entries()
        for g in all_unpaid_guests:
            raw_pid = g.get("player_id")
            if raw_pid is not None and str(raw_pid).isdigit():
                key = str(int(raw_pid))
            elif g.get("name"):
                key = f"ignored:{g['name']}"
            else:
                continue

            entry_amt = float(g.get("fee_required", GUEST_FEE_PER_KICK)) - float(g.get("amount_paid", 0.0))
            if entry_amt <= 0:
                continue

            d = debts.setdefault(key, {
                "total_open": 0.0,
                "guest_kicks_count": 0,
                "guest_kicks": [],
                "dues": [],
                "summary": "",
                "short_summary": "",
                "is_member": False,
            })
            d["total_open"] += entry_amt
            d["guest_kicks_count"] += 1
            d["guest_kicks"].append({
                "match_date": g.get("match_date"),
                "amount": entry_amt,
            })

        # 2. Unpaid membership dues for members across all available halfyears
        try:
            pers = [p["value"] for p in get_available_finance_periods(finances_conn, rb48_conn) if p.get("type") == "halfyear"]
            pers.sort()  # e.g. ['2026-H1', '2026-H2']
            for per in pers:
                dues_ov = get_membership_dues_overview(per)
                for m in dues_ov.get("members", []):
                    pid = str(m["player_id"])
                    due_open = float(m.get("fee_required", 0.0)) - float(m.get("amount_paid", 0.0))
                    # Only if active member and fee > 0 (skip if period ended and member was inactive)
                    if due_open > 0 and m.get("payment_status") in ("unpaid", "partial", "unpaid_inactive_ongoing"):
                        d = debts.setdefault(pid, {
                            "total_open": 0.0,
                            "guest_kicks_count": 0,
                            "guest_kicks": [],
                            "dues": [],
                            "summary": "",
                            "short_summary": "",
                            "is_member": True,
                        })
                        d["is_member"] = True
                        d["total_open"] += due_open
                        d["dues"].append({
                            "period": per,
                            "amount": due_open,
                        })
        except Exception:
            pass

        # 3. Special receivables (Sonderposten)
        try:
            specials = finances_conn.execute(
                "SELECT * FROM finance_receivables WHERE kind = 'special' AND status IN ('open', 'partial')"
            ).fetchall()
            for sp in specials:
                raw_pid = sp.get("player_id")
                if raw_pid is not None and str(raw_pid).isdigit():
                    key = str(int(raw_pid))
                elif sp.get("guest_alias"):
                    key = f"ignored:{sp['guest_alias']}"
                else:
                    continue

                paid = finances_conn.execute(
                    "SELECT SUM(allocated_amount) as s FROM payment_allocations WHERE receivable_id = ? AND payment_method != 'waived'",
                    (sp["id"],),
                ).fetchone()["s"] or 0.0
                sp_open = max(0.0, float(sp["amount"]) - float(paid))
                if sp_open <= 0:
                    continue

                d = debts.setdefault(key, {
                    "total_open": 0.0,
                    "guest_kicks_count": 0,
                    "guest_kicks": [],
                    "dues": [],
                    "specials": [],
                    "summary": "",
                    "short_summary": "",
                    "is_member": False,
                })
                d["total_open"] += sp_open
                if "specials" not in d:
                    d["specials"] = []
                d["specials"].append({
                    "id": sp["id"],
                    "title": sp["title"],
                    "amount": sp_open,
                    "due_date": sp["due_date"],
                })
        except Exception:
            pass

        # Build human-readable summaries for each player with debts
        for key in list(debts.keys()):
            d = debts[key]
            tot = d["total_open"]
            parts = []
            short_parts = []

            for due in d["dues"]:
                p_amt = f"{due['amount']:.2f}".replace('.', ',')
                parts.append(f"Beitrag {due['period']} ({p_amt} €)")
                short_parts.append(f"Beitrag {due['period']}")

            if d["guest_kicks_count"] > 0:
                dates = [k["match_date"][5:].replace("-", ".") for k in d["guest_kicks"] if k.get("match_date")]
                dates_str = ", ".join(dates[:4])
                if len(dates) > 4:
                    dates_str += f" (+{len(dates) - 4})"
                kick_sum = sum(k["amount"] for k in d["guest_kicks"])
                k_amt = f"{kick_sum:.2f}".replace('.', ',')
                parts.append(f"{d['guest_kicks_count']} Kick{'s' if d['guest_kicks_count'] > 1 else ''}: {dates_str}")
                short_parts.append(f"{d['guest_kicks_count']} Kick{'s' if d['guest_kicks_count'] > 1 else ''}")

            if d.get("specials"):
                for sp in d["specials"]:
                    sp_amt = f"{sp['amount']:.2f}".replace('.', ',')
                    parts.append(f"{sp['title']} ({sp_amt} €)")
                    short_parts.append(f"{sp['title']}")

            tot_str = f"{tot:.2f}".replace('.', ',')
            d["summary"] = f"{tot_str} € offen ({', '.join(parts)})"
            d["short_summary"] = f"{tot_str} € ({', '.join(short_parts)})"

            # Register clean alias key without prefix to support direct name lookup
            if str(key).startswith("ignored:"):
                debts[str(key)[8:]] = d

        return debts
    finally:
        if close_fin:
            finances_conn.close()
        if close_rb:
            rb48_conn.close()
        if close_acc:
            accounts_conn.close()


def infer_transaction_settlement_target(
    amount: float,
    tx_date: str | None = None,
    note: str | None = None,
    description: str | None = None,
    player_id: int | str | None = None,
    all_player_debts: dict | None = None,
) -> dict:
    """
    Intelligently infer which membership dues or debts a transaction is meant to settle,
    taking into account the transaction date, payment note/purpose (e.g. SoSe26, H1, 2026),
    transfer amount, and the player's actual open debts.
    """
    import re
    text = f"{note or ''} {description or ''}".strip().lower()

    # 1. Determine base year
    curr_year = str(get_cologne_now().year)
    year = curr_year
    year_match = re.search(r'\b(202\d)\b', text)
    year_short_match = re.search(r'\b(?:sose|wise|ss|ws)\s*(\d{2})\b', text)
    if year_match:
        year = year_match.group(1)
    elif year_short_match:
        year = f"20{year_short_match.group(1)}"
    elif tx_date and len(tx_date) >= 4 and tx_date[:4].isdigit():
        year = tx_date[:4]

    # 2. Check for explicit period hints in text
    has_h1_hint = bool(re.search(r'\b(sose|sommersemester|h1|1\.\s*halbjahr|1\.\s*hj|ss)\b', text))
    has_h2_hint = bool(re.search(r'\b(wise|wintersemester|h2|2\.\s*halbjahr|2\.\s*hj|ws)\b', text))
    has_year_hint = bool(re.search(r'\b(ganzjahr|gesamtjahr|jahresbeitrag|volljahr|h1\s*\+\s*h2|h1\s*und\s*h2|h1/h2)\b', text))
    if not has_year_hint and (f"beitrag {year}" in text or f"mitgliedsbeitrag {year}" in text):
        if amount >= (2 * MEMBERSHIP_DUE_PER_HALFYEAR - 0.5):
            has_year_hint = True

    has_due_hint = any(k in text for k in ("beitrag", "mitglied", "sose", "wise", "verein", "halbjahr"))
    is_dues_amount = amount >= (MEMBERSHIP_DUE_PER_HALFYEAR - 8.0)
    is_full_year_amount = abs(amount - (2 * MEMBERSHIP_DUE_PER_HALFYEAR)) < 1.0 or amount >= (2 * MEMBERSHIP_DUE_PER_HALFYEAR - 0.5)

    # 3. Determine target settlement and period ordering
    if not has_due_hint and not is_dues_amount:
        target_settlement = "kicks_only"
        periods = []
    elif has_year_hint or is_full_year_amount:
        target_settlement = f"due:{year}-year"
        periods = [f"{year}-H1", f"{year}-H2"]
    elif has_h1_hint:
        target_settlement = f"due:{year}-H1"
        periods = [f"{year}-H1", f"{year}-H2"]
    elif has_h2_hint:
        target_settlement = f"due:{year}-H2"
        periods = [f"{year}-H2", f"{year}-H1"]
    else:
        month = 1
        if tx_date and len(tx_date) >= 7 and tx_date[5:7].isdigit():
            try:
                month = int(tx_date[5:7])
            except ValueError:
                month = 1
        if month <= 6:
            target_settlement = f"due:{year}-H1"
            periods = [f"{year}-H1", f"{year}-H2"]
        else:
            target_settlement = f"due:{year}-H2"
            periods = [f"{year}-H2", f"{year}-H1"]

    return {
        "target_settlement": target_settlement,
        "periods": periods,
        "year": year,
        "has_due_hint": has_due_hint,
    }


def get_transaction_cleared_debts_preview(
    amount: float,
    player_id: int | str,
    all_player_debts: dict | None = None,
    finances_conn=None,
    rb48_conn=None,
    accounts_conn=None,
    tx_date: str | None = None,
    tx_note: str | None = None,
    tx_description: str | None = None,
    target_settlement: str | None = None,
) -> str:
    """
    Given a transaction amount and a candidate target player, determine exactly
    which open debt items would be settled upon confirmation.
    """
    if not player_id:
        return ""

    if all_player_debts is None:
        all_player_debts = get_all_players_open_debts(finances_conn, rb48_conn, accounts_conn)

    p_debts = all_player_debts.get(player_id)
    if target_settlement == "credit_only":
        return f"{amount:.2f}".replace('.', ',') + " € als Guthaben (keine Verrechnung mit offenen Posten)"

    inferred = infer_transaction_settlement_target(
        amount, tx_date=tx_date, note=tx_note, description=tx_description, player_id=player_id, all_player_debts=all_player_debts
    )

    effective_target = target_settlement if (target_settlement and target_settlement != "auto") else inferred["target_settlement"]

    rem = float(amount)
    cleared_items = []

    # 1. Target is explicit or inferred membership due period(s)
    if effective_target and effective_target.startswith("due:"):
        req_part = effective_target.split(":", 1)[1]
        if req_part.endswith("-year") or (len(req_part) == 4 and req_part.isdigit()):
            yr = req_part[:4]
            due_pers = [f"{yr}-H1", f"{yr}-H2"]
        else:
            due_pers = [req_part]

        for per in due_pers:
            if rem <= 0:
                break
            cov = min(rem, MEMBERSHIP_DUE_PER_HALFYEAR)
            cov_str = f"{cov:.2f}".replace('.', ',')
            cleared_items.append(f"Mitgliedsbeitrag {per} ({cov_str} €)")
            rem -= cov

        # If remaining amount is still left and player has open guest kicks, cover them
        if rem >= GUEST_FEE_PER_KICK and p_debts and p_debts.get("guest_kicks"):
            covered_kicks = []
            for k in p_debts["guest_kicks"]:
                k_amt = float(k["amount"])
                if rem < k_amt:
                    break
                mdate = k.get("match_date", "")
                mdate_short = mdate[5:].replace("-", ".") if mdate else ""
                covered_kicks.append(mdate_short)
                rem -= k_amt
            if covered_kicks:
                c_count = len(covered_kicks)
                c_tot = f"{c_count * GUEST_FEE_PER_KICK:.2f}".replace('.', ',')
                cleared_items.append(f"{c_count} Gastbeitrag{'s' if c_count > 1 else ''} ({', '.join(covered_kicks)} – gesamt {c_tot} €)")

    # 2. General debts clearance from p_debts
    elif p_debts and p_debts.get("total_open", 0.0) > 0:
        dues_list = list(p_debts.get("dues", []))
        if inferred.get("periods"):
            pref_order = {p: i for i, p in enumerate(inferred["periods"])}
            dues_list.sort(key=lambda d: pref_order.get(d["period"], 99))

        for due in dues_list:
            if rem <= 0:
                break
            due_amt = float(due["amount"])
            covered = min(rem, due_amt)
            cov_str = f"{covered:.2f}".replace('.', ',')
            cleared_items.append(f"Mitgliedsbeitrag {due['period']} ({cov_str} €)")
            rem -= covered

        if effective_target != "due_only":
            covered_kicks = []
            for k in p_debts.get("guest_kicks", []):
                k_amt = float(k["amount"])
                if rem < k_amt:
                    break
                mdate = k.get("match_date", "")
                mdate_short = mdate[5:].replace("-", ".") if mdate else ""
                covered_kicks.append(mdate_short)
                rem -= k_amt

            if covered_kicks:
                c_count = len(covered_kicks)
                c_tot = f"{c_count * GUEST_FEE_PER_KICK:.2f}".replace('.', ',')
                cleared_items.append(f"{c_count} Gastbeitrag{'s' if c_count > 1 else ''} ({', '.join(covered_kicks)} – gesamt {c_tot} €)")

    # 3. Fallback
    if not cleared_items:
        if p_debts and p_debts.get("total_open", 0.0) > 0:
            return f"{amount:.2f}".replace('.', ',') + " € (Teilbetrag / Anzahlung)"
        return "Keine offenen Posten im System erfasst (Zahlung auf Vorrat / Guthaben)"

    res = " + ".join(cleared_items)
    if rem > 0:
        rem_str = f"{rem:.2f}".replace('.', ',')
        res += f" (Rest {rem_str} € als Guthaben)"

    return res

