"""Generate and import the synthetic demo world into a clean RB48 database."""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from pathlib import Path
import random

from scripts.database.database import (
    create_aliases_table, create_calibrations_table, create_ignored_aliases_table,
    create_match_players_table, create_match_ratings_table, create_matches_table,
    create_players_table, create_positions_table, create_ratings_table,
)
from scripts.database.db_matches import create_match, add_match_player
from scripts.database.db_players import create_player, add_alias
from scripts.simulation.generate_demo import (
    PLAYERS, MATCH_COUNT, TEAM_SIZE, choose_balanced_teams, generate_score,
    true_probability,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEMO_DATABASE = PROJECT_ROOT / "data" / "demo" / "demo.db"
SEED = 42


def create_database(connection: sqlite3.Connection) -> None:
    create_players_table(connection)
    create_aliases_table(connection)
    create_positions_table(connection)
    create_ignored_aliases_table(connection)
    create_matches_table(connection)
    create_match_players_table(connection)
    create_calibrations_table(connection)
    create_match_ratings_table(connection)
    create_ratings_table(connection)


def populate_players(connection: sqlite3.Connection) -> None:
    for player in PLAYERS:
        create_player(connection, player.player_id)
        add_alias(connection, player.name, player.player_id)
    connection.commit()


def generate_and_import(connection: sqlite3.Connection) -> None:
    rng = random.Random(SEED)
    start = date(2025, 1, 1)
    for match_id in range(1, MATCH_COUNT + 1):
        team_a, team_b, probability = choose_balanced_teams(PLAYERS, rng)
        winner_a = rng.random() < probability
        pitch = "box" if rng.random() < 0.5 else "hf"
        goals_a, goals_b = generate_score(probability, winner_a, pitch, rng)
        match_date = start + timedelta(days=match_id - 1)
        create_match(
            connection, str(match_id), match_date.isoformat(), pitch,
            len(team_a), len(team_b), goals_a, goals_b,
        )
        for player in team_a:
            add_match_player(connection, str(match_id), player.player_id, "a")
        for player in team_b:
            add_match_player(connection, str(match_id), player.player_id, "b")
    connection.commit()


def main() -> None:
    if DEMO_DATABASE.exists():
        DEMO_DATABASE.unlink()
    DEMO_DATABASE.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DEMO_DATABASE)
    connection.row_factory = sqlite3.Row
    try:
        create_database(connection)
        populate_players(connection)
        generate_and_import(connection)
    finally:
        connection.close()
    print(f"Created {DEMO_DATABASE} with {MATCH_COUNT} synthetic matches and {len(PLAYERS)} players.")


if __name__ == "__main__":
    main()
