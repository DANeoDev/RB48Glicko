import sqlite3
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ACCOUNTS_DATABASE_FILE = PROJECT_ROOT / "data" / "accounts.db"


def get_accounts_connection():
    """Return a connection to the separate account database."""
    ACCOUNTS_DATABASE_FILE.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(ACCOUNTS_DATABASE_FILE)
    connection.row_factory = sqlite3.Row
    create_account_tables(connection)
    return connection


def create_account_tables(connection):
    """Create the initial account tables if they do not exist yet."""
    connection.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user'
                CHECK (role IN ('user', 'admin', 'webmaster')),
            email_verified INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
    """)
    connection.execute("""
        CREATE TABLE IF NOT EXISTS email_verification_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            token_hash TEXT NOT NULL UNIQUE,
            expires_at TEXT NOT NULL,
            used_at TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)
    connection.commit()


def get_user_by_id(connection, user_id):
    return connection.execute(
        "SELECT id, username, email, password_hash, role, email_verified, created_at "
        "FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()


def get_user_by_login(connection, login):
    return connection.execute(
        "SELECT id, username, email, password_hash, role, email_verified, created_at "
        "FROM users WHERE lower(username) = lower(?) OR lower(email) = lower(?)",
        (login, login),
    ).fetchone()


def create_user(connection, username, email, password_hash, created_at):
    cursor = connection.execute(
        "INSERT INTO users (username, email, password_hash, created_at) VALUES (?, ?, ?, ?)",
        (username, email, password_hash, created_at),
    )
    connection.commit()
    return cursor.lastrowid


def username_or_email_exists(connection, username, email):
    row = connection.execute(
        "SELECT 1 FROM users WHERE lower(username) = lower(?) OR lower(email) = lower(?) LIMIT 1",
        (username, email),
    ).fetchone()
    return row is not None
