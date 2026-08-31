import sqlite3
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
NEWS_DATABASE_FILE = PROJECT_ROOT / "data" / "news.db"
NEWS_DIRECTORY = PROJECT_ROOT / "data" / "news"


def get_news_connection():
    """Return a connection to the separate News database."""
    NEWS_DATABASE_FILE.parent.mkdir(parents=True, exist_ok=True)
    NEWS_DIRECTORY.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(NEWS_DATABASE_FILE)
    connection.row_factory = sqlite3.Row
    create_news_table(connection)
    return connection


def create_news_table(connection):
    """Create the News metadata table if it does not exist yet."""
    connection.execute("""
        CREATE TABLE IF NOT EXISTS news (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            published_at TEXT,
            author_id INTEGER,
            is_published INTEGER NOT NULL DEFAULT 0
        )
    """)
    connection.commit()


def get_published_news(connection, limit=None, offset=0):
    """Return published News metadata, newest first, optionally paginated."""
    query = """
        SELECT id, filename, created_at, updated_at, published_at, author_id
        FROM news
        WHERE is_published = 1
        ORDER BY published_at DESC, id DESC
    """
    params = []
    if limit is not None:
        query += " LIMIT ? OFFSET ?"
        params.extend((limit, offset))
    cursor = connection.execute(query, params)
    return cursor.fetchall()


def get_news_item(connection, news_id):
    """Return one News item by id, or None if it does not exist."""
    cursor = connection.execute("""
        SELECT id, filename, created_at, updated_at, published_at, author_id, is_published
        FROM news
        WHERE id = ?
    """, (news_id,))
    return cursor.fetchone()


def add_news_item(connection, filename, created_at, author_id=None):
    """Register a Markdown News file in the News metadata database."""
    cursor = connection.execute("""
        INSERT INTO news (filename, created_at, updated_at, author_id)
        VALUES (?, ?, ?, ?)
    """, (filename, created_at, created_at, author_id))
    connection.commit()
    return cursor.lastrowid


def publish_news_item(connection, news_id, published_at, updated_at=None):
    """Publish a News item and record its publication timestamp."""
    updated_at = updated_at or published_at
    connection.execute("""
        UPDATE news
        SET is_published = 1,
            published_at = ?,
            updated_at = ?
        WHERE id = ?
    """, (published_at, updated_at, news_id))
    connection.commit()


def unpublish_news_item(connection, news_id, updated_at):
    """Remove a News item from public display without deleting its content."""
    connection.execute("""
        UPDATE news
        SET is_published = 0,
            updated_at = ?
        WHERE id = ?
    """, (updated_at, news_id))
    connection.commit()


def delete_news_item(connection, news_id):
    """Remove News metadata; the caller is responsible for deleting the Markdown file."""
    connection.execute("DELETE FROM news WHERE id = ?", (news_id,))
    connection.commit()
