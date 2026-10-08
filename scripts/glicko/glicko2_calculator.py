"""Glicko-2 calculator for full database recalculation.

This module processes all matches chronologically from SQLite, computes
historical match ratings and current ratings across Total, BOX, and HF pitches,
and persists the results into the database.
"""

from collections import defaultdict
from datetime import datetime
import math
import os
from pathlib import Path
import shutil
import sqlite3

from scripts.database.database import get_connection, get_database_file
from scripts.database.db_matches import get_matches, get_match_teams, get_all_match_teams
from scripts.database.db_players import get_players
from scripts.database.db_ratings import (
    get_calibrations,
    get_player_calibrated_priors,
    save_player_calibrated_priors,
)
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

CALIBRATION_THRESHOLD = 15
INACTIVITY_RETIREMENT_DAYS = 365

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def backup_database(connection=None):
    database_file = get_database_file()
    override = os.environ.get("RB48_DATABASE_BACKUP_DIR")
    backup_folder = Path(override) if override else database_file.parent / "backups"
    backup_folder.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    backup_file = backup_folder / f"rb48_{timestamp}.db"
    if connection is not None:
        connection.commit()
        backup_conn = sqlite3.connect(backup_file)
        connection.backup(backup_conn)
        backup_conn.close()
    elif database_file.exists():
        shutil.copy2(database_file, backup_file)
    print(f"Database backup created: {backup_file}")
    return backup_file


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


def compute_player_thresholds(
    connection=None,
    matches=None,
    match_teams_map=None,
    standard_threshold=CALIBRATION_THRESHOLD,
    inactivity_days=INACTIVITY_RETIREMENT_DAYS,
):
    """
    Computes per-player calibration thresholds based on the dual-criterion model:
    1. Standard threshold: 15 games.
    2. Second criterion: If a player has < 15 games across history and has been inactive
       for > 1 year (> 365 days) after their last game, their calibration threshold is set
       to their maximum match count k = max(1, count).
    """
    if matches is None and connection is not None:
        matches = get_matches(connection)
    elif matches is None:
        matches = {}

    match_list = list(matches.values()) if isinstance(matches, dict) else list(matches)
    if match_teams_map is None and connection is not None:
        match_teams_map = get_all_match_teams(connection)

    p_total_games = {}
    p_last_date = {}
    max_date_str = "1900-01-01"

    for m in match_list:
        mid = m["match_id"]
        d_str = m["date"][:10]
        if d_str > max_date_str:
            max_date_str = d_str
        if match_teams_map is not None:
            team_a, team_b = match_teams_map.get(mid, ([], []))
        elif connection is not None:
            team_a, team_b = get_match_teams(connection, mid)
        else:
            team_a, team_b = [], []

        for pid in team_a + team_b:
            p_total_games.setdefault(pid, set()).add(mid)
            p_last_date[pid] = max(p_last_date.get(pid, d_str), d_str)

    ref_dt = datetime.now().date()
    if max_date_str != "1900-01-01":
        m_dt = datetime.strptime(max_date_str, "%Y-%m-%d").date()
        if m_dt > ref_dt:
            ref_dt = m_dt

    player_thresh = {}

    for pid, g_set in p_total_games.items():
        cnt = len(g_set)
        if cnt >= standard_threshold:
            player_thresh[pid] = standard_threshold
        else:
            p_dt = datetime.strptime(p_last_date[pid], "%Y-%m-%d").date()
            if (ref_dt - p_dt).days > inactivity_days:
                player_thresh[pid] = max(1, cnt)
            else:
                player_thresh[pid] = standard_threshold

    if connection is not None:
        try:
            for row in connection.execute("SELECT player_id FROM players"):
                p_id = row["player_id"]
                if p_id not in player_thresh:
                    player_thresh[p_id] = standard_threshold
        except Exception:
            pass

    return player_thresh


def get_first_alias(connection, player_id):
    if connection is None:
        return f"Player {player_id}"
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


def update_session(
    connection,
    session_matches,
    ratings,
    engine,
    debug_player=None,
    match_teams_map=None,
    retro_calibrated=False,
    player_thresholds=None,
    calibrated_players=None,
    games_played_tracker=None,
):
    """
    Update ratings for a session (all matches played on the same calendar date).

    Evidence from all matches in the session is pooled together before updating
    player ratings and RDs simultaneously, eliminating intra-session order dependency.

    When retro_calibrated is active, implements Option A* Surgical Split:
    - Calibrated players with games <= threshold are frozen (preventing double counting).
    - Transition sessions update only matches strictly after threshold.
    - Graduated players update dynamically with all session matches.
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
                team1_total,
                mid,
            ))
            player_games[player_id].setdefault(pitch_type, []).append((
                t1_pitch,
                t2_pitch,
                res1,
                calculate_teammates_rd(player_id, team1_ids, team1_total, ratings, pitch_type),
                team1_total,
                mid,
            ))

        for player_id in team2_ids:
            player_games.setdefault(player_id, {}).setdefault(TOTAL, []).append((
                t2_total,
                t1_total,
                res2,
                calculate_teammates_rd(player_id, team2_ids, team2_total, ratings, TOTAL),
                team2_total,
                mid,
            ))
            player_games[player_id].setdefault(pitch_type, []).append((
                t2_pitch,
                t1_pitch,
                res2,
                calculate_teammates_rd(player_id, team2_ids, team2_total, ratings, pitch_type),
                team2_total,
                mid,
            ))

    # Apply session batch update for all active players
    for player_id, rtypes in player_games.items():
        session_p_mids = [g[5] for g in rtypes[TOTAL]]
        num_session_matches = len(session_p_mids)

        if retro_calibrated and calibrated_players and player_id in calibrated_players:
            p_thresh = player_thresholds.get(player_id, CALIBRATION_THRESHOLD) if player_thresholds else CALIBRATION_THRESHOLD
            prev_games = games_played_tracker[player_id] if games_played_tracker is not None else 0
            total_games = prev_games + num_session_matches

            if total_games <= p_thresh:
                # Option A: Frozen during initial calibration window (1..p_thresh)
                pass
            elif prev_games < p_thresh and total_games > p_thresh:
                # Surgical Split in transition session:
                needed = p_thresh - prev_games
                mids_up_to_thresh = set(session_p_mids[:needed])
                for rtype, games in rtypes.items():
                    games_after = [g for g in games if g[5] not in mids_up_to_thresh]
                    if games_after:
                        ratings[player_id][rtype] = engine.update_player_session(
                            ratings[player_id][rtype],
                            games_after,
                        )
            else:
                # Graduated player (prev_games >= p_thresh)
                for rtype, games in rtypes.items():
                    ratings[player_id][rtype] = engine.update_player_session(
                        ratings[player_id][rtype],
                        games,
                    )
            if games_played_tracker is not None:
                games_played_tracker[player_id] = total_games
        else:
            if games_played_tracker is not None:
                games_played_tracker[player_id] = games_played_tracker.get(player_id, 0) + num_session_matches
            for rtype, games in rtypes.items():
                ratings[player_id][rtype] = engine.update_player_session(
                    ratings[player_id][rtype],
                    games,
                )

    # Apply inactivity tick once per session for inactive players
    for player_id in ratings:
        p_thresh = player_thresholds.get(player_id, CALIBRATION_THRESHOLD) if player_thresholds else CALIBRATION_THRESHOLD
        is_anchored = (
            retro_calibrated
            and calibrated_players is not None
            and player_id in calibrated_players
            and games_played_tracker is not None
            and games_played_tracker.get(player_id, 0) < p_thresh
        )
        if not is_anchored:
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


def _run_single_pass1_step(
    connection,
    matches,
    sessions,
    engine,
    match_teams_map,
    player_thresholds,
    current_priors=None,
    alpha=0.5,
):
    """
    Executes a single step of Pass 1 prior discovery.
    When current_priors is present, ratings_world seeds established priors for provisional players,
    freezing them during their provisional window so opponents face their realistic strength.
    Each player's own discovery path (ratings_discovery) strictly starts from uncalibrated defaults.
    """
    prepared = prepare_glicko_table(
        connection, matches, {}, match_teams_map=match_teams_map
    )
    ratings_world = glicko_table_to_ratings(prepared)
    if current_priors:
        for pid, pr in current_priors.items():
            if pid in ratings_world:
                for rtype in (TOTAL, BOX, HF):
                    ratings_world[pid][rtype] = Rating(
                        pr[rtype].rating, pr[rtype].rd, pr[rtype].sigma
                    )

    ratings_discovery = glicko_table_to_ratings(prepared)
    games_played = defaultdict(int)
    new_discovered = {}

    for session_date, session_matches in sessions.items():
        player_games = {}
        session_active_players = set()
        session_pitches = set()

        for match in session_matches:
            mid = match["match_id"]
            if match_teams_map is not None:
                team1_ids, team2_ids = match_teams_map.get(mid, ([], []))
            elif connection is not None:
                team1_ids, team2_ids = get_match_teams(connection, mid)
            else:
                team1_ids, team2_ids = [], []

            if not team1_ids or not team2_ids:
                continue

            team1_total = match["players_a"]
            team2_total = match["players_b"]

            pitch_type = BOX if match["pitch"] == "box" else HF
            session_pitches.add(pitch_type)
            session_active_players.update(team1_ids)
            session_active_players.update(team2_ids)

            if match["goals_a"] > match["goals_b"]:
                res1, res2 = WIN, LOSS
            elif match["goals_a"] < match["goals_b"]:
                res1, res2 = LOSS, WIN
            else:
                res1 = res2 = DRAW

            # Teammates and opponents are valued via ratings_world
            t1_total = calculate_team_rating(team1_ids, team1_total, ratings_world, TOTAL)
            t2_total = calculate_team_rating(team2_ids, team2_total, ratings_world, TOTAL)
            t1_pitch = calculate_team_rating(team1_ids, team1_total, ratings_world, pitch_type)
            t2_pitch = calculate_team_rating(team2_ids, team2_total, ratings_world, pitch_type)

            for pid in team1_ids:
                player_games.setdefault(pid, {}).setdefault(TOTAL, []).append((
                    t1_total, t2_total, res1,
                    calculate_teammates_rd(pid, team1_ids, team1_total, ratings_world, TOTAL),
                    team1_total, mid,
                ))
                player_games[pid].setdefault(pitch_type, []).append((
                    t1_pitch, t2_pitch, res1,
                    calculate_teammates_rd(pid, team1_ids, team1_total, ratings_world, pitch_type),
                    team1_total, mid,
                ))

            for pid in team2_ids:
                player_games.setdefault(pid, {}).setdefault(TOTAL, []).append((
                    t2_total, t1_total, res2,
                    calculate_teammates_rd(pid, team2_ids, team2_total, ratings_world, TOTAL),
                    team2_total, mid,
                ))
                player_games[pid].setdefault(pitch_type, []).append((
                    t2_pitch, t1_pitch, res2,
                    calculate_teammates_rd(pid, team2_ids, team2_total, ratings_world, pitch_type),
                    team2_total, mid,
                ))

        for pid, rtypes in player_games.items():
            prev_games = games_played[pid]
            session_p_mids = [g[5] for g in rtypes[TOTAL]]
            total_games = prev_games + len(session_p_mids)
            p_thresh = player_thresholds.get(pid, CALIBRATION_THRESHOLD)

            # 1. Update ratings_discovery for player's own discovery trajectory
            if prev_games < p_thresh:
                needed = p_thresh - prev_games
                mids_up = set(session_p_mids[:needed])

                games_up_tot = [g for g in rtypes[TOTAL] if g[5] in mids_up]
                r_tot_thresh = engine.update_player_session(ratings_discovery[pid][TOTAL], games_up_tot)

                games_up_box = [g for g in rtypes.get(BOX, []) if g[5] in mids_up]
                if games_up_box:
                    r_box_thresh = engine.update_player_session(ratings_discovery[pid][BOX], games_up_box)
                else:
                    r_box_thresh = Rating(ratings_discovery[pid][BOX].rating, ratings_discovery[pid][BOX].rd, ratings_discovery[pid][BOX].sigma)

                games_up_hf = [g for g in rtypes.get(HF, []) if g[5] in mids_up]
                if games_up_hf:
                    r_hf_thresh = engine.update_player_session(ratings_discovery[pid][HF], games_up_hf)
                else:
                    r_hf_thresh = Rating(ratings_discovery[pid][HF].rating, ratings_discovery[pid][HF].rd, ratings_discovery[pid][HF].sigma)

                if total_games >= p_thresh and pid not in new_discovered:
                    if current_priors and pid in current_priors:
                        # Damped relaxation update: (1 - alpha) * prior_old + alpha * prior_new
                        d_tot_r = (1.0 - alpha) * current_priors[pid][TOTAL].rating + alpha * r_tot_thresh.rating
                        d_tot_rd = (1.0 - alpha) * current_priors[pid][TOTAL].rd + alpha * r_tot_thresh.rd
                        d_box_r = (1.0 - alpha) * current_priors[pid][BOX].rating + alpha * r_box_thresh.rating
                        d_box_rd = (1.0 - alpha) * current_priors[pid][BOX].rd + alpha * r_box_thresh.rd
                        d_hf_r = (1.0 - alpha) * current_priors[pid][HF].rating + alpha * r_hf_thresh.rating
                        d_hf_rd = (1.0 - alpha) * current_priors[pid][HF].rd + alpha * r_hf_thresh.rd
                        new_discovered[pid] = {
                            TOTAL: Rating(d_tot_r, d_tot_rd, r_tot_thresh.sigma),
                            BOX: Rating(d_box_r, d_box_rd, r_box_thresh.sigma),
                            HF: Rating(d_hf_r, d_hf_rd, r_hf_thresh.sigma),
                        }
                    else:
                        new_discovered[pid] = {
                            TOTAL: Rating(r_tot_thresh.rating, r_tot_thresh.rd, r_tot_thresh.sigma),
                            BOX: Rating(r_box_thresh.rating, r_box_thresh.rd, r_box_thresh.sigma),
                            HF: Rating(r_hf_thresh.rating, r_hf_thresh.rd, r_hf_thresh.sigma),
                        }

                games_after_tot = [g for g in rtypes[TOTAL] if g[5] not in mids_up]
                ratings_discovery[pid][TOTAL] = engine.update_player_session(r_tot_thresh, games_after_tot) if games_after_tot else r_tot_thresh
                games_after_box = [g for g in rtypes.get(BOX, []) if g[5] not in mids_up]
                ratings_discovery[pid][BOX] = engine.update_player_session(r_box_thresh, games_after_box) if games_after_box else r_box_thresh
                games_after_hf = [g for g in rtypes.get(HF, []) if g[5] not in mids_up]
                ratings_discovery[pid][HF] = engine.update_player_session(r_hf_thresh, games_after_hf) if games_after_hf else r_hf_thresh
            else:
                for rtype, games in rtypes.items():
                    ratings_discovery[pid][rtype] = engine.update_player_session(ratings_discovery[pid][rtype], games)

            # 2. Update ratings_world for opponent-facing strength (Option A* Surgical Split)
            if current_priors and pid in current_priors:
                if total_games <= p_thresh:
                    pass  # Frozen during provisional window
                elif prev_games < p_thresh and total_games > p_thresh:
                    needed = p_thresh - prev_games
                    mids_up = set(session_p_mids[:needed])
                    for rtype, games in rtypes.items():
                        ga = [g for g in games if g[5] not in mids_up]
                        if ga:
                            ratings_world[pid][rtype] = engine.update_player_session(ratings_world[pid][rtype], ga)
                else:
                    for rtype, games in rtypes.items():
                        ratings_world[pid][rtype] = engine.update_player_session(ratings_world[pid][rtype], games)
            else:
                for rtype, games in rtypes.items():
                    ratings_world[pid][rtype] = engine.update_player_session(ratings_world[pid][rtype], games)

            games_played[pid] = total_games

        # Inactivity tick
        for pid in ratings_world:
            p_thresh = player_thresholds.get(pid, CALIBRATION_THRESHOLD)
            is_frozen = (
                current_priors
                and pid in current_priors
                and games_played[pid] < p_thresh
            )
            if not is_frozen:
                if pid not in session_active_players:
                    ratings_world[pid][TOTAL].rd = min(ratings_world[pid][TOTAL].rd + INACTIVITY_RD_TICK, DEFAULT_RD)
                for pitch_type in session_pitches:
                    pitch_active = {
                        p for p in session_active_players
                        if p in player_games and pitch_type in player_games[p]
                    }
                    if pid not in pitch_active:
                        ratings_world[pid][pitch_type].rd = min(ratings_world[pid][pitch_type].rd + INACTIVITY_RD_TICK, DEFAULT_RD)

    return new_discovered


def run_recalibration_pass1(
    connection,
    matches,
    initial_calibrations=None,
    match_teams_map=None,
    player_thresholds=None,
    max_iterations=5,
    tolerance=0.5,
    relaxation=0.5,
):
    """
    Pass 1: Discover emergent latent ratings at the calibration threshold for eligible players.
    Uses bounded iterative prior convergence (damped Jacobi fixed-point iteration) to resolve
    simultaneous uncalibrated encounters without newcomer bleed.

    Args:
        max_iterations: Maximum number of convergence passes (default 5).
        tolerance: Maximum change in rating points across all players to declare convergence (default 0.5).
        relaxation: Damping parameter in (0, 1] for fixed-point stability (default 0.5).

    Returns:
        calibrated_priors: dict[player_id -> {TOTAL: Rating, BOX: Rating, HF: Rating}]
    """
    engine = Glicko2()
    if match_teams_map is None and connection is not None:
        match_teams_map = get_all_match_teams(connection)

    if player_thresholds is None:
        player_thresholds = compute_player_thresholds(connection, matches, match_teams_map=match_teams_map)

    sessions = group_matches_by_date(matches)

    # Initial pass (k = 0): everyone discovers from uncalibrated 1500 priors
    priors = _run_single_pass1_step(
        connection=connection,
        matches=matches,
        sessions=sessions,
        engine=engine,
        match_teams_map=match_teams_map,
        player_thresholds=player_thresholds,
        current_priors=None,
        alpha=1.0,
    )

    if max_iterations <= 1 or not priors:
        return priors

    # Iterative refinement passes (k = 1..max_iterations-1)
    for iteration in range(1, max_iterations):
        new_priors = _run_single_pass1_step(
            connection=connection,
            matches=matches,
            sessions=sessions,
            engine=engine,
            match_teams_map=match_teams_map,
            player_thresholds=player_thresholds,
            current_priors=priors,
            alpha=relaxation,
        )

        max_delta = 0.0
        for pid, p_r in new_priors.items():
            if pid in priors:
                d = abs(p_r[TOTAL].rating - priors[pid][TOTAL].rating)
                if d > max_delta:
                    max_delta = d

        priors = new_priors
        if max_delta < tolerance:
            break

    return priors


def write_match_ratings(connection, match_id, ratings):
    if connection is None:
        return
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
    if connection is None:
        return
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


def calculate_glicko(
    connection,
    matches,
    prepared_glicko,
    debug_player=None,
    match_teams_map=None,
    retro_calibrated=True,
    calibrated_priors=None,
    player_thresholds=None,
):
    """
    Compute Glicko-2 ratings chronologically across all matches.
    When retro_calibrated is True, executes Two-Pass Retrospective Prior Calibration
    with Option A* Surgical Split to eliminate Newcomer Bleed.
    """
    engine = Glicko2()
    ratings = glicko_table_to_ratings(prepared_glicko)
    if match_teams_map is None and connection is not None:
        match_teams_map = get_all_match_teams(connection)

    if retro_calibrated:
        if player_thresholds is None:
            player_thresholds = compute_player_thresholds(connection, matches, match_teams_map=match_teams_map)
        if calibrated_priors is None:
            calibrated_priors = run_recalibration_pass1(
                connection, matches, prepared_glicko, match_teams_map, player_thresholds
            )

        # Seed calibrated players with their discovered priors from match 1
        for pid, priors in calibrated_priors.items():
            if pid not in ratings:
                ratings[pid] = {}
            for rtype in (TOTAL, BOX, HF):
                p_r = priors[rtype]
                ratings[pid][rtype] = Rating(p_r.rating, p_r.rd, p_r.sigma)

    sessions = group_matches_by_date(matches)
    games_played_tracker = defaultdict(int) if retro_calibrated else None
    calibrated_players = set(calibrated_priors.keys()) if (retro_calibrated and calibrated_priors) else set()

    for session_date, session_matches in sessions.items():
        # Pre-session snapshot written for all matches on this date
        current_glicko = ratings_to_glicko_table(ratings)
        for match in session_matches:
            write_match_ratings(connection, match["match_id"], current_glicko)
        update_session(
            connection,
            session_matches,
            ratings,
            engine,
            debug_player=debug_player,
            match_teams_map=match_teams_map,
            retro_calibrated=retro_calibrated,
            player_thresholds=player_thresholds,
            calibrated_players=calibrated_players,
            games_played_tracker=games_played_tracker,
        )

    return ratings_to_glicko_table(ratings)


def recalculate_glicko2_ratings(connection=None, create_backup=True, debug_player=None, retro_calibrated=True):
    """
    Full recalculation of Glicko-2 ratings from scratch across all matches in the database.
    Optionally creates an archival SQLite database backup first.
    Executes Two-Pass Retrospective Prior Recalibration (Option A* Surgical Split) by default.
    Returns a dict with execution statistics and backup metadata.
    """
    backup_file = None
    if create_backup:
        backup_file = backup_database(connection)

    conn = connection or get_connection()
    should_close = connection is None
    try:
        matches = get_matches(conn)
        match_teams_map = get_all_match_teams(conn)
        calibrations = get_calibrations(conn)
        clear_ratings(conn)
        player_thresholds = compute_player_thresholds(conn, matches, match_teams_map)
        prepared_glicko = prepare_glicko_table(conn, matches, calibrations, match_teams_map=match_teams_map)

        calibrated_priors = None
        if retro_calibrated:
            calibrated_priors = run_recalibration_pass1(
                conn, matches, prepared_glicko, match_teams_map, player_thresholds
            )
            save_player_calibrated_priors(conn, calibrated_priors, thresholds=player_thresholds)

        glickos = calculate_glicko(
            conn,
            matches,
            prepared_glicko,
            debug_player=debug_player,
            match_teams_map=match_teams_map,
            retro_calibrated=retro_calibrated,
            calibrated_priors=calibrated_priors,
            player_thresholds=player_thresholds,
        )
        write_glicko(conn, glickos)
        try:
            from scripts.docs.generate_model_docs import update_docs_file
            update_docs_file()
        except Exception:
            pass
        return {
            "success": True,
            "backup_file": backup_file.name if backup_file else None,
            "matches_count": len(matches),
            "players_count": len(glickos),
            "calibrated_players_count": len(calibrated_priors) if calibrated_priors else 0,
        }
    finally:
        if should_close:
            conn.close()


def main():
    connection = get_connection()
    try:
        debug_player = select_debug_player(connection)
    finally:
        connection.close()
    result = recalculate_glicko2_ratings(create_backup=True, debug_player=debug_player)
    print(f"Loaded {result['matches_count']} matches")
    print(f"Calculated ratings for {result['players_count']} players")
    if result.get("backup_file"):
        print(f"Database backup created: {result['backup_file']}")


if __name__ == "__main__":
    main()
