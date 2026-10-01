from datetime import datetime, timezone
from scripts.finances.database import (
    get_finances_connection,
    add_payment_allocation,
    get_allocations_for_event,
    get_allocations_for_player,
    get_transaction_by_id,
)
from scripts.planner.database import get_planner_connection
from scripts.accounts.database import get_accounts_connection
from scripts.database.database import get_connection as get_rb48_connection
from scripts.database.db_players import get_players


GUEST_FEE_PER_KICK = 3.50
MEMBERSHIP_DUE_PER_HALFYEAR = 48.00


def get_event_guest_status(event_id: int) -> dict:
    """
    Get financial guest fee breakdown for a specific planner event/matchday.
    """
    planner_conn = get_planner_connection()
    finances_conn = get_finances_connection()
    accounts_conn = get_accounts_connection()

    try:
        event = planner_conn.execute(
            "SELECT * FROM events WHERE id = ?", (event_id,)
        ).fetchone()
        if not event:
            return {}

        attendees = planner_conn.execute(
            """
            SELECT id, event_id, user_id, name, status, is_guest,
                   registered_by_user_id, guest_index, created_at
            FROM attendees
            WHERE event_id = ? AND status = 'attending'
            ORDER BY is_guest ASC, id ASC
            """,
            (event_id,),
        ).fetchall()

        allocations = get_allocations_for_event(finances_conn, event_id)
        alloc_by_attendee: dict[int, list[dict]] = {}
        for a in allocations:
            att_id = a.get("attendee_id")
            if att_id:
                alloc_by_attendee.setdefault(att_id, []).append(a)

        # Users cache for registered_by
        users_cache = {}
        user_rows = accounts_conn.execute("SELECT id, username, attendance_name, player_id FROM users").fetchall()
        for u in user_rows:
            users_cache[u["id"]] = dict(u)

        guest_entries = []
        total_guest_fees_expected = 0.0
        total_guest_fees_collected = 0.0

        for att in attendees:
            # We treat guests (is_guest=1) or visitors (user_id is None and not a known club member) as fee-relevant
            is_guest = bool(att["is_guest"])
            user_id = att["user_id"]
            reg_user_id = att["registered_by_user_id"]
            reg_user_name = users_cache.get(reg_user_id, {}).get("attendance_name") or users_cache.get(reg_user_id, {}).get("username") if reg_user_id else None

            # Check if this attendee is subject to guest fee
            is_fee_relevant = is_guest or (user_id is None)

            att_allocs = alloc_by_attendee.get(att["id"], [])
            paid_sum = sum(a["allocated_amount"] for a in att_allocs if a["payment_method"] != "waived")
            is_waived = any(a["payment_method"] == "waived" for a in att_allocs)

            if is_fee_relevant:
                total_guest_fees_expected += GUEST_FEE_PER_KICK
                total_guest_fees_collected += paid_sum

                if is_waived:
                    payment_status = "waived"
                elif paid_sum >= GUEST_FEE_PER_KICK:
                    payment_methods = {a["payment_method"] for a in att_allocs}
                    if "cash" in payment_methods and "paypal" not in payment_methods:
                        payment_status = "cash"
                    elif "bank" in payment_methods and "paypal" not in payment_methods:
                        payment_status = "bank"
                    else:
                        payment_status = "paid"
                elif paid_sum > 0:
                    payment_status = "partial"
                else:
                    payment_status = "unpaid"

                guest_entries.append({
                    "attendee_id": att["id"],
                    "name": att["name"],
                    "is_guest": is_guest,
                    "registered_by_user_id": reg_user_id,
                    "registered_by_name": reg_user_name,
                    "guest_index": att["guest_index"],
                    "fee_required": GUEST_FEE_PER_KICK,
                    "amount_paid": paid_sum,
                    "payment_status": payment_status,
                    "allocations": att_allocs,
                })

        return {
            "event": dict(event),
            "guest_entries": guest_entries,
            "total_guests": len(guest_entries),
            "total_expected": total_guest_fees_expected,
            "total_collected": total_guest_fees_collected,
            "outstanding": max(0.0, total_guest_fees_expected - total_guest_fees_collected),
        }
    finally:
        planner_conn.close()
        finances_conn.close()
        accounts_conn.close()


def get_all_events_financial_overview() -> list[dict]:
    """
    Return all planner events with summarized guest payment stats.
    """
    planner_conn = get_planner_connection()
    finances_conn = get_finances_connection()

    try:
        events = planner_conn.execute(
            "SELECT * FROM events ORDER BY event_date DESC, id DESC"
        ).fetchall()

        results = []
        for ev in events:
            attendees = planner_conn.execute(
                """
                SELECT id, is_guest, user_id FROM attendees
                WHERE event_id = ? AND status = 'attending' AND (is_guest = 1 OR user_id IS NULL)
                """,
                (ev["id"],),
            ).fetchall()

            guest_count = len(attendees)
            if guest_count == 0:
                continue

            allocations = get_allocations_for_event(finances_conn, ev["id"])
            paid_att_ids = {a["attendee_id"] for a in allocations if a.get("attendee_id") and (a["payment_method"] == "waived" or a["allocated_amount"] >= GUEST_FEE_PER_KICK)}
            
            paid_count = len(paid_att_ids.intersection({att["id"] for att in attendees}))
            unpaid_count = max(0, guest_count - paid_count)
            total_expected = guest_count * GUEST_FEE_PER_KICK
            total_collected = sum(a["allocated_amount"] for a in allocations if a["payment_method"] != "waived")

            results.append({
                "event_id": ev["id"],
                "event_date": ev["event_date"],
                "pitch": ev["pitch"],
                "title": ev["title"] or f"Kick am {ev['event_date']}",
                "status": ev["status"],
                "guest_count": guest_count,
                "paid_count": paid_count,
                "unpaid_count": unpaid_count,
                "total_expected": total_expected,
                "total_collected": total_collected,
                "outstanding": max(0.0, total_expected - total_collected),
            })

        return results
    finally:
        planner_conn.close()
        finances_conn.close()


def manual_mark_attendee_payment(
    event_id: int,
    attendee_id: int,
    payment_method: str,
    player_id: int | None = None,
    note: str | None = None,
    amount: float = GUEST_FEE_PER_KICK,
) -> int:
    """
    Manually mark an attendee's guest fee as cash, paypal direct, or waived.
    """
    planner_conn = get_planner_connection()
    finances_conn = get_finances_connection()

    try:
        event = planner_conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        match_date = event["event_date"] if event else None

        # Remove previous manual/cash allocations for this attendee to avoid duplicates
        finances_conn.execute(
            "DELETE FROM payment_allocations WHERE event_id = ? AND attendee_id = ? AND transaction_id IS NULL",
            (event_id, attendee_id),
        )
        finances_conn.commit()

        if payment_method == "unpaid":
            # Just cleared previous allocations
            return 0

        alloc_amount = 0.0 if payment_method == "waived" else amount

        alloc_id = add_payment_allocation(
            finances_conn,
            fee_type="match_guest",
            allocated_amount=alloc_amount,
            payment_method=payment_method,
            transaction_id=None,
            event_id=event_id,
            match_date=match_date,
            player_id=player_id,
            attendee_id=attendee_id,
            note=note or f"Manuelle Erfassung ({payment_method})",
        )
        return alloc_id
    finally:
        planner_conn.close()
        finances_conn.close()


def auto_allocate_transaction_to_debts(
    transaction_id: int,
    player_id: int,
) -> int:
    """
    Allocate a confirmed transaction amount to the player's oldest unpaid guest attendances.
    Returns number of guest kicks covered.
    """
    finances_conn = get_finances_connection()
    planner_conn = get_planner_connection()
    accounts_conn = get_accounts_connection()
    rb48_conn = get_rb48_connection()

    try:
        tx = get_transaction_by_id(finances_conn, transaction_id)
        if not tx or tx["amount"] <= 0:
            return 0

        # Get player aliases and possible names
        player_aliases = [row["alias"] for row in rb48_conn.execute(
            "SELECT alias FROM aliases WHERE player_id = ?", (player_id,)
        ).fetchall()]

        # Also get linked user
        user = accounts_conn.execute(
            "SELECT id, username, attendance_name FROM users WHERE player_id = ?", (player_id,)
        ).fetchone()

        search_names = set(player_aliases)
        if user:
            if user["username"]:
                search_names.add(user["username"])
            if user["attendance_name"]:
                search_names.add(user["attendance_name"])

        # Find all guest attendances by or associated with this player/user
        attendee_rows = planner_conn.execute(
            """
            SELECT a.id, a.event_id, a.name, a.user_id, a.registered_by_user_id, e.event_date
            FROM attendees a
            JOIN events e ON a.event_id = e.id
            WHERE a.status = 'attending' AND (a.is_guest = 1 OR a.user_id IS NULL)
            ORDER BY e.event_date ASC, a.id ASC
            """
        ).fetchall()

        # Filter attendances relevant to this player
        relevant_attendances = []
        for att in attendee_rows:
            # Check if name matches any alias or if registered by this user
            att_name = att["name"]
            matched = False
            for sname in search_names:
                if sname.lower() in att_name.lower():
                    matched = True
                    break
            if user and att["registered_by_user_id"] == user["id"]:
                matched = True

            if matched:
                relevant_attendances.append(att)

        remaining_amount = float(tx["amount"])
        kicks_covered = 0

        for att in relevant_attendances:
            if remaining_amount < GUEST_FEE_PER_KICK:
                break

            # Check if already paid
            allocs = get_allocations_for_event(finances_conn, att["event_id"])
            att_allocs = [a for a in allocs if a.get("attendee_id") == att["id"]]
            already_paid = sum(a["allocated_amount"] for a in att_allocs if a["payment_method"] != "waived")
            if already_paid >= GUEST_FEE_PER_KICK:
                continue

            # Allocate 3.50 for this kick
            add_payment_allocation(
                finances_conn,
                fee_type="match_guest",
                allocated_amount=GUEST_FEE_PER_KICK,
                payment_method=tx["source"],
                transaction_id=tx["id"],
                event_id=att["event_id"],
                match_date=att["event_date"],
                player_id=player_id,
                attendee_id=att["id"],
                note=f"PayPal {tx['tx_code'] or ''}".strip(),
            )
            remaining_amount -= GUEST_FEE_PER_KICK
            kicks_covered += 1

        return kicks_covered
    finally:
        finances_conn.close()
        planner_conn.close()
        accounts_conn.close()
        rb48_conn.close()
