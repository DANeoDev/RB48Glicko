def get_calibrations(connection):
    cursor = connection.execute("""
        SELECT player_id, rating, rd, sigma
        FROM calibrations
    """)

    calibrations = {}

    for player_id, rating, rd, sigma in cursor:
        calibrations[player_id] = {
            "rating": rating,
            "rd": rd,
            "sigma": sigma
        }

    return calibrations

def get_ratings(connection):
    rows = connection.execute("""
        SELECT player_id, rating_type, rating, rd, sigma
        FROM ratings
    """).fetchall()

    ratings = {}

    for row in rows:

        player_id = row["player_id"]
        rating_type = row["rating_type"]

        if player_id not in ratings:
            ratings[player_id] = {}

        ratings[player_id][rating_type] = {
            "rating": row["rating"],
            "rd": row["rd"],
            "sigma": row["sigma"]
        }

    return ratings

def get_processed_match_ids(connection):
    rows = connection.execute("""
        SELECT DISTINCT match_id
        FROM match_ratings
    """).fetchall()

    return {
        row["match_id"]
        for row in rows
    }