from scripts.db_matches import get_matches, get_match_teams


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
                "conservative": (
                    rating["total"]["rating"]
                    - 3 * rating["total"]["rd"]
                ),
                **player_stats.get("total", {}),
            },

            "box": {
                "rating": rating["box"]["rating"],
                "rd": rating["box"]["rd"],
                "conservative": (
                    rating["box"]["rating"]
                    - 3 * rating["box"]["rd"]
                ),
                **player_stats.get("box", {}),
            },

            "hf": {
                "rating": rating["hf"]["rating"],
                "rd": rating["hf"]["rd"],
                "conservative": (
                    rating["hf"]["rating"]
                    - 3 * rating["hf"]["rd"]
                ),
                **player_stats.get("hf", {}),
            },
        })

    leaderboard.sort(
        key=lambda player: player["total"]["conservative"],
        reverse=True
    )

    return leaderboard


def build_match_history(connection, players, player_id=None):

    matches = get_matches(connection)

    history = []

    for match_id, match in matches.items():

        team_a, team_b = get_match_teams(
            connection,
            match_id
        )

        if player_id is not None:
            if player_id not in team_a and player_id not in team_b:
                continue

        external_a = match["players_a"] - len(team_a)
        external_b = match["players_b"] - len(team_b)

        history.append({
            "match_id": match_id,
            "date": match["date"],
            "pitch": match["pitch"],
            "goals_a": match["goals_a"],
            "goals_b": match["goals_b"],

            "team_a": [
                players[player_id]["aliases"][0]
                for player_id in team_a
            ],

            "team_b": [
                players[player_id]["aliases"][0]
                for player_id in team_b
            ],

            "external_a": external_a,
            "external_b": external_b,

            "team_a_ids": team_a,
            "team_b_ids": team_b,
        })

    history.sort(
        key=lambda match: match["date"],
        reverse=True
    )

    return history