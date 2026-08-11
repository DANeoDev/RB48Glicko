from pathlib import Path
import csv
from loaders import (
    load_players,
    create_alias_lookup,
    get_ignored_aliases,
    read_names_from_matchhistory
)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
IGNORED_ALIASES_FILE = PROJECT_ROOT / "data" / "ignored_aliases.csv"
PLAYERS_FILE = PROJECT_ROOT / "data" / "players.csv"


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
    players = load_players()
    alias_lookup_dict = create_alias_lookup(players)
    name_inputs = read_names_from_matchhistory()
    ignored_aliases = get_ignored_aliases()

    new_player_prompt(players, alias_lookup_dict, name_inputs, ignored_aliases)

    
   
    print("All players have been added")

if __name__ == "__main__":
    update_players()





    

            






