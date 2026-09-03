import math
try:
    from flask import request
except ImportError:
    request = None

from scripts.database.db_matches import get_matches, get_match_teams
from scripts.database.db_ratings import get_match_ratings
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


def build_leaderboard(ratings, players, stats):
    leaderboard = []
    for player_id, rating in ratings.items():
        player_stats = stats.get(player_id, {})
        leaderboard.append({
            "player_id": player_id,
            "alias": players[player_id]["aliases"][0],
            "total": {
                "rating": rating["total"]["rating"],
                "rd": rating["total"]["rd"],
                "conservative": rating["total"]["rating"] - 3 * rating["total"]["rd"],
                **player_stats.get("total", {}),
            },
            "box": {
                "rating": rating["box"]["rating"],
                "rd": rating["box"]["rd"],
                "conservative": rating["box"]["rating"] - 3 * rating["box"]["rd"],
                **player_stats.get("box", {}),
            },
            "hf": {
                "rating": rating["hf"]["rating"],
                "rd": rating["hf"]["rd"],
                "conservative": rating["hf"]["rating"] - 3 * rating["hf"]["rd"],
                **player_stats.get("hf", {}),
            },
        })
    leaderboard.sort(key=lambda player: player["total"]["conservative"], reverse=True)
    return leaderboard


def calculate_match_details(match, team_a, team_b, match_ratings, rating_type=TOTAL, player_id=None):
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


def build_match_history(connection, players, player_id=None, rating_type=TOTAL):
    requested = request.args.get("rating_type", "total").lower() if request else "total"
    rating_type = {"total": TOTAL, "box": BOX, "hf": HF}.get(requested, rating_type)
    matches = get_matches(connection)
    history = []

    for match_id, match in matches.items():
        if rating_type == BOX and match["pitch"].lower() != "box":
            continue
        if rating_type == HF and match["pitch"].lower() != "hf":
            continue

        team_a, team_b = get_match_teams(connection, match_id)
        if player_id is not None and player_id not in team_a and player_id not in team_b:
            continue

        external_a = match["players_a"] - len(team_a)
        external_b = match["players_b"] - len(team_b)
        match_ratings = get_match_ratings(connection, match_id)
        details = calculate_match_details(match, team_a, team_b, match_ratings, rating_type, player_id=player_id)

        def player_entry(pid):
            rating = match_ratings.get(pid, {}).get(rating_type, {}).get("rating")
            return {"name": players[pid]["aliases"][0], "rating": rating}

        team_a_players = [player_entry(pid) for pid in team_a]
        team_b_players = [player_entry(pid) for pid in team_b]
        for team in (team_a_players, team_b_players):
            team.sort(
                key=lambda p: (p["rating"] is not None, p["rating"] if p["rating"] is not None else 0),
                reverse=True,
            )

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
                            session_games.append((own_team, opp_team, entry["team_a_result"], entry["tm_rd_a"]))
                        elif player_id in entry["team_b_ids"]:
                            own_team = Rating(entry["team_b_rating"], entry["team_b_rd"], DEFAULT_SIGMA)
                            opp_team = Rating(entry["team_a_rating"], entry["team_a_rd"], DEFAULT_SIGMA)
                            session_games.append((own_team, opp_team, entry["team_b_result"], entry["tm_rd_b"]))

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
