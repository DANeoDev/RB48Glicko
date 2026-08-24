# Update Glicko ratings only for matches that have not been processed yet.

from scripts.database import get_connection
from scripts.db_matches import get_matches, get_match_teams
from scripts.db_ratings import get_ratings, get_processed_match_ids, get_calibrations

from scripts.glicko2_calculator import (
    glicko_table_to_ratings,
    ratings_to_glicko_table,
    update_match,
    write_match_ratings,
    write_glicko,
    initialize_player_ratings
)
from scripts.glicko2 import Glicko2


def get_new_matches(matches, processed_match_ids):
    """
    Return matches that have not yet been processed.

    Matches are sorted chronologically by match_id.
    This works because match IDs use the YYYY-MM-DD-N format.
    """

    new_matches = [
        match
        for match in matches.values()
        if match["match_id"] not in processed_match_ids
    ]

    new_matches.sort(
        key=lambda match: match["match_id"]
    )

    return new_matches


def split_incremental_matches(matches, processed_match_ids):
    """
    Split unprocessed matches into matches that can safely be handled by
    the incremental updater and retrospective matches that require a full
    recalculation.

    A retrospective match must never be applied on top of current ratings,
    because doing so would apply it at the wrong point in the rating history.
    Importantly, however, retrospective matches are still allowed to exist
    in the database and therefore do not block match entry.
    """

    new_matches = get_new_matches(matches, processed_match_ids)

    if not processed_match_ids:
        return new_matches, []

    latest_processed_match_id = max(processed_match_ids)

    incremental = []
    retrospective = []

    for match in new_matches:
        if match["match_id"] < latest_processed_match_id:
            retrospective.append(match)
        else:
            incremental.append(match)

    return incremental, retrospective


def update_glicko(
    connection,
    matches,
    ratings,
    calibrations
):
    engine = Glicko2()

    rating_objects = glicko_table_to_ratings(
        ratings
    )

    for match in matches:
        team1_ids, team2_ids = get_match_teams(
            connection,
            match["match_id"]
        )

        for player_id in team1_ids + team2_ids:
            initialize_player_ratings(
                player_id,
                rating_objects,
                calibrations
            )

        current_glicko = ratings_to_glicko_table(
            rating_objects
        )

        write_match_ratings(
            connection,
            match["match_id"],
            current_glicko,
        )

        update_match(
            connection,
            match,
            rating_objects,
            engine,
        )

    return ratings_to_glicko_table(
        rating_objects
    )


def main():
    connection = get_connection()

    calibrations = get_calibrations(connection)

    matches = get_matches(connection)
    print(f"Loaded {len(matches)} matches")

    processed_match_ids = get_processed_match_ids(connection)

    print(
        f"\nFound {len(processed_match_ids)} processed matches"
    )

    incremental_matches, retrospective_matches = split_incremental_matches(
        matches,
        processed_match_ids,
    )

    if retrospective_matches:
        print(
            "\nFound retrospective match(es) that are not processed "
            "incrementally:"
        )
        for match in retrospective_matches:
            print(f"  - {match['match_id']}")
        print(
            "These matches remain in the database but require the full "
            "Glicko recalculation. They will not block match entry."
        )

    if not incremental_matches:
        print("No safely incremental matches to process.")
        connection.close()
        return

    print(f"Found {len(incremental_matches)} new matches")

    ratings = get_ratings(connection)

    if not ratings:
        connection.close()

        raise RuntimeError(
            "No current ratings found. "
            "Run glicko2_calculator.py first to perform "
            "a full Glicko calculation."
        )

    print(
        f"Loaded current ratings for {len(ratings)} players"
    )

    final_ratings = update_glicko(
        connection,
        incremental_matches,
        ratings,
        calibrations
    )

    write_glicko(
        connection,
        final_ratings,
    )

    print(
        f"Updated ratings using {len(incremental_matches)} new matches"
    )

    connection.close()


if __name__ == "__main__":
    main()
