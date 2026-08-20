# Update Glicko ratings only for matches that have not been processed yet.

from pathlib import Path

from scripts.database import get_connection
from scripts.db_matches import get_matches, get_match_teams
from scripts.db_ratings import get_ratings, get_processed_match_ids, get_calibrations

from scripts.glicko2_calculator import (
    glicko_table_to_ratings,
    ratings_to_glicko_table,
    update_match,
    write_match_ratings,
    write_glicko,
    calculate_team_rating,
    get_first_alias,
    initialize_player_ratings
)
from scripts.glicko2 import Glicko2, TOTAL, BOX, HF


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


def validate_new_matches(matches, processed_match_ids):
    """
    Make sure all unprocessed matches come after the already
    processed matches.

    The incremental updater assumes that matches are only added
    chronologically. If an old match is inserted later, the existing
    current ratings would no longer be a valid starting point.
    """

    if not processed_match_ids:
        return

    latest_processed_match_id = max(processed_match_ids)

    for match in matches:

        match_id = match["match_id"]

        # Already processed → nothing to validate
        if match_id in processed_match_ids:
            continue

        # New match must come after the latest processed match
        if match_id < latest_processed_match_id:
            raise ValueError(
                f"Match {match_id} has not been processed, "
                f"but a later match ({latest_processed_match_id}) "
                "has already been processed. "
                "Run the full Glicko recalculation instead."
            )




def format_delta(delta, decimals=0):
    if delta > 0:
        return f"▲ {delta:.{decimals}f}"

    if delta < 0:
        return f"▼ {abs(delta):.{decimals}f}"

    return f"→ {0:.{decimals}f}"


def print_match_debug(
    connection,
    match,
    before_ratings,
    after_ratings,
):
    before_objects = glicko_table_to_ratings(
        before_ratings
    )

    after_objects = glicko_table_to_ratings(
        after_ratings
    )

    team1_ids, team2_ids = get_match_teams(
        connection,
        match["match_id"]
    )

    # ---------------------------------------------------------
    # Calculate team ratings before and after the match
    # ---------------------------------------------------------

    if match["pitch"] == "box":
        pitch_rating_type = BOX
    elif match["pitch"] == "hf":
        pitch_rating_type = HF
    else:
        raise ValueError(
            f"Unknown pitch type: {match['pitch']}"
        )

    # ---------------------------------------------------------
    # TOTAL
    # ---------------------------------------------------------

    team1_total_before = calculate_team_rating(
        team1_ids,
        match["players_a"],
        before_objects,
        TOTAL
    )

    team2_total_before = calculate_team_rating(
        team2_ids,
        match["players_b"],
        before_objects,
        TOTAL
    )

    team1_total_after = calculate_team_rating(
        team1_ids,
        match["players_a"],
        after_objects,
        TOTAL
    )

    team2_total_after = calculate_team_rating(
        team2_ids,
        match["players_b"],
        after_objects,
        TOTAL
    )

    # ---------------------------------------------------------
    # PITCH-SPECIFIC
    # ---------------------------------------------------------

    team1_pitch_before = calculate_team_rating(
        team1_ids,
        match["players_a"],
        before_objects,
        pitch_rating_type
    )

    team2_pitch_before = calculate_team_rating(
        team2_ids,
        match["players_b"],
        before_objects,
        pitch_rating_type
    )

    team1_pitch_after = calculate_team_rating(
        team1_ids,
        match["players_a"],
        after_objects,
        pitch_rating_type
    )

    team2_pitch_after = calculate_team_rating(
        team2_ids,
        match["players_b"],
        after_objects,
        pitch_rating_type
    )

    # ---------------------------------------------------------
    # Teams
    # ---------------------------------------------------------

    print("\nTeam A:")
    print(
        "  Players:",
        ", ".join(
            get_first_alias(
                connection,
                player_id
            )
            for player_id in team1_ids
        )
    )

    print("\n  TOTAL:")
    print(f"    Rating: {team1_total_before.rating:.0f}")
    print(f"    RD:     {team1_total_before.rd:.1f}")
    print(f"    Sigma:  {team1_total_before.sigma:.6f}")

    print(f"\n  {pitch_rating_type.upper()}:")
    print(f"    Rating: {team1_pitch_before.rating:.0f}")
    print(f"    RD:     {team1_pitch_before.rd:.1f}")
    print(f"    Sigma:  {team1_pitch_before.sigma:.6f}")


    print("\nTeam B:")
    print(
        "  Players:",
        ", ".join(
            get_first_alias(
                connection,
                player_id
            )
            for player_id in team2_ids
        )
    )

    print("\n  TOTAL:")
    print(f"    Rating: {team2_total_before.rating:.0f}")
    print(f"    RD:     {team2_total_before.rd:.1f}")
    print(f"    Sigma:  {team2_total_before.sigma:.6f}")

    print(f"\n  {pitch_rating_type.upper()}:")
    print(f"    Rating: {team2_pitch_before.rating:.0f}")
    print(f"    RD:     {team2_pitch_before.rd:.1f}")
    print(f"    Sigma:  {team2_pitch_before.sigma:.6f}")

    # ---------------------------------------------------------
    # Result
    # ---------------------------------------------------------

    print(
        f"\nResult: "
        f"A {match['goals_a']} - {match['goals_b']} B"
    )

    if match["goals_a"] > match["goals_b"]:
        print("  A: WIN")
        print("  B: LOSS")

    elif match["goals_a"] < match["goals_b"]:
        print("  A: LOSS")
        print("  B: WIN")

    else:
        print("  A: DRAW")
        print("  B: DRAW")

    # ---------------------------------------------------------
    # Team deltas
    # ---------------------------------------------------------

    team1_total_rating_delta = (
        team1_total_after.rating
        - team1_total_before.rating
    )

    team1_total_rd_delta = (
        team1_total_after.rd
        - team1_total_before.rd
    )

    team1_pitch_rating_delta = (
        team1_pitch_after.rating
        - team1_pitch_before.rating
    )

    team1_pitch_rd_delta = (
        team1_pitch_after.rd
        - team1_pitch_before.rd
    )

    team2_total_rating_delta = (
        team2_total_after.rating
        - team2_total_before.rating
    )

    team2_total_rd_delta = (
        team2_total_after.rd
        - team2_total_before.rd
    )

    team2_pitch_rating_delta = (
        team2_pitch_after.rating
        - team2_pitch_before.rating
    )

    team2_pitch_rd_delta = (
        team2_pitch_after.rd
        - team2_pitch_before.rd
    )

    print("\nTeam A deltas:")

    print("  TOTAL:")
    print(
        f"    Rating: "
        f"{format_delta(team1_total_rating_delta)}"
    )
    print(
        f"    RD:     "
        f"{format_delta(team1_total_rd_delta, 1)}"
    )

    print(f"\n  {pitch_rating_type.upper()}:")
    print(
        f"    Rating: "
        f"{format_delta(team1_pitch_rating_delta)}"
    )
    print(
        f"    RD:     "
        f"{format_delta(team1_pitch_rd_delta, 1)}"
    )


    print("\nTeam B deltas:")

    print("  TOTAL:")
    print(
        f"    Rating: "
        f"{format_delta(team2_total_rating_delta)}"
    )
    print(
        f"    RD:     "
        f"{format_delta(team2_total_rd_delta, 1)}"
    )

    print(f"\n  {pitch_rating_type.upper()}:")
    print(
        f"    Rating: "
        f"{format_delta(team2_pitch_rating_delta)}"
    )
    print(
        f"    RD:     "
        f"{format_delta(team2_pitch_rd_delta, 1)}"
    )

    # ---------------------------------------------------------
    # Player deltas
    # ---------------------------------------------------------

    answer = input(
        "\nShow player deltas? (y/n): "
    )

    if answer.lower() != "y":
        return

    print("\nPlayer deltas:")

    for player_id in team1_ids + team2_ids:

        before_total = before_ratings[player_id][TOTAL]
        after_total = after_ratings[player_id][TOTAL]

        before_pitch = before_ratings[player_id][pitch_rating_type]
        after_pitch = after_ratings[player_id][pitch_rating_type]

        total_rating_delta = (
            after_total["rating"]
            - before_total["rating"]
        )

        total_rd_delta = (
            after_total["rd"]
            - before_total["rd"]
        )

        pitch_rating_delta = (
            after_pitch["rating"]
            - before_pitch["rating"]
        )

        pitch_rd_delta = (
            after_pitch["rd"]
            - before_pitch["rd"]
        )

        alias = get_first_alias(
            connection,
            player_id
        )

        print(
            f"\n  {alias} ({player_id}):"
        )

        print(
            f"    TOTAL: "
            f"{format_delta(total_rating_delta)}, "
            f"RD {format_delta(total_rd_delta, 1)}"
        )

        print(
            f"    {pitch_rating_type.upper()}: "
            f"{format_delta(pitch_rating_delta)}, "
            f"RD {format_delta(pitch_rd_delta, 1)}"
        )

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

        # -----------------------------------------------------
        # Ask whether this match should be debugged
        # -----------------------------------------------------

        debug = input(
            f"\nDebug match {match['match_id']}? (y/n): "
        )

        # -----------------------------------------------------
        # Save ratings BEFORE the match
        # -----------------------------------------------------

        before_ratings = None

        if debug.lower() == "y":
            before_ratings = ratings_to_glicko_table(
                rating_objects
            )

        # -----------------------------------------------------
        # Store pre-match ratings
        # -----------------------------------------------------

        current_glicko = ratings_to_glicko_table(
            rating_objects
        )

        write_match_ratings(
            connection,
            match["match_id"],
            current_glicko,
        )

        # -----------------------------------------------------
        # Apply the match
        # -----------------------------------------------------

        update_match(
            connection,
            match,
            rating_objects,
            engine,
        )

        # -----------------------------------------------------
        # Debug AFTER the match
        # -----------------------------------------------------

        if debug.lower() == "y":

            after_ratings = ratings_to_glicko_table(
                rating_objects
            )

            print_match_debug(
                connection,
                match,
                before_ratings,
                after_ratings,
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



    validate_new_matches(
        matches.values(),
        processed_match_ids,
    )

    new_matches = get_new_matches(
        matches,
        processed_match_ids,
    )

    if not new_matches:
        print("No new matches to process.")
        connection.close()
        return

    print(f"Found {len(new_matches)} new matches")

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
        new_matches,
        ratings,
        calibrations
    )

    write_glicko(
        connection,
        final_ratings,
    )

    print(
        f"Updated ratings using {len(new_matches)} new matches"
    )

    connection.close()


if __name__ == "__main__":
    main()
