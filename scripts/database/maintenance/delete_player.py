import sqlite3
from pathlib import Path

from scripts.database.db_players import get_players

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DB_PATH = PROJECT_ROOT / "data" / "rb48.db"


def get_player_matches(connection, player_id):
    rows = connection.execute(
        "SELECT DISTINCT match_id FROM match_players WHERE player_id = ?",
        (player_id,),
    ).fetchall()
    return [row[0] for row in rows]


def delete_player(connection, player_id):
    player = connection.execute(
        "SELECT player_id, alias FROM players WHERE player_id = ?",
        (player_id,),
    ).fetchone()
    if player is None:
        raise ValueError(f"Player ID {player_id} does not exist.")

    match_ids = get_player_matches(connection, player_id)
    if match_ids:
        placeholders = ",".join("?" for _ in match_ids)
        connection.execute(
            f"DELETE FROM match_ratings WHERE match_id IN ({placeholders})",
            match_ids,
        )
        connection.execute(
            f"DELETE FROM match_players WHERE match_id IN ({placeholders})",
            match_ids,
        )
        connection.execute(
            f"DELETE FROM matches WHERE match_id IN ({placeholders})",
            match_ids,
        )

    connection.execute("DELETE FROM match_ratings WHERE player_id = ?", (player_id,))
    connection.execute("DELETE FROM ratings WHERE player_id = ?", (player_id,))
    connection.execute("DELETE FROM calibrations WHERE player_id = ?", (player_id,))
    connection.execute("DELETE FROM aliases WHERE player_id = ?", (player_id,))
    connection.execute("DELETE FROM positions WHERE player_id = ?", (player_id,))
    connection.execute("DELETE FROM players WHERE player_id = ?", (player_id,))

    return player[1], match_ids


def main():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    try:
        players = get_players(connection)
        if not players:
            print("No players found.")
            return

        print("Players:")
        for player in players:
            print(f"{player['player_id']}: {player['alias']}")

        raw_id = input("\nEnter player ID to permanently delete: ").strip()
        try:
            player_id = int(raw_id)
        except ValueError:
            print("Invalid player ID.")
            return

        row = connection.execute(
            "SELECT player_id, alias FROM players WHERE player_id = ?",
            (player_id,),
        ).fetchone()
        if row is None:
            print(f"Player ID {player_id} does not exist.")
            return

        alias = row[1]
        if input(
            f"You selected {alias} (ID {player_id}), correct? [y/N]: "
        ).strip().lower() not in {"y", "yes"}:
            print("Deletion cancelled.")
            return

        print(
            f"\nWARNING: This permanently deletes {alias} and every match "
            "in which they participated, including all player data for those matches."
        )
        if input(
            f"Permanently delete all {alias} related data? [y/N]: "
        ).strip().lower() not in {"y", "yes"}:
            print("Deletion cancelled.")
            return

        try:
            alias, match_ids = delete_player(connection, player_id)
            connection.commit()
        except Exception:
            connection.rollback()
            raise

        print(f"\nDeleted {alias} (ID {player_id}).")
        print(f"Deleted {len(match_ids)} match(es).")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
