# this will calculate Glicko rating for each player (using matchhistory.csv and players.csv) and update the ratings.csv
from glicko2 import Glicko2, Rating, DEFAULT_RATING, DEFAULT_RD, IGNORED_RD, DEFAULT_SIGMA
from pathlib import Path
from collections import defaultdict
from loaders import (
    load_matchhistory,
    load_players,
    create_alias_lookup,
    get_ignored_aliases,
    load_calibration_table
)
from helpers import (
    get_match_result,
    get_player_ids_from_team,
    total_player_count,
    get_match_dates
)

import math
import csv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RATINGS_FOLDER = PROJECT_ROOT / "data" / "ratings"
MATCHHISTORY_FILE = PROJECT_ROOT / "data" / "matchhistory.csv"
PLAYERS_FILE = PROJECT_ROOT / "data" / "players.csv"
CALIBRATION_FILE = PROJECT_ROOT / "data" / "calibrations.csv"    


def prepare_glicko_table(matchhistory, alias_lookup, calibration_ratings):  # prepare a glicko table for all players in matchhistory.csv, using calibration ratings if available

    prepared_glicko = {}

    for match in matchhistory:

        team_ids = (
            get_player_ids_from_team(match[2], alias_lookup)
            +
            get_player_ids_from_team(match[3], alias_lookup)
        )

        for player_id in team_ids:

            if player_id not in prepared_glicko:

                prepared_glicko[player_id] = calibration_ratings.get(
                    player_id,
                    {
                        "rating": DEFAULT_RATING,
                        "rd": DEFAULT_RD,
                        "sigma": DEFAULT_SIGMA
                    }
                )

    return prepared_glicko

def glicko_table_to_ratings(glicko_table): # Convert Glicko table to rating objects

    ratings = {}

    for player_id, data in glicko_table.items():

        ratings[player_id] = Rating(
            data["rating"],
            data["rd"],
            data["sigma"]
        )

    return ratings


def ratings_to_glicko_table(ratings): # Convert rating objects back to Glicko table

    glicko_table = {}

    for player_id, rating in ratings.items():

        glicko_table[player_id] = {
            "rating": rating.rating,
            "rd": rating.rd,
            "sigma": rating.sigma
        }

    return glicko_table 

def calculate_team_rating(player_ids, total_players, ratings):

    if not player_ids:
        return None

    ignored_players = total_players - len(player_ids)

  
    average_rating = sum(
        ratings[player].rating
        for player in player_ids
    ) / len(player_ids)

    average_rd = math.sqrt(
        (
        sum(
            ratings[player].rd ** 2
            for player in player_ids
        )
            + IGNORED_RD**2 * (ignored_players)
        ) / total_players
    )
    
    average_sigma = math.sqrt(
        (
        sum(
            ratings[player].sigma ** 2
            for player in player_ids
        )
            + DEFAULT_SIGMA**2 * (ignored_players)
        ) / total_players
    )

    return Rating(average_rating, average_rd, average_sigma)

            

def create_virtual_rating(player_id, team_rating, ratings):

    player = ratings[player_id]
    virtual_RD = math.sqrt((player.rd**2 + team_rating.rd**2)/2) # weighted average of the players RD and the team RD

    return Rating(
        team_rating.rating,
        virtual_RD,
        player.sigma
    )

def calculate_glicko(
    matchhistory,
    alias_lookup,
    prepared_glicko
):

    engine = Glicko2()

    ratings = glicko_table_to_ratings(
        prepared_glicko
    )

    for match in matchhistory:

        update_match(
            match,
            alias_lookup,
            ratings,
            engine
        )

    return ratings_to_glicko_table(ratings)

def update_match(match, alias_lookup, ratings, engine, debug_player=29):

    team1_ids = get_player_ids_from_team(
        match[2],
        alias_lookup
    )

    team2_ids = get_player_ids_from_team(
        match[3],
        alias_lookup
    )

    team1_total_players = total_player_count(match[2])
    team2_total_players = total_player_count(match[3])

    active_players = set(team1_ids + team2_ids)

    if not team1_ids or not team2_ids:
        return

    team1_rating = calculate_team_rating(
        team1_ids,
        team1_total_players,
        ratings
    )

    team2_rating = calculate_team_rating(
        team2_ids,
        team2_total_players,
        ratings
    )

    team1_result, team2_result = get_match_result(match)

    
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
            print("Opponent team RD:", team2_rating.rd)
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
            print("Opponent team RD:", team1_rating.rd)
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

        if player_id not in active_players and ratings[player_id].rd < 161.80339:  #linear growth per match of RD for inactive players
            ratings[player_id].rd = min(
        ratings[player_id].rd + 0.6180339,
        161.80339,
    )

def write_glicko(glickos):
    match_dates = get_match_dates()
    latest_date = max(match_dates)

    ratings_file = RATINGS_FOLDER / f"ratings_{latest_date}.csv"

    if ratings_file.exists():
        answer = input(
            f"Rating file for {latest_date} already exists. "
            "Do you want to overwrite it? (y/n): "
        )

        if answer.lower() != "y":
            print("Rating file was not overwritten.")
            return

    with open(ratings_file, "w", newline="", encoding="utf-8") as r_file:
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

    calibration_ratings = load_calibration_table()
    print(f"Loaded {len(calibration_ratings)} ratings")

    prepared_glicko = prepare_glicko_table(
        matchhistory,
        alias_lookup,
        calibration_ratings
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