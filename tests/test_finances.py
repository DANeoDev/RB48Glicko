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

    monkeypatch.setenv("RB48_FINANCES_DATABASE_FILE", str(fin_db))
    monkeypatch.setenv("RB48_DATABASE_FILE", str(rb_db))
    monkeypatch.setenv("RB48_ACCOUNTS_DATABASE_FILE", str(acc_db))
    monkeypatch.setenv("RB48_PLANNER_DATABASE_FILE", str(plan_db))

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
    assert "copyAllOpenDebts" in after_html
    assert "copyDayOpenDebts" in after_html
    assert "Offene Beträge:" in after_html
    assert "buildFooterText" in after_html
    assert "Die Liste kann unvollständig und/oder falsche Einträge beinhalten" in after_html
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



