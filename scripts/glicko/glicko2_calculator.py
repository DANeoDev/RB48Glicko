"""Glicko-2 calculator for full database recalculation.

This module processes all matches chronologically from SQLite, computes
historical match ratings and current ratings across Total, BOX, and HF pitches,
and persists the results into the database.
"""

from datetime import datetime
import math
from pathlib import Path
import shutil

from scripts.database.database import get_connection, get_database_file
from scripts.database.db_matches import get_matches, get_match_teams
from scripts.database.db_players import get_players
from scripts.database.db_ratings import get_calibrations
from scripts.glicko.glicko2 import (
    Glicko2,
    Rating,
    DEFAULT_RATING,
    DEFAULT_RD,
    IGNORED_RD,
    DEFAULT_SIGMA,
    WIN,
    LOSS,
    DRAW,
    TOTAL,
    BOX,
    HF,
    INACTIVITY_RD_TICK,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def backup_database():
    database_file = get_database_file()
    backup_folder = database_file.parent / "backups"
    backup_folder.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    backup_file = backup_folder / f"rb48_{timestamp}.db"
    shutil.copy2(database_file, backup_file)
    print(f"Database backup created: {backup_file}")


def clear_ratings(connection):
    connection.execute("DELETE FROM match_ratings")
    connection.execute("DELETE FROM ratings")
    connection.commit()


def initialize_player_ratings(player_id, ratings, calibration=None):
    if player_id in ratings:
        return
    initial = (calibration or {}).get(
        player_id,
        {"rating": DEFAULT_RATING, "rd": DEFAULT_RD, "sigma": DEFAULT_SIGMA},
    )
    ratings[player_id] = {
        TOTAL: Rating(initial["rating"], initial["rd"], initial["sigma"]),
        BOX: Rating(initial["rating"], initial["rd"], initial["sigma"]),
        HF: Rating(initial["rating"], initial["rd"], initial["sigma"]),
    }


def prepare_glicko_table(connection, matches, calibration_ratings, match_teams_map=None):
    prepared_glicko = {}
    for match in matches.values():
        mid = match["match_id"]
        if match_teams_map is not None:
            team_a, team_b = match_teams_map.get(mid, ([], []))
        else:
            team_a, team_b = get_match_teams(connection, mid)
        for player_id in team_a + team_b:
            if player_id not in prepared_glicko:
                initial = calibration_ratings.get(
                    player_id,
                    {"rating": DEFAULT_RATING, "rd": DEFAULT_RD, "sigma": DEFAULT_SIGMA},
                )
                prepared_glicko[player_id] = {
                    TOTAL: initial.copy(),
                    BOX: initial.copy(),
                    HF: initial.copy(),
                }
    return prepared_glicko


def glicko_table_to_ratings(glicko_table):
    ratings = {}
    for player_id, rating_types in glicko_table.items():
        ratings[player_id] = {}
        for rating_type, data in rating_types.items():
            ratings[player_id][rating_type] = Rating(data["rating"], data["rd"], data["sigma"])
    return ratings


def ratings_to_glicko_table(ratings):
    glicko_table = {}
    for player_id, rating_types in ratings.items():
        glicko_table[player_id] = {}
        for rating_type, rating in rating_types.items():
            glicko_table[player_id][rating_type] = {
                "rating": rating.rating,
                "rd": rating.rd,
                "sigma": rating.sigma,
            }
    return glicko_table


def calculate_team_rating(player_ids, total_players, ratings, rating_type):
    if not player_ids:
        return None
    ignored_players = total_players - len(player_ids)
    average_rating = sum(ratings[player][rating_type].rating for player in player_ids) / len(player_ids)
    average_rd = math.sqrt(
        (sum(ratings[player][rating_type].rd ** 2 for player in player_ids) + IGNORED_RD ** 2 * ignored_players)
        / total_players
    )
    average_sigma = math.sqrt(
        (sum(ratings[player][rating_type].sigma ** 2 for player in player_ids) + DEFAULT_SIGMA ** 2 * ignored_players)
        / total_players
    )
    return Rating(average_rating, average_rd, average_sigma)


def calculate_teammates_rd(player_id, player_ids, total_players, ratings, rating_type):
    """
    Calculate the root-mean-square RD of a player's teammates.

    Excludes the player themselves so personal uncertainty does not bias
    the measurement of teammate uncertainty. Missing/external players on
    the team are accounted for using IGNORED_RD.

    Returns None if there are no teammates (e.g., in a 1v1 match).
    """
    other_player_ids = [pid for pid in player_ids if pid != player_id]
    num_teammates = total_players - 1
    if num_teammates <= 0:
        return None
    ignored_players = num_teammates - len(other_player_ids)
    teammates_rd = math.sqrt(
        (sum(ratings[pid][rating_type].rd ** 2 for pid in other_player_ids) + IGNORED_RD ** 2 * ignored_players)
        / num_teammates
    )
    return teammates_rd


def create_virtual_rating(player_id, team_rating, ratings, rating_type):
    player = ratings[player_id][rating_type]
    return Rating(team_rating.rating, player.rd, player.sigma)


def group_matches_by_date(matches):
    """
    Group matches chronologically by match date.

    Supports matches as a dict (keyed by match_id) or as a list.
    Preserves chronological order of dates and match IDs within each date.
    """
    match_list = list(matches.values()) if isinstance(matches, dict) else list(matches)
    match_list.sort(key=lambda m: m["match_id"])
    sessions = {}
    for match in match_list:
        sessions.setdefault(match["date"], []).append(match)
    return sessions


def calculate_glicko(connection, matches, prepared_glicko, debug_player=None):
    engine = Glicko2()
    ratings = glicko_table_to_ratings(prepared_glicko)
    sessions = group_matches_by_date(matches)

    for session_date, session_matches in sessions.items():
        # Pre-session snapshot written for all matches on this date
        current_glicko = ratings_to_glicko_table(ratings)
        for match in session_matches:
            write_match_ratings(connection, match["match_id"], current_glicko)
        update_session(connection, session_matches, ratings, engine, debug_player)

    return ratings_to_glicko_table(ratings)


def get_first_alias(connection, player_id):
    row = connection.execute(
        "SELECT alias FROM aliases WHERE player_id = ? ORDER BY alias LIMIT 1",
        (player_id,),
    ).fetchone()
    if row is None:
        return f"Player {player_id}"
    return row[0]


def select_debug_player(connection):
    answer = input("\nDebug a player? (y/n): ")
    if answer.lower() != "y":
        return None
    players = get_players(connection)
    print("\nPlayers:")
    player_ids = sorted(players)
    for number, player_id in enumerate(player_ids, start=1):
        print(f"  {number}. {players[player_id]['aliases'][0]}")
    while True:
        try:
            choice = int(input("Select player: "))
            if 1 <= choice <= len(player_ids):
                return player_ids[choice - 1]
        except ValueError:
            pass
        print("Please enter a valid player number.")


def update_session(connection, session_matches, ratings, engine, debug_player=None, match_teams_map=None):
    """
    Update ratings for a session (all matches played on the same calendar date).

    Evidence from all matches in the session is pooled together before updating
    player ratings and RDs simultaneously, eliminating intra-session order dependency.
    """
    if not session_matches:
        return

    pre_session_ratings = {}
    if debug_player:
        pre_session_ratings = {
            rtype: Rating(r.rating, r.rd, r.sigma)
            for rtype, r in ratings.get(debug_player, {}).items()
        }

    player_games = {}
    session_active_players = set()
    session_pitches = set()

    for match in session_matches:
        mid = match["match_id"]
        if match_teams_map is not None:
            team1_ids, team2_ids = match_teams_map.get(mid, ([], []))
        else:
            team1_ids, team2_ids = get_match_teams(connection, mid)
        if not team1_ids or not team2_ids:
            continue

        team1_total = match["players_a"]
        team2_total = match["players_b"]

        if match["pitch"] == "box":
            pitch_type = BOX
        elif match["pitch"] == "hf":
            pitch_type = HF
        else:
            raise ValueError(f"Unknown pitch type: {match['pitch']}")

        session_pitches.add(pitch_type)
        session_active_players.update(team1_ids)
        session_active_players.update(team2_ids)

        if match["goals_a"] > match["goals_b"]:
            res1, res2 = WIN, LOSS
        elif match["goals_a"] < match["goals_b"]:
            res1, res2 = LOSS, WIN
        else:
            res1 = res2 = DRAW

        t1_total = calculate_team_rating(team1_ids, team1_total, ratings, TOTAL)
        t2_total = calculate_team_rating(team2_ids, team2_total, ratings, TOTAL)
        t1_pitch = calculate_team_rating(team1_ids, team1_total, ratings, pitch_type)
        t2_pitch = calculate_team_rating(team2_ids, team2_total, ratings, pitch_type)

        for player_id in team1_ids:
            player_games.setdefault(player_id, {}).setdefault(TOTAL, []).append((
                t1_total,
                t2_total,
                res1,
                calculate_teammates_rd(player_id, team1_ids, team1_total, ratings, TOTAL),
            ))
            player_games[player_id].setdefault(pitch_type, []).append((
                t1_pitch,
                t2_pitch,
                res1,
                calculate_teammates_rd(player_id, team1_ids, team1_total, ratings, pitch_type),
            ))

        for player_id in team2_ids:
            player_games.setdefault(player_id, {}).setdefault(TOTAL, []).append((
                t2_total,
                t1_total,
                res2,
                calculate_teammates_rd(player_id, team2_ids, team2_total, ratings, TOTAL),
            ))
            player_games[player_id].setdefault(pitch_type, []).append((
                t2_pitch,
                t1_pitch,
                res2,
                calculate_teammates_rd(player_id, team2_ids, team2_total, ratings, pitch_type),
            ))

    # Apply session batch update for all active players
    for player_id, rtypes in player_games.items():
        for rtype, games in rtypes.items():
            ratings[player_id][rtype] = engine.update_player_session(
                ratings[player_id][rtype],
                games,
            )

    # Apply inactivity tick once per session for inactive players
    for player_id in ratings:
        if player_id not in session_active_players:
            ratings[player_id][TOTAL].rd = min(
                ratings[player_id][TOTAL].rd + INACTIVITY_RD_TICK, DEFAULT_RD
            )
        for pitch_type in session_pitches:
            pitch_active = {
                pid for pid in session_active_players
                if pid in player_games and pitch_type in player_games[pid]
            }
            if player_id not in pitch_active:
                ratings[player_id][pitch_type].rd = min(
                    ratings[player_id][pitch_type].rd + INACTIVITY_RD_TICK, DEFAULT_RD
                )

    if debug_player and debug_player in session_active_players:
        print(f"\nDEBUG PLAYER: {get_first_alias(connection, debug_player)}")
        print(f"Session Date: {session_matches[0]['date']}")
        print(f"Matches in Session: {len(session_matches)}")
        for rtype in (TOTAL, *session_pitches):
            if debug_player in player_games and rtype in player_games[debug_player]:
                old = pre_session_ratings[rtype]
                new = ratings[debug_player][rtype]
                print(f"\n{rtype.upper()}:")
                print(f"  Games played: {len(player_games[debug_player][rtype])}")
                print(f"  Rating: {old.rating:.3f} -> {new.rating:.3f}")
                print(f"  RD: {old.rd:.3f} -> {new.rd:.3f}")
                print(f"  Sigma: {old.sigma:.6f} -> {new.sigma:.6f}")


def update_match(connection, match, ratings, engine, debug_player=None):
    """Convenience wrapper to update a single match as a 1-match session."""
    update_session(connection, [match], ratings, engine, debug_player)


def write_match_ratings(connection, match_id, ratings):
    for player_id, rating_types in ratings.items():
        for rating_type, rating in rating_types.items():
            connection.execute(
                """
                INSERT INTO match_ratings (match_id, player_id, rating_type, rating, rd, sigma)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(match_id, player_id, rating_type) DO UPDATE SET
                    rating = excluded.rating,
                    rd = excluded.rd,
                    sigma = excluded.sigma
                """,
                (match_id, player_id, rating_type, rating["rating"], rating["rd"], rating["sigma"]),
            )
    connection.commit()


def write_glicko(connection, glickos):
    for player_id, rating_types in glickos.items():
        for rating_type, rating in rating_types.items():
            connection.execute(
                """
                INSERT INTO ratings (player_id, rating_type, rating, rd, sigma)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(player_id, rating_type) DO UPDATE SET
                    rating = excluded.rating,
                    rd = excluded.rd,
                    sigma = excluded.sigma
                """,
                (player_id, rating_type, rating["rating"], rating["rd"], rating["sigma"]),
            )
    connection.commit()


def main():
    backup_database()
    connection = get_connection()
    try:
        matches = get_matches(connection)
        print(f"Loaded {len(matches)} matches")
        calibrations = get_calibrations(connection)
        print(f"Loaded {len(calibrations)} calibrations")
        clear_ratings(connection)
        prepared_glicko = prepare_glicko_table(connection, matches, calibrations)
        print(f"Prepared ratings for {len(prepared_glicko)} players")
        debug_player = select_debug_player(connection)
        glickos = calculate_glicko(connection, matches, prepared_glicko, debug_player)
        print(f"Calculated ratings for {len(glickos)} players")
        write_glicko(connection, glickos)
        try:
            from scripts.docs.generate_model_docs import update_docs_file
            update_docs_file()
        except Exception:
            pass
    finally:
        connection.close()


if __name__ == "__main__":
    main()
