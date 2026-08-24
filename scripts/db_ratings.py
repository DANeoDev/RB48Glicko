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


def set_calibration(connection, player_id, rating, rd, sigma):
    connection.execute("""
        INSERT INTO calibrations (player_id, rating, rd, sigma)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(player_id) DO UPDATE SET
            rating = excluded.rating,
            rd = excluded.rd,
            sigma = excluded.sigma
    """, (player_id, rating, rd, sigma))
    connection.commit()


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


def get_match_ratings(connection, match_id):
    rows = connection.execute("""
        SELECT player_id, rating_type, rating, rd, sigma
        FROM match_ratings
        WHERE match_id = ?
    """, (match_id,)).fetchall()

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
            matches.pitch,
            match_ratings.rating_type,
            match_ratings.rating
        FROM match_ratings
        JOIN matches
            ON match_ratings.match_id = matches.match_id
        JOIN match_players
            ON match_ratings.match_id = match_players.match_id
            AND match_ratings.player_id = match_players.player_id
        WHERE match_ratings.player_id = ?
        AND (
            match_ratings.rating_type = 'total'
            OR match_ratings.rating_type = matches.pitch
        )
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

    current_ratings = connection.execute("""
        SELECT
            rating_type,
            rating
        FROM ratings
        WHERE player_id = ?
    """, (player_id,)).fetchall()

    for row in current_ratings:
        last_entry = (
            history[row["rating_type"]][-1]
            if history[row["rating_type"]]
            else None
        )

        history[row["rating_type"]].append({
            "match_id": None,
            "date": last_entry["date"] if last_entry else None,
            "rating": row["rating"]
        })

    return history
