import math
try:
    from flask import request
except ImportError:
    request = None

from datetime import datetime, timedelta
from scripts.database.db_matches import (
    get_matches,
    get_match_teams,
    get_all_match_players,
    get_all_match_teams,
)
from scripts.database.db_ratings import get_match_ratings, get_all_match_ratings
from scripts.glicko.glicko2 import (
    Glicko2,
    Rating,
    TOTAL,
    BOX,
    HF,
    IGNORED_RD,
    DEFAULT_SIGMA,
    expected_score,
)


def _collect_player_match_events(connection, sorted_matches: list[dict], players: dict) -> dict[int, dict[str, list[dict]]]:
    """Collect and cache match outcome events and prior ratings per player and pitch type."""
    all_mr = get_all_match_ratings(connection)
    all_mps = get_all_match_players(connection)
    match_data_cache = {
        m["match_id"]: (all_mr.get(m["match_id"], {}), all_mps.get(m["match_id"], []))
        for m in sorted_matches
    }

    player_events: dict[int, dict[str, list[dict]]] = {pid: {TOTAL: [], BOX: [], HF: []} for pid in players}
    for m in sorted_matches:
        mid = m["match_id"]
        mr, mps = match_data_cache[mid]
        goals_a = m["goals_a"]
        goals_b = m["goals_b"]
        m_pitch = m["pitch"].lower()
        pitch_type = BOX if m_pitch == "box" else HF

        for mp in mps:
            pid = mp["player_id"]
            if pid not in player_events:
                player_events[pid] = {TOTAL: [], BOX: [], HF: []}
            team = mp["team"]
            is_win = (team == "a" and goals_a > goals_b) or (team == "b" and goals_b > goals_a)
            is_loss = (team == "a" and goals_a < goals_b) or (team == "b" and goals_b < goals_a)

            p_ratings_before = mr.get(pid, {})
            tot_b = p_ratings_before.get(TOTAL, {})
            pitch_b = p_ratings_before.get(pitch_type, {})
            event_entry = {
                "match_id": mid,
                "date": m["date"],
                "pitch": m_pitch,
                "is_win": is_win,
                "is_loss": is_loss,
                "rating_before_total": tot_b.get("rating"),
                "rd_before_total": tot_b.get("rd"),
                "rating_before_pitch": pitch_b.get("rating"),
                "rd_before_pitch": pitch_b.get("rd"),
            }
            player_events[pid][TOTAL].append(event_entry)
            if pitch_type in player_events[pid]:
                player_events[pid][pitch_type].append(event_entry)

    return player_events


def _compute_single_game_delta(
    evts: list[dict],
    pitch_const: str,
    curr_r: float,
    curr_rd: float,
    curr_c: float,
) -> dict:
    """Compute rating delta for the most recent match in the events list."""
    if not evts:
        return {
            "conservative": 0.0,
            "rating": 0.0,
            "rd": 0.0,
            "games": 0,
            "wins": 0,
            "losses": 0,
            "win_percent": 0.0,
        }

    last_evt = evts[-1]
    b_r = last_evt["rating_before_total"] if pitch_const == TOTAL else last_evt["rating_before_pitch"]
    b_rd = last_evt["rd_before_total"] if pitch_const == TOTAL else last_evt["rd_before_pitch"]
    if b_r is not None and b_rd is not None:
        b_c = b_r - 3 * b_rd
        game_delta_r = curr_r - b_r
        game_delta_rd = curr_rd - b_rd
        game_delta_c = curr_c - b_c
    else:
        game_delta_r = 0.0
        game_delta_rd = 0.0
        game_delta_c = 0.0

    is_win = bool(last_evt.get("is_win"))
    is_loss = bool(last_evt.get("is_loss"))
    return {
        "conservative": game_delta_c,
        "rating": game_delta_r,
        "rd": game_delta_rd,
        "games": 1,
        "wins": 1 if is_win else 0,
        "losses": 1 if is_loss else 0,
        "win_percent": 100.0 if is_win else 0.0,
    }


def _compute_period_delta(
    evts: list[dict],
    cutoff_str: str,
    pitch_const: str,
    curr_r: float,
    curr_rd: float,
    curr_c: float,
    baseline_r: float | None = None,
    baseline_rd: float | None = None,
) -> dict:
    """Compute aggregated rating and performance metrics since a cutoff date."""
    p_evts = [e for e in evts if e["date"] >= cutoff_str]
    g = len(p_evts)
    w = sum(1 for e in p_evts if e["is_win"])
    losses = sum(1 for e in p_evts if e["is_loss"])
    wp = (w / g * 100) if g > 0 else 0.0

    b_r: float | None = None
    b_rd: float | None = None

    if baseline_r is not None and baseline_rd is not None:
        b_r = baseline_r
        b_rd = baseline_rd
    elif p_evts:
        first_e = p_evts[0]
        b_r = first_e["rating_before_total"] if pitch_const == TOTAL else first_e["rating_before_pitch"]
        b_rd = first_e["rd_before_total"] if pitch_const == TOTAL else first_e["rd_before_pitch"]

    if b_r is not None and b_rd is not None:
        first_b_c = b_r - 3 * b_rd
        delta_r = curr_r - b_r
        delta_rd = curr_rd - b_rd
        delta_c = curr_c - first_b_c
    else:
        delta_r = 0.0
        delta_rd = 0.0
        delta_c = 0.0

    return {
        "conservative": delta_c,
        "rating": delta_r,
        "rd": delta_rd,
        "games": g,
        "wins": w,
        "losses": losses,
        "win_percent": wp,
    }


def compute_leaderboard_deltas(connection, ratings: dict, players: dict) -> dict[int, dict[str, dict]]:
    """Compute rating and performance deltas across game, month, quarter, and year intervals."""
    matches = get_matches(connection)
    sorted_matches = sorted(matches.values(), key=lambda m: (m["date"], m["match_id"]))

    today = datetime.now().date()
    cutoff_month = (today - timedelta(days=30)).strftime("%Y-%m-%d")
    cutoff_quarter = (today - timedelta(days=90)).strftime("%Y-%m-%d")
    cutoff_year = (today - timedelta(days=365)).strftime("%Y-%m-%d")

    all_mr = get_all_match_ratings(connection)
    post_m = [m for m in sorted_matches if m["date"] >= cutoff_month]
    base_mr_m = all_mr.get(post_m[0]["match_id"], {}) if post_m else None

    post_q = [m for m in sorted_matches if m["date"] >= cutoff_quarter]
    base_mr_q = all_mr.get(post_q[0]["match_id"], {}) if post_q else None

    post_y = [m for m in sorted_matches if m["date"] >= cutoff_year]
    base_mr_y = all_mr.get(post_y[0]["match_id"], {}) if post_y else None

    player_events = _collect_player_match_events(connection, sorted_matches, players)

    deltas: dict[int, dict[str, dict]] = {}
    for pid in players:
        deltas[pid] = {}
        for pitch_key, pitch_const in [("total", TOTAL), ("box", BOX), ("hf", HF)]:
            evts = player_events.get(pid, {}).get(pitch_const, [])
            p_rating_data = ratings.get(pid, {}).get(pitch_const, {})
            curr_r = p_rating_data.get("rating", 1500.0)
            curr_rd = p_rating_data.get("rd", 350.0)
            curr_c = curr_r - 3 * curr_rd

            base_p_m = base_mr_m.get(pid, {}).get(pitch_const) if base_mr_m else None
            base_p_q = base_mr_q.get(pid, {}).get(pitch_const) if base_mr_q else None
            base_p_y = base_mr_y.get(pid, {}).get(pitch_const) if base_mr_y else None

            deltas[pid][pitch_key] = {
                "game": _compute_single_game_delta(evts, pitch_const, curr_r, curr_rd, curr_c),
                "month": _compute_period_delta(
                    evts, cutoff_month, pitch_const, curr_r, curr_rd, curr_c,
                    baseline_r=base_p_m.get("rating") if base_p_m else None,
                    baseline_rd=base_p_m.get("rd") if base_p_m else None,
                ),
                "quarter": _compute_period_delta(
                    evts, cutoff_quarter, pitch_const, curr_r, curr_rd, curr_c,
                    baseline_r=base_p_q.get("rating") if base_p_q else None,
                    baseline_rd=base_p_q.get("rd") if base_p_q else None,
                ),
                "year": _compute_period_delta(
                    evts, cutoff_year, pitch_const, curr_r, curr_rd, curr_c,
                    baseline_r=base_p_y.get("rating") if base_p_y else None,
                    baseline_rd=base_p_y.get("rd") if base_p_y else None,
                ),
            }

    return deltas


def build_leaderboard(
    ratings: dict,
    players: dict,
    stats: dict,
    deltas: dict | None = None,
) -> list[dict]:
    deltas = deltas or {}
    default_deltas = {
        "game": {"conservative": 0.0, "rating": 0.0, "rd": 0.0, "games": 0, "wins": 0, "losses": 0, "win_percent": 0.0},
        "month": {"conservative": 0.0, "rating": 0.0, "rd": 0.0, "games": 0, "wins": 0, "losses": 0, "win_percent": 0.0},
        "quarter": {"conservative": 0.0, "rating": 0.0, "rd": 0.0, "games": 0, "wins": 0, "losses": 0, "win_percent": 0.0},
        "year": {"conservative": 0.0, "rating": 0.0, "rd": 0.0, "games": 0, "wins": 0, "losses": 0, "win_percent": 0.0},
    }
    leaderboard = []
    for player_id, rating in ratings.items():
        player_stats = stats.get(player_id, {})
        p_deltas = deltas.get(player_id, {})
        leaderboard.append({
            "player_id": player_id,
            "alias": players[player_id]["aliases"][0],
            "total": {
                "rating": rating["total"]["rating"],
                "rd": rating["total"]["rd"],
                "conservative": rating["total"]["rating"] - 3 * rating["total"]["rd"],
                **player_stats.get("total", {}),
                "deltas": p_deltas.get("total", default_deltas),
            },
            "box": {
                "rating": rating["box"]["rating"],
                "rd": rating["box"]["rd"],
                "conservative": rating["box"]["rating"] - 3 * rating["box"]["rd"],
                **player_stats.get("box", {}),
                "deltas": p_deltas.get("box", default_deltas),
            },
            "hf": {
                "rating": rating["hf"]["rating"],
                "rd": rating["hf"]["rd"],
                "conservative": rating["hf"]["rating"] - 3 * rating["hf"]["rd"],
                **player_stats.get("hf", {}),
                "deltas": p_deltas.get("hf", default_deltas),
            },
        })
    leaderboard.sort(key=lambda player: player["total"]["conservative"], reverse=True)
    return leaderboard


def calculate_match_details(
    match: dict,
    team_a: list[int],
    team_b: list[int],
    match_ratings: dict,
    rating_type: str = TOTAL,
    player_id: int | None = None,
) -> dict:
    empty_details = {
        "team_a_rating": None,
        "team_a_rd": None,
        "team_b_rating": None,
        "team_b_rd": None,
        "team_a_expected": None,
        "team_b_expected": None,
        "rating_delta": None,
        "delta_a": None,
        "delta_b": None,
        "player_delta": None,
        "player_team": None,
    }
    if not team_a or not team_b or not match_ratings:
        return empty_details

    required_players = team_a + team_b
    if any(
        pid not in match_ratings or rating_type not in match_ratings[pid]
        for pid in required_players
    ):
        return empty_details

    total_players_a = match["players_a"]
    total_players_b = match["players_b"]

    def team_rating(player_ids, total_players):
        active_ratings = [match_ratings[pid][rating_type] for pid in player_ids]
        average_rating = sum(rating["rating"] for rating in active_ratings) / len(active_ratings)
        ignored_players = total_players - len(player_ids)
        average_rd = math.sqrt(
            (sum(rating["rd"] ** 2 for rating in active_ratings) + IGNORED_RD ** 2 * ignored_players)
            / total_players
        )
        average_sigma = math.sqrt(
            (sum(rating["sigma"] ** 2 for rating in active_ratings) + DEFAULT_SIGMA ** 2 * ignored_players)
            / total_players
        )
        return Rating(average_rating, average_rd, average_sigma)

    def teammates_rd(player_id, player_ids, total_players):
        other_ids = [pid for pid in player_ids if pid != player_id]
        num_teammates = total_players - 1
        if num_teammates <= 0:
            return None
        ignored_players = num_teammates - len(other_ids)
        active_ratings = [match_ratings[pid][rating_type] for pid in other_ids]
        return math.sqrt(
            (sum(rating["rd"] ** 2 for rating in active_ratings) + IGNORED_RD ** 2 * ignored_players)
            / num_teammates
        )

    team_a_rating = team_rating(team_a, total_players_a)
    team_b_rating = team_rating(team_b, total_players_b)
    team_a_expected = expected_score(team_a_rating.rating, team_b_rating.rating, team_b_rating.rd)
    team_b_expected = expected_score(team_b_rating.rating, team_a_rating.rating, team_a_rating.rd)

    if match["goals_a"] > match["goals_b"]:
        team_a_result, team_b_result = 1.0, 0.0
    elif match["goals_a"] < match["goals_b"]:
        team_a_result, team_b_result = 0.0, 1.0
    else:
        team_a_result = team_b_result = 0.5

    engine = Glicko2()
    updated_team_a = engine.update_rating(team_a_rating, [(team_a_result, team_b_rating)])
    updated_team_b = engine.update_rating(team_b_rating, [(team_b_result, team_a_rating)])
    delta_a = updated_team_a.rating - team_a_rating.rating
    delta_b = updated_team_b.rating - team_b_rating.rating

    player_delta = None
    player_team = None
    if player_id is not None and player_id in match_ratings and rating_type in match_ratings[player_id]:
        pdata = match_ratings[player_id][rating_type]
        prd = pdata["rd"]
        psigma = pdata["sigma"]
        if player_id in team_a:
            player_team = "a"
            virtual_player = Rating(team_a_rating.rating, prd, psigma)
            updated_virtual = engine.update_rating(virtual_player, [(team_a_result, team_b_rating)])
            tm_weight = engine.teammate_impact(teammates_rd(player_id, team_a, total_players_a))
            player_delta = tm_weight * (updated_virtual.rating - virtual_player.rating)
            delta_a = player_delta
        elif player_id in team_b:
            player_team = "b"
            virtual_player = Rating(team_b_rating.rating, prd, psigma)
            updated_virtual = engine.update_rating(virtual_player, [(team_b_result, team_a_rating)])
            tm_weight = engine.teammate_impact(teammates_rd(player_id, team_b, total_players_b))
            player_delta = tm_weight * (updated_virtual.rating - virtual_player.rating)
            delta_b = player_delta

    return {
        "team_a_rating": team_a_rating.rating,
        "team_a_rd": team_a_rating.rd,
        "team_b_rating": team_b_rating.rating,
        "team_b_rd": team_b_rating.rd,
        "team_a_expected": team_a_expected,
        "team_b_expected": team_b_expected,
        "rating_delta": delta_a,
        "delta_a": delta_a,
        "delta_b": delta_b,
        "player_delta": player_delta,
        "player_team": player_team,
        "tm_rd_a": teammates_rd(player_id, team_a, total_players_a) if (player_id and player_id in team_a) else None,
        "tm_rd_b": teammates_rd(player_id, team_b, total_players_b) if (player_id and player_id in team_b) else None,
        "team_a_result": team_a_result,
        "team_b_result": team_b_result,
    }


def build_match_history(
    connection,
    players: dict,
    player_id: int | None = None,
    rating_type: str = TOTAL,
) -> list[dict]:
    if request and "rating_type" in request.args:
        requested = request.args.get("rating_type", "").lower()
        rating_type = {"total": TOTAL, "box": BOX, "hf": HF}.get(requested, rating_type)
    matches = get_matches(connection)
    all_teams = get_all_match_teams(connection) if connection is not None else {}
    all_ratings = get_all_match_ratings(connection) if connection is not None else {}
    history = []

    for match_id, match in matches.items():
        if rating_type == BOX and match["pitch"].lower() != "box":
            continue
        if rating_type == HF and match["pitch"].lower() != "hf":
            continue

        if match_id in all_teams:
            team_a, team_b = all_teams[match_id]
        else:
            team_a, team_b = get_match_teams(connection, match_id)

        if player_id is not None and player_id not in team_a and player_id not in team_b:
            continue

        external_a = match["players_a"] - len(team_a)
        external_b = match["players_b"] - len(team_b)
        match_ratings = all_ratings.get(match_id) if match_id in all_ratings else get_match_ratings(connection, match_id)
        details = calculate_match_details(match, team_a, team_b, match_ratings, rating_type, player_id=player_id)

        def player_entry(pid):
            rating = match_ratings.get(pid, {}).get(rating_type, {}).get("rating")
            return {"name": players[pid]["aliases"][0], "rating": rating, "player_id": pid}

        team_a_players = [player_entry(pid) for pid in team_a]
        team_b_players = [player_entry(pid) for pid in team_b]
        for team in (team_a_players, team_b_players):
            team.sort(
                key=lambda p: (p["rating"] is not None, p["rating"] if p["rating"] is not None else 0),
                reverse=True,
            )

        p_team = details.get("player_team")
        own_ids = []
        opp_ids = []
        is_win = False
        is_loss = False
        is_draw = match["goals_a"] == match["goals_b"]
        goals_for = None
        goals_against = None

        if p_team == "a":
            own_ids = [pid for pid in team_a if pid != player_id]
            opp_ids = list(team_b)
            is_win = match["goals_a"] > match["goals_b"]
            is_loss = match["goals_a"] < match["goals_b"]
            goals_for = match["goals_a"]
            goals_against = match["goals_b"]
        elif p_team == "b":
            own_ids = [pid for pid in team_b if pid != player_id]
            opp_ids = list(team_a)
            is_win = match["goals_b"] > match["goals_a"]
            is_loss = match["goals_b"] < match["goals_a"]
            goals_for = match["goals_b"]
            goals_against = match["goals_a"]

        history.append({
            "match_id": match_id,
            "date": match["date"],
            "pitch": match["pitch"],
            "goals_a": match["goals_a"],
            "goals_b": match["goals_b"],
            "team_a": [players[pid]["aliases"][0] for pid in team_a],
            "team_b": [players[pid]["aliases"][0] for pid in team_b],
            "team_a_players": team_a_players,
            "team_b_players": team_b_players,
            "external_a": external_a,
            "external_b": external_b,
            "team_a_ids": team_a,
            "team_b_ids": team_b,
            "own_team_ids": own_ids,
            "opp_team_ids": opp_ids,
            "is_win": is_win,
            "is_loss": is_loss,
            "is_draw": is_draw,
            "goals_for": goals_for,
            "goals_against": goals_against,
            "individual_player_delta": details.get("player_delta"),
            **details,
        })

    # Group history by date to handle session batch indicators and net deltas
    date_groups = {}
    for entry in history:
        date_groups.setdefault(entry["date"], []).append(entry)

    engine = Glicko2()

    for date, entries in date_groups.items():
        total_on_date = len(entries)
        if total_on_date == 1:
            entries[0]["is_session_pending"] = False
            entries[0]["is_session_final"] = False
            entries[0]["session_match_num"] = 1
            entries[0]["session_matches_total"] = 1
            entries[0]["session_tooltip"] = None
        else:
            for idx, entry in enumerate(entries):
                match_num = idx + 1
                entry["session_match_num"] = match_num
                entry["session_matches_total"] = total_on_date
                if idx < total_on_date - 1:
                    entry["is_session_pending"] = True
                    entry["is_session_final"] = False
                    entry["session_tooltip"] = (
                        f"Game {match_num} of {total_on_date}: Rating is updated after the second game of the day."
                        if total_on_date == 2 else
                        f"Game {match_num} of {total_on_date}: Rating is updated after the final game of the day."
                    )
                else:
                    entry["is_session_pending"] = False
                    entry["is_session_final"] = True
                    entry["session_tooltip"] = (
                        f"Session result ({total_on_date} games): Net rating change for {date}."
                    )

            # For personal profile view with multiple games on this date,
            # calculate the true net session delta for the player
            if player_id is not None:
                first_match_ratings = get_match_ratings(connection, entries[0]["match_id"])
                if player_id in first_match_ratings and rating_type in first_match_ratings[player_id]:
                    pdata = first_match_ratings[player_id][rating_type]
                    prior = Rating(pdata["rating"], pdata["rd"], pdata["sigma"])
                    session_games = []
                    for entry in entries:
                        if player_id in entry["team_a_ids"]:
                            own_team = Rating(entry["team_a_rating"], entry["team_a_rd"], DEFAULT_SIGMA)
                            opp_team = Rating(entry["team_b_rating"], entry["team_b_rd"], DEFAULT_SIGMA)
                            raw_size = entry.get("team_a_players", len(entry["team_a_ids"]))
                            team_size = len(raw_size) if isinstance(raw_size, (list, tuple)) else int(raw_size)
                            session_games.append((own_team, opp_team, entry["team_a_result"], entry["tm_rd_a"], team_size))
                        elif player_id in entry["team_b_ids"]:
                            own_team = Rating(entry["team_b_rating"], entry["team_b_rd"], DEFAULT_SIGMA)
                            opp_team = Rating(entry["team_a_rating"], entry["team_a_rd"], DEFAULT_SIGMA)
                            raw_size = entry.get("team_b_players", len(entry["team_b_ids"]))
                            team_size = len(raw_size) if isinstance(raw_size, (list, tuple)) else int(raw_size)
                            session_games.append((own_team, opp_team, entry["team_b_result"], entry["tm_rd_b"], team_size))

                    if session_games:
                        updated_player = engine.update_player_session(prior, session_games)
                        net_session_delta = updated_player.rating - prior.rating
                        final_entry = entries[-1]
                        if player_id in final_entry["team_a_ids"]:
                            final_entry["delta_a"] = net_session_delta
                            final_entry["player_delta"] = net_session_delta
                            final_entry["rating_delta"] = net_session_delta
                        elif player_id in final_entry["team_b_ids"]:
                            final_entry["delta_b"] = net_session_delta
                            final_entry["player_delta"] = net_session_delta
                            final_entry["rating_delta"] = net_session_delta

    return history
