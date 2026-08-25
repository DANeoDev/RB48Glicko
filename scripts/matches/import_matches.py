import csv
from pathlib import Path
from datetime import date

from scripts.database import get_connection
from scripts.db_players import (
    get_players,
    get_alias_lookup,
    get_ignored_aliases,
    create_player,
    add_alias,
    add_position,
    add_ignored_alias,
    get_next_player_id
)
from scripts.db_matches import (
    match_exists,
    create_match,
    add_match_player,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
MATCHES_FOLDER = PROJECT_ROOT / "matches"


VALID_POSITIONS = {
    "gk", "def", "mid", "att",
    "gk*", "def*", "mid*", "att*"
}


def print_players(players):
    print("\nExisting players:")
    print("-" * 50)
    print(f"{'ID':<5} {'Aliases':<25} {'Positions'}")
    print("-" * 50)

    for player_id, data in players.items():
        aliases = "; ".join(data["aliases"])
        positions = "; ".join(data["positions"])

        print(f"{player_id:<5} {aliases:<25} {positions}")

    print("-" * 50)


def ask_about_alias(
    connection,
    alias,
    players,
    alias_lookup,
    ignored_aliases
):
    CYAN = "\033[96m"
    RESET = "\033[0m"

    while True:

        print_players(players)

        prompt = input(
            f"Create a new player ID for {CYAN}'{alias}'{RESET}? "
            "Enter 'y'\n"
            f"Add {CYAN}'{alias}'{RESET} as an alias to an existing ID? "
            "Enter 'add'\n"
            "Enter 'n' to ignore\n"
        )

        if prompt == "n":
            add_ignored_alias(connection, alias)
            ignored_aliases.add(alias)
            return None

        if prompt == "add":

            while True:
                player_id_input = input(
                    "Choose a player ID. Enter n to cancel\n"
                )

                if player_id_input == "n":
                    break

                try:
                    player_id = int(player_id_input)
                except ValueError:
                    print("Please enter a valid player ID.")
                    continue

                if player_id not in players:
                    print("Player ID does not exist.")
                    continue

                add_alias(connection, alias, player_id)

                players[player_id]["aliases"].append(alias)
                alias_lookup[alias] = player_id

                return player_id

            continue

        if prompt == "y":

            while True:
                pos_prompt = input(
                    "Add positions? "
                    "gk, def, mid, att "
                    "(append * for main position; enter n to skip): "
                )

                positions = [
                    pos.strip().lower()
                    for pos in pos_prompt.split(",")
                ]

                if positions == ["n"]:
                    positions = []
                    break

                if not all(
                    position in VALID_POSITIONS
                    for position in positions
                ):
                    print(
                        "Invalid positions. "
                        "Please enter valid positions or n."
                    )
                    continue

                break

            new_id = get_next_player_id(connection)

            create_player(connection, new_id)

            add_alias(connection, alias, new_id)

            for position in positions:
                if position.endswith("*"):
                    add_position(
                        connection,
                        new_id,
                        position[:-1],
                        True
                    )
                else:
                    add_position(
                        connection,
                        new_id,
                        position,
                        False
                    )

            players[new_id] = {
                "aliases": [alias],
                "positions": [
                    position.rstrip("*")
                    for position in positions
                ]
            }

            alias_lookup[alias] = new_id

            return new_id

        print("Invalid syntax.")


def resolve_alias(
    connection,
    alias,
    players,
    alias_lookup,
    ignored_aliases
):

    if alias in alias_lookup:
        return alias_lookup[alias]

    if alias in ignored_aliases:
        return None

    return ask_about_alias(
        connection,
        alias,
        players,
        alias_lookup,
        ignored_aliases
    )


def parse_match(row):

    match_id = row[0]
    pitch = row[1]
    team_a = [
        name.strip()
        for name in row[2].split(",")
    ]
    team_b = [
        name.strip()
        for name in row[3].split(",")
    ]
    goals_a = int(row[4])
    goals_b = int(row[5])

    match_date = match_id.rsplit("-", 1)[0]
    date.fromisoformat(match_date)

    return (
        match_id,
        match_date,
        pitch,
        team_a,
        team_b,
        goals_a,
        goals_b
    )


def import_match(
    connection,
    row,
    players,
    alias_lookup,
    ignored_aliases
):

    try:
        connection.execute("BEGIN")

        (
            match_id,
            match_date,
            pitch,
            team_a,
            team_b,
            goals_a,
            goals_b
        ) = parse_match(row)

        if match_exists(connection, match_id):
            connection.rollback()
            return False

        team_a_ids = []
        team_b_ids = []

        # ---------------------------------------------------------
        # Resolve Team A
        # ---------------------------------------------------------

        for alias in team_a:

            player_id = resolve_alias(
                connection,
                alias,
                players,
                alias_lookup,
                ignored_aliases
            )

            if player_id is not None:
                team_a_ids.append(player_id)

        # ---------------------------------------------------------
        # Resolve Team B
        # ---------------------------------------------------------

        for alias in team_b:

            player_id = resolve_alias(
                connection,
                alias,
                players,
                alias_lookup,
                ignored_aliases
            )

            if player_id is not None:
                team_b_ids.append(player_id)

        # ---------------------------------------------------------
        # Validate players
        # ---------------------------------------------------------

        all_player_ids = team_a_ids + team_b_ids

        if len(all_player_ids) != len(set(all_player_ids)):
            print(
                f"Invalid match {match_id}: "
                "a player appears more than once."
            )

            connection.rollback()
            return False

        if set(team_a_ids) & set(team_b_ids):
            print(
                f"Invalid match {match_id}: "
                "a player appears on both teams."
            )

            connection.rollback()
            return False

        # ---------------------------------------------------------
        # Write match
        # ---------------------------------------------------------

        create_match(
            connection,
            match_id,
            match_date,
            pitch,
            len(team_a),
            len(team_b),
            goals_a,
            goals_b
        )

        # ---------------------------------------------------------
        # Write Team A players
        # ---------------------------------------------------------

        for player_id in team_a_ids:

            add_match_player(
                connection,
                match_id,
                player_id,
                "a"
            )

        # ---------------------------------------------------------
        # Write Team B players
        # ---------------------------------------------------------

        for player_id in team_b_ids:

            add_match_player(
                connection,
                match_id,
                player_id,
                "b"
            )

        # ---------------------------------------------------------
        # Everything succeeded
        # ---------------------------------------------------------

        connection.commit()
        return True

    except Exception:
        connection.rollback()
        raise


def import_matches():

    connection = get_connection()

    players = get_players(connection)
    alias_lookup = get_alias_lookup(connection)
    ignored_aliases = get_ignored_aliases(connection)

    imported = 0
    skipped = 0

    for file in sorted(MATCHES_FOLDER.glob("*.csv")):

        with open(
            file,
            "r",
            newline="",
            encoding="utf-8"
        ) as csvfile:

            reader = csv.reader(csvfile)

            for row in reader:

                if not row:
                    continue

                if import_match(
                    connection,
                    row,
                    players,
                    alias_lookup,
                    ignored_aliases
                ):
                    imported += 1
                    print(f"Imported {row[0]}")
                else:
                    skipped += 1

    connection.close()

    print()
    print(f"Imported {imported} new matches.")
    print(f"Skipped {skipped} existing matches.")


if __name__ == "__main__":
    import_matches()