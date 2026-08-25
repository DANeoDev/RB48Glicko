def get_players(connection):
    cursor = connection.execute("""
        SELECT player_id
        FROM players
        ORDER BY player_id
    """)

    players = {}

    for (player_id,) in cursor:
        players[player_id] = {
            "aliases": [],
            "positions": []
        }

    cursor = connection.execute("""
        SELECT alias, player_id
        FROM aliases
    """)

    for alias, player_id in cursor:
        players[player_id]["aliases"].append(alias)

    cursor = connection.execute("""
        SELECT player_id, position, is_primary
        FROM positions
    """)

    for player_id, position, is_primary in cursor:
        if is_primary:
            position += "*"

        players[player_id]["positions"].append(position)

    return players

def get_next_player_id(connection):

    cursor = connection.execute("""
        SELECT COALESCE(MAX(player_id), 0) + 1
        FROM players
    """)

    return cursor.fetchone()[0]


def get_alias_lookup(connection):

    cursor = connection.execute("""
        SELECT alias, player_id
        FROM aliases
    """)

    return {
        alias: player_id
        for alias, player_id in cursor
    }


def get_ignored_aliases(connection):

    cursor = connection.execute("""
        SELECT alias
        FROM ignored_aliases
    """)

    return {
        alias
        for (alias,) in cursor
    }


def create_player(connection, player_id):

    connection.execute("""
        INSERT INTO players (player_id)
        VALUES (?)
    """, (player_id,))


def add_alias(connection, alias, player_id):

    connection.execute("""
        INSERT INTO aliases (alias, player_id)
        VALUES (?, ?)
    """, (alias, player_id))


def add_position(
    connection,
    player_id,
    position,
    is_primary=False
):

    connection.execute("""
        INSERT INTO positions (
            player_id,
            position,
            is_primary
        )
        VALUES (?, ?, ?)
    """, (
        player_id,
        position,
        int(is_primary)
    ))


def add_ignored_alias(connection, alias):

    connection.execute("""
        INSERT INTO ignored_aliases (alias)
        VALUES (?)
    """, (alias,))