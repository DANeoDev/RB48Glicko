import io
import os
from pathlib import Path
import pytest
from datetime import datetime, timezone

from scripts.finances.database import (
    create_finance_tables,
    get_finances_connection,
    insert_transaction,
    get_transactions,
    get_transaction_by_id,
    update_transaction_assignment,
    save_or_update_identity,
    get_identities,
    delete_identity,
    add_payment_allocation,
    set_player_membership_status,
    get_player_membership_status,
    get_all_player_membership_statuses,
    create_receivable,
    get_receivable_by_id,
    get_receivables,
    update_receivable,
    delete_receivable,
    get_allocations_for_receivable,
    create_special_receivables_group,
)
from scripts.finances.paypal_parser import (
    parse_german_amount,
    parse_date_to_iso,
    parse_paypal_csv,
)
from scripts.finances.matcher import find_player_match, normalize_text, mask_payer_name
from scripts.finances.reconciliation import (
    get_match_history_financial_overview,
    get_match_date_guest_status,
    get_all_players_with_membership,
    get_membership_dues_overview,
    manual_mark_match_guest_payment,
    manual_mark_membership_due,
    auto_allocate_transaction_to_debts,
    settle_transaction_and_debts,
    reset_transaction_settlement,
    get_all_unpaid_guest_entries,
    get_all_players_open_debts,
    OpenDebtsDict,
    get_available_finance_periods,
    get_period_display_label,
    get_finance_summary_metrics,
    resolve_player_membership_status,
    get_proxy_payment_suggestion,
    settle_smart_combo_transaction,
    get_period_date_range,
    get_membership_dues_matrix,
    bulk_set_inactive_members,
    sync_rule_based_receivables,
    allocate_transaction_receivables,
    create_manual_due_receivables,
    GUEST_FEE_PER_KICK,
    MEMBERSHIP_DUE_PER_HALFYEAR,
)
from web.services.finance_ai import suggest_transaction_allocation_ai

from scripts.finances.bank_pdf_parser import (
    parse_bank_pdf,
    convert_pdf_to_csv,
    parse_bank_csv,
)
from scripts.database.database import (
    get_connection as get_rb48_connection,
    create_players_table,
    create_aliases_table,
    create_ignored_aliases_table,
    create_positions_table,
    create_matches_table,
    create_match_players_table,
)
from scripts.database.db_matches import create_match, add_match_player
from scripts.accounts.database import (
    get_accounts_connection,
    create_account_tables,
    approve_user,
    mark_email_verified,
    update_user_role,
)
from scripts.accounts.auth import register_user, pass_psychology_test
from web.app import create_app


def _login_webmaster(app):
    """Helper to create and log in a verified, approved webmaster user."""
    import time
    unique_name = f"wm_{int(time.time() * 1000000)}"
    user_id, _ = register_user(unique_name, f"{unique_name}@example.com", "Password123!", role="webmaster")
    acc_conn = get_accounts_connection()
    mark_email_verified(acc_conn, user_id)
    approve_user(acc_conn, user_id, approved=True)
    update_user_role(acc_conn, user_id, "webmaster")
    acc_conn.close()
    pass_psychology_test(user_id)
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["username"] = unique_name
        sess["role"] = "webmaster"
    return client



@pytest.fixture
def clean_finances_env(tmp_path, monkeypatch):
    """Fixture to set up isolated test databases for finances, rb48, accounts, and planner."""
    fin_db = tmp_path / "finances_test.db"
    rb_db = tmp_path / "rb48_test.db"
    acc_db = tmp_path / "accounts_test.db"
    plan_db = tmp_path / "planner_test.db"
    matches_dir = tmp_path / "matches"
    matches_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("RB48_FINANCES_DATABASE_FILE", str(fin_db))
    monkeypatch.setenv("RB48_DATABASE_FILE", str(rb_db))
    monkeypatch.setenv("RB48_ACCOUNTS_DATABASE_FILE", str(acc_db))
    monkeypatch.setenv("RB48_PLANNER_DATABASE_FILE", str(plan_db))
    monkeypatch.setenv("RB48_MATCHES_DIR", str(matches_dir))

    # Initialize tables
    f_conn = get_finances_connection()
    create_finance_tables(f_conn)
    f_conn.close()

    r_conn = get_rb48_connection()
    create_players_table(r_conn)
    create_aliases_table(r_conn)
    create_ignored_aliases_table(r_conn)
    create_positions_table(r_conn)
    create_matches_table(r_conn)
    create_match_players_table(r_conn)

    r_conn.execute("INSERT INTO players (player_id) VALUES (1), (2), (33)")
    r_conn.execute("INSERT INTO aliases (alias, player_id) VALUES ('Stefan', 1), ('Nik', 2), ('Kha', 33)")
    r_conn.execute("INSERT INTO ignored_aliases (alias) VALUES ('Micha+1')")
    
    # Create sample match
    create_match(r_conn, "2026-07-15-1", "2026-07-15", "box", 2, 1, 5, 3)
    add_match_player(r_conn, "2026-07-15-1", 1, "A")
    add_match_player(r_conn, "2026-07-15-1", 2, "A")
    add_match_player(r_conn, "2026-07-15-1", 33, "B")

    r_conn.commit()
    r_conn.close()

    a_conn = get_accounts_connection()
    create_account_tables(a_conn)
    a_conn.close()

    return {
        "fin_db": fin_db,
        "rb_db": rb_db,
        "acc_db": acc_db,
        "plan_db": plan_db,
    }


def test_amount_and_date_parser():
    assert parse_german_amount("3,50") == 3.50
    assert parse_german_amount("7,00") == 7.00
    assert parse_german_amount("-74,00") == -74.00
    assert parse_german_amount("1.250,50") == 1250.50
    assert parse_german_amount("0,00") == 0.0

    assert parse_date_to_iso("10.07.2026") == "2026-07-10"
    assert parse_date_to_iso("2026-07-10") == "2026-07-10"


def test_parse_paypal_csv():
    csv_sample = """"Datum","Uhrzeit","Zeitzone","Beschreibung","Währung","Brutto","Entgelt","Netto","Guthaben","Transaktionscode","Absender E-Mail-Adresse","Name","Name der Bank","Bankkonto","Versand- und Bearbeitungsgebühr","Umsatzsteuer","Rechnungsnummer","Zugehöriger Transaktionscode"
"10.07.2026","12:09:12","Europe/Berlin","Handyzahlung","EUR","3,50","0,00","3,50","732,06","0Y2212597K454212L","samuel@schelp.eu","Samuel Schelp","","","0,00","0,00","",""
"30.07.2026","19:24:30","Europe/Berlin","PayPal Express-Zahlung","EUR","-74,00","0,00","-74,00","699,56","9E66146045931164J","finance@eversports.com","Eversport GmbH","","","0,00","0,00","",""
"""
    txs = parse_paypal_csv(csv_sample)
    assert len(txs) == 2
    assert txs[0]["tx_code"] == "0Y2212597K454212L"
    assert txs[0]["amount"] == 3.50
    assert txs[0]["date"] == "2026-07-10"
    assert txs[0]["raw_payer_name"] == "Samuel Schelp"
    assert txs[0]["status"] == "imported"

    assert txs[1]["amount"] == -74.00
    assert txs[1]["status"] == "expense"


def test_transactions_crud_and_deduplication(clean_finances_env):
    conn = get_finances_connection()
    tx_id_1 = insert_transaction(
        conn,
        source="paypal",
        tx_code="TX12345",
        date="2026-07-10",
        time="12:00:00",
        raw_payer_name="Max Mustermann",
        raw_payer_email="max@example.com",
        amount=3.50,
    )
    assert tx_id_1 is not None

    tx_id_dup = insert_transaction(
        conn,
        source="paypal",
        tx_code="TX12345",
        date="2026-07-10",
        time="12:00:00",
        raw_payer_name="Max Mustermann",
        raw_payer_email="max@example.com",
        amount=3.50,
    )
    assert tx_id_dup is None

    txs = get_transactions(conn)
    assert len(txs) == 1
    assert txs[0]["tx_code"] == "TX12345"

    update_transaction_assignment(conn, tx_id_1, player_id=1, status="assigned", is_confirmed=1)
    updated = get_transaction_by_id(conn, tx_id_1)
    assert updated["matched_player_id"] == 1
    assert updated["is_confirmed"] == 1
    conn.close()


def test_smart_matcher_and_learning(clean_finances_env):
    fin_conn = get_finances_connection()
    rb_conn = get_rb48_connection()
    acc_conn = get_accounts_connection()

    match1 = find_player_match(
        raw_payer_name="An-Kha Ha-Phuoc",
        raw_payer_email="ying.yang89@hotmail.de",
        finances_conn=fin_conn,
        rb48_conn=rb_conn,
        accounts_conn=acc_conn,
    )
    assert match1["player_id"] == 33
    assert match1["confidence"] >= 0.80

    save_or_update_identity(
        fin_conn,
        player_id=1,
        payer_email="unknown.custom@provider.de",
        payer_name="Unknown Custom",
        confidence=1.0,
    )

    match2 = find_player_match(
        raw_payer_name="Random Name",
        raw_payer_email="unknown.custom@provider.de",
        finances_conn=fin_conn,
        rb48_conn=rb_conn,
        accounts_conn=acc_conn,
    )
    assert match2["player_id"] == 1
    assert match2["confidence"] == 1.0
    assert match2["match_type"] == "learned_email"

    fin_conn.close()
    rb_conn.close()
    acc_conn.close()


def test_player_membership_status_resolution(clean_finances_env):
    fin_conn = get_finances_connection()
    acc_conn = get_accounts_connection()

    # Player 1 is linked to an approved user -> should default to 'member'
    user_id, _ = register_user("stefan_user", "stefan@rb48.de", "Password123!", role="user")
    acc_conn.execute("UPDATE users SET player_id = ? WHERE id = ?", (1, user_id))
    acc_conn.commit()

    assert resolve_player_membership_status(1, fin_conn, acc_conn) == "member"
    # Player 2 has no linked user and no override -> should default to 'guest'
    assert resolve_player_membership_status(2, fin_conn, acc_conn) == "guest"

    # Override player 2 to member
    set_player_membership_status(fin_conn, 2, "member")
    assert resolve_player_membership_status(2, fin_conn, acc_conn) == "member"

    # Override player 1 to guest
    set_player_membership_status(fin_conn, 1, "guest")
    assert resolve_player_membership_status(1, fin_conn, acc_conn) == "guest"

    fin_conn.close()
    acc_conn.close()


def test_match_history_reconciliation_and_marking(clean_finances_env):
    fin_conn = get_finances_connection()
    # Player 1 is member, Player 2 is guest, Player 33 is guest
    set_player_membership_status(fin_conn, 1, "member")
    set_player_membership_status(fin_conn, 2, "guest")
    set_player_membership_status(fin_conn, 33, "guest")
    fin_conn.close()

    overview = get_match_history_financial_overview()
    assert len(overview) == 1
    assert overview[0]["match_date"] == "2026-07-15"
    assert overview[0]["guest_count"] == 2  # Player 2 & 33
    assert overview[0]["unpaid_count"] == 2
    assert overview[0]["total_expected"] == 7.00
    assert overview[0]["outstanding"] == 7.00

    # Mark player 2 as cash paid
    manual_mark_match_guest_payment("2026-07-15", 2, payment_method="cash")
    status_date = get_match_date_guest_status("2026-07-15")
    assert status_date["total_guests"] == 2
    assert status_date["total_collected"] == 3.50
    assert status_date["outstanding"] == 3.50

    p2_entry = [g for g in status_date["guest_entries"] if g["player_id"] == 2][0]
    assert p2_entry["payment_status"] == "cash"


def test_membership_dues_reconciliation(clean_finances_env):
    fin_conn = get_finances_connection()
    set_player_membership_status(fin_conn, 1, "member")
    fin_conn.close()

    dues = get_membership_dues_overview("2026-H2")
    assert dues["total_members"] >= 1
    assert dues["total_expected"] >= 48.00

    manual_mark_membership_due("2026-H2", 1, payment_method="bank")
    dues_after = get_membership_dues_overview("2026-H2")
    p1_due = [m for m in dues_after["members"] if m["player_id"] == 1][0]
    assert p1_due["payment_status"] == "bank"
    assert p1_due["amount_paid"] == 48.00


def test_webmaster_finances_web_routes(clean_finances_env):
    app = create_app()
    client = app.test_client()

    user_id, _ = register_user("master", "master@rb48.de", "Password123!", role="webmaster")
    acc_conn = get_accounts_connection()
    from scripts.accounts.database import mark_email_verified, update_user_role
    mark_email_verified(acc_conn, user_id)
    approve_user(acc_conn, user_id, approved=True)
    update_user_role(acc_conn, user_id, "webmaster")
    acc_conn.close()
    pass_psychology_test(user_id)

    # Access without login -> redirect
    resp = client.get("/admin/finances")
    assert resp.status_code == 302

    # Login as webmaster
    with client.session_transaction() as sess:
        sess["user_id"] = user_id

    # Access dashboard
    resp = client.get("/admin/finances")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Finanzen" in html
    assert "Beitragsverwaltung" in html

    # Test toggling player status via AJAX
    resp_status = client.post(
        "/admin/finances/set-player-status",
        data={"player_id": 2, "status": "member"},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert resp_status.status_code == 200
    assert resp_status.json["success"] is True

    # Test marking match guest via AJAX
    resp_mark = client.post(
        "/admin/finances/mark-match-guest",
        data={"match_date": "2026-07-15", "player_id": 33, "payment_method": "cash"},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert resp_mark.status_code == 200
    assert resp_mark.json["success"] is True

    # Test presence of copy buttons and header text in tab=matches
    resp_after = client.get("/admin/finances?tab=matches")
    assert resp_after.status_code == 200
    after_html = resp_after.get_data(as_text=True)
    assert "btn-copy-all-open" in after_html
    assert "btn-copy-month-open" in after_html
    assert "copyAllOpenDebts" in after_html
    assert "copyMonthOpenDebts" in after_html
    assert "copyDayOpenDebts" in after_html
    assert "Offene Beträge seit" in after_html
    assert "buildFooterText" in after_html
    assert "Die Liste kann unvollständig sein und/oder falsche Einträge beinhalten" in after_html
    assert "(automatisch erstellt)" in after_html

    # Test presence of new cards and period filter
    assert "Offene Gastbeiträge" in after_html
    assert "Offene Mitgliedsbeiträge" in after_html
    assert "Paypaleinnahmen" in after_html
    assert "Kontoeinnahmen" in after_html
    assert "finance-period-select" in after_html
    assert "changeFinancePeriod" in after_html

    # Test presence of ignored aliases in tab=identities dropdown
    resp_identities = client.get("/admin/finances?tab=identities")
    assert resp_identities.status_code == 200
    identities_html = resp_identities.get_data(as_text=True)
    assert "ignored:Micha+1" in identities_html
    assert "Ignorierte Aliase / Externe G" in identities_html

    # Test saving identity with ignored alias (transparent guest promotion)
    resp_save_id = client.post(
        "/admin/finances/identity/save",
        data={
            "payer_email": "micha.gast@example.com",
            "payer_name": "Micha Gast",
            "player_id": "ignored:Micha+1",
        },
        follow_redirects=True,
    )
    assert resp_save_id.status_code == 200


def test_get_all_unpaid_guest_entries(clean_finances_env):
    unpaid = get_all_unpaid_guest_entries()
    assert isinstance(unpaid, list)
    # Player 33 is a guest who played on 2026-07-15 and has not paid yet
    assert len(unpaid) >= 1
    found_33 = any(u["player_id"] == 33 and u["match_date"] == "2026-07-15" for u in unpaid)
    assert found_33
    entry = next(u for u in unpaid if u["player_id"] == 33)
    assert entry["name"] == "Kha"
    assert entry["match_date"] == "2026-07-15"
    assert entry["fee_required"] == 3.50
    assert entry["payment_status"] == "unpaid"


def test_finance_summary_metrics_and_period_filtering(clean_finances_env):
    # Test available periods
    periods = get_available_finance_periods()
    assert len(periods) >= 3
    values = [p["value"] for p in periods]
    assert "2026-H2" in values
    assert "2026" in values
    assert "all" in values

    # Test period labels
    assert "2. Halbjahr" in get_period_display_label("2026-H2")
    assert "Gesamtjahr 2026" == get_period_display_label("2026")
    assert "Gesamter Zeitraum" in get_period_display_label("all")

    # Initial metrics before payments
    m_h2 = get_finance_summary_metrics("2026-H2")
    assert "open_klecker_amount" in m_h2
    assert "open_dues_amount" in m_h2
    assert "total_paypal_income" in m_h2
    assert "total_bank_income" in m_h2

    # Add a PayPal allocation for guest fee and bank allocation for membership due
    f_conn = get_finances_connection()
    # 1. Guest fee paid via PayPal
    add_payment_allocation(
        f_conn,
        fee_type="match_guest",
        allocated_amount=3.50,
        payment_method="paypal",
        match_date="2026-07-15",
        player_id=33,
    )
    # 2. Member due paid via Bank
    add_payment_allocation(
        f_conn,
        fee_type="membership_due",
        allocated_amount=48.00,
        payment_method="bank",
        period="2026-H2",
        player_id=1,
    )
    f_conn.close()

    # Recalculate metrics for 2026-H2
    m_after = get_finance_summary_metrics("2026-H2")
    assert m_after["paypal_guest_fees"] == 3.50
    assert m_after["bank_membership_dues"] == 48.00
    assert m_after["total_bank_income"] == 48.00
    assert m_after["total_paypal_income"] >= 3.50

    # For an unrelated period (e.g. 2025-H1), these 2026 allocations should NOT count
    m_2025 = get_finance_summary_metrics("2025-H1")
    assert m_2025["paypal_guest_fees"] == 0.0
    assert m_2025["bank_membership_dues"] == 0.0


def test_mask_payer_name():
    # User's exact prompt examples
    assert mask_payer_name("Sarah Lagona") == "Sarah Lago..."
    assert mask_payer_name("Julian Lang") == "Julian La.."
    assert mask_payer_name("Stefan Metzger") == "Stefan Met..."

    # Email inputs
    assert mask_payer_name("sarah.lagona@gmail.com") == "Sarah Lago..."
    assert mask_payer_name("juliankorsch@googlemail.com") == "Jul..."

    # Fallback string
    assert mask_payer_name("Transaktion #42") == "Transaktion #42"
    assert mask_payer_name("") == ""


def test_third_party_external_proxy_payment(clean_finances_env):
    """
    Test scenario: Sarah Lago pays via PayPal.
    Sender is actually Claudio (external guest), who pays on behalf of Paul (another external guest).
    """
    r_conn = get_rb48_connection()
    # Claudio (player 50) and Paul (player 51) are both guests
    r_conn.execute("INSERT INTO players (player_id) VALUES (50), (51)")
    r_conn.execute("INSERT INTO aliases (alias, player_id) VALUES ('Claudio', 50), ('Paul', 51)")
    # Paul played in match on 2026-07-15
    add_match_player(r_conn, "2026-07-15-1", 51, "B")
    r_conn.commit()
    r_conn.close()

    f_conn = get_finances_connection()
    set_player_membership_status(f_conn, 50, "guest")
    set_player_membership_status(f_conn, 51, "guest")

    # Transaction from Sarah Lago
    tx_id = insert_transaction(
        f_conn,
        source="paypal",
        tx_code="SL-12345",
        date="2026-07-16",
        time="10:00:00",
        raw_payer_name="Sarah Lago",
        raw_payer_email="sarah.lago@example.com",
        amount=3.50,
        status="imported",
        is_confirmed=0,
    )
    f_conn.close()

    # Settle: Claudio (payer) pays for Paul (beneficiary), and remember identity (Sarah Lago = Claudio)
    res = settle_transaction_and_debts(
        transaction_id=tx_id,
        payer_player_id=50,
        beneficiary_player_id=51,
        match_date="2026-07-15",
        remember=True,
    )
    assert res["success"] is True
    assert res["covered_count"] == 1

    f_conn = get_finances_connection()
    # 1. Transaction is confirmed and assigned to Claudio
    tx = get_transaction_by_id(f_conn, tx_id)
    assert tx["is_confirmed"] == 1
    assert tx["status"] == "assigned"
    assert tx["matched_player_id"] == 50

    # 2. Identity mapping Sarah Lago -> Claudio (50) was saved
    identities = get_identities(f_conn)
    matching_ident = [i for i in identities if i["player_id"] == 50 and i["payer_name"] == "Sarah Lago"]
    assert len(matching_ident) == 1

    # 3. Paul's debt is cleared and attributed to Claudio as payer
    paul_status = get_match_date_guest_status("2026-07-15")
    paul_entry = next(g for g in paul_status["guest_entries"] if g["player_id"] == 51)
    assert paul_entry["payment_status"] == "paid"
    assert paul_entry["paid_by_player_id"] == 50
    assert paul_entry["paid_by_name"] == "Claudio"

    f_conn.close()


def test_settle_transaction_direct_and_manual_linking(clean_finances_env):
    """
    Test scenario: Martin (player 60, guest) had an open kick and was already
    marked as paid manually on the match day. Then an imported transaction is settled:
    it should link to that manual payment, confirm the transaction, and update status.
    """
    r_conn = get_rb48_connection()
    r_conn.execute("INSERT INTO players (player_id) VALUES (60)")
    r_conn.execute("INSERT INTO aliases (alias, player_id) VALUES ('Martin', 60)")
    add_match_player(r_conn, "2026-07-15-1", 60, "B")
    r_conn.commit()
    r_conn.close()

    f_conn = get_finances_connection()
    set_player_membership_status(f_conn, 60, "guest")

    # User manually marked Martin as paid (without transaction_id)
    manual_mark_match_guest_payment("2026-07-15", 60, payment_method="cash")

    # Imported transaction from Martin
    tx_id = insert_transaction(
        f_conn,
        source="paypal",
        tx_code="MART-777",
        date="2026-07-16",
        time="11:00:00",
        raw_payer_name="Martin Meier",
        raw_payer_email="martin.meier@example.com",
        amount=3.50,
        status="imported",
        is_confirmed=0,
    )
    f_conn.close()

    # Settle transaction for Martin directly
    res = settle_transaction_and_debts(
        transaction_id=tx_id,
        payer_player_id=60,
        beneficiary_player_id=60,
    )
    assert res["success"] is True

    f_conn = get_finances_connection()
    tx = get_transaction_by_id(f_conn, tx_id)
    assert tx["is_confirmed"] == 1
    assert tx["status"] == "assigned"

    # Allocation is now linked to this transaction
    allocs = f_conn.execute(
        "SELECT * FROM payment_allocations WHERE match_date = '2026-07-15' AND player_id = 60"
    ).fetchall()
    assert len(allocs) == 1
    assert allocs[0]["transaction_id"] == tx_id

    # Reset transaction
    reset_transaction_settlement(tx_id)
    tx_reset = get_transaction_by_id(f_conn, tx_id)
    assert tx_reset["is_confirmed"] == 0
    assert tx_reset["status"] == "imported"
    assert tx_reset["matched_player_id"] is None

    allocs_after_reset = f_conn.execute(
        "SELECT * FROM payment_allocations WHERE transaction_id = ?", (tx_id,)
    ).fetchall()
    assert len(allocs_after_reset) == 0

    f_conn.close()


def test_ignored_alias_guest_reconciliation_and_manual_marking(clean_finances_env):
    """Test that ignored aliases in match CSVs are properly reconciled as guests and can be marked paid."""
    import csv
    from pathlib import Path

    matches_dir = Path(os.environ["RB48_MATCHES_DIR"])
    match_csv = matches_dir / "2026-08-01-1.csv"
    with open(match_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["match_id", "date", "team_a", "team_b", "score_a", "score_b"])
        writer.writerow(["2026-08-01-1", "2026-08-01", "Stefan, Nik", "Micha+1, Calvin", "10", "8"])

    r_conn = get_rb48_connection()
    # Add Calvin to ignored_aliases as well
    r_conn.execute("INSERT OR IGNORE INTO ignored_aliases (alias) VALUES ('Calvin')")
    create_match(r_conn, "2026-08-01-1", "2026-08-01", "box", 2, 2, 10, 8)
    add_match_player(r_conn, "2026-08-01-1", 1, "A")  # Stefan (member)
    add_match_player(r_conn, "2026-08-01-1", 2, "A")  # Nik (guest)
    r_conn.commit()
    r_conn.close()

    fin_conn = get_finances_connection()
    set_player_membership_status(fin_conn, 1, "member")
    set_player_membership_status(fin_conn, 2, "guest")
    fin_conn.close()

    # Match overview should show 3 guests: Nik (player 2), Micha+1 (ignored), Calvin (ignored)
    overview = get_match_history_financial_overview()
    match_ov = next((m for m in overview if m["match_date"] == "2026-08-01"), None)
    assert match_ov is not None
    assert match_ov["guest_count"] == 3
    assert match_ov["unpaid_count"] == 3

    # Date guest status should list the 3 guests
    details = get_match_date_guest_status("2026-08-01")
    assert len(details["guest_entries"]) == 3
    guest_names = [g["name"] for g in details["guest_entries"]]
    assert "Nik" in guest_names
    assert "Micha+1" in guest_names
    assert "Calvin" in guest_names

    ignored_entry = next(g for g in details["guest_entries"] if g["name"] == "Micha+1")
    assert ignored_entry.get("is_ignored_alias") is True
    assert ignored_entry["player_id"] == "ignored:Micha+1"
    assert ignored_entry["payment_status"] == "unpaid"

    # All unpaid guest entries should include Micha+1 and Calvin
    unpaid = get_all_unpaid_guest_entries()
    unpaid_names = [u["name"] for u in unpaid if u["match_date"] == "2026-08-01"]
    assert "Nik" in unpaid_names
    assert "Micha+1" in unpaid_names
    assert "Calvin" in unpaid_names

    # Manually mark Micha+1 as paid
    manual_mark_match_guest_payment("2026-08-01", "ignored:Micha+1", payment_method="paypal")

    # Re-verify
    details_after = get_match_date_guest_status("2026-08-01")
    micha_after = next(g for g in details_after["guest_entries"] if g["name"] == "Micha+1")
    assert micha_after["payment_status"] == "paid"

    unpaid_after = get_all_unpaid_guest_entries()
    unpaid_names_after = [u["name"] for u in unpaid_after if u["match_date"] == "2026-08-01"]
    assert "Micha+1" not in unpaid_names_after
    assert "Calvin" in unpaid_names_after
    assert "Nik" in unpaid_names_after


def test_third_party_settlement_for_ignored_alias_and_no_remember(clean_finances_env):
    """Test settling a payment for an ignored alias beneficiary without storing identity."""
    f_conn = get_finances_connection()
    tx_id = insert_transaction(
        f_conn,
        source="paypal",
        tx_code="JULIAN-PAY-CALVIN",
        date="2026-08-02",
        time="12:00:00",
        raw_payer_name="Julian Korsch",
        raw_payer_email="julian.korsch@example.com",
        amount=3.50,
        status="imported",
        is_confirmed=0,
    )
    f_conn.close()

    # Settle transaction: payer = Stefan (player 1), beneficiary = ignored:Calvin, remember=False
    res = settle_transaction_and_debts(
        transaction_id=tx_id,
        payer_player_id=1,
        beneficiary_player_id="ignored:Calvin",
        remember=False,
    )
    assert res["success"] is True

    f_conn = get_finances_connection()
    tx = get_transaction_by_id(f_conn, tx_id)
    assert tx["status"] == "assigned"
    assert tx["is_confirmed"] == 1

    allocs = f_conn.execute("SELECT * FROM payment_allocations WHERE transaction_id = ?", (tx_id,)).fetchall()
    assert len(allocs) == 1
    assert allocs[0]["guest_alias"] == "Calvin"
    assert allocs[0]["player_id"] is None

    # Check identities: no identity should be stored for Calvin or mapped erroneously
    idents = get_identities(f_conn)
    for ident in idents:
        assert ident["player_id"] != "ignored:Calvin"
    f_conn.close()


def test_historical_kicks_guest_fee_when_now_member(clean_finances_env):
    """Test that a player who became a member later is still tracked as a guest for kicks before member_since."""
    r_conn = get_rb48_connection()
    r_conn.execute("INSERT INTO players (player_id) VALUES (50)")
    r_conn.execute("INSERT INTO aliases (alias, player_id) VALUES ('Malte', 50)")
    # Match on 2026-07-01 (when Malte was a guest)
    create_match(r_conn, "2026-07-01-1", "2026-07-01", "box", 1, 1, 5, 2)
    add_match_player(r_conn, "2026-07-01-1", 50, "A")
    # Match on 2026-09-15 (after Malte became a member)
    create_match(r_conn, "2026-09-15-1", "2026-09-15", "box", 1, 1, 5, 4)
    add_match_player(r_conn, "2026-09-15-1", 50, "A")
    r_conn.commit()
    r_conn.close()

    fin_conn = get_finances_connection()
    # Malte became a member on 2026-09-01
    set_player_membership_status(fin_conn, 50, "member", member_since="2026-09-01")
    fin_conn.close()

    # As of 2026-07-01, Malte was a guest
    f_conn = get_finances_connection()
    status_jul = resolve_player_membership_status(50, finances_conn=f_conn, as_of_date="2026-07-01")
    assert status_jul == "guest"

    # As of 2026-09-15, Malte is a member
    status_sep = resolve_player_membership_status(50, finances_conn=f_conn, as_of_date="2026-09-15")
    assert status_sep == "member"
    f_conn.close()

    # Unpaid guest entries should include Malte for 2026-07-01, but NOT for 2026-09-15
    unpaid = get_all_unpaid_guest_entries()
    malte_unpaid_dates = [u["match_date"] for u in unpaid if u["player_id"] == 50]
    assert "2026-07-01" in malte_unpaid_dates
    assert "2026-09-15" not in malte_unpaid_dates


def test_unregistered_payer_direct_settlement(clean_finances_env):
    """Test 1-click settlement for an unregistered external payer (e.g. Martin Wagener 7.00 €) without player ID."""
    f_conn = get_finances_connection()
    tx_id = insert_transaction(
        f_conn,
        source="paypal",
        tx_code="MARTIN-WAGENER-7EUR",
        date="2026-07-30",
        time="09:02:31",
        raw_payer_name="Martin Wagener",
        raw_payer_email="machtin@mail.com",
        amount=7.00,
        status="imported",
        is_confirmed=0,
        note="Handyzahlung",
    )
    f_conn.close()

    # 1-click settle directly (payer_player_id=None, remember=False)
    res = settle_transaction_and_debts(
        transaction_id=tx_id,
        payer_player_id=None,
        remember=False,
    )
    assert res["success"] is True

    f_conn = get_finances_connection()
    tx = get_transaction_by_id(f_conn, tx_id)
    assert tx["status"] == "assigned"
    assert tx["is_confirmed"] == 1

    allocs = f_conn.execute("SELECT * FROM payment_allocations WHERE transaction_id = ?", (tx_id,)).fetchall()
    assert len(allocs) == 1
    assert allocs[0]["fee_type"] == "match_guest"
    assert allocs[0]["guest_alias"] == "Martin Wagener"
    assert allocs[0]["player_id"] is None
    assert allocs[0]["allocated_amount"] == 7.00
    f_conn.close()


def test_flexible_member_dues_allocation(clean_finances_env):
    """Test voluntary/flexible membership due payment less than 48.00 € (e.g. 30.00 €) credited properly."""
    f_conn = get_finances_connection()
    set_player_membership_status(f_conn, 1, "member")
    tx_id = insert_transaction(
        f_conn,
        source="bank",
        tx_code="BANK-FLEX-DUE-30",
        date="2026-08-15",
        time="10:00:00",
        raw_payer_name="Stefan Player1",
        raw_payer_email="",
        amount=30.00,
        status="imported",
        is_confirmed=0,
        note="Mitgliedsbeitrag ermäßigt",
    )
    f_conn.close()

    res = settle_transaction_and_debts(
        transaction_id=tx_id,
        payer_player_id=1,
        remember=True,
    )
    assert res["success"] is True

    f_conn = get_finances_connection()
    allocs = f_conn.execute("SELECT * FROM payment_allocations WHERE transaction_id = ?", (tx_id,)).fetchall()
    assert len(allocs) == 1
    assert allocs[0]["fee_type"] == "membership_due"
    assert allocs[0]["player_id"] == 1
    assert allocs[0]["period"] == "2026-H2"
    assert allocs[0]["allocated_amount"] == 30.00
    f_conn.close()

    # Verify metrics for 2026-H2
    metrics = get_finance_summary_metrics("2026-H2")
    # Member 1 should count towards partial_dues_count and not open_dues_count
    assert metrics["partial_dues_count"] >= 1
    assert metrics["open_dues_count"] == 0  # Assuming only player 1 is a member in clean_finances_env


def test_skatbank_pdf_parsing_and_csv_conversion(tmp_path):
    """Test parsing a synthetic Deutsche Skatbank statement PDF and converting to CSV."""
    import pymupdf
    doc = pymupdf.open()
    page = doc.new_page()
    text = (
        "Deutsche Skatbank Kontoauszug 2026\n"
        "01.07.2026 01.07.2026 SEPA-Gutschrift 48,00+\n"
        "Auftraggeber: Max Mustermann\n"
        "Verwendungszweck: Vereinsbeitrag 2026-H2 EREF+11111\n"
        "15.07.2026 15.07.2026 SEPA-Gutschrift 69,00+\n"
        "Auftraggeber: Konstantin Steuer\n"
        "Verwendungszweck: Vereinsbeitrag und Zahlung von Luecke und Jens EREF+22222\n"
        "20.07.2026 20.07.2026 Lastschrift 15,00-\n"
        "Auftraggeber: Sportstaette GmbH\n"
        "Verwendungszweck: Hallenmiete EREF+33333\n"
    )
    page.insert_text((50, 50), text)
    pdf_bytes = doc.tobytes()
    doc.close()

    txs = parse_bank_pdf(pdf_bytes)
    assert len(txs) == 3

    t1 = txs[0]
    assert t1["amount"] == 48.00
    assert t1["raw_payer_name"] == "Max Mustermann"
    assert "Vereinsbeitrag" in t1["note"]
    assert t1["tx_code"] == "EREF-11111"
    assert t1["status"] == "imported"

    t2 = txs[1]
    assert t2["amount"] == 69.00
    assert t2["raw_payer_name"] == "Konstantin Steuer"
    assert "Luecke und Jens" in t2["note"]
    assert t2["tx_code"] == "EREF-22222"

    t3 = txs[2]
    assert t3["amount"] == -15.00
    assert t3["status"] == "expense"

    # Test CSV conversion
    out_csv = tmp_path / "skatbank_test.csv"
    csv_str = convert_pdf_to_csv(pdf_bytes, out_csv)
    assert out_csv.exists()
    assert "48,00" in csv_str
    assert "69,00" in csv_str
    assert "-15,00" in csv_str
    assert "Konstantin Steuer" in csv_str


def test_multi_file_upload_and_directory_storage(clean_finances_env):
    """Test uploading multiple statements (PDF & CSV) simultaneously."""
    import pymupdf
    from web.app import app

    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((50, 50), "Deutsche Skatbank 2026\n01.07.2026 SEPA-Gutschrift 48,00+\nAuftraggeber: Stefan Player1\nVerwendungszweck: Beitrag EREF+998877\n")
    pdf_bytes = doc.tobytes()
    doc.close()

    csv_bytes = (
        '"Datum","Uhrzeit","Zeitzone","Beschreibung","Währung","Brutto","Entgelt","Netto","Guthaben","Transaktionscode","Absender E-Mail-Adresse","Name","Name der Bank","Bankkonto","Versand- und Bearbeitungsgebühr","Umsatzsteuer","Rechnungsnummer","Zugehöriger Transaktionscode"\n'
        '"10.07.2026","12:09:12","Europe/Berlin","Handyzahlung","EUR","3,50","0,00","3,50","732,06","PP-TEST-MULTI-1","samuel@schelp.eu","Samuel Schelp","","","0,00","0,00","",""\n'
    ).encode("utf-8")

    client = _login_webmaster(app)

    resp = client.post(
        "/admin/finances/upload",
        data={
            "files": [
                (io.BytesIO(pdf_bytes), "kontoauszug_juli.pdf"),
                (io.BytesIO(csv_bytes), "paypal_juli.csv"),
            ]
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Upload erfolgreich" in html
    assert "Einträge wurden zur Bearbeitung hinzugefügt" in html

    # Verify directory contents
    sk_dir = Path("data/finances/skatbank")
    pp_dir = Path("data/finances/paypal")
    assert (sk_dir / "kontoauszug_juli.pdf").exists()
    assert (sk_dir / "kontoauszug_juli.csv").exists()
    assert (pp_dir / "paypal_juli.csv").exists()

    # Clean up test files in data/finances/
    (sk_dir / "kontoauszug_juli.pdf").unlink(missing_ok=True)
    (sk_dir / "kontoauszug_juli.csv").unlink(missing_ok=True)
    (pp_dir / "paypal_juli.csv").unlink(missing_ok=True)


def test_combo_split_suggestion_and_bulk_apply(clean_finances_env):
    """Test smart combination payment split (48€ due + 21€ guests) and 'Alle Vorschläge übernehmen'."""
    from web.app import app
    r_conn = get_rb48_connection()
    # Payer Konstantin (player 20), Guests: Luecke (player 27) and Jens (player 31)
    r_conn.execute("INSERT INTO players (player_id) VALUES (20), (27), (31)")
    r_conn.execute("INSERT INTO aliases (alias, player_id) VALUES ('Konsti', 20), ('Lücke', 27), ('Konsti+1 (Jens)', 31)")
    # Unpaid matches for Luecke
    create_match(r_conn, "2026-07-22-1", "2026-07-22", "box", 1, 1, 5, 2)
    add_match_player(r_conn, "2026-07-22-1", 27, "A")
    create_match(r_conn, "2026-07-29-1", "2026-07-29", "box", 1, 1, 5, 2)
    add_match_player(r_conn, "2026-07-29-1", 27, "A")
    create_match(r_conn, "2026-08-04-1", "2026-08-04", "box", 1, 1, 5, 2)
    add_match_player(r_conn, "2026-08-04-1", 27, "A")
    # Unpaid matches for Jens
    create_match(r_conn, "2026-08-19-1", "2026-08-19", "box", 1, 1, 5, 2)
    add_match_player(r_conn, "2026-08-19-1", 31, "A")
    create_match(r_conn, "2026-08-26-1", "2026-08-26", "box", 1, 1, 5, 2)
    add_match_player(r_conn, "2026-08-26-1", 31, "A")
    create_match(r_conn, "2026-09-23-1", "2026-09-23", "box", 1, 1, 5, 2)
    add_match_player(r_conn, "2026-09-23-1", 31, "A")
    r_conn.commit()
    r_conn.close()

    f_conn = get_finances_connection()
    set_player_membership_status(f_conn, 20, "member")
    tx_id = insert_transaction(
        f_conn,
        source="paypal",
        tx_code="KONSTI-69-EUR-COMBO",
        date="2026-10-02",
        time="08:26:22",
        raw_payer_name="Konstantin Steuer",
        raw_payer_email="konstantin-steuer@web.de",
        amount=69.00,
        status="imported",
        is_confirmed=0,
        note="Vereinsbeitrag und Zahlung von Lücke und Jens",
    )
    f_conn.close()

    # Verify suggestion calculation
    sug = get_proxy_payment_suggestion(tx_id, 20)
    assert sug is not None
    assert sug["is_combo_split"] is True
    assert sug["due_amount"] == 48.00
    assert sug["guest_amount"] == 21.00
    assert sug["num_kicks"] == 6
    assert len(sug["suggested_guests"]) == 6
    guest_pids = [g["player_id"] for g in sug["suggested_guests"]]
    assert guest_pids.count(27) == 3  # 3 kicks for Luecke
    assert guest_pids.count(31) == 3  # 3 kicks for Jens
    assert "48,00" in sug["summary_text"]
    assert "21,00" in sug["summary_text"]

    client = _login_webmaster(app)

    # Test "Alle Vorschläge übernehmen" route
    resp = client.post("/admin/finances/apply_all_suggestions", follow_redirects=True)
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Vorschläge erfolgreich übernommen" in html or "Vorschlag erfolgreich übernommen" in html

    # Verify allocations in database
    f_conn = get_finances_connection()
    tx = get_transaction_by_id(f_conn, tx_id)
    assert tx["status"] == "assigned"
    assert tx["is_confirmed"] == 1

    allocs = f_conn.execute("SELECT * FROM payment_allocations WHERE transaction_id = ?", (tx_id,)).fetchall()
    assert len(allocs) == 7  # 1 membership due + 6 guest kicks
    due_alloc = next(a for a in allocs if a["fee_type"] == "membership_due")
    assert due_alloc["allocated_amount"] == 48.00
    assert due_alloc["player_id"] == 20

    guest_allocs = [a for a in allocs if a["fee_type"] == "match_guest"]
    assert len(guest_allocs) == 6
    assert sum(a["allocated_amount"] for a in guest_allocs) == 21.00
    f_conn.close()


def test_copy_paste_footer_unassigned_payer_with_date(clean_finances_env):
    """Test copy-paste footer formatting with payment date for unassigned payers."""
    from web.app import app
    f_conn = get_finances_connection()
    insert_transaction(
        f_conn,
        source="paypal",
        tx_code="UNASSIGNED-STEFAN-METZGER",
        date="2026-08-19",
        time="22:53:47",
        raw_payer_name="Stefan Metzger",
        raw_payer_email="stef.metzger@gmail.com",
        amount=3.50,
        status="imported",
        is_confirmed=0,
    )
    f_conn.close()

    client = _login_webmaster(app)

    resp = client.get("/admin/finances?tab=import")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    # UNASSIGNED_PAYERS in JS
    assert 'UNASSIGNED_PAYERS = [{"date": "2026-08-19", "name": "Stefan Met..."}]' in html or 'Stefan Met...' in html
    assert "die Zahlung von" in html or "die Zahlungen von" in html


def test_dues_period_date_range():
    """Test date range, label, and has_ended status computation."""
    h1 = get_period_date_range("2026-H1")
    assert h1["start"] == "2026-01-01"
    assert h1["end"] == "2026-06-30"
    assert h1["has_ended"] is True  # 2026-10-02 > 2026-06-30
    assert "1. Halbjahr" in h1["label"]

    h2 = get_period_date_range("2026-H2")
    assert h2["start"] == "2026-07-01"
    assert h2["end"] == "2026-12-31"
    assert h2["has_ended"] is False  # 2026-10-02 <= 2026-12-31
    assert "2. Halbjahr" in h2["label"]


def test_dues_attendance_active_vs_inactive_in_ended_period(clean_finances_env):
    """Test distinguishing active open dues vs inactive members with 0 kicks in ended periods."""
    r_conn = get_rb48_connection()
    # Player 1 played in 2026-H1 (March 2026)
    create_match(r_conn, "2026-03-10-1", "2026-03-10", "box", 1, 1, 5, 3)
    add_match_player(r_conn, "2026-03-10-1", 1, "A")
    # Player 2 has 0 matches in 2026-H1
    r_conn.commit()
    r_conn.close()

    f_conn = get_finances_connection()
    set_player_membership_status(f_conn, 1, "member")
    set_player_membership_status(f_conn, 2, "member")
    f_conn.close()

    # Initial check for 2026-H1 (ended period)
    ov = get_membership_dues_overview("2026-H1")
    assert ov["period_dates"]["has_ended"] is True
    p1 = next(m for m in ov["members"] if m["player_id"] == 1)
    p2 = next(m for m in ov["members"] if m["player_id"] == 2)

    assert p1["games_count"] == 1
    assert p1["was_present"] is True
    assert p1["payment_status"] == "unpaid"  # Truly unpaid, active player!

    assert p2["games_count"] == 0
    assert p2["was_present"] is False
    assert p2["payment_status"] == "unpaid_inactive_ended"  # 0 games, period ended!

    # Setting Player 2 to inactive removes their debt requirement
    manual_mark_membership_due("2026-H1", 2, "waived", note="inaktiv")
    ov2 = get_membership_dues_overview("2026-H1")
    p2_updated = next(m for m in ov2["members"] if m["player_id"] == 2)
    assert p2_updated["payment_status"] == "inactive"
    assert p2_updated["is_inactive"] is True
    assert p2_updated["fee_required"] == 0.0

    # Total expected now only counts the active member (Player 1)
    assert ov2["total_expected"] == 48.00
    assert ov2["outstanding"] == 48.00
    assert ov2["count_unpaid_active"] == 1
    assert ov2["count_inactive"] == 1

    # Test bulk_set_inactive_members for any remaining 0-kick members
    f_conn = get_finances_connection()
    set_player_membership_status(f_conn, 33, "member")
    f_conn.close()

    # Player 33 has 0 games in 2026-H1
    ov3 = get_membership_dues_overview("2026-H1")
    assert ov3["count_unpaid_inactive"] >= 1

    count = bulk_set_inactive_members("2026-H1")
    assert count >= 1

    ov4 = get_membership_dues_overview("2026-H1")
    p33 = next(m for m in ov4["members"] if m["player_id"] == 33)
    assert p33["payment_status"] == "inactive"
    assert p33["fee_required"] == 0.0


def test_dues_matrix_and_web_routes(clean_finances_env):
    """Test cross-period dues matrix and web routes."""
    from web.app import app
    f_conn = get_finances_connection()
    set_player_membership_status(f_conn, 1, "member")
    set_player_membership_status(f_conn, 2, "member")
    f_conn.close()

    # Matrix computation
    mat = get_membership_dues_matrix()
    assert len(mat["periods"]) >= 2
    assert any(p["value"] == "2026-H2" for p in mat["periods"])
    assert any(p["value"] == "2026-H1" for p in mat["periods"])
    assert len(mat["members"]) >= 2

    client = _login_webmaster(app)

    # 1. Period detail view
    resp = client.get("/admin/finances?tab=dues&period=2026-H2")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Mitgliedsbeiträge" in html
    assert "Soll (" in html
    assert "Halbjahr-Detailansicht" in html
    assert "Gesamt-Matrix" in html

    # 2. Matrix view
    resp_mat = client.get("/admin/finances?tab=dues&dues_view=matrix")
    assert resp_mat.status_code == 200
    html_mat = resp_mat.get_data(as_text=True)
    assert "Gesamt bezahlt" in html_mat
    assert "2026-H2" in html_mat

    # 3. Mark inactive via AJAX
    resp_ajax = client.post(
        "/admin/finances/mark-membership-due",
        data={"period": "2026-H1", "player_id": 2, "payment_method": "waived", "note": "inaktiv"},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert resp_ajax.status_code == 200
    assert resp_ajax.get_json()["success"] is True

    # 4. Bulk set inactive route
    resp_bulk = client.post("/admin/finances/bulk-set-inactive", data={"period": "2026-H1"}, follow_redirects=True)
    assert resp_bulk.status_code == 200


def test_detailed_paypal_csv_parsing():
    """Test that detailed PayPal CSV format (Download.CSV) with Hinweis, Betreff, and Typ is parsed properly."""
    detailed_csv = """Datum;Uhrzeit;Zeitzone;Name;Typ;Status;Währung;Brutto;Gebühr;Netto;Absender E-Mail-Adresse;Empfänger E-Mail-Adresse;Transaktionscode;Lieferadresse;Adress-Status;Artikelbezeichnung;Artikelnummer;Versand- und Bearbeitungsgebühr;Versicherungsbetrag;Umsatzsteuer;Option 1 Name;Option 1 Wert;Option 2 Name;Option 2 Wert;Zugehöriger Transaktionscode;Rechnungsnummer;Zollnummer;Anzahl;Empfangsnummer;Guthaben;Adresszeile 1;Adresszusatz;Ort;Bundesland;PLZ;Land;Telefon;Betreff;Hinweis;Ländervorwahl;Auswirkung auf Guthaben
10.07.2026;09:00:00;MESZ;Tim Hauler;Handyzahlung;Abgeschlossen;EUR;3,50;0,00;3,50;tim@example.com;;TX1001;;;;;;;;;;;;;;;;;;;;;;;;;Kicken;;Haben
29.07.2026;11:00:00;MESZ;Aron Salamon;Handyzahlung;Abgeschlossen;EUR;10,50;0,00;10,50;aron@example.com;;TX1002;;;;;;;;;;;;;;;;;;;;;;;;;Zock Aron 08. / 22. / 29. Juli;;Haben
30.07.2026;12:00:00;MESZ;Eversport GmbH;PayPal Express-Zahlung;Abgeschlossen;EUR;-74,00;0,00;-74,00;ever@example.com;;TX1003;;;Platzbuchung Kautz;;;;;;;;;;;;;;;;;;;;;;Platzbuchung Fußball 04.08.2026;;;Soll
05.08.2026;14:00:00;MESZ;Philipp Nockemann;Handyzahlung;Abgeschlossen;EUR;36,00;0,00;36,00;philipp@example.com;;TX1004;;;;;;;;;;;;;;;;;;;;;;;;;Mitgliedsbeitrag SoSe 2026;;Haben
"""
    txs = parse_paypal_csv(detailed_csv)
    assert len(txs) == 4

    # Tim Hauler
    assert txs[0]["tx_code"] == "TX1001"
    assert txs[0]["amount"] == 3.50
    assert txs[0]["note"] == "Kicken"
    assert txs[0]["status"] == "imported"

    # Aron Salamon
    assert txs[1]["tx_code"] == "TX1002"
    assert txs[1]["amount"] == 10.50
    assert "Zock Aron" in txs[1]["note"]

    # Eversport
    assert txs[2]["tx_code"] == "TX1003"
    assert txs[2]["amount"] == -74.00
    assert txs[2]["status"] == "expense"
    assert "Platzbuchung" in txs[2]["note"]

    # Philipp Nockemann (flexible / self-chosen dues amount)
    assert txs[3]["tx_code"] == "TX1004"
    assert txs[3]["amount"] == 36.00
    assert "Mitgliedsbeitrag SoSe 2026" in txs[3]["note"]


def test_skatbank_pdf_parsing_if_available():
    """Test Skatbank PDF parsing on real statements if present in data/finances/skatbank."""
    skatbank_dir = Path("data/finances/skatbank")
    pdf_files = list(skatbank_dir.glob("*.pdf"))
    if not pdf_files:
        pytest.skip("No Skatbank PDFs found in data/finances/skatbank/")

    total_txs = 0
    for p in pdf_files:
        txs = parse_bank_pdf(p)
        total_txs += len(txs)
        for t in txs:
            assert t["source"] == "bank"
            assert t["date"].startswith("202")
            assert t["amount"] != 0.0

    assert total_txs >= 15


def test_finance_archive_workflow(clean_finances_env, monkeypatch):
    """Test archiving current list, viewing archives, downloading CSV, and deleting archive."""
    app = create_app()
    client = _login_webmaster(app)

    # Insert a couple of sample transactions
    finances_conn = get_finances_connection()
    insert_transaction(
        finances_conn,
        source="paypal",
        tx_code="TX_ARCHIVE_1",
        date="2026-07-22",
        time="10:00:00",
        raw_payer_name="Tim Hauler",
        raw_payer_email="tim@example.com",
        amount=3.50,
        description="Handyzahlung",
        status="imported",
        is_confirmed=1,
    )
    insert_transaction(
        finances_conn,
        source="bank",
        tx_code="TX_ARCHIVE_2",
        date="2026-07-23",
        time="00:00:00",
        raw_payer_name="Universitat zu Koln",
        raw_payer_email=None,
        amount=-120.00,
        description="Basislastschrift",
        status="expense",
        is_confirmed=1,
    )
    finances_conn.close()

    # 1. Trigger archive
    resp_arch = client.post(
        "/admin/finances/archive-current",
        data={"archive_title": "Testarchiv 2026", "archive_notes": "Sicherung vor Monatsabschluss"},
        follow_redirects=True,
    )
    assert resp_arch.status_code == 200
    html = resp_arch.get_data(as_text=True)
    assert "Testarchiv 2026" in html
    assert "Zahlungslisten-Archiv" in html
    assert "bereinigt" in html

    # 2. Check archive list from DB and verify active transactions table was purged
    finances_conn = get_finances_connection()
    from scripts.finances.database import get_finance_archives
    remaining_tx = get_transactions(finances_conn)
    assert len(remaining_tx) == 0  # Imported list was cleared!

    archives = get_finance_archives(finances_conn)
    assert len(archives) >= 1
    arch_id = archives[0]["id"]
    assert archives[0]["title"] == "Testarchiv 2026"
    assert archives[0]["tx_count"] == 2
    assert archives[0]["total_income"] == 3.50
    assert archives[0]["total_expenses"] == 120.00
    finances_conn.close()

    # 3. Download archive CSV
    resp_dl = client.get(f"/admin/finances/download-archive/{arch_id}")
    assert resp_dl.status_code == 200
    assert "text/csv" in resp_dl.content_type
    dl_content = resp_dl.get_data(as_text=True)
    assert "TX_ARCHIVE_1" in dl_content
    assert "Tim Hauler" in dl_content
    assert "TX_ARCHIVE_2" in dl_content
    assert "Universitat zu Koln" in dl_content

    # 4. Delete archive
    resp_del = client.post(f"/admin/finances/delete-archive/{arch_id}", follow_redirects=True)
    assert resp_del.status_code == 200
    finances_conn = get_finances_connection()
    archives_after = get_finance_archives(finances_conn)
    assert not any(a["id"] == arch_id for a in archives_after)
    finances_conn.close()


def test_admin_finances_import_tab_display(clean_finances_env):
    """
    Test that the import tab renders the Betreff / Verwendungszweck and Absender columns,
    displays transaction notes prominently, and positions the archive section below the list.
    """
    app = create_app()
    client = _login_webmaster(app)

    finances_conn = get_finances_connection()
    insert_transaction(
        finances_conn,
        source="paypal",
        tx_code="TX_NOTE_DISPLAY_TEST",
        date="2026-08-01",
        time="14:30:00",
        raw_payer_name="Konstantin Steuer",
        raw_payer_email="konsti@example.com",
        amount=69.00,
        description="PayPal Zahlung",
        status="imported",
        is_confirmed=0,
        note="Vereinsbeitrag und Zahlung von Lücke und Jens",
    )
    finances_conn.close()

    resp = client.get("/admin/finances?tab=import")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    # 1. Check table headers
    assert "Absender" in html
    assert "Betreff / Verwendungszweck" in html

    # 2. Check sender and note display
    assert "Konstantin Steuer" in html
    assert "konsti@example.com" in html
    assert "Vereinsbeitrag und Zahlung von Lücke und Jens" in html

    # 3. Verify positioning: Open list appears before archive section in DOM
    open_list_pos = html.find("Importierte Zahlungen")
    archive_section_pos = html.find('id="archive-section"')
    assert open_list_pos != -1
    assert archive_section_pos != -1
    assert open_list_pos < archive_section_pos, "Archive section must be positioned below the open transactions list!"


def test_skatbank_csv_verwendungszweck_and_payer_parsing():
    """Verify that Skatbank / Bank CSV correctly extracts Verwendungszweck and Auftraggeber."""
    from scripts.finances.bank_pdf_parser import parse_bank_csv
    from scripts.finances.paypal_parser import parse_paypal_csv

    bank_csv_text = (
        '"Buchungstag";"Valutadatum";"Auftraggeber";"Empfänger";"Verwendungszweck";"Betrag";"Währung";"Umsatzart"\n'
        '"23.09.2026";"23.09.2026";"Stefan Met...";"RB48 e.V.";"Mitgliedsbeitrag 2. Halbjahr 2026";"48,00";"EUR";"Überweisungsgutschr. PN:931"\n'
        '"24.09.2026";"24.09.2026";"Martin Wagener";"RB48 e.V.";"2x Gastbeitrag 17.09 und 23.09";"7,00";"EUR";"Gutschrift"\n'
    )
    rows = parse_bank_csv(bank_csv_text)
    assert len(rows) == 2

    assert rows[0]["raw_payer_name"] == "Stefan Met..."
    assert rows[0]["note"] == "Mitgliedsbeitrag 2. Halbjahr 2026"
    assert rows[0]["amount"] == 48.00
    assert rows[0]["source"] == "bank"

    assert rows[1]["raw_payer_name"] == "Martin Wagener"
    assert rows[1]["note"] == "2x Gastbeitrag 17.09 und 23.09"
    assert rows[1]["amount"] == 7.00
    assert rows[1]["source"] == "bank"

    # Also test that parse_paypal_csv gracefully detects bank columns as fallback
    fallback_rows = parse_paypal_csv(bank_csv_text)
    assert len(fallback_rows) == 2
    assert fallback_rows[0]["source"] == "bank"
    assert fallback_rows[0]["raw_payer_name"] == "Stefan Met..."
    assert fallback_rows[0]["note"] == "Mitgliedsbeitrag 2. Halbjahr 2026"


def test_open_debts_and_transaction_cleared_debts_preview(clean_finances_env):
    """Test get_all_players_open_debts and get_transaction_cleared_debts_preview."""
    from scripts.finances.reconciliation import (
        get_all_players_open_debts,
        get_transaction_cleared_debts_preview,
    )
    from scripts.finances.database import get_finances_connection
    from scripts.database.database import get_connection as get_rb48_connection
    from scripts.accounts.database import get_accounts_connection

    fin_conn = get_finances_connection()
    rb_conn = get_rb48_connection()
    acc_conn = get_accounts_connection()

    all_debts = get_all_players_open_debts(fin_conn, rb_conn, acc_conn)
    assert isinstance(all_debts, dict)

    # Test preview for member or guest
    preview_48 = get_transaction_cleared_debts_preview(48.0, 1, all_player_debts=all_debts)
    assert "Gastbeitrag" in preview_48 or "Mitgliedsbeitrag" in preview_48 or "Keine offenen Posten" in preview_48

    # Test preview for 7€ (2 kicks)
    preview_7 = get_transaction_cleared_debts_preview(7.0, 2, all_player_debts=all_debts)
    assert "Gastbeitrag" in preview_7 or "Mitgliedsbeitrag" in preview_7 or "Keine offenen Posten" in preview_7 or "Teilbetrag" in preview_7

    fin_conn.close()
    rb_conn.close()
    acc_conn.close()


def test_admin_finances_cleared_debts_preview_and_upload_ui_display(clean_finances_env):
    """Test that admin finances renders drag & drop upload UI and debt preview badges."""
    from web.app import app
    from scripts.finances.database import get_finances_connection, insert_transaction

    fin_conn = get_finances_connection()
    tx_id = insert_transaction(
        fin_conn,
        source="bank",
        tx_code="SKATBANK-TEST-123",
        date="2026-09-23",
        time="10:00:00",
        raw_payer_name="Martin Wagener",
        raw_payer_email=None,
        amount=7.00,
        description="Banküberweisung",
        status="imported",
        is_confirmed=0,
        note="2x Gastbeitrag",
    )
    fin_conn.close()

    client = _login_webmaster(app)
    resp = client.get("/admin/finances?tab=import")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    # Upload UI elements
    assert 'id="upload-dropzone"' in html
    assert 'id="upload-file-input"' in html
    assert 'id="upload-files-preview"' in html
    assert 'id="upload-submit-btn"' in html

    # Transaction rendered with source and note
    assert "Martin Wagener" in html
    assert "2x Gastbeitrag" in html
    assert "bank" in html
    assert f'value="{tx_id}"' in html


def test_all_open_debts_json_serialization_sort_keys(clean_finances_env):
    """Verify that get_all_players_open_debts produces string keys and serializes with sort_keys=True."""
    import json
    from web.app import app

    debts = get_all_players_open_debts()
    assert isinstance(debts, OpenDebtsDict)

    # All keys in the returned dictionary must be strings so json.dumps(sort_keys=True) works
    for k in debts.keys():
        assert isinstance(k, str), f"Key {k!r} is not a string (type: {type(k)})"

    # Must serialize without raising TypeError: '<' not supported between instances of 'str' and 'int'
    serialized = json.dumps(debts, sort_keys=True)
    assert isinstance(serialized, str)

    # Test dictionary transparent lookup with both int and str
    test_dict = OpenDebtsDict()
    test_dict["12"] = {"total_open": 7.0}
    test_dict["ignored:Lücke"] = {"total_open": 3.5}
    test_dict["Lücke"] = {"total_open": 3.5}

    assert test_dict[12]["total_open"] == 7.0
    assert test_dict["12"]["total_open"] == 7.0
    assert test_dict.get(12)["total_open"] == 7.0
    assert test_dict.get("12")["total_open"] == 7.0
    assert test_dict["ignored:Lücke"]["total_open"] == 3.5
    assert test_dict["Lücke"]["total_open"] == 3.5
    assert test_dict.get("Lücke")["total_open"] == 3.5
    assert test_dict.get("ignored:Lücke")["total_open"] == 3.5
    assert 12 in test_dict
    assert "12" in test_dict
    assert "Lücke" in test_dict
    assert "ignored:Lücke" in test_dict

    # Verify that Jinja2 /tojson in admin_finances route template renders without TypeError
    client = _login_webmaster(app)
    resp = client.get("/admin/finances")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "const ALL_OPEN_DEBTS =" in html


def test_semester_and_fullyear_dues_inference_and_settlement(clean_finances_env):
    """Test SoSe26 (Bernhard Greven 48€) and Ganzjahr 2026 (Michael Schneemann 96€) inference, preview, and settlement."""
    from scripts.finances.reconciliation import (
        infer_transaction_settlement_target,
        get_transaction_cleared_debts_preview,
        settle_transaction_and_debts,
        get_allocations_for_period,
    )
    from scripts.finances.database import insert_transaction, set_player_membership_status, get_finances_connection
    from scripts.database.database import get_connection as get_rb48_conn

    # Setup players 70 (Bernhard) and 71 (Michael)
    r_conn = get_rb48_conn()
    r_conn.execute("INSERT INTO players (player_id) VALUES (70)")
    r_conn.execute("INSERT INTO aliases (alias, player_id) VALUES ('Bernhard', 70)")
    r_conn.execute("INSERT INTO players (player_id) VALUES (71)")
    r_conn.execute("INSERT INTO aliases (alias, player_id) VALUES ('Micha', 71)")
    r_conn.commit()
    r_conn.close()

    f_conn = get_finances_connection()
    set_player_membership_status(f_conn, 70, "member")
    set_player_membership_status(f_conn, 71, "member")
    f_conn.close()

    # 1. Bernhard Greven: 48,00 € with note "Mitgliedsbeitrag SoSe26"
    inferred_bernhard = infer_transaction_settlement_target(
        48.0, tx_date="2026-05-04", note="Mitgliedsbeitrag SoSe26", description="Überweisungsgutschr. PN:5931"
    )
    assert inferred_bernhard["target_settlement"] == "due:2026-H1"
    assert inferred_bernhard["periods"] == ["2026-H1", "2026-H2"]

    preview_bernhard = get_transaction_cleared_debts_preview(
        48.0, 70, tx_date="2026-05-04", tx_note="Mitgliedsbeitrag SoSe26", tx_description="Überweisungsgutschr. PN:5931"
    )
    assert "Mitgliedsbeitrag 2026-H1 (48,00 €)" in preview_bernhard

    # Insert transaction and settle
    f_conn = get_finances_connection()
    tx_b_id = insert_transaction(
        f_conn,
        source="bank",
        tx_code="SKAT-BERNHARD-SOSE26",
        date="2026-05-04",
        time="00:00:00",
        raw_payer_name="Bernhard Greven",
        raw_payer_email="",
        amount=48.00,
        status="imported",
        is_confirmed=0,
        note="Mitgliedsbeitrag SoSe26",
    )
    f_conn.close()

    res_b = settle_transaction_and_debts(
        transaction_id=tx_b_id,
        payer_player_id=70,
        beneficiary_player_id=70,
    )
    assert res_b["success"] is True

    f_conn = get_finances_connection()
    allocs_h1 = get_allocations_for_period(f_conn, "2026-H1")
    b_allocs_h1 = [a for a in allocs_h1 if a["player_id"] == 70]
    assert len(b_allocs_h1) == 1
    assert b_allocs_h1[0]["allocated_amount"] == 48.00
    assert b_allocs_h1[0]["fee_type"] == "membership_due"
    f_conn.close()

    # 2. Michael Schneemann: 96,00 € with note "Schneemann Mitgliedsbeitrag 2026"
    inferred_micha = infer_transaction_settlement_target(
        96.0, tx_date="2026-04-30", note="Schneemann Mitgliedsbeitrag 2026", description="Überweisungsgutschr. PN:931"
    )
    assert inferred_micha["target_settlement"] == "due:2026-year"
    assert inferred_micha["periods"] == ["2026-H1", "2026-H2"]

    preview_micha = get_transaction_cleared_debts_preview(
        96.0, 71, tx_date="2026-04-30", tx_note="Schneemann Mitgliedsbeitrag 2026", tx_description="Überweisungsgutschr. PN:931"
    )
    assert "Mitgliedsbeitrag 2026-H1 (48,00 €)" in preview_micha
    assert "Mitgliedsbeitrag 2026-H2 (48,00 €)" in preview_micha
    assert "Guthaben" not in preview_micha

    # Insert transaction and settle
    f_conn = get_finances_connection()
    tx_m_id = insert_transaction(
        f_conn,
        source="bank",
        tx_code="SKAT-MICHA-2026",
        date="2026-04-30",
        time="00:00:00",
        raw_payer_name="Michael Schneemann",
        raw_payer_email="",
        amount=96.00,
        status="imported",
        is_confirmed=0,
        note="Schneemann Mitgliedsbeitrag 2026",
    )
    f_conn.close()

    res_m = settle_transaction_and_debts(
        transaction_id=tx_m_id,
        payer_player_id=71,
        beneficiary_player_id=71,
    )
    assert res_m["success"] is True

    f_conn = get_finances_connection()
    allocs_m_h1 = [a for a in get_allocations_for_period(f_conn, "2026-H1") if a["player_id"] == 71]
    allocs_m_h2 = [a for a in get_allocations_for_period(f_conn, "2026-H2") if a["player_id"] == 71]
    assert len(allocs_m_h1) == 1
    assert allocs_m_h1[0]["allocated_amount"] == 48.00
    assert len(allocs_m_h2) == 1
    assert allocs_m_h2[0]["allocated_amount"] == 48.00
    f_conn.close()

    # 3. Test explicit manual target override: user chooses due:2026-H2 for a 48€ payment
    f_conn = get_finances_connection()
    tx_override_id = insert_transaction(
        f_conn,
        source="bank",
        tx_code="SKAT-OVERRIDE-48",
        date="2026-05-04",
        time="00:00:00",
        raw_payer_name="Bernhard Greven",
        raw_payer_email="",
        amount=48.00,
        status="imported",
        is_confirmed=0,
        note="Mitgliedsbeitrag",
    )
    f_conn.close()

    res_override = settle_transaction_and_debts(
        transaction_id=tx_override_id,
        payer_player_id=70,
        beneficiary_player_id=70,
        target_settlement="due:2026-H2",
    )
    assert res_override["success"] is True

    f_conn = get_finances_connection()
    allocs_b_h2 = [a for a in get_allocations_for_period(f_conn, "2026-H2") if a["player_id"] == 70]
    assert len(allocs_b_h2) == 1
    assert allocs_b_h2[0]["allocated_amount"] == 48.00
    f_conn.close()


def test_receivables_crud_and_special_group(clean_finances_env):
    """Test CRUD operations for finance_receivables and group creation."""
    f_conn = get_finances_connection()
    # 1. Create single receivable
    rec_id = create_receivable(
        f_conn,
        kind="special",
        amount=15.00,
        title="Trikotsatz 2026",
        player_id=1,
        due_date="2026-08-01",
        note="Rückennummer 10",
        source="manual",
    )
    assert rec_id > 0

    # 2. Get by ID
    rec = get_receivable_by_id(f_conn, rec_id)
    assert rec is not None
    assert rec["title"] == "Trikotsatz 2026"
    assert rec["amount"] == 15.00
    assert rec["status"] == "open"
    assert rec["paid_amount"] == 0.00
    assert rec["open_amount"] == 15.00

    # 3. Update receivable
    update_receivable(
        f_conn,
        rec_id,
        status="settled",
        manual_settled=1,
        note="Bar bei Übergabe",
    )
    rec_updated = get_receivable_by_id(f_conn, rec_id)
    assert rec_updated["status"] == "settled"
    assert rec_updated["manual_settled"] == 1
    assert rec_updated["note"] == "Bar bei Übergabe"
    assert rec_updated["open_amount"] == 0.00

    # 4. Filter receivables
    recs = get_receivables(f_conn, player_id=1, kind="special")
    assert len(recs) == 1
    assert recs[0]["id"] == rec_id

    # 5. Create special receivables group (Option B: manual list with custom aliases)
    group_id, count = create_special_receivables_group(
        f_conn,
        title="Turniergebühr Sommerfest",
        amount_per_person=10.00,
        due_date="2026-07-20",
        note="Startgeld",
        player_ids=[2, 3],
        guest_aliases=["Lukas", "Timo"],
    )
    assert count == 4
    group_recs = get_receivables(f_conn, special_group_id=group_id)
    assert len(group_recs) == 4
    assert all(r["amount"] == 10.00 for r in group_recs)
    assert all(r["title"] == "Turniergebühr Sommerfest" for r in group_recs)
    assert all(r["special_group_id"] == group_id for r in group_recs)

    # 6. Delete manual receivable
    delete_receivable(f_conn, rec_id)
    assert get_receivable_by_id(f_conn, rec_id) is None
    f_conn.close()


def test_sync_rule_based_receivables(clean_finances_env):
    """Test idempotent synchronization of dues and match guests into finance_receivables."""
    r_conn = get_rb48_connection()
    # Player 1 is a member, Player 2 is a guest
    # Add match where Player 2 participated
    create_match(r_conn, "2026-09-29-1", "2026-09-29", "box", 1, 1, 5, 3)
    add_match_player(r_conn, "2026-09-29-1", 1, "A")
    add_match_player(r_conn, "2026-09-29-1", 2, "B")
    r_conn.commit()
    r_conn.close()

    f_conn = get_finances_connection()
    set_player_membership_status(f_conn, 1, "member")
    set_player_membership_status(f_conn, 2, "guest")
    f_conn.close()

    count1 = sync_rule_based_receivables()
    assert count1["created_dues"] + count1["created_kicks"] >= 2

    f_conn = get_finances_connection()
    recs = get_receivables(f_conn)
    # Check dues receivable for player 1
    p1_due = next((r for r in recs if r["kind"] == "membership_due" and r["player_id"] == 1 and r["period"] == "2026-H2"), None)
    assert p1_due is not None
    assert p1_due["amount"] == 48.00

    # Check guest fee receivable for player 2
    p2_guest = next((r for r in recs if r["kind"] == "match_guest" and r["player_id"] == 2 and r["match_date"] == "2026-09-29"), None)
    assert p2_guest is not None
    assert p2_guest["amount"] == 3.50
    f_conn.close()

    # Second sync is idempotent
    count2 = sync_rule_based_receivables()
    assert count2["created_dues"] + count2["created_kicks"] == 0
    f_conn = get_finances_connection()
    recs2 = get_receivables(f_conn)
    assert len(recs2) == len(recs)
    f_conn.close()


def test_allocate_transaction_receivables_partial_and_settled(clean_finances_env):
    """Test allocating a transaction against a receivable with partial payment and mark_settled override."""
    f_conn = get_finances_connection()
    rec_id = create_receivable(
        f_conn,
        kind="membership_due",
        amount=48.00,
        title="Mitgliedsbeitrag 2026-H1",
        player_id=1,
        period="2026-H1",
    )
    tx_id = insert_transaction(
        f_conn,
        source="bank",
        tx_code="TX-PARTIAL-SETTLE",
        date="2026-05-10",
        time="12:00:00",
        raw_payer_name="Test Member",
        raw_payer_email="test@example.com",
        amount=30.00,
        status="imported",
        is_confirmed=0,
    )
    f_conn.close()

    # Allocate 30 € out of 48 €, but user marks it settled (reduced rate exemption)
    res = allocate_transaction_receivables(
        transaction_id=tx_id,
        payer_player_id=1,
        allocations=[{
            "receivable_id": rec_id,
            "amount": 30.00,
            "mark_settled": True,
        }],
        remember=True,
    )
    assert res["success"] is True

    f_conn = get_finances_connection()
    tx = get_transaction_by_id(f_conn, tx_id)
    assert tx["status"] in ("assigned", "settled")
    assert tx["is_confirmed"] == 1
    assert tx["matched_player_id"] == 1

    rec = get_receivable_by_id(f_conn, rec_id)
    assert rec["status"] == "settled"
    assert rec["manual_settled"] == 1
    assert rec["paid_amount"] == 30.00
    assert rec["open_amount"] == 0.00

    allocs = get_allocations_for_receivable(f_conn, rec_id)
    assert len(allocs) == 1
    assert allocs[0]["allocated_amount"] == 30.00
    assert allocs[0]["transaction_id"] == tx_id
    f_conn.close()


def test_allocate_transaction_receivables_multi_and_surplus(clean_finances_env):
    """Test allocating transaction over multiple receivables with leftover surplus credited."""
    f_conn = get_finances_connection()
    rec1_id = create_receivable(
        f_conn,
        kind="membership_due",
        amount=48.00,
        title="Mitgliedsbeitrag 2026-H1",
        player_id=2,
        period="2026-H1",
    )
    rec2_id = create_receivable(
        f_conn,
        kind="membership_due",
        amount=48.00,
        title="Mitgliedsbeitrag 2026-H2",
        player_id=2,
        period="2026-H2",
    )
    # Payment of 100.00 € (48 + 48 + 4 leftover)
    tx_id = insert_transaction(
        f_conn,
        source="bank",
        tx_code="TX-MULTI-100",
        date="2026-05-15",
        time="12:00:00",
        raw_payer_name="Player Two",
        raw_payer_email="player2@example.com",
        amount=100.00,
        status="imported",
        is_confirmed=0,
    )
    f_conn.close()

    res = allocate_transaction_receivables(
        transaction_id=tx_id,
        payer_player_id=2,
        allocations=[
            {"receivable_id": rec1_id, "amount": 48.00, "mark_settled": False},
            {"receivable_id": rec2_id, "amount": 48.00, "mark_settled": False},
        ],
    )
    assert res["success"] is True

    f_conn = get_finances_connection()
    r1 = get_receivable_by_id(f_conn, rec1_id)
    r2 = get_receivable_by_id(f_conn, rec2_id)
    assert r1["status"] == "settled"
    assert r2["status"] == "settled"

    allocs = f_conn.execute("SELECT * FROM payment_allocations WHERE transaction_id = ?", (tx_id,)).fetchall()
    # 2 linked to receivables + 1 unlinked credit surplus (4.00 €)
    assert len(allocs) == 3
    surplus_alloc = [a for a in allocs if a["receivable_id"] is None]
    assert len(surplus_alloc) == 1
    assert surplus_alloc[0]["allocated_amount"] == 4.00
    assert surplus_alloc[0]["fee_type"] == "manual_adjustment"
    f_conn.close()


def test_manual_due_receivables_creation(clean_finances_env):
    """Test creating historical / manual dues for a period (e.g. 2026-H1)."""
    f_conn = get_finances_connection()
    set_player_membership_status(f_conn, 1, "member")
    set_player_membership_status(f_conn, 2, "member")
    set_player_membership_status(f_conn, 3, "guest")
    f_conn.close()

    count = create_manual_due_receivables("2026-H1")
    assert count == 2  # exactly the 2 members

    f_conn = get_finances_connection()
    recs = get_receivables(f_conn, period="2026-H1", kind="membership_due")
    assert len(recs) == 2
    assert all(r["amount"] == 48.00 for r in recs)

    # Calling again does not duplicate
    count2 = create_manual_due_receivables("2026-H1")
    assert count2 == 0
    f_conn.close()


def test_finance_routes_receivables_and_modals(clean_finances_env):
    """Test HTTP endpoints for receivables management, creation, marking, and deletion."""
    from web.app import app
    client = _login_webmaster(app)

    # 1. GET receivables tab
    resp = client.get("/admin/finances?tab=receivables")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Soll" in html and "Offene Posten" in html

    # 2. POST create special receivable
    resp_spec = client.post("/admin/finances/receivables/special/create", data={
        "title": "Vereinsmeisterschaft Essen",
        "amount": "12.50",
        "due_date": "2026-09-01",
        "note": "BBQ & Drinks",
        "mode": "manual",
        "player_ids": ["1", "2"],
        "custom_aliases": "Lukas",
    }, follow_redirects=True)
    assert resp_spec.status_code == 200
    html_spec = resp_spec.get_data(as_text=True)
    assert "Vereinsmeisterschaft Essen" in html_spec

    f_conn = get_finances_connection()
    spec_recs = get_receivables(f_conn, kind="special")
    assert len(spec_recs) == 3
    test_rec_id = spec_recs[0]["id"]
    f_conn.close()

    # 3. POST mark receivable settled
    resp_mark = client.post(f"/admin/finances/receivables/{test_rec_id}/mark", data={
        "action": "settled",
    }, follow_redirects=True)
    assert resp_mark.status_code == 200

    f_conn = get_finances_connection()
    r_marked = get_receivable_by_id(f_conn, test_rec_id)
    assert r_marked["status"] == "settled"
    assert r_marked["manual_settled"] == 1
    f_conn.close()

    # 4. POST mark receivable open again
    resp_open = client.post(f"/admin/finances/receivables/{test_rec_id}/mark", data={
        "action": "open",
    }, follow_redirects=True)
    assert resp_open.status_code == 200

    f_conn = get_finances_connection()
    r_open = get_receivable_by_id(f_conn, test_rec_id)
    assert r_open["status"] == "open"
    assert r_open["manual_settled"] == 0
    f_conn.close()

    # 5. POST create manual dues
    f_conn = get_finances_connection()
    set_player_membership_status(f_conn, 1, "member")
    f_conn.close()

    resp_due = client.post("/admin/finances/receivables/manual-due/create", data={
        "period": "2026-H1",
        "scope": "all_members",
    }, follow_redirects=True)
    assert resp_due.status_code == 200

    # 6. POST allocate receivables
    f_conn = get_finances_connection()
    tx_id = insert_transaction(
        f_conn,
        source="bank",
        tx_code="TX-ROUTE-ALLOC",
        date="2026-06-01",
        time="12:00:00",
        raw_payer_name="Lukas Test",
        raw_payer_email="lukas@example.com",
        amount=12.50,
        status="imported",
        is_confirmed=0,
    )
    f_conn.close()

    import json
    resp_alloc = client.post("/admin/finances/allocate-receivables", data={
        "tx_id": str(tx_id),
        "payer_player_id": "1",
        "remember": "1",
        "allocations_json": json.dumps([{
            "receivable_id": test_rec_id,
            "amount": 12.50,
            "mark_settled": True,
        }]),
    }, follow_redirects=True)
    assert resp_alloc.status_code == 200

    f_conn = get_finances_connection()
    r_after = get_receivable_by_id(f_conn, test_rec_id)
    assert r_after["status"] == "settled"
    f_conn.close()

    # 7. POST delete receivable (on unallocated special receivable)
    other_rec_id = spec_recs[1]["id"]
    resp_del = client.post(f"/admin/finances/receivables/{other_rec_id}/delete", follow_redirects=True)
    assert resp_del.status_code == 200
    f_conn = get_finances_connection()
    assert get_receivable_by_id(f_conn, other_rec_id) is None
    f_conn.close()


def test_finance_ai_service(clean_finances_env, monkeypatch):
    """Test AI suggestion service graceful fallback when no key is present or on API calls."""
    monkeypatch.setenv("GEMINI_API_KEY", "")
    tx = {
        "id": 999,
        "amount": 48.00,
        "raw_payer_name": "Bernhard Greven",
        "purpose": "Mitgliedsbeitrag 2026-H1",
        "subject": "",
        "date": "2026-05-04",
    }
    recs = [
        {"id": 1, "kind": "membership_due", "title": "Mitgliedsbeitrag 2026-H1", "player_name": "Bernhard", "amount": 48.0, "open_amount": 48.0},
    ]
    players = [{"id": 70, "name": "Bernhard"}]

    # When no key or offline, it safely returns None without raising exceptions
    res = suggest_transaction_allocation_ai(tx, recs, players)
    assert res is None


def test_legacy_schema_migration_without_receivable_id(tmp_path):
    """Test that existing databases lacking receivable_id migrate seamlessly without OperationalError."""
    import sqlite3
    db_file = tmp_path / "legacy_finances.db"
    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row

    # Create ancient payment_allocations table without receivable_id or proxy columns
    conn.execute("""
        CREATE TABLE payment_allocations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            transaction_id INTEGER,
            fee_type TEXT NOT NULL,
            event_id INTEGER,
            match_date TEXT,
            player_id INTEGER,
            attendee_id INTEGER,
            period TEXT,
            allocated_amount REAL NOT NULL,
            payment_method TEXT NOT NULL,
            note TEXT,
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()

    # Now run create_finance_tables on this legacy database
    create_finance_tables(conn)

    # Verify column exists and index was created
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(payment_allocations)").fetchall()]
    assert "receivable_id" in cols
    assert "paid_by_player_id" in cols
    assert "paid_by_user_id" in cols
    assert "guest_alias" in cols

    idx_rows = conn.execute("PRAGMA index_list(payment_allocations)").fetchall()
    idx_names = [r["name"] for r in idx_rows]
    assert "idx_allocations_receivable" in idx_names

    conn.close()

