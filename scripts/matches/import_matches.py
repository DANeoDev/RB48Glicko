import csv
from datetime import date
from pathlib import Path

from scripts.database.database import get_connection
from scripts.database.db_matches import get_matches, add_match_player, create_match
from scripts.database.db_players import get_players, get_alias_lookup, get_ignored_aliases

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MATCHES_FOLDER = PROJECT_ROOT / "matches"


def resolve_alias(connection, alias, players, alias_lookup, ignored_aliases):
    if alias in alias_lookup:
        return alias_lookup[alias]
    if alias in ignored_aliases:
        return None
    raise ValueError(f"Unknown player alias: {alias}")


def parse_match(row):
    # Match CSVs normally have a header. Be defensive here so the importer
    # also accepts headerless files and never tries to parse the header as a match.
    if len(row) >= 6 and row[0].strip().casefold() == "match_id":
        return None

    if len(row) < 6:
        raise ValueError(f"Invalid match row: expected 6 columns, got {len(row)}")

    match_id = row[0].strip()
    pitch = row[1].strip()
    team_a = [name.strip() for name in row[2].split(",") if name.strip()]
    team_b = [name.strip() for name in row[3].split(",") if name.strip()]
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


def import_match(connection, row, players, alias_lookup, ignored_aliases):
    parsed = parse_match(row)
    if parsed is None:
        return False

    (
        match_id,
        match_date,
        pitch,
        team_a,
        team_b,
        goals_a,
        goals_b
    ) = parsed

    if match_id in get_matches(connection):
        return False

    team_a_ids = []
    team_b_ids = []

    for alias in team_a:
        player_id = resolve_alias(connection, alias, players, alias_lookup, ignored_aliases)
        if player_id is not None:
            team_a_ids.append(player_id)

    for alias in team_b:
        player_id = resolve_alias(connection, alias, players, alias_lookup, ignored_aliases)
        if player_id is not None:
            team_b_ids.append(player_id)

    create_match(
        connection,
        match_id,
        match_date,
        pitch,
        team_a_ids,
        team_b_ids,
        goals_a,
        goals_b,
        len(team_a),
        len(team_b)
    )

    for player_id in team_a_ids:
        add_match_player(connection, match_id, player_id, "a")

    for player_id in team_b_ids:
        add_match_player(connection, match_id, player_id, "b")

    connection.commit()
    return True


def import_matches():
    connection = get_connection()
    players = get_players(connection)
    alias_lookup = get_alias_lookup(connection)
    ignored_aliases = get_ignored_aliases(connection)

    imported = 0
    skipped = 0

    for file in sorted(MATCHES_FOLDER.glob("*.csv")):
        with open(file, "r", newline="", encoding="utf-8") as csvfile:
            reader = csv.reader(csvfile)
            for row in reader:
                if not row:
                    continue
                if import_match(connection, row, players, alias_lookup, ignored_aliases):
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
