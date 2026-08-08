# this will calculate Glicko rating for each player (using matchhistory.csv and players.csv) and update the ratings.csv
from glicko2 import Glicko2, Rating, WIN, LOSS, DRAW, DEFAULT_RATING, DEFAULT_RD, DEFAULT_SIGMA
from pathlib import Path
from collections import defaultdict
import math
import csv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MATCHHISTORY_FILE = PROJECT_ROOT / "data" / "matchhistory.csv"
PLAYERS_FILE = PROJECT_ROOT / "data" / "players.csv"
RATINGS_FILE = PROJECT_ROOT / "data" / "ratings.csv"    

def load_matchhistory():
    matchhistory = []
    if MATCHHISTORY_FILE.exists():
        with open(MATCHHISTORY_FILE, "r", newline="", encoding="utf-8") as h_file:
            reader = csv.reader(h_file)
            for row in reader:
                if not row:
                    continue
                if row[0].startswith("#"):
                    continue  # Skip comment lines
                if row[0] == "match_id":
                    continue  # Skip header row

                matchhistory.append(row)
    matchhistory.sort(key=lambda x: x[0])
    return matchhistory

def load_players():
    players = {}
    if PLAYERS_FILE.exists():
        with open(PLAYERS_FILE, "r", newline="", encoding="utf-8") as p_file:
            reader = csv.DictReader(p_file)
            for row in reader:
                if not row:
                    continue
                player_id = int(row["player_id"])
                aliases = row["aliases"].split(";")
                positions = row["positions"].split(";")
                players[player_id] = {
                    "aliases": aliases,
                    "positions": positions
                }
    return players

def create_alias_lookup(players):
    alias_lookup = {}
    for player_id, data in players.items():
        for alias in data["aliases"]:
            alias_lookup[alias] = player_id
    return alias_lookup

def load_glicko_table():
    glicko_table = {}
    if RATINGS_FILE.exists():
        with open(RATINGS_FILE, "r", newline="", encoding="utf-8") as r_file:
            reader = csv.DictReader(r_file)
            for row in reader:
                if not row:
                    continue
                player_id = int(row["player_id"])
                rating = float(row["rating"])
                rd = float(row["rd"])
                sigma = float(row["sigma"])
                glicko_table[player_id] = {
                    "rating": rating,
                    "rd": rd,
                    "sigma": sigma
                }
    return glicko_table

def prepare_glicko_table(matchhistory, alias_lookup, glicko_table):

    prepared_glicko = {}

    for match in matchhistory:

        team_ids = (
            get_team_ids(match[2], alias_lookup)
            +
            get_team_ids(match[3], alias_lookup)
        )

        for player_id in team_ids:

            if player_id not in prepared_glicko:

                prepared_glicko[player_id] = glicko_table.get(
                    player_id,
                    {
                        "rating": DEFAULT_RATING,
                        "rd": DEFAULT_RD,
                        "sigma": DEFAULT_SIGMA
                    }
                )

    return prepared_glicko

def get_team_ids(team_string, alias_lookup):

    aliases = team_string.split(",")

    player_ids = []

    for alias in aliases:

        alias = alias.strip()

        player_id = alias_lookup.get(alias)

        if player_id is not None:
            player_ids.append(player_id)

    return player_ids

def calculate_team_rating(player_ids, ratings):

    if not player_ids:
        return None

    average_rating = sum(
        ratings[player].rating
        for player in player_ids
    ) / len(player_ids)

    average_rd = math.sqrt(
        sum(
            ratings[player].rd ** 2
            for player in player_ids
        ) / len(player_ids)
    )
    average_sigma = math.sqrt(
        sum(
            ratings[player].sigma ** 2
            for player in player_ids
        ) / len(player_ids)
    )

    return Rating(average_rating, average_rd, average_sigma)

def get_match_result(match):

    team1_goals = int(match[4])
    team2_goals = int(match[5])

    if team1_goals > team2_goals:
        return WIN, LOSS

    elif team1_goals < team2_goals:
        return LOSS, WIN

    else:
        return DRAW, DRAW
  


            
def convert_to_rating_objects(glicko_table):

    ratings = {}

    for player_id, data in glicko_table.items():

        ratings[player_id] = Rating(
            data["rating"],
            data["rd"],
            data["sigma"]
        )

    return ratings

def convert_back(ratings):

    glicko_table = {}

    for player_id, rating in ratings.items():

        glicko_table[player_id] = {
            "rating": rating.rating,
            "rd": rating.rd,
            "sigma": rating.sigma
        }

    return glicko_table

def create_virtual_rating(player_id, team_rating, ratings):

    player = ratings[player_id]

    return Rating(
        team_rating.rating,
        player.rd,
        player.sigma
    )

def calculate_glicko(
    matchhistory,
    alias_lookup,
    prepared_glicko
):

    engine = Glicko2()

    ratings = convert_to_rating_objects(
        prepared_glicko
    )

    for match in matchhistory:

        update_match(
            match,
            alias_lookup,
            ratings,
            engine
        )

    return convert_back(ratings)

def update_match(match, alias_lookup, ratings, engine, debug_player=10):

    team1_ids = get_team_ids(
        match[2],
        alias_lookup
    )

    team2_ids = get_team_ids(
        match[3],
        alias_lookup
    )

    active_players = set(team1_ids + team2_ids)

    if not team1_ids or not team2_ids:
        return

    team1_rating = calculate_team_rating(
        team1_ids,
        ratings
    )

    team2_rating = calculate_team_rating(
        team2_ids,
        ratings
    )

    team1_result, team2_result = get_match_result(match)

    # temporary old behaviour:
    # update each player against opposing team average

    for player_id in team1_ids:

        old_rating = ratings[player_id].rating
        old_rd = ratings[player_id].rd
        old_sigma = ratings[player_id].sigma
        
        virtual_player = create_virtual_rating(
            player_id,
            team1_rating,
            ratings
        )

        updated_virtual = engine.update_rating(
            virtual_player,
            [
                (
                    team1_result,
                    team2_rating
                )
            ]
        )

        rating_change = (
            updated_virtual.rating 
            - virtual_player.rating
        )

        ratings[player_id].rating += rating_change
        ratings[player_id].rd = updated_virtual.rd
        ratings[player_id].sigma = updated_virtual.sigma

        if player_id == debug_player:
            print("\nDEBUG PLAYER")
            print("Match:", match[0])
            print("Team:", "Team 1")
            print("Result:", team1_result)
            print("Personal rating before:", old_rating)
            print("Personal RD before:", old_rd)
            print("Personal Sigma before:", old_sigma)
            print("Team average:", team1_rating.rating)
            print("Opponent team average:", team2_rating.rating)
            print("Virtual rating before:", virtual_player.rating)
            print("Virtual RD before:", virtual_player.rd)
            print("Virtual Sigma before:", virtual_player.sigma)
            print("Virtual rating after:", updated_virtual.rating)
            print("Virtual RD after:", updated_virtual.rd)
            print("Virtual Sigma after:", updated_virtual.sigma)
            print("Rating delta:", rating_change)
            print("Personal rating after:", ratings[player_id].rating)
            print("Personal RD after:", ratings[player_id].rd)
            print("Personal Sigma after:", ratings[player_id].sigma)



    for player_id in team2_ids:

        old_rating = ratings[player_id].rating
        old_rd = ratings[player_id].rd
        old_sigma = ratings[player_id].sigma

        virtual_player = create_virtual_rating(
            player_id,
            team2_rating,
            ratings
        )

        updated_virtual = engine.update_rating(
            virtual_player,
            [
                (
                    team2_result,
                    team1_rating
                )
            ]
        )

        rating_change = (
            updated_virtual.rating 
            - virtual_player.rating
        )

        ratings[player_id].rating += rating_change
        ratings[player_id].rd = updated_virtual.rd
        ratings[player_id].sigma = updated_virtual.sigma


        if player_id == debug_player:
            print("\nDEBUG PLAYER")
            print("Match:", match[0])
            print("Team:", "Team 2")
            print("Result:", team2_result)
            print("Personal rating before:", old_rating)
            print("Personal RD before:", old_rd)
            print("Personal Sigma before:", old_sigma)
            print("Team average:", team2_rating.rating)
            print("Opponent team average:", team1_rating.rating)
            print("Virtual rating before:", virtual_player.rating)
            print("Virtual RD before:", virtual_player.rd)
            print("Virtual Sigma before:", virtual_player.sigma)
            print("Virtual rating after:", updated_virtual.rating)
            print("Virtual RD after:", updated_virtual.rd)
            print("Virtual Sigma after:", updated_virtual.sigma)
            print("Rating delta:", rating_change)
            print("Personal rating after:", ratings[player_id].rating)
            print("Personal RD after:", ratings[player_id].rd)
            print("Personal Sigma after:", ratings[player_id].sigma)

    for player_id in ratings:

        if player_id not in active_players:
            ratings[player_id].rd = min(
        ratings[player_id].rd + 0.6180339,
        161.80339,
    )

def write_glicko(glickos):
    with open(RATINGS_FILE, "w", newline="", encoding="utf-8") as r_file:
        fieldnames = ["player_id", "rating", "rd", "sigma"]
        writer = csv.DictWriter(r_file, fieldnames=fieldnames)
        writer.writeheader()
        for player_id, data in glickos.items():
            writer.writerow({
                "player_id": player_id,
                "rating": data["rating"],
                "rd": data["rd"],
                "sigma": data["sigma"]
            })


def main():

    matchhistory = load_matchhistory()
    print(f"Loaded {len(matchhistory)} matches")

    players = load_players()
    print(f"Loaded {len(players)} players")

    alias_lookup = create_alias_lookup(players)

    old_ratings = load_glicko_table()
    print(f"Loaded {len(old_ratings)} ratings")

    prepared_glicko = prepare_glicko_table(
        matchhistory,
        alias_lookup,
        old_ratings
    )

    print(
        f"Prepared ratings for {len(prepared_glicko)} players"
    )


    glickos = calculate_glicko(
        matchhistory,
        alias_lookup,
        prepared_glicko
    )


    print(
        f"Calculated ratings for {len(glickos)} players"
    )


    write_glicko(glickos)

    print("Finished")


if __name__ == "__main__":
    main()