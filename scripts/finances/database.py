import json
import os
from pathlib import Path
import sqlite3
from datetime import datetime, timezone
from scripts.utils.timezone import get_cologne_timestamp_str

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
            paid_by_player_id INTEGER DEFAULT NULL,
            paid_by_user_id INTEGER DEFAULT NULL,
            guest_alias TEXT DEFAULT NULL,
            receivable_id INTEGER DEFAULT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (transaction_id) REFERENCES finance_transactions(id) ON DELETE SET NULL
        )
    """)

    # Migrations for existing payment_allocations table before creating indices
    for col, col_def in [
        ("paid_by_player_id", "INTEGER DEFAULT NULL"),
        ("paid_by_user_id", "INTEGER DEFAULT NULL"),
        ("guest_alias", "TEXT DEFAULT NULL"),
        ("receivable_id", "INTEGER DEFAULT NULL"),
    ]:
        try:
            connection.execute(f"ALTER TABLE payment_allocations ADD COLUMN {col} {col_def}")
        except Exception:
            pass

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
        CREATE INDEX IF NOT EXISTS idx_allocations_receivable
        ON payment_allocations(receivable_id)
    """)

    connection.execute("""
        CREATE TABLE IF NOT EXISTS player_membership_status (
            player_id INTEGER PRIMARY KEY,
            status TEXT NOT NULL DEFAULT 'guest' CHECK (status IN ('member', 'guest')),
            member_since TEXT DEFAULT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    try:
        connection.execute("ALTER TABLE player_membership_status ADD COLUMN member_since TEXT DEFAULT NULL")
    except Exception:
        pass

    try:
        connection.execute("ALTER TABLE finance_transactions ADD COLUMN note TEXT DEFAULT NULL")
    except Exception:
        pass

    connection.execute("""
        CREATE TABLE IF NOT EXISTS finance_archives (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            archived_at TEXT NOT NULL,
            title TEXT NOT NULL,
            tx_count INTEGER NOT NULL DEFAULT 0,
            total_income REAL NOT NULL DEFAULT 0.0,
            total_expenses REAL NOT NULL DEFAULT 0.0,
            csv_data TEXT NOT NULL,
            notes TEXT
        )
    """)

    connection.execute("""
        CREATE TABLE IF NOT EXISTS finance_receivables (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL CHECK (kind IN ('membership_due', 'match_guest', 'special')),
            player_id INTEGER,
            guest_alias TEXT,
            period TEXT,
            match_date TEXT,
            due_date TEXT,
            amount REAL NOT NULL,
            title TEXT NOT NULL,
            note TEXT,
            special_group_id TEXT,
            status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'partial', 'settled', 'waived')),
            source TEXT NOT NULL DEFAULT 'rule' CHECK (source IN ('rule', 'manual')),
            manual_settled INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)

    connection.execute("""
        CREATE INDEX IF NOT EXISTS idx_receivables_player
        ON finance_receivables(player_id)
    """)
    connection.execute("""
        CREATE INDEX IF NOT EXISTS idx_receivables_guest_alias
        ON finance_receivables(guest_alias)
    """)
    connection.execute("""
        CREATE INDEX IF NOT EXISTS idx_receivables_period
        ON finance_receivables(period)
    """)
    connection.execute("""
        CREATE INDEX IF NOT EXISTS idx_receivables_match_date
        ON finance_receivables(match_date)
    """)
    connection.execute("""
        CREATE INDEX IF NOT EXISTS idx_receivables_status
        ON finance_receivables(status)
    """)
    connection.execute("""
        CREATE INDEX IF NOT EXISTS idx_receivables_special_group
        ON finance_receivables(special_group_id)
    """)

    # Migration: add manual_settled column if missing
    try:
        connection.execute("ALTER TABLE finance_receivables ADD COLUMN manual_settled INTEGER NOT NULL DEFAULT 0")
    except Exception:
        pass

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
    note: str | None = None,
) -> int | None:
    """
    Insert a financial transaction. If source+tx_code already exists, it is ignored and returns None.
    """
    now = get_cologne_timestamp_str()
    raw_json = json.dumps(raw_payload, ensure_ascii=False) if raw_payload else None

    try:
        cursor = connection.execute(
            """
            INSERT INTO finance_transactions (
                source, tx_code, date, time, raw_payer_name, raw_payer_email,
                amount, currency, description, status, matched_player_id,
                matched_user_id, is_confirmed, raw_payload, note, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                note.strip() if note else None,
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
    now = get_cologne_timestamp_str()
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
    paid_by_player_id: int | None = None,
    paid_by_user_id: int | None = None,
    guest_alias: str | None = None,
    receivable_id: int | None = None,
) -> int:
    """Record a payment allocation linking transaction/cash to a debt/event/receivable."""
    now = get_cologne_timestamp_str()
    cursor = connection.execute(
        """
        INSERT INTO payment_allocations (
            transaction_id, fee_type, event_id, match_date, player_id,
            attendee_id, period, allocated_amount, payment_method, note,
            paid_by_player_id, paid_by_user_id, guest_alias, receivable_id, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            paid_by_player_id,
            paid_by_user_id,
            guest_alias.strip() if guest_alias else None,
            receivable_id,
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


def create_receivable(
    connection,
    kind: str,
    amount: float,
    title: str,
    player_id: int | None = None,
    guest_alias: str | None = None,
    period: str | None = None,
    match_date: str | None = None,
    due_date: str | None = None,
    note: str | None = None,
    special_group_id: str | None = None,
    status: str = "open",
    source: str = "rule",
    manual_settled: int = 0,
) -> int:
    """Create a new receivable record in finance_receivables."""
    now = get_cologne_timestamp_str()
    cursor = connection.execute(
        """
        INSERT INTO finance_receivables (
            kind, player_id, guest_alias, period, match_date, due_date,
            amount, title, note, special_group_id, status, source,
            manual_settled, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            kind,
            player_id,
            guest_alias.strip() if guest_alias else None,
            period,
            match_date,
            due_date or match_date,
            round(float(amount), 2),
            title.strip(),
            note.strip() if note else None,
            special_group_id,
            status,
            source,
            1 if manual_settled else 0,
            now,
            now,
        ),
    )
    connection.commit()
    return cursor.lastrowid


def get_receivable_by_id(connection, receivable_id: int) -> dict | None:
    """Fetch a single receivable by ID, enriched with paid_amount and open_amount."""
    row = connection.execute(
        "SELECT * FROM finance_receivables WHERE id = ?", (receivable_id,)
    ).fetchone()
    if not row:
        return None
    r = dict(row)
    alloc_sum_row = connection.execute(
        "SELECT COALESCE(SUM(allocated_amount), 0.0) AS paid FROM payment_allocations WHERE receivable_id = ?",
        (receivable_id,)
    ).fetchone()
    paid_sum = float(alloc_sum_row["paid"]) if alloc_sum_row else 0.0
    r["paid_amount"] = paid_sum
    if r.get("manual_settled") == 1 or r["status"] in ("settled", "waived"):
        r["open_amount"] = 0.0
    else:
        r["open_amount"] = max(0.0, float(r["amount"]) - paid_sum)
    return r


def get_receivables(
    connection,
    player_id: int | None = None,
    guest_alias: str | None = None,
    status: str | None = None,
    kind: str | None = None,
    period: str | None = None,
    match_date: str | None = None,
    search: str | None = None,
    special_group_id: str | None = None,
) -> list[dict]:
    """Fetch receivables with optional filtering, enriched with paid_amount and open_amount."""
    query = "SELECT * FROM finance_receivables WHERE 1=1"
    params = []

    if player_id is not None:
        query += " AND player_id = ?"
        params.append(player_id)
    if guest_alias is not None:
        query += " AND LOWER(guest_alias) = LOWER(?)"
        params.append(guest_alias)
    if status is not None and status != "all":
        query += " AND status = ?"
        params.append(status)
    if kind is not None and kind != "all":
        query += " AND kind = ?"
        params.append(kind)
    if period is not None and period != "all":
        query += " AND period = ?"
        params.append(period)
    if match_date is not None:
        query += " AND match_date = ?"
        params.append(match_date)
    if special_group_id is not None:
        query += " AND special_group_id = ?"
        params.append(special_group_id)
    if search:
        s = f"%{search.strip().lower()}%"
        query += " AND (LOWER(title) LIKE ? OR LOWER(note) LIKE ? OR LOWER(guest_alias) LIKE ?)"
        params.extend([s, s, s])

    query += " ORDER BY CASE WHEN due_date IS NOT NULL THEN due_date ELSE created_at END DESC, id DESC"
    cursor = connection.execute(query, params)
    recs = [dict(row) for row in cursor.fetchall()]
    if not recs:
        return []

    alloc_rows = connection.execute(
        "SELECT receivable_id, COALESCE(SUM(allocated_amount), 0.0) AS paid FROM payment_allocations WHERE receivable_id IS NOT NULL GROUP BY receivable_id"
    ).fetchall()
    alloc_map = {row["receivable_id"]: float(row["paid"]) for row in alloc_rows}
    for r in recs:
        paid_sum = alloc_map.get(r["id"], 0.0)
        r["paid_amount"] = paid_sum
        if r.get("manual_settled") == 1 or r["status"] in ("settled", "waived"):
            r["open_amount"] = 0.0
        else:
            r["open_amount"] = max(0.0, float(r["amount"]) - paid_sum)
    return recs


def update_receivable(
    connection,
    receivable_id: int,
    status: str | None = None,
    amount: float | None = None,
    title: str | None = None,
    note: str | None = None,
    manual_settled: int | None = None,
):
    """Update attributes or status of a receivable."""
    now = get_cologne_timestamp_str()
    updates = ["updated_at = ?"]
    params = [now]

    if status is not None:
        updates.append("status = ?")
        params.append(status)
    if amount is not None:
        updates.append("amount = ?")
        params.append(round(float(amount), 2))
    if title is not None:
        updates.append("title = ?")
        params.append(title.strip())
    if note is not None:
        updates.append("note = ?")
        params.append(note.strip() if note else None)
    if manual_settled is not None:
        updates.append("manual_settled = ?")
        params.append(int(manual_settled))

    params.append(receivable_id)
    connection.execute(
        f"UPDATE finance_receivables SET {', '.join(updates)} WHERE id = ?",
        params,
    )
    connection.commit()


def delete_receivable(connection, receivable_id: int) -> bool:
    """Delete a receivable if no confirmed transaction allocations depend on it."""
    has_allocs = connection.execute(
        "SELECT COUNT(*) as cnt FROM payment_allocations WHERE receivable_id = ?",
        (receivable_id,),
    ).fetchone()["cnt"]
    if has_allocs > 0:
        return False
    connection.execute("DELETE FROM finance_receivables WHERE id = ?", (receivable_id,))
    connection.commit()
    return True


def get_allocations_for_receivable(connection, receivable_id: int) -> list[dict]:
    """Retrieve all payment allocations for a specific receivable."""
    cursor = connection.execute(
        "SELECT * FROM payment_allocations WHERE receivable_id = ? ORDER BY id ASC",
        (receivable_id,),
    )
    return [dict(row) for row in cursor.fetchall()]


def create_special_receivables_group(
    connection,
    title: str,
    amount_per_person: float,
    player_ids: list[int] | None = None,
    guest_aliases: list[str] | None = None,
    due_date: str | None = None,
    note: str | None = None,
) -> tuple[str, int]:
    """
    Batch-create special receivables for a group of players and/or guest aliases.
    Returns (special_group_id, created_count).
    """
    import uuid
    group_id = f"special-{uuid.uuid4().hex[:8]}"
    count = 0

    if player_ids:
        for pid in player_ids:
            create_receivable(
                connection,
                kind="special",
                amount=amount_per_person,
                title=title,
                player_id=pid,
                guest_alias=None,
                due_date=due_date,
                note=note,
                special_group_id=group_id,
                status="open",
                source="manual",
            )
            count += 1

    if guest_aliases:
        for alias in guest_aliases:
            clean_a = alias.strip()
            if not clean_a:
                continue
            create_receivable(
                connection,
                kind="special",
                amount=amount_per_person,
                title=title,
                player_id=None,
                guest_alias=clean_a,
                due_date=due_date,
                note=note,
                special_group_id=group_id,
                status="open",
                source="manual",
            )
            count += 1

    return group_id, count


def get_all_player_membership_statuses(connection) -> dict[int, str]:
    """Return dictionary mapping player_id -> status ('member' | 'guest')."""
    cursor = connection.execute("SELECT player_id, status FROM player_membership_status")
    return {row["player_id"]: row["status"] for row in cursor.fetchall()}


def get_all_player_membership_records(connection) -> dict[int, dict]:
    """Return dictionary mapping player_id -> {'status': str, 'member_since': str|None, 'updated_at': str}."""
    try:
        cursor = connection.execute("SELECT player_id, status, member_since, updated_at FROM player_membership_status")
        return {row["player_id"]: dict(row) for row in cursor.fetchall()}
    except Exception:
        cursor = connection.execute("SELECT player_id, status, updated_at FROM player_membership_status")
        return {row["player_id"]: {"player_id": row["player_id"], "status": row["status"], "member_since": None, "updated_at": row["updated_at"]} for row in cursor.fetchall()}


def get_player_membership_status(connection, player_id: int, default: str = "guest") -> str:
    """Return membership status for a single player."""
    row = connection.execute(
        "SELECT status FROM player_membership_status WHERE player_id = ?",
        (player_id,),
    ).fetchone()
    return row["status"] if row else default


def set_player_membership_status(connection, player_id: int, status: str, member_since: str | None = None):
    """Set or update player membership status ('member' or 'guest'), optionally with member_since date."""
    if status not in ("member", "guest"):
        status = "guest"
    now = get_cologne_timestamp_str()
    if status == "guest":
        member_since = None

    connection.execute(
        """
        INSERT INTO player_membership_status (player_id, status, member_since, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(player_id) DO UPDATE SET
            status = excluded.status,
            member_since = excluded.member_since,
            updated_at = excluded.updated_at
        """,
        (player_id, status, member_since, now),
    )
    connection.commit()


def get_allocations_paid_by_player(connection, paid_by_player_id: int) -> list[dict]:
    """Retrieve all payment allocations where a specific player paid on behalf of others."""
    cursor = connection.execute(
        "SELECT * FROM payment_allocations WHERE paid_by_player_id = ? ORDER BY created_at DESC",
        (paid_by_player_id,),
    )
    return [dict(row) for row in cursor.fetchall()]


def create_finance_archive(
    connection,
    title: str,
    tx_count: int,
    total_income: float,
    total_expenses: float,
    csv_data: str,
    notes: str | None = None,
) -> int:
    """Store an archived snapshot of transactions and allocations."""
    now = get_cologne_timestamp_str()
    cursor = connection.execute(
        """
        INSERT INTO finance_archives (
            archived_at, title, tx_count, total_income, total_expenses, csv_data, notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (now, title, tx_count, round(total_income, 2), round(total_expenses, 2), csv_data, notes),
    )
    connection.commit()
    return cursor.lastrowid


def get_finance_archives(connection) -> list[dict]:
    """Retrieve all saved financial archives ordered newest first."""
    cursor = connection.execute(
        "SELECT id, archived_at, title, tx_count, total_income, total_expenses, notes FROM finance_archives ORDER BY id DESC"
    )
    return [dict(row) for row in cursor.fetchall()]


def get_finance_archive_by_id(connection, archive_id: int) -> dict | None:
    """Retrieve a single archive including its full CSV data."""
    row = connection.execute(
        "SELECT * FROM finance_archives WHERE id = ?",
        (archive_id,),
    ).fetchone()
    return dict(row) if row else None


def delete_finance_archive(connection, archive_id: int) -> bool:
    """Delete a finance archive by ID."""
    cursor = connection.execute(
        "DELETE FROM finance_archives WHERE id = ?",
        (archive_id,),
    )
    connection.commit()
    return cursor.rowcount > 0

