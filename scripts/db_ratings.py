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

def get_player_rating_history(connection, player_id):
    rows = connection.execute("""
        SELECT
            match_ratings.match_id,
            matches.date,
            match_ratings.rating_type,
            match_ratings.rating
        FROM match_ratings
        JOIN matches
            ON match_ratings.match_id = matches.match_id
        WHERE match_ratings.player_id = ?
        ORDER BY matches.date, match_ratings.match_id
    """, (player_id,)).fetchall()

    history = {
        "total": [],
        "box": [],
        "hf": []
    }

    for row in rows:
        history[row["rating_type"]].append({
            "match_id": row["match_id"],
            "date": row["date"],
            "rating": row["rating"]
        })

    return history