import json
import os
from pathlib import Path
import sqlite3
from datetime import datetime, timezone

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def get_finances_db_file():
    override = os.environ.get("RB48_FINANCES_DATABASE_FILE")
    return Path(override) if override else PROJECT_ROOT / "data" / "finances.db"


_INITIALIZED_FINANCE_DBS = set()


def get_finances_connection():
    """Return a connection to the finances database with foreign keys enabled."""
    db_file = get_finances_db_file().resolve()
    db_file.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_file)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    if db_file not in _INITIALIZED_FINANCE_DBS:
        create_finance_tables(connection)
        _INITIALIZED_FINANCE_DBS.add(db_file)
    return connection


def create_finance_tables(connection):
    """Create all financial tracking tables."""
    connection.execute("""
        CREATE TABLE IF NOT EXISTS finance_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            tx_code TEXT,
            date TEXT NOT NULL,
            time TEXT,
            raw_payer_name TEXT,
            raw_payer_email TEXT,
            amount REAL NOT NULL,
            currency TEXT NOT NULL DEFAULT 'EUR',
            description TEXT,
            status TEXT NOT NULL DEFAULT 'imported'
                CHECK (status IN ('imported', 'assigned', 'ignored', 'expense')),
            matched_player_id INTEGER,
            matched_user_id INTEGER,
            is_confirmed INTEGER NOT NULL DEFAULT 0,
            raw_payload TEXT,
            created_at TEXT NOT NULL
        )
    """)

    connection.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_tx_source_code
        ON finance_transactions(source, tx_code)
        WHERE tx_code IS NOT NULL AND tx_code != ''
    """)

    connection.execute("""
        CREATE TABLE IF NOT EXISTS payment_identities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            payer_email TEXT,
            payer_name TEXT,
            player_id INTEGER NOT NULL,
            user_id INTEGER,
            confidence REAL NOT NULL DEFAULT 1.0,
            created_by_user_id INTEGER,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)

    connection.execute("""
        CREATE INDEX IF NOT EXISTS idx_identity_email
        ON payment_identities(payer_email)
    """)
    connection.execute("""
        CREATE INDEX IF NOT EXISTS idx_identity_name
        ON payment_identities(payer_name)
    """)

    connection.execute("""
        CREATE TABLE IF NOT EXISTS payment_allocations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            transaction_id INTEGER,
            fee_type TEXT NOT NULL CHECK (fee_type IN ('match_guest', 'membership_due', 'manual_adjustment')),
            event_id INTEGER,
            match_date TEXT,
            player_id INTEGER,
            attendee_id INTEGER,
            period TEXT,
            allocated_amount REAL NOT NULL,
            payment_method TEXT NOT NULL CHECK (payment_method IN ('paypal', 'bank', 'cash', 'waived')),
            note TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (transaction_id) REFERENCES finance_transactions(id) ON DELETE SET NULL
        )
    """)

    connection.execute("""
        CREATE INDEX IF NOT EXISTS idx_allocations_event
        ON payment_allocations(event_id, attendee_id)
    """)
    connection.execute("""
        CREATE INDEX IF NOT EXISTS idx_allocations_player
        ON payment_allocations(player_id)
    """)
    connection.execute("""
        CREATE INDEX IF NOT EXISTS idx_allocations_match_date
        ON payment_allocations(match_date)
    """)

    connection.execute("""
        CREATE TABLE IF NOT EXISTS player_membership_status (
            player_id INTEGER PRIMARY KEY,
            status TEXT NOT NULL DEFAULT 'guest' CHECK (status IN ('member', 'guest')),
            updated_at TEXT NOT NULL
        )
    """)

    connection.commit()


def insert_transaction(
    connection,
    source: str,
    tx_code: str,
    date: str,
    time: str,
    raw_payer_name: str,
    raw_payer_email: str,
    amount: float,
    currency: str = "EUR",
    description: str = "",
    status: str = "imported",
    matched_player_id: int | None = None,
    matched_user_id: int | None = None,
    is_confirmed: int = 0,
    raw_payload: dict | None = None,
) -> int | None:
    """
    Insert a financial transaction. If source+tx_code already exists, it is ignored and returns None.
    """
    now = datetime.now(timezone.utc).isoformat()
    raw_json = json.dumps(raw_payload, ensure_ascii=False) if raw_payload else None

    try:
        cursor = connection.execute(
            """
            INSERT INTO finance_transactions (
                source, tx_code, date, time, raw_payer_name, raw_payer_email,
                amount, currency, description, status, matched_player_id,
                matched_user_id, is_confirmed, raw_payload, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source,
                tx_code.strip() if tx_code else None,
                date.strip(),
                time.strip() if time else None,
                raw_payer_name.strip() if raw_payer_name else None,
                raw_payer_email.strip().lower() if raw_payer_email else None,
                round(float(amount), 2),
                currency.strip().upper() if currency else "EUR",
                description.strip() if description else "",
                status,
                matched_player_id,
                matched_user_id,
                int(is_confirmed),
                raw_json,
                now,
            ),
        )
        connection.commit()
        return cursor.lastrowid
    except sqlite3.IntegrityError:
        # Duplicate tx_code for this source
        return None


def get_transactions(
    connection,
    source: str | None = None,
    status: str | None = None,
    player_id: int | None = None,
    limit: int = 200,
    offset: int = 0,
) -> list[dict]:
    """Fetch transactions with optional filtering."""
    query = "SELECT * FROM finance_transactions WHERE 1=1"
    params: list = []

    if source:
        query += " AND source = ?"
        params.append(source)
    if status:
        query += " AND status = ?"
        params.append(status)
    if player_id is not None:
        query += " AND matched_player_id = ?"
        params.append(player_id)

    query += " ORDER BY date DESC, time DESC, id DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    cursor = connection.execute(query, params)
    return [dict(row) for row in cursor.fetchall()]


def get_transaction_by_id(connection, tx_id: int) -> dict | None:
    """Fetch a transaction by its ID."""
    row = connection.execute(
        "SELECT * FROM finance_transactions WHERE id = ?", (tx_id,)
    ).fetchone()
    return dict(row) if row else None


def update_transaction_assignment(
    connection,
    tx_id: int,
    player_id: int | None,
    user_id: int | None = None,
    status: str = "assigned",
    is_confirmed: int = 1,
):
    """Update player/user assignment on a transaction."""
    connection.execute(
        """
        UPDATE finance_transactions
        SET matched_player_id = ?, matched_user_id = ?, status = ?, is_confirmed = ?
        WHERE id = ?
        """,
        (player_id, user_id, status, is_confirmed, tx_id),
    )
    connection.commit()


def save_or_update_identity(
    connection,
    player_id: int,
    payer_email: str | None = None,
    payer_name: str | None = None,
    user_id: int | None = None,
    confidence: float = 1.0,
    created_by_user_id: int | None = None,
) -> int:
    """
    Save or update a learned payment identity mapping (Email and/or Name -> Player).
    """
    now = datetime.now(timezone.utc).isoformat()
    clean_email = payer_email.strip().lower() if payer_email else None
    clean_name = payer_name.strip() if payer_name else None

    # Check if exact identity exists
    existing = None
    if clean_email and clean_name:
        existing = connection.execute(
            "SELECT id FROM payment_identities WHERE payer_email = ? AND payer_name = ?",
            (clean_email, clean_name),
        ).fetchone()
    elif clean_email:
        existing = connection.execute(
            "SELECT id FROM payment_identities WHERE payer_email = ?",
            (clean_email,),
        ).fetchone()
    elif clean_name:
        existing = connection.execute(
            "SELECT id FROM payment_identities WHERE payer_name = ?",
            (clean_name,),
        ).fetchone()

    if existing:
        connection.execute(
            """
            UPDATE payment_identities
            SET player_id = ?, user_id = ?, confidence = ?, updated_at = ?
            WHERE id = ?
            """,
            (player_id, user_id, confidence, now, existing["id"]),
        )
        connection.commit()
        return existing["id"]

    cursor = connection.execute(
        """
        INSERT INTO payment_identities (
            payer_email, payer_name, player_id, user_id, confidence,
            created_by_user_id, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            clean_email,
            clean_name,
            player_id,
            user_id,
            confidence,
            created_by_user_id,
            now,
            now,
        ),
    )
    connection.commit()
    return cursor.lastrowid


def get_identities(connection) -> list[dict]:
    """Return all known payment identities."""
    cursor = connection.execute(
        "SELECT * FROM payment_identities ORDER BY updated_at DESC, id DESC"
    )
    return [dict(row) for row in cursor.fetchall()]


def delete_identity(connection, identity_id: int):
    """Delete a learned payment identity."""
    connection.execute("DELETE FROM payment_identities WHERE id = ?", (identity_id,))
    connection.commit()


def add_payment_allocation(
    connection,
    fee_type: str,
    allocated_amount: float,
    payment_method: str,
    transaction_id: int | None = None,
    event_id: int | None = None,
    match_date: str | None = None,
    player_id: int | None = None,
    attendee_id: int | None = None,
    period: str | None = None,
    note: str | None = None,
) -> int:
    """Record a payment allocation linking transaction/cash to a debt/event."""
    now = datetime.now(timezone.utc).isoformat()
    cursor = connection.execute(
        """
        INSERT INTO payment_allocations (
            transaction_id, fee_type, event_id, match_date, player_id,
            attendee_id, period, allocated_amount, payment_method, note, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            transaction_id,
            fee_type,
            event_id,
            match_date,
            player_id,
            attendee_id,
            period,
            round(float(allocated_amount), 2),
            payment_method,
            note.strip() if note else None,
            now,
        ),
    )
    connection.commit()
    return cursor.lastrowid


def get_allocations_for_event(connection, event_id: int) -> list[dict]:
    """Retrieve all payment allocations for an event/matchday."""
    cursor = connection.execute(
        "SELECT * FROM payment_allocations WHERE event_id = ? ORDER BY id ASC",
        (event_id,),
    )
    return [dict(row) for row in cursor.fetchall()]


def get_allocations_for_match_date(connection, match_date: str) -> list[dict]:
    """Retrieve all payment allocations for a match date (YYYY-MM-DD)."""
    cursor = connection.execute(
        "SELECT * FROM payment_allocations WHERE match_date = ? ORDER BY id ASC",
        (match_date,),
    )
    return [dict(row) for row in cursor.fetchall()]


def get_allocations_for_player(connection, player_id: int) -> list[dict]:
    """Retrieve all payment allocations for a player."""
    cursor = connection.execute(
        "SELECT * FROM payment_allocations WHERE player_id = ? ORDER BY created_at DESC",
        (player_id,),
    )
    return [dict(row) for row in cursor.fetchall()]


def get_allocations_for_period(connection, period: str) -> list[dict]:
    """Retrieve all payment allocations for a membership due period (e.g. '2026-H2')."""
    cursor = connection.execute(
        "SELECT * FROM payment_allocations WHERE period = ? AND fee_type = 'membership_due' ORDER BY id ASC",
        (period,),
    )
    return [dict(row) for row in cursor.fetchall()]


def delete_allocation(connection, allocation_id: int):
    """Delete a payment allocation."""
    connection.execute("DELETE FROM payment_allocations WHERE id = ?", (allocation_id,))
    connection.commit()


def get_all_player_membership_statuses(connection) -> dict[int, str]:
    """Return dictionary mapping player_id -> status ('member' | 'guest')."""
    cursor = connection.execute("SELECT player_id, status FROM player_membership_status")
    return {row["player_id"]: row["status"] for row in cursor.fetchall()}


def get_player_membership_status(connection, player_id: int, default: str = "guest") -> str:
    """Return membership status for a single player."""
    row = connection.execute(
        "SELECT status FROM player_membership_status WHERE player_id = ?",
        (player_id,),
    ).fetchone()
    return row["status"] if row else default


def set_player_membership_status(connection, player_id: int, status: str):
    """Set or update player membership status ('member' or 'guest')."""
    if status not in ("member", "guest"):
        status = "guest"
    now = datetime.now(timezone.utc).isoformat()
    connection.execute(
        """
        INSERT INTO player_membership_status (player_id, status, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(player_id) DO UPDATE SET status = excluded.status, updated_at = excluded.updated_at
        """,
        (player_id, status, now),
    )
    connection.commit()
