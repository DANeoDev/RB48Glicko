def get_matches(connection):
    cursor = connection.execute("""
        SELECT match_id, date, pitch, players_a, players_b, goals_a, goals_b
        FROM matches
        ORDER BY match_id
    """)

    matches = {}

    for row in cursor:
        (
            match_id,
            date,
            pitch,
            players_a,
            players_b,
            goals_a,
            goals_b
        ) = row

        matches[match_id] = {
            "match_id": match_id,
            "date": date,
            "pitch": pitch,
            "players_a": int(players_a),
            "players_b": int(players_b),
            "goals_a": goals_a,
            "goals_b": goals_b
        }

    return matches


def match_exists(connection, match_id):
    cursor = connection.execute("""
        SELECT 1
        FROM matches
        WHERE match_id = ?
    """, (match_id,))

    return cursor.fetchone() is not None


def create_match(
    connection,
    match_id,
    date,
    pitch,
    players_a,
    players_b,
    goals_a,
    goals_b
):
    connection.execute("""
        INSERT INTO matches (
            match_id,
            date,
            pitch,
            players_a,
            players_b,
            goals_a,
            goals_b
        )
        VALUES (?, ?, ?, ?, ?,?,?)
    """, (
        match_id,
        date,
        pitch,
        players_a,
        players_b,
        goals_a,
        goals_b
    ))

    connection.commit()


def add_match_player(
    connection,
    match_id,
    player_id,
    team
):
    connection.execute("""
        INSERT INTO match_players (
            match_id,
            player_id,
            team
        )
        VALUES (?, ?, ?)
    """, (
        match_id,
        player_id,
        team
    ))

    connection.commit()


def get_match_players(connection, match_id):
    cursor = connection.execute("""
        SELECT player_id, team
        FROM match_players
        WHERE match_id = ?
    """, (match_id,))

    return [
        {
            "player_id": player_id,
            "team": team
        }
        for player_id, team in cursor
    ]

def get_match_teams(connection, match_id):
    players = get_match_players(connection, match_id)

    team_a = []
    team_b = []

    for player in players:
        if player["team"] == "a":
            team_a.append(player["player_id"])
        elif player["team"] == "b":
            team_b.append(player["player_id"])

    return team_a, team_b