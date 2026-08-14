# this will calculate Glicko rating for each player (using matchhistory.csv and players.csv) and update the ratings.csv
from glicko2 import Glicko2, Rating, DEFAULT_RATING, DEFAULT_RD, IGNORED_RD, DEFAULT_SIGMA, WIN, LOSS, DRAW
from pathlib import Path
from database import get_connection
from db_matches import get_matches, get_match_teams
from db_players import get_players
from db_ratings import get_calibrations
import math
import shutil
from datetime import datetime


PROJECT_ROOT = Path(__file__).resolve().parent.parent
RATINGS_FOLDER = PROJECT_ROOT / "data" / "ratings"
MATCHHISTORY_FILE = PROJECT_ROOT / "data" / "matchhistory.csv"
PLAYERS_FILE = PROJECT_ROOT / "data" / "players.csv"
CALIBRATION_FILE = PROJECT_ROOT / "data" / "calibrations.csv"    

def backup_database():
    database_file = PROJECT_ROOT / "data" / "rb48.db"
    backup_folder = PROJECT_ROOT / "data" / "backups"

    backup_folder.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    backup_file = backup_folder / f"rb48_{timestamp}.db"

    shutil.copy2(database_file, backup_file)

    print(f"Database backup created: {backup_file}")

def clear_ratings(connection):
    connection.execute("DELETE FROM match_ratings")
    connection.execute("DELETE FROM ratings")
    connection.commit()

def prepare_glicko_table(connection, matches, calibration_ratings):
    prepared_glicko = {}

    for match in matches.values():

        team_a, team_b = get_match_teams(
            connection,
            match["match_id"]
        )

        for player_id in team_a + team_b:

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
    connection,
    matches,
    prepared_glicko,
    debug_player=None
):

    engine = Glicko2()

    ratings = glicko_table_to_ratings(
        prepared_glicko
    )

    for match in matches.values():

        current_glicko = ratings_to_glicko_table(ratings)

        write_match_ratings(
            connection,
            match["match_id"],
            current_glicko
        )

        update_match(
            connection,
            match,
            ratings,
            engine, 
            debug_player
        )

    return ratings_to_glicko_table(ratings)

def get_first_alias(connection, player_id):
    row = connection.execute(
        """
        SELECT alias
        FROM aliases
        WHERE player_id = ?
        ORDER BY alias
        LIMIT 1
        """,
        (player_id,),
    ).fetchone()

    if row is None:
        return f"Player {player_id}"

    return row[0]


def select_debug_player(connection):
    answer = input(
        "\nDebug a player? (y/n): "
    )

    if answer.lower() != "y":
        return None

    players = get_players(connection)

    print("\nPlayers:")

    player_ids = sorted(players)

    for number, player_id in enumerate(player_ids, start=1):
        player = players[player_id]

        print(
            f"  {number}. {player['aliases'][0]}"
        )

    while True:
        try:
            choice = int(input("Select player: "))

            if 1 <= choice <= len(player_ids):
                return player_ids[choice - 1]

        except ValueError:
            pass

        print("Please enter a valid player number.")



def update_match(
    connection,
    match,
    ratings,
    engine,
    debug_player=None,
):

    team1_ids, team2_ids = get_match_teams(
        connection,
        match["match_id"]
    )

    if not team1_ids or not team2_ids:
        return

    team1_total_players = match["players_a"]
    team2_total_players = match["players_b"]

    active_players = set(team1_ids + team2_ids)

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

    if match["goals_a"] > match["goals_b"]:
        team1_result = WIN
        team2_result = LOSS

    elif match["goals_a"] < match["goals_b"]:
        team1_result = LOSS
        team2_result = WIN

    else:
        team1_result = DRAW
        team2_result = DRAW

    # ---------------------------------------------------------
    # Update Team 1
    # ---------------------------------------------------------

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

            print(
                f"\nDEBUG PLAYER: {get_first_alias(connection, player_id)}"
            )
            print(
                f"Match: {match['match_id']}"
            )
            print(
                f"Team: Team 1"
            )
            print(
                f"Result: {team1_result}"
            )
            print(
                f"Team rating: {team1_rating.rating:.3f}"
            )
            print(
                f"Team RD: {team1_rating.rd:.3f}"
            )
            print(
                f"Team Sigma: {team1_rating.sigma:.6f}"
            )
            print(
                f"Opponent rating: {team2_rating.rating:.3f}"
            )
            print(
                f"Opponent RD: {team2_rating.rd:.3f}"
            )
            print(
                f"Opponent Sigma: {team2_rating.sigma:.6f}"
            )
            print(
                f"Rating: "
                f"{old_rating:.3f} -> "
                f"{ratings[player_id].rating:.3f}"
            )
            print(
                f"RD: "
                f"{old_rd:.3f} -> "
                f"{ratings[player_id].rd:.3f}"
            )
            print(
                f"Sigma: "
                f"{old_sigma:.6f} -> "
                f"{ratings[player_id].sigma:.6f}"
            )

    # ---------------------------------------------------------
    # Update Team 2
    # ---------------------------------------------------------

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

            print(
                f"\nDEBUG PLAYER: {get_first_alias(connection, player_id)}"
            )
            print(
                f"Match: {match['match_id']}"
            )
            print(
                f"Team: Team 2"
            )
            print(
                f"Result: {team2_result}"
            )
            print(
                f"Team rating: {team2_rating.rating:.3f}"
            )
            print(
                f"Team RD: {team2_rating.rd:.3f}"
            )
            print(
                f"Team Sigma: {team2_rating.sigma:.6f}"
            )
            print(
                f"Opponent rating: {team1_rating.rating:.3f}"
            )
            print(
                f"Opponent RD: {team1_rating.rd:.3f}"
            )
            print(
                f"Opponent Sigma: {team1_rating.sigma:.6f}"
            )
            print(
                f"Rating: "
                f"{old_rating:.3f} -> "
                f"{ratings[player_id].rating:.3f}"
            )
            print(
                f"RD: "
                f"{old_rd:.3f} -> "
                f"{ratings[player_id].rd:.3f}"
            )
            print(
                f"Sigma: "
                f"{old_sigma:.6f} -> "
                f"{ratings[player_id].sigma:.6f}"
            )

    # ---------------------------------------------------------
    # Increase RD for inactive players
    # ---------------------------------------------------------

    for player_id in ratings:

        if (
            player_id not in active_players
            and ratings[player_id].rd < 161.80339
        ):
            ratings[player_id].rd = min(
                ratings[player_id].rd + 0.6180339,
                161.80339,
            )        



            
def write_match_ratings(connection, match_id, ratings):
    for player_id, data in ratings.items():
        connection.execute(
            """
            INSERT INTO match_ratings
                (match_id, player_id, rating, rd, sigma)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(match_id, player_id) DO UPDATE SET
                rating = excluded.rating,
                rd = excluded.rd,
                sigma = excluded.sigma
            """,
            (
                match_id,
                player_id,
                data["rating"],
                data["rd"],
                data["sigma"],
            ),
        )

    connection.commit()

def write_glicko(connection, glickos):    
    for player_id, data in glickos.items():
        connection.execute(
            """
            INSERT INTO ratings (player_id, rating, rd, sigma)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(player_id) DO UPDATE SET
                rating = excluded.rating,
                rd = excluded.rd,
                sigma = excluded.sigma
            """,
            (
                player_id,
                data["rating"],
                data["rd"],
                data["sigma"],
            ),
        )

    connection.commit()


def main():

    backup_database()

    connection = get_connection()

    matches = get_matches(connection)
    print(f"Loaded {len(matches)} matches")

    calibrations = get_calibrations(connection)
    print(f"Loaded {len(calibrations)} calibrations")

    clear_ratings(connection)

    prepared_glicko = prepare_glicko_table(
        connection,
        matches,
        calibrations
    )

    print(
        f"Prepared ratings for {len(prepared_glicko)} players"
    )

    debug_player = select_debug_player(connection)

    glickos = calculate_glicko(
        connection,
        matches,
        prepared_glicko,
        debug_player
    )

    print(
        f"Calculated ratings for {len(glickos)} players"
    )

    write_glicko(connection, glickos)

    connection.close()


if __name__ == "__main__":
    main()