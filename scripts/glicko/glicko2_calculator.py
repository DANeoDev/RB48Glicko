# this will calculate Glicko rating for each player (using matchhistory.csv and players.csv) and update the ratings.csv
from scripts.glicko2 import (Glicko2, Rating, DEFAULT_RATING, DEFAULT_RD, IGNORED_RD, DEFAULT_SIGMA, WIN, LOSS, DRAW, TOTAL, BOX, HF, INACTIVITY_RD_TICK) 
from pathlib import Path
from scripts.database import get_connection
from scripts.db_matches import get_matches, get_match_teams
from scripts.db_players import get_players
from scripts.db_ratings import get_calibrations
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

def initialize_player_ratings(
    player_id,
    ratings,
    calibration=None,
):
    if player_id in ratings:
        return

    initial_rating = (calibration or {}).get(
        player_id,
        {
            "rating": DEFAULT_RATING,
            "rd": DEFAULT_RD,
            "sigma": DEFAULT_SIGMA
        }
    )

    ratings[player_id] = {
        TOTAL: Rating(
            initial_rating["rating"],
            initial_rating["rd"],
            initial_rating["sigma"]
        ),
        BOX: Rating(
            initial_rating["rating"],
            initial_rating["rd"],
            initial_rating["sigma"]
        ),
        HF: Rating(
            initial_rating["rating"],
            initial_rating["rd"],
            initial_rating["sigma"]
        ),
    }    

def prepare_glicko_table(connection, matches, calibration_ratings):
    prepared_glicko = {}

    for match in matches.values():

        team_a, team_b = get_match_teams(
            connection,
            match["match_id"]
        )

        for player_id in team_a + team_b:

            if player_id not in prepared_glicko:

                initial_rating = calibration_ratings.get(
                    player_id,
                    {
                        "rating": DEFAULT_RATING,
                        "rd": DEFAULT_RD,
                        "sigma": DEFAULT_SIGMA
                    }
                )

                prepared_glicko[player_id] = {
                    TOTAL: initial_rating.copy(),
                    BOX: initial_rating.copy(),
                    HF: initial_rating.copy(),
                }

    return prepared_glicko

def glicko_table_to_ratings(glicko_table):

    ratings = {}

    for player_id, rating_types in glicko_table.items():

        ratings[player_id] = {}

        for rating_type, data in rating_types.items():

            ratings[player_id][rating_type] = Rating(
                data["rating"],
                data["rd"],
                data["sigma"]
            )

    return ratings


def ratings_to_glicko_table(ratings):

    glicko_table = {}

    for player_id, rating_types in ratings.items():

        glicko_table[player_id] = {}

        for rating_type, rating in rating_types.items():

            glicko_table[player_id][rating_type] = {
                "rating": rating.rating,
                "rd": rating.rd,
                "sigma": rating.sigma
            }

    return glicko_table

def calculate_team_rating(
    player_ids,
    total_players,
    ratings,
    rating_type
):

    if not player_ids:
        return None

    ignored_players = total_players - len(player_ids)

  
    average_rating = sum(
        ratings[player][rating_type].rating
        for player in player_ids
    ) / len(player_ids)

    average_rd = math.sqrt(
        (
        sum(
            ratings[player][rating_type].rd ** 2
            for player in player_ids
        )
            + IGNORED_RD**2 * (ignored_players)
        ) / total_players
    )
    
    average_sigma = math.sqrt(
        (
        sum(
            ratings[player][rating_type].sigma ** 2
            for player in player_ids
        )
            + DEFAULT_SIGMA**2 * (ignored_players)
        ) / total_players
    )

    return Rating(average_rating, average_rd, average_sigma)

            

def create_virtual_rating(
    player_id,
    team_rating,
    ratings,
    rating_type
):

    player = ratings[player_id][rating_type]

    virtual_RD = math.sqrt(
        (player.rd**2 + team_rating.rd**2) / 2
    )

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

    if match["pitch"] == "box":
        pitch_rating_type = BOX
    elif match["pitch"] == "hf":
        pitch_rating_type = HF
    else:
        raise ValueError(
            f"Unknown pitch type: {match['pitch']}"
    )
    total_team1_rating = calculate_team_rating(
    team1_ids,
    team1_total_players,
    ratings,
    TOTAL
    )

    total_team2_rating = calculate_team_rating(
        team2_ids,
        team2_total_players,
        ratings,
        TOTAL
    )

    pitch_team1_rating = calculate_team_rating(
        team1_ids,
        team1_total_players,
        ratings,
        pitch_rating_type
    )

    pitch_team2_rating = calculate_team_rating(
        team2_ids,
        team2_total_players,
        ratings,
        pitch_rating_type
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

        # -----------------------------------------------------
        # TOTAL
        # -----------------------------------------------------

        total_player = ratings[player_id][TOTAL]
        
        old_total_rating = total_player.rating
        old_total_rd = total_player.rd
        old_total_sigma = total_player.sigma       

        total_virtual_player = create_virtual_rating(
            player_id,
            total_team1_rating,
            ratings,
            TOTAL
        )

        total_updated_virtual = engine.update_rating(
            total_virtual_player,
            [
                (
                    team1_result,
                    total_team2_rating
                )
            ]
        )

        total_rating_change = (
            total_updated_virtual.rating
            - total_virtual_player.rating
        )

        total_rd_change =(
            total_updated_virtual.rd
            - total_virtual_player.rd
        )
        total_sigma_change =(
                    total_updated_virtual.sigma
                    - total_virtual_player.sigma
                )

        total_player.rating += total_rating_change
        total_player.rd += total_rd_change
        total_player.sigma += total_sigma_change

        # -----------------------------------------------------
        # PITCH-SPECIFIC
        # -----------------------------------------------------

        pitch_player = ratings[player_id][pitch_rating_type]
        
        old_pitch_rating = pitch_player.rating
        old_pitch_rd = pitch_player.rd
        old_pitch_sigma = pitch_player.sigma
        

        pitch_virtual_player = create_virtual_rating(
            player_id,
            pitch_team1_rating,
            ratings,
            pitch_rating_type
        )

        pitch_updated_virtual = engine.update_rating(
            pitch_virtual_player,
            [
                (
                    team1_result,
                    pitch_team2_rating
                )
            ]
        )

        pitch_rating_change = (
            pitch_updated_virtual.rating
            - pitch_virtual_player.rating
        )

        pitch_rd_change = (
            pitch_updated_virtual.rd
            - pitch_virtual_player.rd
        )

        pitch_sigma_change = (
            pitch_updated_virtual.sigma
            - pitch_virtual_player.sigma
        )

        pitch_player.rating += pitch_rating_change
        pitch_player.rd += pitch_rd_change
        pitch_player.sigma += pitch_sigma_change


    # DEBUG TEAM 1    

        if player_id == debug_player:

            print(
                f"\nDEBUG PLAYER: "
                f"{get_first_alias(connection, player_id)}"
            )

            print(f"Match: {match['match_id']}")
            print("Team: Team 1")
            print(f"Result: {team1_result}")

            print("\nTOTAL:")
            print(
                f"  Team rating: "
                f"{total_team1_rating.rating:.3f}"
            )
            print(
                f"  Team RD: "
                f"{total_team1_rating.rd:.3f}"
            )
            print(
                f"  Opponent rating: "
                f"{total_team2_rating.rating:.3f}"
            )
            print(
                f"  Rating: "
                f"{old_total_rating:.3f} -> "
                f"{total_player.rating:.3f}"
            )
            print(
                f"  RD: "
                f"{old_total_rd:.3f} -> "
                f"{total_player.rd:.3f}"
            )
            print(
                f"  Sigma: "
                f"{old_total_sigma:.6f} -> "
                f"{total_player.sigma:.6f}"
            )

            print(f"\n{pitch_rating_type.upper()}:")

            print(
                f"  Team rating: "
                f"{pitch_team1_rating.rating:.3f}"
            )
            print(
                f"  Team RD: "
                f"{pitch_team1_rating.rd:.3f}"
            )
            print(
                f"  Opponent rating: "
                f"{pitch_team2_rating.rating:.3f}"
            )
            print(
                f"  Rating: "
                f"{old_pitch_rating:.3f} -> "
                f"{pitch_player.rating:.3f}"
            )
            print(
                f"  RD: "
                f"{old_pitch_rd:.3f} -> "
                f"{pitch_player.rd:.3f}"
            )
            print(
                f"  Sigma: "
                f"{old_pitch_sigma:.6f} -> "
                f"{pitch_player.sigma:.6f}"
            )


    # ---------------------------------------------------------
    # Update Team 2
    # ---------------------------------------------------------

    for player_id in team2_ids:

        # -----------------------------------------------------
        # TOTAL
        # -----------------------------------------------------

        total_player = ratings[player_id][TOTAL]
        
        old_total_rating = total_player.rating
        old_total_rd = total_player.rd
        old_total_sigma = total_player.sigma

        

        total_virtual_player = create_virtual_rating(
            player_id,
            total_team2_rating,
            ratings,
            TOTAL
        )

        total_updated_virtual = engine.update_rating(
            total_virtual_player,
            [
                (
                    team2_result,
                    total_team1_rating
                )
            ]
        )

        total_rating_change = (
            total_updated_virtual.rating
            - total_virtual_player.rating
        )

        total_rd_change =(
            total_updated_virtual.rd
            - total_virtual_player.rd
        )
        total_sigma_change =(
                    total_updated_virtual.sigma
                    - total_virtual_player.sigma
                )

        total_player.rating += total_rating_change
        total_player.rd += total_rd_change
        total_player.sigma += total_sigma_change

        # -----------------------------------------------------
        # PITCH-SPECIFIC
        # -----------------------------------------------------

        pitch_player = ratings[player_id][pitch_rating_type]
        
        old_pitch_rating = pitch_player.rating
        old_pitch_rd = pitch_player.rd
        old_pitch_sigma = pitch_player.sigma

     

        pitch_virtual_player = create_virtual_rating(
            player_id,
            pitch_team2_rating,
            ratings,
            pitch_rating_type
        )

        pitch_updated_virtual = engine.update_rating(
            pitch_virtual_player,
            [
                (
                    team2_result,
                    pitch_team1_rating
                )
            ]
        )

        pitch_rating_change = (
            pitch_updated_virtual.rating
            - pitch_virtual_player.rating
        )

        pitch_player.rating += pitch_rating_change
        pitch_player.rd = pitch_updated_virtual.rd
        pitch_player.sigma = pitch_updated_virtual.sigma

        # DEBUG TEAM 2

        if player_id == debug_player:

            print(
                f"\nDEBUG PLAYER: "
                f"{get_first_alias(connection, player_id)}"
            )

            print(f"Match: {match['match_id']}")
            print("Team: Team 2")
            print(f"Result: {team2_result}")

            print("\nTOTAL:")
            print(
                f"  Team rating: "
                f"{total_team2_rating.rating:.3f}"
            )
            print(
                f"  Team RD: "
                f"{total_team2_rating.rd:.3f}"
            )
            print(
                f"  Opponent rating: "
                f"{total_team1_rating.rating:.3f}"
            )
            print(
                f"  Rating: "
                f"{old_total_rating:.3f} -> "
                f"{total_player.rating:.3f}"
            )
            print(
                f"  RD: "
                f"{old_total_rd:.3f} -> "
                f"{total_player.rd:.3f}"
            )
            print(
                f"  Sigma: "
                f"{old_total_sigma:.6f} -> "
                f"{total_player.sigma:.6f}"
            )

            print(f"\n{pitch_rating_type.upper()}:")

            print(
                f"  Team rating: "
                f"{pitch_team2_rating.rating:.3f}"
            )
            print(
                f"  Team RD: "
                f"{pitch_team2_rating.rd:.3f}"
            )
            print(
                f"  Opponent rating: "
                f"{pitch_team1_rating.rating:.3f}"
            )
            print(
                f"  Rating: "
                f"{old_pitch_rating:.3f} -> "
                f"{pitch_player.rating:.3f}"
            )
            print(
                f"  RD: "
                f"{old_pitch_rd:.3f} -> "
                f"{pitch_player.rd:.3f}"
            )
            print(
                f"  Sigma: "
                f"{old_pitch_sigma:.6f} -> "
                f"{pitch_player.sigma:.6f}"
            )

    # ---------------------------------------------------------
    # Increase RD for inactive players
    # ---------------------------------------------------------

    for player_id in ratings:

        if player_id not in active_players:

            # Every missed match increases Total RD
            ratings[player_id][TOTAL].rd = min(
                ratings[player_id][TOTAL].rd + INACTIVITY_RD_TICK,
                DEFAULT_RD
            )

            # Only the played pitch's rating gets the pitch-specific increase
            ratings[player_id][pitch_rating_type].rd = min(
                ratings[player_id][pitch_rating_type].rd + INACTIVITY_RD_TICK,
                DEFAULT_RD
            )    



def write_match_ratings(connection, match_id, ratings):

    for player_id, rating_types in ratings.items():

        for rating_type, rating in rating_types.items():

            connection.execute(
                """
                INSERT INTO match_ratings
                    (match_id, player_id, rating_type, rating, rd, sigma)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(match_id, player_id, rating_type) DO UPDATE SET
                    rating = excluded.rating,
                    rd = excluded.rd,
                    sigma = excluded.sigma
                """,
                (
                    match_id,
                    player_id,
                    rating_type,
                    rating["rating"],
                    rating["rd"],
                    rating["sigma"],
                ),
            )

    connection.commit()

def write_glicko(connection, glickos):

    for player_id, rating_types in glickos.items():

        for rating_type, rating in rating_types.items():

            connection.execute(
                """
                INSERT INTO ratings
                    (player_id, rating_type, rating, rd, sigma)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(player_id, rating_type) DO UPDATE SET
                    rating = excluded.rating,
                    rd = excluded.rd,
                    sigma = excluded.sigma
                """,
                (
                    player_id,
                    rating_type,
                    rating["rating"],
                    rating["rd"],
                    rating["sigma"],
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