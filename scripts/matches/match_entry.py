import csv
import io
import re
from pathlib import Path

from scripts.database.db_matches import create_match, add_match_player, get_matches, get_match_teams, match_exists
from scripts.database.db_ratings import get_ratings, get_processed_match_ids, get_calibrations, set_calibration
from scripts.database.db_players import get_alias_lookup, get_ignored_aliases, get_next_player_id, create_player, add_alias, add_position
from scripts.glicko.glicko2 import Glicko2, DEFAULT_RATING, DEFAULT_RD, DEFAULT_SIGMA
from scripts.glicko.glicko2_calculator import (
    glicko_table_to_ratings,
    ratings_to_glicko_table,
    update_match,
    write_match_ratings,
    write_glicko,
    initialize_player_ratings,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MATCHES_DIR = PROJECT_ROOT / "matches"
CALIBRATION_LEVELS = {
    "extremely_weak": (0.15, "Extremely weak"),
    "weak": (0.35, "Weak"),
    "average": (None, "Average (standard)"),
    "strong": (0.65, "Strong"),
    "extremely_strong": (0.85, "Extremely strong"),
}


def _percentile(values, percentile):
    if not values:
        return DEFAULT_RATING
    values = sorted(values)
    if len(values) == 1:
        return values[0]
    position = (len(values) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    fraction = position - lower
    return values[lower] + (values[upper] - values[lower]) * fraction


def calibration_values(connection, level):
    if level not in CALIBRATION_LEVELS:
        raise ValueError("Invalid calibration level.")
    percentile, _ = CALIBRATION_LEVELS[level]
    if percentile is None:
        return {"rating": DEFAULT_RATING, "rd": DEFAULT_RD, "sigma": DEFAULT_SIGMA}
    ratings = get_ratings(connection)
    total_ratings = [data["total"]["rating"] for data in ratings.values() if "total" in data]
    return {"rating": _percentile(total_ratings, percentile), "rd": DEFAULT_RD, "sigma": DEFAULT_SIGMA}


def create_new_player(connection, alias, positions=None, calibration_level="average"):
    alias = alias.strip()
    if not alias:
        raise ValueError("Player name cannot be empty.")
    if alias in get_alias_lookup(connection):
        raise ValueError(f"The alias '{alias}' already exists.")
    player_id = get_next_player_id(connection)
    create_player(connection, player_id)
    add_alias(connection, alias, player_id)
    for position in positions or []:
        if position.upper() in {"GK", "DEF", "MID", "ATT"}:
            add_position(connection, player_id, position.upper())
    values = calibration_values(connection, calibration_level)
    set_calibration(connection, player_id, values["rating"], values["rd"], values["sigma"])
    connection.commit()
    return player_id, values


def next_match_id(connection, match_date):
    rows = connection.execute("SELECT match_id FROM matches WHERE date = ?", (match_date,)).fetchall()
    highest = 0
    for row in rows:
        match = re.fullmatch(rf"{re.escape(match_date)}-(\d+)", row["match_id"])
        if match:
            highest = max(highest, int(match.group(1)))
    return f"{match_date}-{highest + 1}"


def _write_match_file(connection, match_id, match_date, pitch, team_a_ids, team_b_ids, goals_a, goals_b):
    """Write the match to the matches folder. This folder is the match source of truth."""
    aliases = {row["player_id"]: row["alias"] for row in connection.execute("SELECT alias, player_id FROM aliases")}
    MATCHES_DIR.mkdir(parents=True, exist_ok=True)
    csv_file = MATCHES_DIR / f"{match_date}.csv"
    existing_ids = set()
    if csv_file.exists():
        with csv_file.open("r", encoding="utf-8-sig", newline="") as file:
            existing_ids = {row[0].strip() for row in csv.reader(file) if row and row[0].strip()}
    if match_id in existing_ids:
        return
    write_header = not csv_file.exists() or csv_file.stat().st_size == 0
    with csv_file.open("a", encoding="utf-8", newline="") as file:
        writer = csv.writer(file)
        if write_header:
            writer.writerow(["match_id", "pitch", "team A", "team B", "goals A", "goals B"])
        writer.writerow([
            match_id,
            pitch,
            ",".join(aliases[p] for p in team_a_ids),
            ",".join(aliases[p] for p in team_b_ids),
            goals_a,
            goals_b,
        ])


def add_match(connection, match_date, pitch, team_a_ids, team_b_ids, goals_a, goals_b, players_a_count=None, players_b_count=None, match_id=None):
    """Persist a match through the canonical pipeline: matches file first, then SQLite."""
    match_id = match_id or next_match_id(connection, match_date)
    if match_exists(connection, match_id):
        raise ValueError(f"Match {match_id} already exists.")
    players_a_count = len(team_a_ids) if players_a_count is None else players_a_count
    players_b_count = len(team_b_ids) if players_b_count is None else players_b_count

    _write_match_file(connection, match_id, match_date, pitch, team_a_ids, team_b_ids, goals_a, goals_b)

    connection.execute("BEGIN")
    try:
        create_match(connection, match_id, match_date, pitch, players_a_count, players_b_count, goals_a, goals_b)
        for player_id in team_a_ids:
            add_match_player(connection, match_id, player_id, "a")
        for player_id in team_b_ids:
            add_match_player(connection, match_id, player_id, "b")
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    return match_id


def process_new_matches(connection):
    calibrations = get_calibrations(connection)
    matches = get_matches(connection)
    processed_ids = get_processed_match_ids(connection)
    new_matches = sorted([m for m in matches.values() if m["match_id"] not in processed_ids], key=lambda m: m["match_id"])
    if not new_matches:
        return 0
    ratings = get_ratings(connection)
    if not ratings:
        raise RuntimeError("No current ratings found. Run the full Glicko calculation first.")
    rating_objects = glicko_table_to_ratings(ratings)
    engine = Glicko2()
    for match in new_matches:
        team_a, team_b = get_match_teams(connection, match["match_id"])
        for player_id in team_a + team_b:
            initialize_player_ratings(player_id, rating_objects, calibrations)
        write_match_ratings(connection, match["match_id"], ratings_to_glicko_table(rating_objects))
        update_match(connection, match, rating_objects, engine)
    write_glicko(connection, ratings_to_glicko_table(rating_objects))
    return len(new_matches)


def parse_uploaded_matches(file_bytes):
    reader = csv.reader(io.StringIO(file_bytes.decode("utf-8-sig")))
    rows = []
    for line_number, row in enumerate(reader, start=1):
        if not row or all(not cell.strip() for cell in row):
            continue
        if len(row) < 6:
            raise ValueError(f"Line {line_number}: expected 6 columns (match_id, pitch, team A, team B, goals A, goals B).")
        rows.append(row[:6])
    return rows


def resolve_uploaded_match(row, alias_lookup, ignored_aliases):
    match_id, pitch, team_a_text, team_b_text, goals_a, goals_b = row
    match_date = match_id.rsplit("-", 1)[0]
    if pitch not in ("box", "hf"):
        raise ValueError(f"{match_id}: pitch must be 'box' or 'hf'.")
    try:
        goals_a, goals_b = int(goals_a), int(goals_b)
    except ValueError:
        raise ValueError(f"{match_id}: goals must be integers.")

    def resolve_team(text):
        ids = []
        for alias in (name.strip() for name in text.split(",")):
            if not alias:
                continue
            if alias in alias_lookup:
                ids.append(alias_lookup[alias])
            elif alias in ignored_aliases:
                continue
            else:
                raise ValueError(f"{match_id}: unknown player alias '{alias}'.")
        return ids

    team_a, team_b = resolve_team(team_a_text), resolve_team(team_b_text)
    if set(team_a) & set(team_b):
        raise ValueError(f"{match_id}: a player appears on both teams.")
    if len(team_a) != len(set(team_a)) or len(team_b) != len(set(team_b)):
        raise ValueError(f"{match_id}: a player appears more than once.")
    return {
        "match_id": match_id,
        "date": match_date,
        "pitch": pitch,
        "team_a": team_a,
        "team_b": team_b,
        "goals_a": goals_a,
        "goals_b": goals_b,
        "players_a": len(team_a_text.split(",")) if team_a_text.strip() else 0,
        "players_b": len(team_b_text.split(",")) if team_b_text.strip() else 0,
    }


def import_uploaded_matches(connection, file_bytes):
    rows = parse_uploaded_matches(file_bytes)
    alias_lookup = get_alias_lookup(connection)
    ignored_aliases = get_ignored_aliases(connection)
    imported = []
    for row in rows:
        parsed = resolve_uploaded_match(row, alias_lookup, ignored_aliases)
        if match_exists(connection, parsed["match_id"]):
            continue
        add_match(
            connection,
            parsed["date"],
            parsed["pitch"],
            parsed["team_a"],
            parsed["team_b"],
            parsed["goals_a"],
            parsed["goals_b"],
            parsed["players_a"],
            parsed["players_b"],
            parsed["match_id"],
        )
        imported.append(parsed["match_id"])
    return imported, process_new_matches(connection) if imported else 0
