# ALPHA VERSION (TBD)
# creates stats.csv, containing Player Alias, Rating, Conservative, RD, Matches, Wins, Draws, Losses, Win %
from pathlib import Path
import csv
from loaders import load_players, load_matchhistory, load_latest_ratings, create_alias_lookup, get_ignored_aliases
from helpers import get_player_ids_from_team, get_match_result, get_match_dates

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATS_FOLDER = PROJECT_ROOT / "data" / "stats"


def create_player_stats(player_id, ratings, alias):

    rating_data = ratings.get(player_id)

    if rating_data is None:
        return {
            "player_id": player_id,
            "alias": alias,
            "rating": None,
            "conservative": None,
            "rd": None,
            "matches": 0,
            "wins": 0,
            "draws": 0,
            "losses": 0,
            "win_percent": 0
        }

    rating = rating_data["rating"]
    rd = rating_data["rd"]

    return {
        "player_id": player_id,
        "alias": alias,
        "rating": rating,
        "conservative": rating - 3 * rd,
        "rd": rd,
        "matches": 0,
        "wins": 0,
        "draws": 0,
        "losses": 0,
        "win_percent": 0
    }


def calculate_stats(matchhistory, players, ratings, alias_lookup):

    stats = {}

    # Create an entry for every player
    for player_id, player in players.items():
        aliases = player["aliases"]

        alias = aliases[0] if aliases else None

        stats[player_id] = create_player_stats(
            player_id,
            ratings,
            alias
        )
        

        

    # Process every match
    for match in matchhistory:

        team1_ids = get_player_ids_from_team(
            match[2],
            alias_lookup
        )

        team2_ids = get_player_ids_from_team(
            match[3],
            alias_lookup
        )

        if not team1_ids or not team2_ids:
            continue

        team1_result, team2_result = get_match_result(match)

        for player_id in team1_ids:

            if player_id not in stats:
                continue

            stats[player_id]["matches"] += 1

            if team1_result == 1.0:
                stats[player_id]["wins"] += 1

            elif team1_result == 0.5:
                stats[player_id]["draws"] += 1

            elif team1_result == 0.0:
                stats[player_id]["losses"] += 1

        for player_id in team2_ids:

            if player_id not in stats:
                continue

            stats[player_id]["matches"] += 1

            if team2_result == 1.0:
                stats[player_id]["wins"] += 1

            elif team2_result == 0.5:
                stats[player_id]["draws"] += 1

            elif team2_result == 0.0:
                stats[player_id]["losses"] += 1

    # Calculate percentages
    for player_stats in stats.values():

        matches = player_stats["matches"]

        if matches:
            player_stats["win_percent"] = (
                player_stats["wins"] / matches * 100
            )

    return stats



def write_stats_csv(stats):
    match_dates = get_match_dates()

    if not match_dates:
        print("No matches found. Stats file was not created.")
        return

    latest_match = max(match_dates)

    STATS_FOLDER.mkdir(exist_ok=True)

    stats_file = STATS_FOLDER / f"stats_{latest_match}.csv"

    if stats_file.exists():
        answer = input(
            f"Stats file for {latest_match} already exists. "
            "Do you want to overwrite it? (y/n): "
        )

        if answer.lower() != "y":
            print("Stats file was not overwritten.")
            return

    stats = sorted(
    stats.values(),
    key=lambda data: data["conservative"],
    reverse=True
)
    fieldnames = [
        "rank",
        "alias",
        "conservative",
        "rating",
        "rd",
        "matches",
        "wins",
        "draws",
        "losses",
        "win_percent"
    ]

    with open(stats_file, "w", newline="", encoding="utf-8") as s_file:
        writer = csv.DictWriter(s_file, fieldnames=fieldnames)
        writer.writeheader()

        MAX_ALIAS_LENGTH = 10

        for rank, data in enumerate(stats, start=1):

            alias = data["alias"] or ""

            if len(alias) > MAX_ALIAS_LENGTH:
                alias = alias[:MAX_ALIAS_LENGTH - 3] + "..."

            writer.writerow({
                "rank": rank,
                "alias": alias,
                "conservative": round(data["conservative"]),
                "rating": round(data["rating"]),
                "rd": round(data["rd"]),
                "matches": data["matches"],
                "wins": data["wins"],
                "draws": data["draws"],
                "losses": data["losses"],
                "win_percent": f"{data['win_percent']:.2f}"
            })





def main():

    matchhistory = load_matchhistory()
    players = load_players()
    ratings = load_latest_ratings()

    alias_lookup = create_alias_lookup(players)

    stats = calculate_stats(
        matchhistory,
        players,
        ratings,
        alias_lookup
    )

    write_stats_csv(stats)


if __name__ == "__main__":
    main()