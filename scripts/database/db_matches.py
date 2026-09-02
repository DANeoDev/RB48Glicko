"""Database operations for match results and participant records."""

from scripts.glicko.glicko2 import TOTAL, HF, BOX


def get_matches(connection):
    cursor = connection.execute("""
        SELECT match_id, date, pitch, players_a, players_b, goals_a, goals_b
        FROM matches
        ORDER BY match_id
    """)

    matches = {}
    for row in cursor:
        matches[row["match_id"]] = {
            "match_id": row["match_id"],
            "date": row["date"],
            "pitch": row["pitch"],
            "players_a": int(row["players_a"]),
            "players_b": int(row["players_b"]),
            "goals_a": int(row["goals_a"]),
            "goals_b": int(row["goals_b"]),
        }
    return matches


def match_exists(connection, match_id):
    cursor = connection.execute(
        "SELECT 1 FROM matches WHERE match_id = ?",
        (match_id,),
    )
    return cursor.fetchone() is not None


def create_match(
    connection,
    match_id,
    match_date,
    pitch,
    players_a,
    players_b,
    goals_a,
    goals_b,
):
    connection.execute(
        """
        INSERT INTO matches (
            match_id,
            date,
            pitch,
            players_a,
            players_b,
            goals_a,
            goals_b
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            match_id,
            match_date,
            pitch,
            players_a,
            players_b,
            goals_a,
            goals_b,
        ),
    )
    connection.commit()


def add_match_player(connection, match_id, player_id, team):
    connection.execute(
        """
        INSERT INTO match_players (match_id, player_id, team)
        VALUES (?, ?, ?)
        """,
        (match_id, player_id, team),
    )
    connection.commit()


def get_match_players(connection, match_id):
    cursor = connection.execute(
        """
        SELECT player_id, team
        FROM match_players
        WHERE match_id = ?
        """,
        (match_id,),
    )
    return [{"player_id": row["player_id"], "team": row["team"]} for row in cursor]


def get_match_teams(connection, match_id):
    players = get_match_players(connection, match_id)
    team_a = [p["player_id"] for p in players if p["team"] == "a"]
    team_b = [p["player_id"] for p in players if p["team"] == "b"]
    return team_a, team_b


def get_player_stats(connection):
    cursor = connection.execute("""
        SELECT
            m.match_id,
            m.pitch,
            m.goals_a,
            m.goals_b,
            mp.player_id,
            mp.team
        FROM matches m
        JOIN match_players mp
            ON m.match_id = mp.match_id
        ORDER BY m.match_id
    """)

    stats = {}
    for row in cursor:
        player_id = row["player_id"]
        pitch = row["pitch"]
        goals_a = row["goals_a"]
        goals_b = row["goals_b"]
        team = row["team"]

        if player_id not in stats:
            stats[player_id] = {
                TOTAL: {"games": 0, "wins": 0, "draws": 0, "losses": 0},
                BOX: {"games": 0, "wins": 0, "draws": 0, "losses": 0},
                HF: {"games": 0, "wins": 0, "draws": 0, "losses": 0},
            }

        if goals_a == goals_b:
            result = "draw"
        elif (team == "a" and goals_a > goals_b) or (team == "b" and goals_b > goals_a):
            result = "win"
        else:
            result = "loss"

        stats[player_id][TOTAL]["games"] += 1
        stats[player_id][pitch]["games"] += 1

        result_key = "wins" if result == "win" else "draws" if result == "draw" else "losses"
        stats[player_id][TOTAL][result_key] += 1
        stats[player_id][pitch][result_key] += 1

    for player_stats in stats.values():
        for rating_type in (TOTAL, BOX, HF):
            games = player_stats[rating_type]["games"]
            wins = player_stats[rating_type]["wins"]
            player_stats[rating_type]["win_percent"] = (wins / games * 100) if games else 0

    return stats
