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


PROJECT_ROOT = Path(__file__).resolve().parents[2]
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
        )
    }

# ...
