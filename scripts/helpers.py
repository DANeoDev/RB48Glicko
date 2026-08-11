from glicko2 import LOSS, WIN, DRAW
from datetime import date
from loaders import load_matchhistory

#helper functions for processing match data; likely to be used in multiple scripts

def get_match_result(match):

    team1_goals = int(match[4])
    team2_goals = int(match[5])

    if team1_goals > team2_goals:
        return WIN, LOSS

    elif team1_goals < team2_goals:
        return LOSS, WIN

    else:
        return DRAW, DRAW


def get_player_ids_from_team(team_string, alias_lookup):

    aliases = team_string.split(",")

    player_ids = []

    for alias in aliases:

        alias = alias.strip()

        player_id = alias_lookup.get(alias)

        if player_id is not None:
            player_ids.append(player_id)

    return player_ids


def total_player_count(team_string):

    aliases = team_string.split(",")

    total_players=len(aliases)

    return total_players


def get_match_dates():
    dates = []

    matchhistory = load_matchhistory()

    for row in matchhistory:
        match_id = row[0]
        date_string = match_id.rsplit("-", 1)[0]
        dates.append(date.fromisoformat(date_string))

    return dates