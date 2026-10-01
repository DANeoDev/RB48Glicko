import io
from flask import (
    Blueprint,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from web.services.security import require_webmaster, get_current_user
from scripts.database.database import get_connection as get_rb48_connection
from scripts.database.db_players import get_players
from scripts.accounts.database import get_accounts_connection
from scripts.finances.database import (
    get_finances_connection,
    get_transactions,
    get_transaction_by_id,
    insert_transaction,
    update_transaction_assignment,
    get_identities,
    save_or_update_identity,
    delete_identity,
)
from scripts.finances.paypal_parser import parse_paypal_csv
from scripts.finances.matcher import find_player_match
from scripts.finances.reconciliation import (
    get_all_events_financial_overview,
    get_event_guest_status,
    manual_mark_attendee_payment,
    auto_allocate_transaction_to_debts,
    GUEST_FEE_PER_KICK,
    MEMBERSHIP_DUE_PER_HALFYEAR,
)


finances_bp = Blueprint("finances", __name__, url_prefix="/admin/finances")


@finances_bp.route("", methods=["GET"])
@require_webmaster
def admin_finances():
    """Main Webmaster Finances & Payment Management Dashboard."""
    active_tab = request.args.get("tab", "matchdays")
    selected_event_id = request.args.get("event_id", type=int)

    finances_conn = get_finances_connection()
    rb48_conn = get_rb48_connection()
    accounts_conn = get_accounts_connection()

    try:
        # Load players for dropdowns
        players_dict = get_players(rb48_conn)
        player_list = []
        for pid, pdata in players_dict.items():
            primary_alias = pdata["aliases"][0] if pdata["aliases"] else f"Player #{pid}"
            all_aliases = ", ".join(pdata["aliases"])
            player_list.append({
                "player_id": pid,
                "name": primary_alias,
                "aliases_str": all_aliases,
            })
        player_list.sort(key=lambda x: x["name"].lower())

        # Matchdays overview
        events_overview = get_all_events_financial_overview()

        # Selected event details
        selected_event_details = None
        if selected_event_id:
            selected_event_details = get_event_guest_status(selected_event_id)
        elif events_overview:
            # Default to first event with guests
            selected_event_id = events_overview[0]["event_id"]
            selected_event_details = get_event_guest_status(selected_event_id)

        # Transactions
        transactions = get_transactions(finances_conn, limit=200)
        
        # Attach match suggestions & player names to transactions
        for tx in transactions:
            if tx.get("matched_player_id"):
                pinfo = players_dict.get(tx["matched_player_id"], {})
                tx["matched_player_name"] = pinfo.get("aliases", [f"Player #{tx['matched_player_id']}"])[0]
            else:
                # Calculate real-time suggestion
                match_res = find_player_match(
                    tx.get("raw_payer_name"),
                    tx.get("raw_payer_email"),
                    finances_conn=finances_conn,
                    rb48_conn=rb48_conn,
                    accounts_conn=accounts_conn,
                )
                tx["suggestion"] = match_res
                if match_res["player_id"]:
                    pinfo = players_dict.get(match_res["player_id"], {})
                    tx["suggestion_player_name"] = pinfo.get("aliases", [f"Player #{match_res['player_id']}"])[0]

        # Learned identities
        identities = get_identities(finances_conn)
        for ident in identities:
            pinfo = players_dict.get(ident["player_id"], {})
            ident["player_name"] = pinfo.get("aliases", [f"Player #{ident['player_id']}"])[0]

        # Overall summary metrics
        total_income = sum(t["amount"] for t in transactions if t["amount"] > 0)
        total_expenses = sum(abs(t["amount"]) for t in transactions if t["amount"] < 0)
        unassigned_count = sum(1 for t in transactions if not t.get("is_confirmed") and t["status"] == "imported")

        return render_template(
            "admin_finances.html",
            active_tab=active_tab,
            events_overview=events_overview,
            selected_event_id=selected_event_id,
            selected_event_details=selected_event_details,
            transactions=transactions,
            identities=identities,
            player_list=player_list,
            total_income=total_income,
            total_expenses=total_expenses,
            unassigned_count=unassigned_count,
            guest_fee_rate=GUEST_FEE_PER_KICK,
            membership_due_rate=MEMBERSHIP_DUE_PER_HALFYEAR,
        )
    finally:
        finances_conn.close()
        rb48_conn.close()
        accounts_conn.close()


@finances_bp.route("/event-details/<int:event_id>", methods=["GET"])
@require_webmaster
def event_details(event_id: int):
    """JSON API to fetch guest payment status for a single event."""
    data = get_event_guest_status(event_id)
    return jsonify(data)


@finances_bp.route("/upload", methods=["POST"])
@require_webmaster
def upload_csv():
    """Upload and process a PayPal or bank CSV statement."""
    file = request.files.get("csv_file")
    if not file or not file.filename:
        flash("Bitte eine CSV-Datei zum Hochladen auswählen.", "warning")
        return redirect(url_for("finances.admin_finances", tab="import"))

    finances_conn = get_finances_connection()
    rb48_conn = get_rb48_connection()
    accounts_conn = get_accounts_connection()
    curr_user = get_current_user()

    try:
        content = file.read()
        parsed_txs = parse_paypal_csv(content)

        if not parsed_txs:
            flash("Keine gültigen Transaktionen in der Datei gefunden. Bitte prüfe das Format.", "danger")
            return redirect(url_for("finances.admin_finances", tab="import"))

        imported_count = 0
        skipped_duplicates = 0
        auto_confirmed_count = 0

        for tx in parsed_txs:
            # Find smart match
            match = find_player_match(
                tx.get("raw_payer_name"),
                tx.get("raw_payer_email"),
                finances_conn=finances_conn,
                rb48_conn=rb48_conn,
                accounts_conn=accounts_conn,
            )

            is_confirmed = 0
            matched_pid = match.get("player_id")
            matched_uid = match.get("user_id")

            # High confidence auto-confirm
            if match.get("confidence", 0.0) >= 0.95 and matched_pid:
                is_confirmed = 1
                status = "assigned"
            else:
                status = tx.get("status", "imported")

            new_id = insert_transaction(
                finances_conn,
                source=tx["source"],
                tx_code=tx["tx_code"],
                date=tx["date"],
                time=tx["time"],
                raw_payer_name=tx["raw_payer_name"],
                raw_payer_email=tx["raw_payer_email"],
                amount=tx["amount"],
                currency=tx["currency"],
                description=tx["description"],
                status=status,
                matched_player_id=matched_pid if is_confirmed else None,
                matched_user_id=matched_uid if is_confirmed else None,
                is_confirmed=is_confirmed,
                raw_payload=tx.get("raw_payload"),
            )

            if new_id:
                imported_count += 1
                if is_confirmed and matched_pid:
                    auto_confirmed_count += 1
                    # Auto-allocate to oldest debts
                    auto_allocate_transaction_to_debts(new_id, matched_pid)
            else:
                skipped_duplicates += 1

        flash(
            f"CSV-Import erfolgreich: {imported_count} neue Transaktionen importiert ({auto_confirmed_count} automatisch sicher zugeordnet), {skipped_duplicates} bereits vorhandene duplikate übersprungen.",
            "success",
        )
        return redirect(url_for("finances.admin_finances", tab="import"))
    except Exception as exc:
        flash(f"Fehler beim CSV-Import: {exc}", "danger")
        return redirect(url_for("finances.admin_finances", tab="import"))
    finally:
        finances_conn.close()
        rb48_conn.close()
        accounts_conn.close()


@finances_bp.route("/assign-transaction", methods=["POST"])
@require_webmaster
def assign_transaction():
    """Assign or confirm a player for a transaction and optionally learn the mapping."""
    tx_id = request.form.get("tx_id", type=int)
    player_id = request.form.get("player_id", type=int)
    remember = request.form.get("remember_identity") in ("1", "true", "on")
    ignore = request.form.get("ignore") in ("1", "true", "on")

    if not tx_id:
        return jsonify({"success": False, "error": "Missing transaction ID"}), 400

    finances_conn = get_finances_connection()
    curr_user = get_current_user()

    try:
        tx = get_transaction_by_id(finances_conn, tx_id)
        if not tx:
            return jsonify({"success": False, "error": "Transaction not found"}), 404

        if ignore:
            update_transaction_assignment(finances_conn, tx_id, None, None, status="ignored", is_confirmed=1)
            flash("Transaktion als ignoriert markiert.", "info")
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return jsonify({"success": True, "status": "ignored"})
            return redirect(url_for("finances.admin_finances", tab="import"))

        if not player_id:
            return jsonify({"success": False, "error": "Bitte einen Spieler auswählen"}), 400

        # Save assignment
        update_transaction_assignment(finances_conn, tx_id, player_id, None, status="assigned", is_confirmed=1)

        # Learn mapping if requested
        if remember:
            save_or_update_identity(
                finances_conn,
                player_id=player_id,
                payer_email=tx.get("raw_payer_email"),
                payer_name=tx.get("raw_payer_name"),
                confidence=1.0,
                created_by_user_id=curr_user["id"] if curr_user else None,
            )

        # Allocate to unpaid kicks
        kicks_covered = auto_allocate_transaction_to_debts(tx_id, player_id)

        flash(
            f"Transaktion #{tx_id} erfolgreich zugeordnet ({kicks_covered} offene Kicks automatisch ausgeglichen).",
            "success",
        )
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"success": True, "kicks_covered": kicks_covered})
        return redirect(url_for("finances.admin_finances", tab="import"))
    finally:
        finances_conn.close()


@finances_bp.route("/mark-attendee", methods=["POST"])
@require_webmaster
def mark_attendee():
    """Quick AJAX action to mark guest payment status on a matchday."""
    event_id = request.form.get("event_id", type=int)
    attendee_id = request.form.get("attendee_id", type=int)
    payment_method = request.form.get("payment_method", "cash")
    player_id = request.form.get("player_id", type=int)
    note = request.form.get("note")

    if not event_id or not attendee_id:
        return jsonify({"success": False, "error": "Missing event or attendee ID"}), 400

    manual_mark_attendee_payment(
        event_id=event_id,
        attendee_id=attendee_id,
        payment_method=payment_method,
        player_id=player_id,
        note=note,
    )

    return jsonify({"success": True, "event_id": event_id, "attendee_id": attendee_id, "payment_method": payment_method})


@finances_bp.route("/identity/save", methods=["POST"])
@require_webmaster
def save_identity():
    """Save or update a learned payment identity."""
    player_id = request.form.get("player_id", type=int)
    payer_email = request.form.get("payer_email")
    payer_name = request.form.get("payer_name")

    if not player_id or (not payer_email and not payer_name):
        flash("Bitte einen Spieler und eine E-Mail oder einen Namen angeben.", "warning")
        return redirect(url_for("finances.admin_finances", tab="identities"))

    finances_conn = get_finances_connection()
    curr_user = get_current_user()
    try:
        save_or_update_identity(
            finances_conn,
            player_id=player_id,
            payer_email=payer_email,
            payer_name=payer_name,
            confidence=1.0,
            created_by_user_id=curr_user["id"] if curr_user else None,
        )
        flash("Zahler-Zuordnung erfolgreich gespeichert.", "success")
        return redirect(url_for("finances.admin_finances", tab="identities"))
    finally:
        finances_conn.close()


@finances_bp.route("/identity/delete/<int:identity_id>", methods=["POST"])
@require_webmaster
def remove_identity(identity_id: int):
    """Delete a learned payment identity."""
    finances_conn = get_finances_connection()
    try:
        delete_identity(finances_conn, identity_id)
        flash("Zahler-Zuordnung gelöscht.", "info")
        return redirect(url_for("finances.admin_finances", tab="identities"))
    finally:
        finances_conn.close()
