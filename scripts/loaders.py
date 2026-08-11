import csv
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
MATCHHISTORY_FILE = PROJECT_ROOT / "data" / "matchhistory.csv"
IGNORED_ALIASES_FILE = PROJECT_ROOT / "data" / "ignored_aliases.csv"
PLAYERS_FILE = PROJECT_ROOT / "data" / "players.csv"
CALIBRATION_FILE = PROJECT_ROOT / "data" / "calibrations.csv"
RATINGS_FOLDER = PROJECT_ROOT / "data" / "ratings"


def load_players():
    players = {}
    

    if PLAYERS_FILE.exists():
        with open(PLAYERS_FILE, "r", newline="", encoding="utf-8") as h_file:
            reader = csv.DictReader(h_file)
            for row in reader:                
                if not row: 
                    continue
                player_id = int(row["player_id"])
                aliases = row["aliases"].split(";")
                positions = row["positions"].split(";")

                players[player_id]={
                    "aliases":aliases,
                    "positions":positions
                }

    return players


def create_alias_lookup(players):
    
    alias_lookup_dict = {
        alias: player_id
        for player_id, data in players.items()
        for alias in data["aliases"]    
    }
    return alias_lookup_dict

def get_ignored_aliases():
    ignored_aliases = set()

    if IGNORED_ALIASES_FILE.exists():
        with open(IGNORED_ALIASES_FILE, "r", newline="", encoding="utf-8") as h_file:
            reader = csv.DictReader(h_file)

            for row in reader:
                ignored_aliases.add(row["alias"])

    return ignored_aliases
  
def read_names_from_matchhistory():
    if MATCHHISTORY_FILE.exists():
        with open(MATCHHISTORY_FILE, "r", newline="", encoding="utf-8") as h_file:
            reader=csv.DictReader(h_file)
            all_names=[]
            for row in reader:
                if not row:
                    continue
                names = [name.strip() for name in row["team_a"].split(",") + row["team_b"].split(",")]

                if row["match_id"].startswith("#"):
                    continue
                
                all_names.extend(names)

    return list(dict.fromkeys(all_names))

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

def load_calibration_table():
    glicko_table = {}
    if CALIBRATION_FILE.exists():
        with open(CALIBRATION_FILE, "r", newline="", encoding="utf-8") as r_file:
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

def load_latest_ratings():
    rating_files = list(RATINGS_FOLDER.glob("ratings_*.csv"))

    if not rating_files:
        return {}

    latest_file = max(rating_files)

    ratings = {}

    with open(latest_file, "r", newline="", encoding="utf-8") as r_file:
        reader = csv.DictReader(r_file)

        for row in reader:
            player_id = int(row["player_id"])

            ratings[player_id] = {
                "rating": float(row["rating"]),
                "rd": float(row["rd"]),
                "sigma": float(row["sigma"])
            }

    return ratings

