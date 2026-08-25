"""Reset all match-derived database data.

Use this when the match database contains test/imported data that should be
removed and rebuilt from the authoritative match source files.

This script deletes:
    - matches
    - match_players
    - match_ratings
    - ratings

It deliberately keeps:
    - players
    - aliases
    - positions
    - ignored_aliases
    - calibrations

Player records are not match data and may contain legitimate players that
should survive a match-data reset.
"""

from scripts.database import get_connection


TABLES = (
    "match_ratings",
    "match_players",
    "matches",
    "ratings",
)


def wipe_matchdata(connection):
    counts = {}

    for table in TABLES:
        counts[table] = connection.execute(
            f"SELECT COUNT(*) FROM {table}"
        ).fetchone()[0]

    print("This will permanently delete:")
    for table in TABLES:
        print(f"  {table}: {counts[table]} rows")

    confirmation = input(
        "\nType 'WIPE MATCHDATA' to continue: "
    )

    if confirmation != "WIPE MATCHDATA":
        print("Aborted. No data was changed.")
        return False

    try:
        connection.execute("BEGIN")

        for table in TABLES:
            connection.execute(f"DELETE FROM {table}")

        connection.commit()

    except Exception:
        connection.rollback()
        raise

    print("\nMatch data wiped successfully.")
    print("Players, aliases, positions, ignored aliases and calibrations were kept.")
    return True


def main():
    connection = get_connection()

    try:
        wipe_matchdata(connection)
    finally:
        connection.close()


if __name__ == "__main__":
    main()
