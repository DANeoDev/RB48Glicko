import sqlite3
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATABASE_FILE = PROJECT_ROOT / "data" / "rb48.db"


def get_connection():
    connection = sqlite3.connect(DATABASE_FILE)
    connection.row_factory = sqlite3.Row
    return connection


def create_players_table(connection): # table of player_ids, which are unique identifiers for players
    connection.execute("""
        CREATE TABLE IF NOT EXISTS players (
            player_id INTEGER PRIMARY KEY
        )
    """)

    connection.commit()

def create_aliases_table(connection): # table to store aliases for players, with a foreign key reference to the player_id in the players table
    connection.execute("""
        CREATE TABLE IF NOT EXISTS aliases (
            alias TEXT PRIMARY KEY,
            player_id INTEGER NOT NULL,
            FOREIGN KEY (player_id) REFERENCES players(player_id)
        )
    """)

    connection.commit()

def create_positions_table(connection): # table to store player positions, with a flag for primary position
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

def create_ignored_aliases_table(connection): # table to store aliases that should be ignored when processing match data
    connection.execute("""
        CREATE TABLE IF NOT EXISTS ignored_aliases (
            alias TEXT NOT NULL, 
            PRIMARY KEY (alias)
        )
    """)

    connection.commit()

def create_matches_table(connection): # table to store match information
    connection.execute("""
        CREATE TABLE IF NOT EXISTS matches (
            match_id TEXT NOT NULL, 
            date TEXT NOT NULL,
            pitch TEXT NOT NULL, 
            players_a INTEGER NOT NULL,
            players_b INTEGER NOT NULL,
            goals_a INTEGER NOT NULL,
            goals_b INTEGER NOT NULL,
            PRIMARY KEY (match_id)
        )
    """)

    connection.commit()


def create_match_players_table(connection): # table to link players to matches they played in
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

def create_calibrations_table(connection): # Calibration table - used if new players are very far from avarage
    connection.execute("""
        CREATE TABLE IF NOT EXISTS calibrations (
            player_id INTEGER NOT NULL,
            rating REAL NOT NULL,
            rd REAL NOT NULL,
            sigma REAL NOT NULL,

            PRIMARY KEY (player_id),

            FOREIGN KEY (player_id) REFERENCES players(player_id)
        )
    """)

    connection.commit()



def create_match_ratings_table(connection): #ratings of ALL players in the DB at the time of the match, not just those who played
    connection.execute("""
        CREATE TABLE IF NOT EXISTS match_ratings (
            match_id TEXT NOT NULL,
            player_id INTEGER NOT NULL,
            rating REAL NOT NULL,
            rd REAL NOT NULL,
            sigma REAL NOT NULL,

            PRIMARY KEY (match_id, player_id),
            FOREIGN KEY (match_id) REFERENCES matches(match_id),
            FOREIGN KEY (player_id) REFERENCES players(player_id)
        )
    """)

    connection.commit()

def create_ratings_table(connection): # table of current ratings of all players in the DB
    connection.execute("""
        CREATE TABLE IF NOT EXISTS ratings (
            player_id INTEGER NOT NULL,
            rating REAL NOT NULL,
            rd REAL NOT NULL,
            sigma REAL NOT NULL,

            PRIMARY KEY (player_id),

            FOREIGN KEY (player_id) REFERENCES players(player_id)
        )
    """)

    connection.commit()

def main():
    connection = get_connection()

    create_players_table(connection)
    create_aliases_table(connection)
    create_positions_table(connection)
    create_ignored_aliases_table(connection)
    create_matches_table(connection)
    create_match_players_table(connection)
    create_calibrations_table(connection)
    create_match_ratings_table(connection)
    create_ratings_table(connection)
    connection.close()

    print(f"Database created at: {DATABASE_FILE}")


if __name__ == "__main__":
    main()