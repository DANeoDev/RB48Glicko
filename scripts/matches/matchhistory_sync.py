import csv
from pathlib import Path

from scripts.db_matches import get_matches, get_match_teams

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MATCHHISTORY_FILE = PROJECT_ROOT / "data" / "matchhistory.csv"


def sync_matchhistory_csv(connection):
    """Rebuild the CSV used by glicko2_calculator from the matches in SQLite."""
    matches = get_matches(connection)
    aliases = {
        row["player_id"]: row["alias"]
        for row in connection.execute("SELECT alias, player_id FROM aliases")
    }
    MATCHHISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    with MATCHHISTORY_FILE.open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["match_id", "pitch", "team A", "team B", "goals A", "goals B"])
        for match_id, match in sorted(matches.items(), key=lambda item: (item[1]["date"], item[0])):
            team_a, team_b = get_match_teams(connection, match_id)
            writer.writerow([
                match_id,
                match["pitch"],
                ",".join(aliases[player_id] for player_id in team_a),
                ",".join(aliases[player_id] for player_id in team_b),
                match["goals_a"],
                match["goals_b"],
            ])
