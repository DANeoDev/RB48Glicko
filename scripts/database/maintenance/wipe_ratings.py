"""Reset rating tables for testing or full recalculation.

CAUTION: This will wipe all current and historical rating records from the
database. Match records and player entities are preserved.
"""

from scripts.database.database import (
    get_connection,
    create_ratings_table,
    create_match_ratings_table,
)


def wipe_ratings(connection):
    connection.execute("DROP TABLE IF EXISTS match_ratings")
    connection.execute("DROP TABLE IF EXISTS ratings")
    connection.commit()

    create_match_ratings_table(connection)
    create_ratings_table(connection)


def main():
    connection = get_connection()
    try:
        wipe_ratings(connection)
        print("Rating tables dropped and recreated successfully.")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
