"""Build the synthetic demo database and run the real Glicko calculation on it."""

from __future__ import annotations

import csv
import os
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEMO_DIR = ROOT / "data" / "demo"
EVAL_DIR = ROOT / "data" / "simulation_eval"
PLAYERS_FILE = DEMO_DIR / "demo_players.csv"
MATCHES_FILE = DEMO_DIR / "demo_matches.csv"
DATABASE_FILE = DEMO_DIR / "demo.db"
CHECKPOINT_FILE = EVAL_DIR / "checkpoint_ratings.csv"

# Dense sampling where the system changes fastest, then progressively wider
# intervals as the learning curve flattens.
# 25-150: every 2 games
# 150-200: every 4 games
# 250-500: every 10 games
# 500-1000: every 50 games
# 1000-1500: every 125 games
CHECKPOINTS = tuple(
    list(range(25, 151, 2))
    + list(range(154, 201, 4))
    + [250]
    + list(range(260, 501, 10))
    + list(range(550, 1001, 50))
    + list(range(1125, 1501, 125))
)

os.environ["RB48_DATABASE_FILE"] = str(DATABASE_FILE)

from scripts.database.database import (  # noqa: E402
    create_players_table, create_aliases_table, create_positions_table,
    create_ignored_aliases_table, create_matches_table,
    create_match_players_table, create_calibrations_table,
    create_match_ratings_table, create_ratings_table, get_connection,
)
from scripts.database.db_ratings import get_calibrations  # noqa: E402
from scripts.glicko.glicko2_calculator import (  # noqa: E402
    calculate_glicko, clear_ratings, prepare_glicko_table, write_glicko,
)
from scripts.database.db_matches import get_matches  # noqa: E402


def generate_matches() -> None:
    subprocess.run(
        [sys.executable, "-m", "scripts.simulation.generate_demo"],
        check=True, cwd=ROOT,
    )


def create_schema(connection) -> None:
    create_players_table(connection)
    create_aliases_table(connection)
    create_positions_table(connection)
    create_ignored_aliases_table(connection)
    create_matches_table(connection)
    create_match_players_table(connection)
    create_calibrations_table(connection)
    create_match_ratings_table(connection)
    create_ratings_table(connection)


def import_demo_data(connection) -> None:
    with PLAYERS_FILE.open("r", encoding="utf-8", newline="") as file:
        players = list(csv.DictReader(file))
    with MATCHES_FILE.open("r", encoding="utf-8", newline="") as file:
        matches = list(csv.DictReader(file))

    player_rows = []
    alias_rows = []
    match_rows = []
    match_player_rows = []

    for player in players:
        player_id = int(player["player_id"])
        player_rows.append((player_id,))
        alias_rows.append((player["name"], player_id))

    start_date = date(2025, 1, 1)
    for row in matches:
        match_number = int(row["match_id"])
        match_id = f"{(start_date + timedelta(days=match_number - 1)).isoformat()}-1"
        match_date = start_date + timedelta(days=match_number - 1)
        team_a = [int(x) for x in row["players_a"].split(",")]
        team_b = [int(x) for x in row["players_b"].split(",")]
        match_rows.append((
            match_id, match_date, row["pitch"], len(team_a), len(team_b),
            int(row["goals_a"]), int(row["goals_b"]),
        ))
        match_player_rows.extend((match_id, pid, "a") for pid in team_a)
        match_player_rows.extend((match_id, pid, "b") for pid in team_b)

    with connection:
        connection.executemany("INSERT INTO players (player_id) VALUES (?)", player_rows)
        connection.executemany("INSERT INTO aliases (alias, player_id) VALUES (?, ?)", alias_rows)
        connection.executemany(
            """INSERT INTO matches
            (match_id, date, pitch, players_a, players_b, goals_a, goals_b)
            VALUES (?, ?, ?, ?, ?, ?, ?)""", match_rows)
        connection.executemany(
            "INSERT INTO match_players (match_id, player_id, team) VALUES (?, ?, ?)",
            match_player_rows,
        )

    print(
        f"Imported {len(players)} players, {len(matches)} matches and "
        f"{len(match_player_rows)} match-player records."
    )


def export_checkpoint_ratings(connection, matches) -> None:
    """Write the Glicko state after each configured number of games."""
    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    ordered_matches = list(matches.values())
    checkpoint_rows = []

    for checkpoint in CHECKPOINTS:
        if checkpoint > len(ordered_matches):
            continue

        # The first match after N completed games contains the desired
        # post-N-games rating state. At the final checkpoint use ratings.
        if checkpoint < len(ordered_matches):
            next_match_id = ordered_matches[checkpoint]["match_id"]
            rows = connection.execute(
                """SELECT player_id, rating_type, rating, rd, sigma
                   FROM match_ratings WHERE match_id = ?
                   ORDER BY player_id, rating_type""",
                (next_match_id,),
            ).fetchall()
        else:
            rows = connection.execute(
                """SELECT player_id, rating_type, rating, rd, sigma
                   FROM ratings ORDER BY player_id, rating_type"""
            ).fetchall()

        for row in rows:
            checkpoint_rows.append((
                checkpoint, row["player_id"], row["rating_type"],
                row["rating"], row["rd"], row["sigma"],
            ))

    with CHECKPOINT_FILE.open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(("games", "player_id", "rating_type", "rating", "rd", "sigma"))
        writer.writerows(checkpoint_rows)

    print(f"Wrote {len(checkpoint_rows)} checkpoint rating records to {CHECKPOINT_FILE}")


def run_glicko(connection) -> None:
    matches = get_matches(connection)
    calibrations = get_calibrations(connection)
    clear_ratings(connection)
    prepared = prepare_glicko_table(connection, matches, calibrations)
    final_ratings = calculate_glicko(connection, matches, prepared)
    write_glicko(connection, final_ratings)
    export_checkpoint_ratings(connection, matches)
    print(f"Processed {len(matches)} synthetic matches.")
    print(f"Calculated ratings for {len(final_ratings)} players.")


def main() -> None:
    generate_matches()
    if DATABASE_FILE.exists():
        DATABASE_FILE.unlink()
    connection = get_connection()
    try:
        create_schema(connection)
        import_demo_data(connection)
        run_glicko(connection)
    finally:
        connection.close()
    print(f"Demo database: {DATABASE_FILE}")


if __name__ == "__main__": main()
