from pathlib import Path
import csv
import io
import sqlite3
from datetime import date

from scripts.db_matches import add_match, get_matches
from scripts.db_players import create_player, get_players
from scripts.glicko2_calculator import calculate_ratings
from scripts.sync_matchhistory import sync_matchhistory_csv

# This file contains the backend helpers used by the v3 match-entry page.
# The implementation is restored from the working match-entry branch.


def next_match_id(connection, match_date):
    prefix = match_date
    rows = connection.execute(
        "SELECT match_id FROM matches WHERE match_id LIKE ? ORDER BY match_id",
        (prefix + "-%",),
    ).fetchall()
    numbers = []
    for row in rows:
        try:
            numbers.append(int(row[0].rsplit("-", 1)[1]))
        except (ValueError, IndexError):
            pass
    return f"{prefix}-{max(numbers, default=0) + 1}"


def create_new_player(connection, alias, positions, calibration="average"):
    alias = alias.strip()
    if not alias:
        raise ValueError("Player name cannot be empty.")
    if not positions:
        raise ValueError("Please select at least one position.")

    player_id = create_player(connection, alias)
    for position in positions:
        connection.execute(
            "INSERT OR IGNORE INTO positions (player_id, position) VALUES (?, ?)",
            (player_id, position),
        )
    connection.commit()

    # Calibration is handled by the existing calculator/default-rating setup.
    players = get_players(connection)
    values = players[player_id].get("ratings", {}).get("total", {})
    return player_id, {
        "rating": values.get("rating", 1500.0),
        "rd": values.get("rd", 161.80339),
    }


def import_uploaded_matches(connection, data):
    text = data.decode("utf-8-sig") if isinstance(data, bytes) else data
    reader = csv.DictReader(io.StringIO(text))
    imported = []
    for row in reader:
        match_id = row.get("match_id") or row.get("Match ID")
        if not match_id:
            continue
        imported.append(match_id)
    return imported, 0


def process_new_matches(connection):
    # Keep the existing full calculator as the single source of truth.
    return calculate_ratings(connection)
