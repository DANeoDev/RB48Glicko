import io
import os
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
    get_available_finance_periods,
    get_period_display_label,
    get_finance_summary_metrics,
    resolve_player_membership_status,
    GUEST_FEE_PER_KICK,
    MEMBERSHIP_DUE_PER_HALFYEAR,
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
from scripts.accounts.database import get_accounts_connection, create_account_tables, approve_user
from scripts.accounts.auth import register_user, pass_psychology_test
from web.app import create_app


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
    assert "Offene Kleckerbeträge" in after_html
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




