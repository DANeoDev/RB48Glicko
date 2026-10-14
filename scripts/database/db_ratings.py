from datetime import datetime


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


def get_all_match_ratings(connection):
    """Return a mapping of match_id -> {player_id -> {rating_type -> {rating, rd, sigma}}} in a single query."""
    rows = connection.execute("""
        SELECT match_id, player_id, rating_type, rating, rd, sigma
        FROM match_ratings
        ORDER BY match_id
    """).fetchall()

    all_ratings = {}
    for row in rows:
        mid = row["match_id"]
        pid = row["player_id"]
        rtype = row["rating_type"]

        if mid not in all_ratings:
            all_ratings[mid] = {}
        if pid not in all_ratings[mid]:
            all_ratings[mid][pid] = {}

        all_ratings[mid][pid][rtype] = {
            "rating": row["rating"],
            "rd": row["rd"],
            "sigma": row["sigma"]
        }

    return all_ratings


def get_processed_match_ids(connection):
    rows = connection.execute("""
        SELECT DISTINCT match_id
        FROM match_ratings
    """).fetchall()

    return {
        row["match_id"]
        for row in rows
    }


def ensure_player_discovery_ratings_table(connection):
    connection.execute("""
        CREATE TABLE IF NOT EXISTS player_discovery_ratings (
            player_id INTEGER NOT NULL,
            match_id TEXT NOT NULL,
            rating_type TEXT NOT NULL,
            rating REAL NOT NULL,
            rd REAL NOT NULL,
            sigma REAL NOT NULL,
            PRIMARY KEY (player_id, match_id, rating_type),
            FOREIGN KEY (player_id) REFERENCES players(player_id),
            FOREIGN KEY (match_id) REFERENCES matches(match_id)
        )
    """)
    connection.commit()


def save_player_discovery_ratings(connection, discovery_records):
    """
    Persist discovery trajectory records for provisional matches.
    discovery_records can be a list of tuples: (player_id, match_id, rating_type, rating, rd, sigma)
    or a list of dicts.
    """
    ensure_player_discovery_ratings_table(connection)
    if not discovery_records:
        return
    for rec in discovery_records:
        if isinstance(rec, (list, tuple)):
            pid, mid, rtype, r, rd, sigma = rec
        else:
            pid = rec["player_id"]
            mid = rec["match_id"]
            rtype = rec["rating_type"]
            r = rec["rating"]
            rd = rec["rd"]
            sigma = rec["sigma"]
        connection.execute("""
            INSERT INTO player_discovery_ratings (player_id, match_id, rating_type, rating, rd, sigma)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(player_id, match_id, rating_type) DO UPDATE SET
                rating = excluded.rating,
                rd = excluded.rd,
                sigma = excluded.sigma
        """, (pid, mid, rtype, r, rd, sigma))
    connection.commit()


def get_all_player_discovery_ratings(connection):
    """Return mapping of match_id -> {player_id -> {rating_type -> {rating, rd, sigma}}} from player_discovery_ratings."""
    ensure_player_discovery_ratings_table(connection)
    rows = connection.execute("""
        SELECT match_id, player_id, rating_type, rating, rd, sigma
        FROM player_discovery_ratings
        ORDER BY match_id
    """).fetchall()

    discovery = {}
    for row in rows:
        mid = row["match_id"]
        pid = row["player_id"]
        rtype = row["rating_type"]
        if mid not in discovery:
            discovery[mid] = {}
        if pid not in discovery[mid]:
            discovery[mid][pid] = {}
        discovery[mid][pid][rtype] = {
            "rating": row["rating"],
            "rd": row["rd"],
            "sigma": row["sigma"]
        }
    return discovery


def get_effective_player_match_ratings(connection):
    """
    Return all match ratings with player discovery ratings overlaid.
    Used for player-level profile graphs, personal match events, and delta baselines.
    """
    all_mr = get_all_match_ratings(connection)
    all_disc = get_all_player_discovery_ratings(connection)
    if not all_disc:
        return all_mr
    effective = {}
    for mid, p_dict in all_mr.items():
        effective[mid] = {}
        for pid, r_dict in p_dict.items():
            effective[mid][pid] = dict(r_dict)
            if mid in all_disc and pid in all_disc[mid]:
                for rtype, r_val in all_disc[mid][pid].items():
                    effective[mid][pid][rtype] = r_val
    return effective


def get_player_rating_history(connection, player_id):
    ensure_player_discovery_ratings_table(connection)
    rows = connection.execute("""
        SELECT
            match_ratings.match_id,
            matches.date,
            matches.pitch,
            match_ratings.rating_type,
            COALESCE(pdr.rating, match_ratings.rating) AS rating
        FROM match_ratings
        JOIN matches
            ON match_ratings.match_id = matches.match_id
        JOIN match_players
            ON match_ratings.match_id = match_players.match_id
            AND match_ratings.player_id = match_players.player_id
        LEFT JOIN player_discovery_ratings pdr
            ON match_ratings.player_id = pdr.player_id
            AND match_ratings.match_id = pdr.match_id
            AND match_ratings.rating_type = pdr.rating_type
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


def get_player_calibrated_priors(connection):
    """
    Return a mapping of player_id -> {rating_type -> {rating, rd, sigma, threshold, is_auto, calibrated_at}}.
    Ensures table exists if not yet created.
    """
    connection.execute("""
        CREATE TABLE IF NOT EXISTS player_calibrated_priors (
            player_id INTEGER NOT NULL,
            rating_type TEXT NOT NULL,
            rating REAL NOT NULL,
            rd REAL NOT NULL,
            sigma REAL NOT NULL,
            threshold INTEGER NOT NULL,
            is_auto INTEGER NOT NULL DEFAULT 1,
            calibrated_at TEXT NOT NULL,
            PRIMARY KEY (player_id, rating_type),
            FOREIGN KEY (player_id) REFERENCES players(player_id)
        )
    """)
    rows = connection.execute("""
        SELECT player_id, rating_type, rating, rd, sigma, threshold, is_auto, calibrated_at
        FROM player_calibrated_priors
        ORDER BY player_id, rating_type
    """).fetchall()

    priors = {}
    for row in rows:
        pid = row["player_id"]
        rtype = row["rating_type"]
        if pid not in priors:
            priors[pid] = {}
        priors[pid][rtype] = {
            "rating": row["rating"],
            "rd": row["rd"],
            "sigma": row["sigma"],
            "threshold": row["threshold"],
            "is_auto": row["is_auto"],
            "calibrated_at": row["calibrated_at"],
        }
    return priors


def save_player_calibrated_priors(connection, priors, thresholds=None, is_auto=1, calibrated_at=None):
    """
    Persist discovered or updated calibrated priors for players across rating types.
    priors can be either:
      - dict of player_id -> {rating_type: {"rating": float, "rd": float, "sigma": float, ...}}
      - dict of player_id -> {rating_type: Rating(...)}
      - dict of player_id -> Rating(...)  (interpreted as TOTAL prior)
    thresholds can optionally be provided as a dict of player_id -> int.
    Also syncs the TOTAL rating to the legacy calibrations table.
    """
    connection.execute("""
        CREATE TABLE IF NOT EXISTS player_calibrated_priors (
            player_id INTEGER NOT NULL,
            rating_type TEXT NOT NULL,
            rating REAL NOT NULL,
            rd REAL NOT NULL,
            sigma REAL NOT NULL,
            threshold INTEGER NOT NULL,
            is_auto INTEGER NOT NULL DEFAULT 1,
            calibrated_at TEXT NOT NULL,
            PRIMARY KEY (player_id, rating_type),
            FOREIGN KEY (player_id) REFERENCES players(player_id)
        )
    """)
    cal_time = calibrated_at or datetime.now().isoformat()
    thresholds = thresholds or {}

    for player_id, p_val in priors.items():
        thresh = thresholds.get(player_id, 15)
        # Check structure: dict of rating_types or single Rating/dict
        if isinstance(p_val, dict) and any(k in ("total", "box", "hf") for k in p_val.keys()):
            for rtype, r_data in p_val.items():
                r = r_data["rating"] if isinstance(r_data, dict) else r_data.rating
                rd = r_data["rd"] if isinstance(r_data, dict) else r_data.rd
                sigma = r_data["sigma"] if isinstance(r_data, dict) else r_data.sigma
                p_thresh = r_data.get("threshold", thresh) if isinstance(r_data, dict) else thresh
                connection.execute("""
                    INSERT INTO player_calibrated_priors (player_id, rating_type, rating, rd, sigma, threshold, is_auto, calibrated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(player_id, rating_type) DO UPDATE SET
                        rating = excluded.rating,
                        rd = excluded.rd,
                        sigma = excluded.sigma,
                        threshold = excluded.threshold,
                        is_auto = excluded.is_auto,
                        calibrated_at = excluded.calibrated_at
                """, (player_id, rtype, r, rd, sigma, p_thresh, is_auto, cal_time))
                if rtype == "total":
                    set_calibration(connection, player_id, r, rd, sigma)
        else:
            r = p_val["rating"] if isinstance(p_val, dict) else p_val.rating
            rd = p_val["rd"] if isinstance(p_val, dict) else p_val.rd
            sigma = p_val["sigma"] if isinstance(p_val, dict) else p_val.sigma
            for rtype in ("total", "box", "hf"):
                connection.execute("""
                    INSERT INTO player_calibrated_priors (player_id, rating_type, rating, rd, sigma, threshold, is_auto, calibrated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(player_id, rating_type) DO UPDATE SET
                        rating = excluded.rating,
                        rd = excluded.rd,
                        sigma = excluded.sigma,
                        threshold = excluded.threshold,
                        is_auto = excluded.is_auto,
                        calibrated_at = excluded.calibrated_at
                """, (player_id, rtype, r, rd, sigma, thresh, is_auto, cal_time))
            set_calibration(connection, player_id, r, rd, sigma)
    connection.commit()
