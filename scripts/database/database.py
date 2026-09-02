import os
from pathlib import Path
import sqlite3

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def get_database_file():
    override = os.environ.get("RB48_DATABASE_FILE")
    return Path(override) if override else PROJECT_ROOT / "data" / "rb48.db"


DATABASE_FILE = get_database_file()


def get_connection():
    """Return a connection to the primary RB48 database with foreign keys enabled."""
    connection = sqlite3.connect(get_database_file())
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def create_players_table(connection):
    """Table of unique player identifiers."""
    connection.execute("""
        CREATE TABLE IF NOT EXISTS players (
            player_id INTEGER PRIMARY KEY
        )
    """)
    connection.commit()


def create_aliases_table(connection):
    """Table to store aliases for players."""
    connection.execute("""
        CREATE TABLE IF NOT EXISTS aliases (
            alias TEXT PRIMARY KEY,
            player_id INTEGER NOT NULL,
            FOREIGN KEY (player_id) REFERENCES players(player_id)
        )
    """)
    connection.commit()


def create_positions_table(connection):
    """Table to store player positions with an optional primary flag."""
    connection.execute("""
        CREATE TABLE IF NOT EXISTS positions (
            player_id INTEGER NOT NULL,
            position TEXT NOT NULL,
            is_primary INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (player_id, position),
            FOREIGN KEY (player_id) REFERENCES players(player_id)
        )
    """)
    connection.commit()


def create_ignored_aliases_table(connection):
    """Table to store aliases that should be ignored during match processing."""
    connection.execute("""
        CREATE TABLE IF NOT EXISTS ignored_aliases (
            alias TEXT NOT NULL PRIMARY KEY
        )
    """)
    connection.commit()


def create_matches_table(connection):
    """Table to store match headers and results."""
    connection.execute("""
        CREATE TABLE IF NOT EXISTS matches (
            match_id TEXT NOT NULL PRIMARY KEY,
            date TEXT NOT NULL,
            pitch TEXT NOT NULL,
            players_a INTEGER NOT NULL,
            players_b INTEGER NOT NULL,
            goals_a INTEGER NOT NULL,
            goals_b INTEGER NOT NULL
        )
    """)
    connection.commit()


def create_match_players_table(connection):
    """Table to link players to matches they played in."""
    connection.execute("""
        CREATE TABLE IF NOT EXISTS match_players (
            match_id TEXT NOT NULL,
            player_id INTEGER NOT NULL,
            team TEXT NOT NULL,
            PRIMARY KEY (match_id, player_id),
            FOREIGN KEY (match_id) REFERENCES matches(match_id),
            FOREIGN KEY (player_id) REFERENCES players(player_id)
        )
    """)
    connection.commit()


def create_calibrations_table(connection):
    """Table to store custom initial rating calibrations for new players."""
    connection.execute("""
        CREATE TABLE IF NOT EXISTS calibrations (
            player_id INTEGER NOT NULL PRIMARY KEY,
            rating REAL NOT NULL,
            rd REAL NOT NULL,
            sigma REAL NOT NULL,
            FOREIGN KEY (player_id) REFERENCES players(player_id)
        )
    """)
    connection.commit()


def create_match_ratings_table(connection):
    """Historical rating snapshot for all players at the time of each match."""
    connection.execute("""
        CREATE TABLE IF NOT EXISTS match_ratings (
            match_id TEXT NOT NULL,
            player_id INTEGER NOT NULL,
            rating_type TEXT NOT NULL,
            rating REAL NOT NULL,
            rd REAL NOT NULL,
            sigma REAL NOT NULL,
            PRIMARY KEY (match_id, player_id, rating_type),
            FOREIGN KEY (match_id) REFERENCES matches(match_id),
            FOREIGN KEY (player_id) REFERENCES players(player_id)
        )
    """)
    connection.commit()


def create_ratings_table(connection):
    """Current Glicko ratings for all players across rating types."""
    connection.execute("""
        CREATE TABLE IF NOT EXISTS ratings (
            player_id INTEGER NOT NULL,
            rating_type TEXT NOT NULL,
            rating REAL NOT NULL,
            rd REAL NOT NULL,
            sigma REAL NOT NULL,
            PRIMARY KEY (player_id, rating_type),
            FOREIGN KEY (player_id) REFERENCES players(player_id)
        )
    """)
    connection.commit()


def main():
    DATABASE_FILE.parent.mkdir(parents=True, exist_ok=True)
    connection = get_connection()
    try:
        create_players_table(connection)
        create_aliases_table(connection)
        create_positions_table(connection)
        create_ignored_aliases_table(connection)
        create_matches_table(connection)
        create_match_players_table(connection)
        create_calibrations_table(connection)
        create_match_ratings_table(connection)
        create_ratings_table(connection)
        print(f"Database created at: {DATABASE_FILE}")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
