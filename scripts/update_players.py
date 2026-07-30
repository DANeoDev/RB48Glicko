from pathlib import Path
import csv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MATCHHISORY_FILE = PROJECT_ROOT / "data" / "matchhistory.csv"
IGNORED_ALIASES_FILE = PROJECT_ROOT / "data" / "ignored_aliases.csv"
PLAYERS_FILE = PROJECT_ROOT / "data" / "players.csv"


def get_existing_player_data():
    players_dict = {}
    

    if PLAYERS_FILE.exists():
        with open(PLAYERS_FILE, "r", newline="", encoding="utf-8") as h_file:
            reader = csv.DictReader(h_file)
            for row in reader:                
                if not row: 
                    continue
                player_id = int(row["player_id"])
                aliases = row["aliases"].split(";")
                positions = row["positions"].split(";")

                players_dict[player_id]={
                    "aliases":aliases,
                    "positions":positions
                }

    return players_dict


def create_alias_lookup(players_dict):
    
    alias_lookup_dict = {
        alias: player_id
        for player_id, data in players_dict.items()
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
    if MATCHHISORY_FILE.exists():
        with open(MATCHHISORY_FILE, "r", newline="", encoding="utf-8") as h_file:
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

def print_players(players_dict):
    print("\nExisting players:")
    print("-" * 50)
    print(f"{'ID':<5} {'Aliases':<25} {'Positions'}")
    print("-" * 50)

    for player_id, data in players_dict.items():
        aliases = "; ".join(data["aliases"])
        positions = "; ".join(data["positions"])

        print(f"{player_id:<5} {aliases:<25} {positions}")

    print("-" * 50)

def new_player_prompt(players_dict, alias_lookup_dict, name_inputs, ignored_aliases):
    
    valid_positions = [
        "gk", "def", "mid", "att",
        "gk*", "def*", "mid*", "att*"
    ]

    CYAN = "\033[96m"
    RESET = "\033[0m"

    for name in name_inputs:

        if name in alias_lookup_dict or name in ignored_aliases:
            continue

        while True:
            print_players(players_dict)           
            np_prompt = input(f"Create a new player ID for {CYAN}'{name}'{RESET}? Enter  'y' \nAdd {CYAN}'{name}'{RESET} as a new alias to an existing ID? Enter 'add' \nEnter 'n' to skip \n  ")

            if np_prompt == "n":
                ignored_aliases.add(name)
                write_ignored_aliases(ignored_aliases)
                skip_player = True
                break
            if np_prompt =="y":
                skip_player = False
                break
            if np_prompt == "add":
                     

                while True:
                    add_to_id_prompt = input("Chose a player ID. Enter n to skip \n")
                    if add_to_id_prompt =="n":
                        break

                    player_id = int(add_to_id_prompt)
                    if player_id in players_dict:
                        players_dict[player_id]["aliases"].append(name)
                        alias_lookup_dict[name] = player_id
                        write_players(players_dict)
                        skip_player =  True
                        break
                break
            print("invalid syntax")

        if skip_player:
            continue
        
        while True:
            pos_prompt = input(
                        "Add positions? gk, def, mid, att (append * for main position; enter n to skip for now): "
                    )
            
            positions = [pos.strip().lower() for pos in pos_prompt.split(",")]
            
            if positions == ["n"]:
                 positions = []
                 break
            
            if not all(pos in valid_positions for pos in positions):
                print("Invalid positions. Please enter valid positions or n")
                continue
            break

        new_id = max(players_dict.keys(), default=0) + 1          
                    
        players_dict[new_id] ={
            "aliases" : [name],
            "positions" : positions
        }

        write_players(players_dict)

    

def write_players(players_dict):
    with open(PLAYERS_FILE, "w", newline="", encoding="utf-8") as h_file:
        writer = csv.DictWriter(
            h_file,
            fieldnames=["player_id", "aliases", "positions"]
        )      

        writer.writeheader()

        for player_id, data in players_dict.items():
            writer.writerow({
                "player_id": player_id,
                "aliases": ";".join(data["aliases"]),
                "positions": ";".join(data["positions"])
            })

def write_ignored_aliases(ignored_aliases):
    with open(
        IGNORED_ALIASES_FILE,
        "w",
        newline="",
        encoding="utf-8"
    ) as h_file:

        writer = csv.DictWriter(
            h_file,
            fieldnames=["alias"]
        )

        writer.writeheader()

        for alias in ignored_aliases:
            writer.writerow({
                "alias": alias
            })


            

def update_players():
    players_dict = get_existing_player_data()
    alias_lookup_dict = create_alias_lookup(players_dict)
    name_inputs = read_names_from_matchhistory()
    ignored_aliases = get_ignored_aliases()

    new_player_prompt(players_dict, alias_lookup_dict, name_inputs, ignored_aliases)

    
   
    print("All players have been added")

if __name__ == "__main__":
    update_players()





    

            






