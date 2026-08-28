import math

from scripts.database.db_matches import get_matches, get_match_teams
from scripts.database.db_ratings import get_match_ratings
from scripts.glicko.glicko2 import Glicko2, Rating, TOTAL, BOX, HF, IGNORED_RD, DEFAULT_SIGMA, expected_score


def build_leaderboard(ratings, players, stats):
    leaderboard = []
    for player_id, rating in ratings.items():
        player_stats = stats.get(player_id, {})
        leaderboard.append({
            "player_id": player_id,
            "alias": players[player_id]["aliases"][0],
            "total": {"rating": rating["total"]["rating"], "rd": rating["total"]["rd"], "conservative": rating["total"]["rating"] - 3 * rating["total"]["rd"], **player_stats.get("total", {})},
            "box": {"rating": rating["box"]["rating"], "rd": rating["box"]["rd"], "conservative": rating["box"]["rating"] - 3 * rating["box"]["rd"], **player_stats.get("box", {})},
            "hf": {"rating": rating["hf"]["rating"], "rd": rating["hf"]["rd"], "conservative": rating["hf"]["rating"] - 3 * rating["hf"]["rd"], **player_stats.get("hf", {})},
        })
    leaderboard.sort(key=lambda player: player["total"]["conservative"], reverse=True)
    return leaderboard


def calculate_match_details(match, team_a, team_b, match_ratings, rating_type=TOTAL):
    if not team_a or not team_b or not match_ratings:
        return {"team_a_rating": None, "team_a_rd": None, "team_b_rating": None, "team_b_rd": None, "team_a_expected": None, "team_b_expected": None, "rating_delta": None}

    required_players = team_a + team_b
    if any(player_id not in match_ratings or rating_type not in match_ratings[player_id] for player_id in required_players):
        return {"team_a_rating": None, "team_a_rd": None, "team_b_rating": None, "team_b_rd": None, "team_a_expected": None, "team_b_expected": None, "rating_delta": None}

    total_players_a = match["players_a"]
    total_players_b = match["players_b"]

    def team_rating(player_ids, total_players):
        active_ratings = [match_ratings[player_id][rating_type] for player_id in player_ids]
        average_rating = sum(rating["rating"] for rating in active_ratings) / len(active_ratings)
        ignored_players = total_players - len(player_ids)
        average_rd = math.sqrt((sum(rating["rd"] ** 2 for rating in active_ratings) + IGNORED_RD ** 2 * ignored_players) / total_players)
        average_sigma = math.sqrt((sum(rating["sigma"] ** 2 for rating in active_ratings) + DEFAULT_SIGMA ** 2 * ignored_players) / total_players)
        return Rating(average_rating, average_rd, average_sigma)

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
    rating_delta_a = updated_team_a.rating - team_a_rating.rating
    return {"team_a_rating": team_a_rating.rating, "team_a_rd": team_a_rating.rd, "team_b_rating": team_b_rating.rating, "team_b_rd": team_b_rating.rd, "team_a_expected": team_a_expected, "team_b_expected": team_b_expected, "rating_delta": rating_delta_a}


def build_match_history(connection, players, player_id=None, rating_type=TOTAL):
    matches = get_matches(connection)
    history = []
    for match_id, match in matches.items():
        team_a, team_b = get_match_teams(connection, match_id)
        if player_id is not None and player_id not in team_a and player_id not in team_b:
            continue

        external_a = match["players_a"] - len(team_a)
        external_b = match["players_b"] - len(team_b)
        match_ratings = get_match_ratings(connection, match_id)
        details = calculate_match_details(match, team_a, team_b, match_ratings, rating_type)

        def player_entry(pid):
            rating = None
            if pid in match_ratings and rating_type in match_ratings[pid]:
                rating = match_ratings[pid][rating_type]["rating"]
            return {"name": players[pid]["aliases"][0], "rating": rating}

        team_a_players = [player_entry(pid) for pid in team_a]
        team_b_players = [player_entry(pid) for pid in team_b]
        for team in (team_a_players, team_b_players):
            team.sort(key=lambda player: (player["rating"] is not None, player["rating"] if player["rating"] is not None else 0), reverse=True)

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
            **details,
        })
    return history
