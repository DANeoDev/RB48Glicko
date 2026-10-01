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
    get_allocations_for_event,
)
from scripts.finances.paypal_parser import (
    parse_german_amount,
    parse_date_to_iso,
    parse_paypal_csv,
)
from scripts.finances.matcher import find_player_match, normalize_text
from scripts.finances.reconciliation import (
    get_event_guest_status,
    manual_mark_attendee_payment,
    auto_allocate_transaction_to_debts,
    GUEST_FEE_PER_KICK,
)
from scripts.database.database import (
    get_connection as get_rb48_connection,
    create_players_table,
    create_aliases_table,
    create_positions_table,
)
from scripts.accounts.database import get_accounts_connection, create_account_tables, approve_user
from scripts.planner.database import get_planner_connection, create_planner_tables, create_event, add_guest_rsvp
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
    create_positions_table(r_conn)
    r_conn.execute("INSERT INTO players (player_id) VALUES (1), (2), (33)")
    r_conn.execute("INSERT INTO aliases (alias, player_id) VALUES ('Stefan', 1), ('Nik', 2), ('Kha', 33)")
    r_conn.commit()
    r_conn.close()

    a_conn = get_accounts_connection()
    create_account_tables(a_conn)
    a_conn.close()

    p_conn = get_planner_connection()
    create_planner_tables(p_conn)
    p_conn.close()

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

    # Duplicate should return None
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

    # Match by alias token "Kha" in "An-Kha Ha-Phuoc"
    match1 = find_player_match(
        raw_payer_name="An-Kha Ha-Phuoc",
        raw_payer_email="ying.yang89@hotmail.de",
        finances_conn=fin_conn,
        rb48_conn=rb_conn,
        accounts_conn=acc_conn,
    )
    assert match1["player_id"] == 33
    assert match1["confidence"] >= 0.80

    # Save learned identity for a completely new email
    save_or_update_identity(
        fin_conn,
        player_id=1,
        payer_email="unknown.custom@provider.de",
        payer_name="Unknown Custom",
        confidence=1.0,
    )

    # Next match should return 100% learned profile match
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


def test_reconciliation_and_manual_marking(clean_finances_env):
    plan_conn = get_planner_connection()
    event_id = create_event(
        plan_conn,
        event_date="2026-08-01",
        pitch="box",
        max_players=10,
        title="Samstags-Kick",
    )
    # Add guest RSVP
    add_guest_rsvp(plan_conn, event_id, guest_name="Gastspieler 1")
    attendees = plan_conn.execute("SELECT id FROM attendees WHERE event_id = ?", (event_id,)).fetchall()
    att_id = attendees[0]["id"]
    plan_conn.close()

    # Check initial status (should be unpaid)
    status_before = get_event_guest_status(event_id)
    assert status_before["total_guests"] == 1
    assert status_before["guest_entries"][0]["payment_status"] == "unpaid"
    assert status_before["outstanding"] == 3.50

    # Mark as cash paid
    manual_mark_attendee_payment(event_id, att_id, payment_method="cash")
    status_after_cash = get_event_guest_status(event_id)
    assert status_after_cash["guest_entries"][0]["payment_status"] == "cash"
    assert status_after_cash["outstanding"] == 0.0

    # Reset to unpaid
    manual_mark_attendee_payment(event_id, att_id, payment_method="unpaid")
    status_reset = get_event_guest_status(event_id)
    assert status_reset["guest_entries"][0]["payment_status"] == "unpaid"


def test_webmaster_finances_web_routes(clean_finances_env):
    app = create_app()
    client = app.test_client()

    # Create webmaster user
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

    # Upload CSV statement
    csv_bytes = """\"Datum\",\"Uhrzeit\",\"Zeitzone\",\"Beschreibung\",\"Währung\",\"Brutto\",\"Entgelt\",\"Netto\",\"Guthaben\",\"Transaktionscode\",\"Absender E-Mail-Adresse\",\"Name\",\"Name der Bank\",\"Bankkonto\",\"Versand- und Bearbeitungsgebühr\",\"Umsatzsteuer\",\"Rechnungsnummer\",\"Zugehöriger Transaktionscode\"
\"10.07.2026\",\"12:09:12\",\"Europe/Berlin\",\"Handyzahlung\",\"EUR\",\"3,50\",\"0,00\",\"3,50\",\"732,06\",\"TEST_TX_999\",\"stefan@rb48.de\",\"Stefan Metzger\",\"\",\"\",\"0,00\",\"0,00\",\"\",\"\"
""".encode("utf-8")
    upload_resp = client.post(
        "/admin/finances/upload",
        data={"csv_file": (io.BytesIO(csv_bytes), "paypal.csv")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert upload_resp.status_code == 200
    assert "CSV-Import erfolgreich" in upload_resp.get_data(as_text=True)

    # Verify transaction in db
    fin_conn = get_finances_connection()
    txs = get_transactions(fin_conn)
    assert len(txs) == 1
    assert txs[0]["tx_code"] == "TEST_TX_999"
    fin_conn.close()
