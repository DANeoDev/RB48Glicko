"""Rebuild the News metadata database from Markdown files on disk.

Run from the project root with:
    python -m scripts.database.maintenance.rebuild_news_database

The Markdown files are the source of truth for which News entries exist.
Existing metadata (author and timestamps) is preserved when a filename remains.
New files are published automatically and receive their timestamp from the
filename when it follows YYYYMMDD-HHMMSS-*.md, otherwise from file mtime.
"""

from datetime import datetime, timezone
from pathlib import Path
import re
import sqlite3

PROJECT_ROOT = Path(__file__).resolve().parents[3]
NEWS_DATABASE_FILE = PROJECT_ROOT / "data" / "news.db"
NEWS_DIRECTORY = PROJECT_ROOT / "data" / "news"
TIMESTAMP_RE = re.compile(r"^(\d{8}-\d{6})-")


def _timestamp_for_file(path: Path) -> str:
    match = TIMESTAMP_RE.match(path.name)
    if match:
        return datetime.strptime(match.group(1), "%Y%m%d-%H%M%S").replace(tzinfo=timezone.utc).isoformat()
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()


def rebuild() -> None:
    NEWS_DIRECTORY.mkdir(parents=True, exist_ok=True)
    NEWS_DATABASE_FILE.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(NEWS_DATABASE_FILE)
    try:
        connection.row_factory = sqlite3.Row
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

        files = sorted(NEWS_DIRECTORY.glob("*.md"))
        existing = {
            row["filename"]: row
            for row in connection.execute("SELECT * FROM news").fetchall()
        }
        filenames = {path.name for path in files}

        removed = 0
        for filename in set(existing) - filenames:
            connection.execute("DELETE FROM news WHERE filename = ?", (filename,))
            removed += 1

        added = 0
        for path in files:
            if path.name in existing:
                continue
            timestamp = _timestamp_for_file(path)
            connection.execute(
                """
                INSERT INTO news (filename, created_at, updated_at, published_at, is_published)
                VALUES (?, ?, ?, ?, 1)
                """,
                (path.name, timestamp, timestamp, timestamp),
            )
            added += 1

        connection.commit()
        print(f"News database rebuilt: {len(files)} Markdown files found, {added} added, {removed} removed.")
    finally:
        connection.close()


if __name__ == "__main__":
    rebuild()
