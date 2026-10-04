import csv
import io
from datetime import datetime
from scripts.utils.timezone import get_cologne_now, get_cologne_file_timestamp
from flask import (
    Blueprint,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
    Response,
)
from web.services.security import require_webmaster, get_current_user
from scripts.database.database import get_connection as get_rb48_connection
from scripts.database.db_players import (
    get_players,
    get_ignored_aliases,
    ensure_ignored_alias_as_guest_player,
)
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
    set_player_membership_status,
    create_finance_archive,
    get_finance_archives,
    get_finance_archive_by_id,
    delete_finance_archive,
)
from pathlib import Path
from scripts.finances.paypal_parser import parse_paypal_csv
from scripts.finances.bank_pdf_parser import parse_bank_pdf, convert_pdf_to_csv, parse_bank_csv
from scripts.finances.matcher import find_player_match, mask_payer_name
from scripts.finances.reconciliation import (
    get_match_history_financial_overview,
    get_match_date_guest_status,
    get_all_players_with_membership,
    get_membership_dues_overview,
    get_membership_dues_matrix,
    bulk_set_inactive_members,
    get_period_date_range,
    manual_mark_match_guest_payment,

    manual_mark_membership_due,
    auto_allocate_transaction_to_debts,
    settle_transaction_and_debts,
    reset_transaction_settlement,
    get_all_unpaid_guest_entries,
    get_available_finance_periods,
    get_period_display_label,
    get_finance_summary_metrics,
    get_proxy_payment_suggestion,
    settle_smart_combo_transaction,
    get_all_players_open_debts,
    get_transaction_cleared_debts_preview,
    infer_transaction_settlement_target,
    GUEST_FEE_PER_KICK,
    MEMBERSHIP_DUE_PER_HALFYEAR,
)


finances_bp = Blueprint("finances", __name__, url_prefix="/admin/finances")


@finances_bp.route("", methods=["GET"])
@require_webmaster
def admin_finances():
    """Main Webmaster Finances & Payment Management Dashboard."""
    active_tab = request.args.get("tab", "matches")
    selected_date = request.args.get("date")
    selected_period = request.args.get("period", "2026-H2")

    finances_conn = get_finances_connection()
    rb48_conn = get_rb48_connection()
    accounts_conn = get_accounts_connection()

    try:
        # Load players with membership status
        players_with_status = get_all_players_with_membership(
            finances_conn=finances_conn,
            rb48_conn=rb48_conn,
            accounts_conn=accounts_conn,
        )
        players_dict = get_players(rb48_conn)

        # Match history financial overview
        matches_overview = get_match_history_financial_overview()

        # Selected date details
        selected_date_details = None
        if selected_date:
            selected_date_details = get_match_date_guest_status(selected_date)
        elif matches_overview:
            # Default to first match date with guests, or latest date
            guest_dates = [m for m in matches_overview if m["guest_count"] > 0]
            selected_date = guest_dates[0]["match_date"] if guest_dates else matches_overview[0]["match_date"]
            selected_date_details = get_match_date_guest_status(selected_date)

        # Membership dues overview
        dues_overview = get_membership_dues_overview(selected_period)

        # Comprehensive open debts map (dues + guest kicks) for all players
        all_open_debts = get_all_players_open_debts(finances_conn, rb48_conn, accounts_conn)

        # Transactions
        transactions = get_transactions(finances_conn, limit=200)

        # Attach allocations and human-readable settlement summary to transactions
        tx_ids = [tx["id"] for tx in transactions]
        allocs_by_tx = {}
        if tx_ids:
            placeholders = ",".join("?" for _ in tx_ids)
            arows = finances_conn.execute(
                f"SELECT * FROM payment_allocations WHERE transaction_id IN ({placeholders})",
                tx_ids,
            ).fetchall()
            for ar in arows:
                allocs_by_tx.setdefault(ar["transaction_id"], []).append(dict(ar))

        # Attach match suggestions, player names, and allocations to transactions
        for tx in transactions:
            tx_allocs = allocs_by_tx.get(tx["id"], [])
            tx["allocations"] = tx_allocs
            tx["proxy_allocations_count"] = len([a for a in tx_allocs if a.get("paid_by_player_id")])

            settled_labels = []
            for a in tx_allocs:
                bene_name = None
                if a.get("player_id"):
                    bene_pdata = players_dict.get(a["player_id"], {})
                    bene_name = bene_pdata.get("aliases", [f"Spieler #{a['player_id']}"])[0]

                if a.get("fee_type") == "match_guest":
                    date_part = f" ({a['match_date']})" if a.get("match_date") else ""
                    if bene_name:
                        if a.get("paid_by_player_id") and a["paid_by_player_id"] != a.get("player_id"):
                            settled_labels.append(f"Gastbeitrag für {bene_name}{date_part}")
                        else:
                            settled_labels.append(f"Gastbeitrag {bene_name}{date_part}")
                    else:
                        settled_labels.append(f"Gastbeitrag{date_part}")
                elif a.get("fee_type") == "membership_due":
                    per_part = f" ({a['period']})" if a.get("period") else ""
                    settled_labels.append(f"Mitgliedsbeitrag{per_part}")
                else:
                    settled_labels.append(a.get("note") or "Beglichen")

            tx["settled_summary"] = ", ".join(settled_labels)

            if tx.get("matched_player_id"):
                pinfo = players_dict.get(tx["matched_player_id"], {})
                tx["matched_player_name"] = pinfo.get("aliases", [f"Player #{tx['matched_player_id']}"])[0]
            else:
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

            # Check for proxy payment or combination payment pattern
            amount = float(tx.get("amount", 0))
            if amount > 0 and not tx.get("is_confirmed"):
                check_pid = tx.get("matched_player_id") or (tx.get("suggestion") and tx["suggestion"].get("player_id"))
                if check_pid:
                    inferred = infer_transaction_settlement_target(
                        amount, tx.get("date"), tx.get("note"), tx.get("description"), check_pid, all_open_debts
                    )
                    tx["inferred_target_settlement"] = inferred.get("target_settlement")
                    tx["cleared_debts_preview"] = get_transaction_cleared_debts_preview(
                        amount, check_pid, all_player_debts=all_open_debts,
                        tx_date=tx.get("date"), tx_note=tx.get("note"), tx_description=tx.get("description")
                    )
                    proxy_sug = get_proxy_payment_suggestion(tx["id"], check_pid)
                    if proxy_sug:
                        tx["is_proxy_candidate"] = True
                        tx["proxy_num_kicks"] = proxy_sug.get("num_kicks", 0)
                        tx["proxy_suggestion"] = proxy_sug

        # Learned identities
        identities = get_identities(finances_conn)
        for ident in identities:
            pinfo = players_dict.get(ident["player_id"], {})
            ident["player_name"] = pinfo.get("aliases", [f"Player #{ident['player_id']}"])[0]

        # Overall summary metrics
        total_income = sum(t["amount"] for t in transactions if t["amount"] > 0)
        total_expenses = sum(abs(t["amount"]) for t in transactions if t["amount"] < 0)
        unassigned_count = sum(1 for t in transactions if not t.get("is_confirmed") and t["status"] == "imported")
        total_members_count = sum(1 for p in players_with_status if p["status"] == "member")
        total_guests_count = sum(1 for p in players_with_status if p["status"] == "guest")
        all_unpaid_entries = get_all_unpaid_guest_entries()

        # Available periods and summary metrics for the selected period
        available_periods = get_available_finance_periods(finances_conn=finances_conn, rb48_conn=rb48_conn)
        period_display_label = get_period_display_label(selected_period)
        metrics = get_finance_summary_metrics(
            period=selected_period,
            finances_conn=finances_conn,
            rb48_conn=rb48_conn,
            accounts_conn=accounts_conn,
        )

        # Unassigned transaction payers with date (payers of positive unconfirmed transactions)
        unassigned_payers = []
        for t in transactions:
            if not t.get("is_confirmed") and t.get("amount", 0) > 0 and t.get("status") == "imported":
                name = t.get("raw_payer_name") or t.get("raw_payer_email") or f"Transaktion #{t['id']}"
                masked = mask_payer_name(name)
                t_date = t.get("date")
                if masked and not any(u["name"] == masked and u["date"] == t_date for u in unassigned_payers):
                    unassigned_payers.append({"name": masked, "date": t_date})

        has_any_suggestion = any(
            bool(t.get("proxy_suggestion") or (t.get("suggestion") and t["suggestion"].get("player_id")))
            for t in transactions
            if not t.get("is_confirmed") and t.get("status") == "imported"
        )

        # Ignored aliases list (sorted alphabetically)
        ignored_aliases_list = sorted(list(get_ignored_aliases(rb48_conn)))

        # Enrich players and ignored aliases with their debt summaries for dropdown grouping
        for p in players_with_status:
            p_debts = all_open_debts.get(p["player_id"])
            if p_debts and p_debts.get("total_open", 0.0) > 0:
                p["has_open_debts"] = True
                p["open_debts_sum"] = p_debts["total_open"]
                p["open_debts_summary"] = p_debts["summary"]
                p["open_debts_short_summary"] = p_debts["short_summary"]
            else:
                p["has_open_debts"] = False
                p["open_debts_sum"] = 0.0
                p["open_debts_summary"] = ""
                p["open_debts_short_summary"] = ""

        ignored_aliases_with_debts = []
        for ign in ignored_aliases_list:
            ign_debts = all_open_debts.get(ign)
            if ign_debts and ign_debts.get("total_open", 0.0) > 0:
                ignored_aliases_with_debts.append({
                    "name": ign,
                    "has_open_debts": True,
                    "open_debts_sum": ign_debts["total_open"],
                    "open_debts_summary": ign_debts["summary"],
                    "open_debts_short_summary": ign_debts["short_summary"],
                })
            else:
                ignored_aliases_with_debts.append({
                    "name": ign,
                    "has_open_debts": False,
                    "open_debts_sum": 0.0,
                    "open_debts_summary": "",
                    "open_debts_short_summary": "",
                })

        dues_view = request.args.get("dues_view", "period")
        available_halfyear_periods = [p for p in available_periods if p.get("type") == "halfyear"]
        dues_matrix = get_membership_dues_matrix(finances_conn=finances_conn, rb48_conn=rb48_conn)
        finance_archives = get_finance_archives(finances_conn)

        return render_template(
            "admin_finances.html",
            active_tab=active_tab,
            matches_overview=matches_overview,
            selected_date=selected_date,
            selected_date_details=selected_date_details,
            all_unpaid_entries=all_unpaid_entries,
            unassigned_payers=unassigned_payers,
            ignored_aliases=ignored_aliases_list,
            ignored_aliases_with_debts=ignored_aliases_with_debts,
            all_open_debts=all_open_debts,
            players_with_status=players_with_status,
            dues_overview=dues_overview,
            dues_matrix=dues_matrix,
            dues_view=dues_view,
            available_halfyear_periods=available_halfyear_periods,
            selected_period=selected_period,
            period_display_label=period_display_label,
            available_periods=available_periods,
            metrics=metrics,
            transactions=transactions,
            identities=identities,
            player_list=players_with_status,
            total_income=total_income,
            total_expenses=total_expenses,
            unassigned_count=unassigned_count,
            total_members_count=total_members_count,
            total_guests_count=total_guests_count,
            guest_fee_rate=GUEST_FEE_PER_KICK,
            membership_due_rate=MEMBERSHIP_DUE_PER_HALFYEAR,
            has_any_suggestion=has_any_suggestion,
            finance_archives=finance_archives,
        )
    finally:
        finances_conn.close()
        rb48_conn.close()
        accounts_conn.close()



@finances_bp.route("/set-player-status", methods=["POST"])
@require_webmaster
def set_status():
    """Toggle or update a player's membership status ('member' or 'guest')."""
    player_id = request.form.get("player_id", type=int)
    status = request.form.get("status", "guest")
    member_since = request.form.get("member_since")

    if not player_id:
        return jsonify({"success": False, "error": "Missing player ID"}), 400

    finances_conn = get_finances_connection()
    try:
        set_player_membership_status(finances_conn, player_id, status, member_since=member_since)
        flash(f"Status für Spieler #{player_id} auf '{status}' aktualisiert.", "success")
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"success": True, "player_id": player_id, "status": status, "member_since": member_since})
        return redirect(url_for("finances.admin_finances", tab="players"))
    finally:
        finances_conn.close()


@finances_bp.route("/mark-match-guest", methods=["POST"])
@require_webmaster
def mark_match_guest():
    """AJAX action to mark match guest payment status for a specific date and player/alias."""
    match_date = request.form.get("match_date")
    raw_player_id = request.form.get("player_id")
    payment_method = request.form.get("payment_method", "cash")
    note = request.form.get("note")

    if not match_date or not raw_player_id:
        return jsonify({"success": False, "error": "Missing match date or player ID"}), 400

    manual_mark_match_guest_payment(
        match_date=match_date,
        player_id=raw_player_id,
        payment_method=payment_method,
        note=note,
    )

    return jsonify({"success": True, "match_date": match_date, "player_id": raw_player_id, "payment_method": payment_method})


@finances_bp.route("/mark-membership-due", methods=["POST"])
@require_webmaster
def mark_due():
    """AJAX action to mark membership due for a player and period."""
    period = request.form.get("period", "2026-H2")
    player_id = request.form.get("player_id", type=int)
    payment_method = request.form.get("payment_method", "bank")
    note = request.form.get("note")

    if not period or not player_id:
        return jsonify({"success": False, "error": "Missing period or player ID"}), 400

    manual_mark_membership_due(
        period=period,
        player_id=player_id,
        payment_method=payment_method,
        note=note,
    )

    return jsonify({"success": True, "period": period, "player_id": player_id, "payment_method": payment_method})


@finances_bp.route("/bulk-set-inactive", methods=["POST"])
@require_webmaster
def bulk_set_inactive():
    """Bulk mark all members with 0 kicks in a period as inactive/waived."""
    period = request.form.get("period", "2026-H1")
    count = bulk_set_inactive_members(period)
    if count > 0:
        flash(f"{count} inaktive Mitglieder mit 0 Kicks wurden für {period} auf inaktiv/befreit gesetzt.", "success")
    else:
        flash(f"Keine offenen Mitglieder mit 0 Kicks in {period} gefunden.", "info")
    return redirect(url_for("finances.admin_finances", tab="dues", period=period))


@finances_bp.route("/upload", methods=["POST"])

@require_webmaster
def upload_csv():
    """Upload and process bank PDFs (Skatbank / VR-Bank) or PayPal/bank CSV statements (supports multiple files)."""
    uploaded_files = request.files.getlist("files")
    if not uploaded_files or not any(f.filename for f in uploaded_files):
        single_f = request.files.get("csv_file")
        if single_f and single_f.filename:
            uploaded_files = [single_f]

    valid_files = [f for f in uploaded_files if f and f.filename]
    if not valid_files:
        flash("Bitte mindestens eine Datei (PDF-Kontoauszug oder CSV) zum Hochladen auswählen.", "warning")
        return redirect(url_for("finances.admin_finances", tab="import"))

    finances_conn = get_finances_connection()
    rb48_conn = get_rb48_connection()
    accounts_conn = get_accounts_connection()

    skatbank_dir = Path("data/finances/skatbank")
    paypal_dir = Path("data/finances/paypal")
    skatbank_dir.mkdir(parents=True, exist_ok=True)
    paypal_dir.mkdir(parents=True, exist_ok=True)

    imported_count = 0
    skipped_duplicates = 0
    auto_confirmed_count = 0
    processed_files_count = 0

    try:
        for file in valid_files:
            filename = file.filename
            content = file.read()
            if not content:
                continue

            lower_name = filename.lower()
            parsed_txs = []

            if lower_name.endswith(".pdf"):
                # Save original PDF into skatbank directory
                pdf_target = skatbank_dir / filename
                pdf_target.write_bytes(content)
                # Convert PDF to CSV and store in data/finances/skatbank/
                csv_stem = Path(filename).stem
                csv_target = skatbank_dir / f"{csv_stem}.csv"
                try:
                    convert_pdf_to_csv(content, csv_target)
                    parsed_txs = parse_bank_pdf(content)
                except RuntimeError as err:
                    flash(str(err), "danger")
                    continue
            elif lower_name.endswith(".csv"):

                text_sample = ""
                for enc in ("utf-8-sig", "utf-8", "cp1252", "latin1"):
                    try:
                        text_sample = content.decode(enc)
                        break
                    except Exception:
                        continue
                sample_lower = text_sample.lower()
                is_bank_indicator = any(k in sample_lower for k in (
                    "auftraggeber", "verwendungszweck", "skatbank", "buchungstag",
                    "valutadatum", "iban", "bic", "svwz", "buchungstext", "zahlungsbeteiligter"
                ))
                is_paypal_indicator = any(k in sample_lower for k in (
                    "absender e-mail-adresse", "empfänger e-mail-adresse", "from email address",
                    "auswirkung auf guthaben", "guthaben", "handyzahlung"
                ))

                if is_bank_indicator:
                    is_paypal = False
                elif is_paypal_indicator:
                    is_paypal = True
                else:
                    is_paypal = "paypal" in sample_lower or (sample_lower.count("@") > 3)

                if is_paypal:
                    pp_target = paypal_dir / filename
                    pp_target.write_bytes(content)
                    parsed_txs = parse_paypal_csv(content)
                else:
                    sk_target = skatbank_dir / filename
                    sk_target.write_bytes(content)
                    parsed_txs = parse_bank_csv(content)
            else:
                continue

            if not parsed_txs:
                continue

            processed_files_count += 1

            for tx in parsed_txs:
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

                # Auto-confirm only if single payment without complex split/proxy hints
                from scripts.finances.matcher import analyze_payment_note
                tx_analysis = analyze_payment_note(tx.get("note"))
                has_combo_hint = tx_analysis.get("has_due_hint") and len(tx_analysis.get("guest_names", [])) > 0
                if match.get("confidence", 0.0) >= 0.95 and matched_pid and not has_combo_hint and tx.get("amount", 0) > 0:
                    amt = float(tx.get("amount", 0))
                    if amt == GUEST_FEE_PER_KICK or amt == MEMBERSHIP_DUE_PER_HALFYEAR:
                        is_confirmed = 1
                        status = "assigned"
                    else:
                        status = "imported"
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
                    note=tx.get("note"),
                )

                if new_id:
                    imported_count += 1
                    if is_confirmed and matched_pid:
                        auto_confirmed_count += 1
                        auto_allocate_transaction_to_debts(new_id, matched_pid)
                else:
                    skipped_duplicates += 1

        open_manual_count = max(0, imported_count - auto_confirmed_count)
        dup_text = f", {skipped_duplicates} bereits vorhandene Duplikate übersprungen" if skipped_duplicates > 0 else ""
        flash(
            f"📥 Upload erfolgreich ({processed_files_count} Datei(en) verarbeitet): "
            f"{imported_count} Einträge wurden zur Bearbeitung hinzugefügt, "
            f"{auto_confirmed_count} Zuordnungen wurden bereits festgelegt (automatisch sicher zugeordnet), "
            f"{open_manual_count} noch offen zur manuellen Zuordnung{dup_text}.",
            "success",
        )
        return redirect(url_for("finances.admin_finances", tab="import"))
    except Exception as exc:
        flash(f"Fehler beim Import: {exc}", "danger")
        return redirect(url_for("finances.admin_finances", tab="import"))
    finally:
        finances_conn.close()
        rb48_conn.close()
        accounts_conn.close()


@finances_bp.route("/apply_suggestion", methods=["POST"])
@require_webmaster
def apply_suggestion():
    """Apply a smart combo split or proxy suggestion for a single transaction."""
    tx_id = request.form.get("tx_id", type=int)
    if not tx_id:
        flash("Transaktions-ID fehlt.", "danger")
        return redirect(url_for("finances.admin_finances", tab="import"))

    res = settle_smart_combo_transaction(tx_id)
    if res.get("success"):
        sug = res.get("suggestion") or {}
        summary = sug.get("summary_text") or "Zahlung erfolgreich verbucht"
        flash(f"Vorschlag übernommen: {summary}", "success")
    else:
        flash(f"Fehler beim Übernehmen des Vorschlags: {res.get('error', 'Unbekannter Fehler')}", "danger")

    return redirect(url_for("finances.admin_finances", tab="import"))


@finances_bp.route("/apply_all_suggestions", methods=["POST"])
@require_webmaster
def apply_all_suggestions():
    """Apply all pending suggestions across all unconfirmed imported transactions."""
    finances_conn = get_finances_connection()
    rb48_conn = get_rb48_connection()
    accounts_conn = get_accounts_connection()

    applied_count = 0
    try:
        txs = get_transactions(finances_conn)
        open_txs = [t for t in txs if not t.get("is_confirmed") and t.get("amount", 0) > 0 and t.get("status") == "imported"]

        for t in open_txs:
            tid = t["id"]
            check_pid = t.get("matched_player_id")
            if not check_pid:
                match = find_player_match(
                    t.get("raw_payer_name"),
                    t.get("raw_payer_email"),
                    finances_conn=finances_conn,
                    rb48_conn=rb48_conn,
                    accounts_conn=accounts_conn,
                )
                if match.get("confidence", 0.0) >= 0.60:
                    check_pid = match.get("player_id")

            if check_pid:
                sug = get_proxy_payment_suggestion(tid, check_pid)
                if sug:
                    res = settle_smart_combo_transaction(tid, payer_player_id=check_pid, suggestion=sug)
                    if res.get("success"):
                        applied_count += 1
                        continue

                res = settle_transaction_and_debts(tid, payer_player_id=check_pid, remember=True)
                if res.get("success"):
                    applied_count += 1

        flash(
            f"{applied_count} Vorschläge erfolgreich übernommen und verbucht!",
            "success" if applied_count > 0 else "info",
        )
        return redirect(url_for("finances.admin_finances", tab="import"))
    finally:
        finances_conn.close()
        rb48_conn.close()
        accounts_conn.close()


@finances_bp.route("/assign-transaction", methods=["POST"])
@require_webmaster
def assign_transaction():
    """Assign or confirm a player for a transaction, optionally settling on behalf of another guest."""
    tx_id = request.form.get("tx_id", type=int)
    raw_player_id = request.form.get("player_id", "")
    raw_beneficiary_id = request.form.get("beneficiary_player_id", "")
    remember = request.form.get("remember_identity") in ("1", "true", "on")
    ignore = request.form.get("ignore") in ("1", "true", "on")

    player_id = None
    beneficiary_player_id = None
    rb_conn = None

    try:
        if raw_player_id:
            if str(raw_player_id).startswith("ignored:"):
                ignored_alias = str(raw_player_id).split(":", 1)[1]
                rb_conn = get_rb48_connection()
                player_id = ensure_ignored_alias_as_guest_player(rb_conn, ignored_alias)
            else:
                try:
                    player_id = int(raw_player_id)
                except (ValueError, TypeError):
                    player_id = None

        if raw_beneficiary_id:
            if str(raw_beneficiary_id).startswith("ignored:"):
                ign_alias = str(raw_beneficiary_id).split(":", 1)[1]
                if rb_conn is None:
                    rb_conn = get_rb48_connection()
                beneficiary_player_id = ensure_ignored_alias_as_guest_player(rb_conn, ign_alias)
            else:
                try:
                    beneficiary_player_id = int(raw_beneficiary_id)
                except (ValueError, TypeError):
                    beneficiary_player_id = None
    finally:
        if rb_conn:
            rb_conn.close()

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

        target_settlement = request.form.get("target_settlement", "auto")
        res = settle_transaction_and_debts(
            transaction_id=tx_id,
            payer_player_id=player_id,
            beneficiary_player_id=beneficiary_player_id,
            remember=remember,
            current_user_id=curr_user["id"] if curr_user else None,
            target_settlement=target_settlement,
        )

        kicks_covered = res.get("covered_count", 0)
        flash(
            f"Transaktion #{tx_id} erfolgreich zugeordnet & beglichen ({kicks_covered} offene Posten ausgeglichen).",
            "success",
        )
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"success": True, "kicks_covered": kicks_covered})
        return redirect(url_for("finances.admin_finances", tab="import"))
    finally:
        finances_conn.close()


@finances_bp.route("/settle-transaction", methods=["POST"])
@require_webmaster
def settle_transaction_route():
    """Directly mark an imported transaction as settled, or reset it to unconfirmed/Prüfung."""
    tx_id = request.form.get("tx_id", type=int)
    action = request.form.get("action", "settle")

    if not tx_id:
        return jsonify({"success": False, "error": "Missing transaction ID"}), 400

    if action == "reset":
        reset_transaction_settlement(tx_id)
        flash(f"Transaktion #{tx_id} zurückgesetzt auf 'Prüfung'.", "info")
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"success": True, "action": "reset"})
        return redirect(url_for("finances.admin_finances", tab="import"))

    raw_payer_id = request.form.get("payer_player_id") or request.form.get("player_id", "")
    raw_bene_id = request.form.get("beneficiary_player_id", "")
    target_settlement = request.form.get("target_settlement", "auto")
    remember = request.form.get("remember_identity") in ("1", "true", "on")
    match_date = request.form.get("match_date")

    curr_user = get_current_user()
    res = settle_transaction_and_debts(
        transaction_id=tx_id,
        payer_player_id=raw_payer_id if raw_payer_id else None,
        beneficiary_player_id=raw_bene_id if raw_bene_id else None,
        match_date=match_date,
        remember=remember,
        current_user_id=curr_user["id"] if curr_user else None,
        target_settlement=target_settlement,
    )

    if not res.get("success"):
        flash(res.get("error", "Fehler beim Begleichen"), "danger")
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify(res), 400
        return redirect(url_for("finances.admin_finances", tab="import"))

    flash(
        f"Transaktion #{tx_id} als beglichen markiert ({res.get('covered_count', 0)} offene Posten ausgeglichen).",
        "success",
    )
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify(res)
    return redirect(url_for("finances.admin_finances", tab="import"))


@finances_bp.route("/identity/save", methods=["POST"])
@require_webmaster
def save_identity():
    """Save or update a learned payment identity."""
    raw_player_id = request.form.get("player_id", "")
    payer_email = request.form.get("payer_email")
    payer_name = request.form.get("payer_name")

    player_id = None
    if raw_player_id:
        if str(raw_player_id).startswith("ignored:"):
            ignored_alias = str(raw_player_id).split(":", 1)[1]
            rb_conn = get_rb48_connection()
            try:
                player_id = ensure_ignored_alias_as_guest_player(rb_conn, ignored_alias)
            finally:
                rb_conn.close()
        else:
            try:
                player_id = int(raw_player_id)
            except (ValueError, TypeError):
                player_id = None

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


@finances_bp.route("/split-assign", methods=["POST"])
@require_webmaster
def split_assign_transaction():
    """Split-assign a proxy payment to multiple guest players."""
    import json as _json
    
    tx_id = request.form.get("tx_id", type=int)
    raw_paid_by = request.form.get("paid_by_player_id", "")
    paid_by_player_id = None
    if raw_paid_by:
        if str(raw_paid_by).startswith("ignored:"):
            rb_c = get_rb48_connection()
            try:
                paid_by_player_id = ensure_ignored_alias_as_guest_player(rb_c, str(raw_paid_by).split(":", 1)[1])
            finally:
                rb_c.close()
        else:
            try:
                paid_by_player_id = int(raw_paid_by)
            except (ValueError, TypeError):
                paid_by_player_id = None

    remember = request.form.get("remember_identity") in ("1", "true", "on")
    allocations_json = request.form.get("allocations", "[]")

    if not tx_id or not paid_by_player_id:
        return jsonify({"success": False, "error": "Missing transaction or payer ID"}), 400
    
    try:
        alloc_list = _json.loads(allocations_json)
    except (ValueError, TypeError):
        return jsonify({"success": False, "error": "Invalid allocations data"}), 400
    
    if not alloc_list:
        return jsonify({"success": False, "error": "No allocations provided"}), 400

    # Convert any ignored: alias guest allocations to real guest player_ids
    rb_conn = None
    try:
        for item in alloc_list:
            raw_pid = item.get("player_id")
            if raw_pid and str(raw_pid).startswith("ignored:"):
                ignored_alias = str(raw_pid).split(":", 1)[1]
                if rb_conn is None:
                    rb_conn = get_rb48_connection()
                item["player_id"] = ensure_ignored_alias_as_guest_player(rb_conn, ignored_alias)
    finally:
        if rb_conn:
            rb_conn.close()
    
    finances_conn = get_finances_connection()
    curr_user = get_current_user()
    
    try:
        tx = get_transaction_by_id(finances_conn, tx_id)
        if not tx:
            return jsonify({"success": False, "error": "Transaction not found"}), 404
        
        # Mark transaction as assigned to the payer
        update_transaction_assignment(
            finances_conn, tx_id, paid_by_player_id, None,
            status="assigned", is_confirmed=1,
        )
        
        if remember:
            save_or_update_identity(
                finances_conn,
                player_id=paid_by_player_id,
                payer_email=tx.get("raw_payer_email"),
                payer_name=tx.get("raw_payer_name"),
                confidence=1.0,
                created_by_user_id=curr_user["id"] if curr_user else None,
            )
        
        # Import here to avoid circular import at module level
        from scripts.finances.reconciliation import auto_allocate_proxy_guest_payment
        
        covered = auto_allocate_proxy_guest_payment(
            tx_id, paid_by_player_id, guest_allocations=alloc_list,
        )
        
        flash(
            f"Stellvertreter-Zahlung #{tx_id} aufgeteilt: {covered} Gastbeiträge zugeordnet.",
            "success",
        )
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"success": True, "covered": covered})
        return redirect(url_for("finances.admin_finances", tab="import"))
    finally:
        finances_conn.close()


@finances_bp.route("/proxy-suggestion", methods=["GET"])
@require_webmaster
def proxy_suggestion():
    """AJAX endpoint returning proxy payment split suggestion for a transaction."""
    tx_id = request.args.get("tx_id", type=int)
    player_id = request.args.get("player_id", type=int)
    
    if not tx_id or not player_id:
        return jsonify({"suggestion": None})
    
    from scripts.finances.reconciliation import get_proxy_payment_suggestion
    suggestion = get_proxy_payment_suggestion(tx_id, player_id)
    return jsonify({"suggestion": suggestion})


@finances_bp.route("/archive-current", methods=["POST"])
@require_webmaster
def archive_current():
    """Archive current transaction list and payment allocations into a saved snapshot."""
    title = request.form.get("archive_title", "").strip()
    notes = request.form.get("archive_notes", "").strip() or None

    finances_conn = get_finances_connection()
    rb48_conn = get_rb48_connection()
    try:
        transactions = get_transactions(finances_conn, limit=1000)
        if not transactions:
            flash("Keine Transaktionen zum Archivieren vorhanden.", "warning")
            return redirect(url_for("finances.admin_finances", tab="import"))

        players_dict = get_players(rb48_conn)

        # Get allocations for all transactions
        tx_ids = [t["id"] for t in transactions]
        allocs_by_tx = {}
        if tx_ids:
            placeholders = ",".join("?" for _ in tx_ids)
            arows = finances_conn.execute(
                f"SELECT * FROM payment_allocations WHERE transaction_id IN ({placeholders})",
                tx_ids,
            ).fetchall()
            for ar in arows:
                allocs_by_tx.setdefault(ar["transaction_id"], []).append(dict(ar))

        output = io.StringIO()
        writer = csv.writer(output, delimiter=';')
        writer.writerow([
            "ID", "Datum", "Uhrzeit", "Quelle", "Transaktionscode",
            "Betrag", "Waehrung", "Absender_Name", "Absender_Email",
            "Status", "Zugeordneter_Spieler", "Bestaetigt",
            "Verwendungszweck_Notiz", "Beglichene_Posten"
        ])

        total_income = 0.0
        total_expenses = 0.0

        for tx in transactions:
            amt = float(tx.get("amount", 0.0))
            if amt > 0:
                total_income += amt
            else:
                total_expenses += abs(amt)

            player_name = ""
            if tx.get("matched_player_id"):
                pinfo = players_dict.get(tx["matched_player_id"], {})
                player_name = pinfo.get("aliases", [f"Player #{tx['matched_player_id']}"])[0]

            tx_allocs = allocs_by_tx.get(tx["id"], [])
            alloc_summaries = []
            for a in tx_allocs:
                bene_name = ""
                if a.get("player_id"):
                    bene_pdata = players_dict.get(a["player_id"], {})
                    bene_name = bene_pdata.get("aliases", [f"Spieler #{a['player_id']}"])[0]
                fee_t = a.get("fee_type", "")
                if fee_t == "match_guest":
                    alloc_summaries.append(f"Gastbeitrag {bene_name or ''} ({a.get('match_date', '')})")
                elif fee_t == "membership_due":
                    alloc_summaries.append(f"Mitgliedsbeitrag {bene_name or ''} ({a.get('period', '')})")
                else:
                    alloc_summaries.append(a.get("note") or "Zahlung")

            amt_str = f"{amt:.2f}".replace('.', ',')
            writer.writerow([
                tx["id"],
                tx["date"],
                tx.get("time", ""),
                tx.get("source", ""),
                tx.get("tx_code", ""),
                amt_str,
                tx.get("currency", "EUR"),
                tx.get("raw_payer_name", "") or "",
                tx.get("raw_payer_email", "") or "",
                tx.get("status", ""),
                player_name,
                "Ja" if tx.get("is_confirmed") else "Nein",
                tx.get("note", "") or tx.get("description", "") or "",
                ", ".join(alloc_summaries),
            ])

        csv_data = output.getvalue()

        now_str = get_cologne_now().strftime("%d.%m.%Y %H:%M")
        if not title:
            title = f"Zahlungsliste vom {now_str}"

        archive_id = create_finance_archive(
            finances_conn,
            title=title,
            tx_count=len(transactions),
            total_income=total_income,
            total_expenses=total_expenses,
            csv_data=csv_data,
            notes=notes,
        )

        # Also store local backup copy in data/finances/archives/
        arch_dir = Path("data/finances/archives")
        arch_dir.mkdir(parents=True, exist_ok=True)
        file_ts = get_cologne_file_timestamp()
        (arch_dir / f"archive_{archive_id}_{file_ts}.csv").write_text(csv_data, encoding="utf-8-sig")

        # Purge archived transactions from the active table
        if tx_ids:
            for i in range(0, len(tx_ids), 500):
                chunk = tx_ids[i:i + 500]
                placeholders = ",".join("?" for _ in chunk)
                finances_conn.execute(
                    f"DELETE FROM finance_transactions WHERE id IN ({placeholders})",
                    chunk,
                )
            finances_conn.commit()

        flash(
            f"📦 Archiv '{title}' mit {len(transactions)} Buchungen erfolgreich gespeichert und Importliste bereinigt.",
            "success",
        )
        return redirect(url_for("finances.admin_finances", tab="import"))
    finally:
        finances_conn.close()
        rb48_conn.close()


@finances_bp.route("/download-archive/<int:archive_id>", methods=["GET"])
@require_webmaster
def download_archive(archive_id: int):
    """Download a saved financial archive as CSV."""
    finances_conn = get_finances_connection()
    try:
        archive = get_finance_archive_by_id(finances_conn, archive_id)
        if not archive:
            flash("Archiv nicht gefunden.", "danger")
            return redirect(url_for("finances.admin_finances", tab="import"))

        clean_date = (archive["archived_at"][:10]).replace("-", "")
        filename = f"rb48_archiv_{archive['id']}_{clean_date}.csv"
        csv_bytes = ("\ufeff" + archive["csv_data"]).encode("utf-8")
        return Response(
            csv_bytes,
            mimetype="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename={filename}",
                "Content-Type": "text/csv; charset=utf-8",
            },
        )
    finally:
        finances_conn.close()


@finances_bp.route("/delete-archive/<int:archive_id>", methods=["POST"])
@require_webmaster
def delete_archive(archive_id: int):
    """Delete a saved financial archive."""
    finances_conn = get_finances_connection()
    try:
        delete_finance_archive(finances_conn, archive_id)
        flash(f"Archiv #{archive_id} gelöscht.", "info")
        return redirect(url_for("finances.admin_finances", tab="import"))
    finally:
        finances_conn.close()

