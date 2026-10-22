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
        ORDER BY is_primary DESC, rowid ASC
    """)

    for alias, player_id in cursor:
        players[player_id]["aliases"].append(alias)

    cursor = connection.execute("""
        SELECT player_id, position, is_primary
        FROM positions
    """)

    for player_id, position, is_primary in cursor:
        pos_clean = position.replace("*", "").strip().upper()
        if is_primary:
            pos_formatted = pos_clean + "*"
        else:
            pos_formatted = pos_clean

        if pos_formatted not in players[player_id]["positions"]:
            players[player_id]["positions"].append(pos_formatted)

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
    try:
        cursor = connection.execute("""
            SELECT alias
            FROM ignored_aliases
        """)
        return {
            alias
            for (alias,) in cursor
        }
    except Exception:
        return set()


def create_player(connection, player_id):

    connection.execute("""
        INSERT INTO players (player_id)
        VALUES (?)
    """, (player_id,))


def add_alias(connection, alias, player_id, is_primary=False):
    alias_clean = alias.strip()
    if not alias_clean:
        raise ValueError("Alias cannot be empty.")
    count_row = connection.execute("SELECT COUNT(*) FROM aliases WHERE player_id = ?", (player_id,)).fetchone()
    count = count_row[0] if count_row else 0
    is_prim = 1 if (is_primary or count == 0) else 0

    if is_prim:
        connection.execute("UPDATE aliases SET is_primary = 0 WHERE player_id = ?", (player_id,))

    connection.execute("""
        INSERT INTO aliases (alias, player_id, is_primary)
        VALUES (?, ?, ?)
    """, (alias_clean, player_id, is_prim))


def add_position(
    connection,
    player_id,
    position,
    is_primary=False
):
    pos_clean = position.replace("*", "").strip().upper()
    connection.execute("""
        INSERT OR REPLACE INTO positions (
            player_id,
            position,
            is_primary
        )
        VALUES (?, ?, ?)
    """, (
        player_id,
        pos_clean,
        int(is_primary)
    ))


def set_player_positions(connection, player_id, positions, primary_position=None):
    """Set all positions for a player, replacing any existing positions."""
    connection.execute("DELETE FROM positions WHERE player_id = ?", (player_id,))

    clean_primary = primary_position.replace("*", "").strip().upper() if primary_position else None

    clean_positions = set()
    for pos in positions:
        pos_clean = pos.replace("*", "").strip().upper()
        if pos_clean in ("GK", "DEF", "MID", "ATT"):
            clean_positions.add(pos_clean)

    if clean_primary and clean_primary in ("GK", "DEF", "MID", "ATT"):
        clean_positions.add(clean_primary)

    for pos_clean in sorted(clean_positions):
        is_primary = 1 if (clean_primary and pos_clean == clean_primary) else 0
        connection.execute(
            """
            INSERT INTO positions (player_id, position, is_primary)
            VALUES (?, ?, ?)
            """,
            (player_id, pos_clean, is_primary),
        )
    connection.commit()


def add_ignored_alias(connection, alias):

    connection.execute("""
        INSERT OR IGNORE INTO ignored_aliases (alias)
        VALUES (?)
    """, (alias,))


def delete_ignored_alias(connection, alias):
    """Remove an alias from the ignored_aliases table."""
    connection.execute("DELETE FROM ignored_aliases WHERE alias = ?", (alias,))
    connection.commit()


def ensure_ignored_alias_as_guest_player(connection, alias: str) -> int:
    """
    Ensure that an ignored alias exists as a registered player in players & aliases.
    If it already exists in aliases, returns the existing player_id.
    If not, creates a new player_id, adds the alias, and removes it from ignored_aliases.
    """
    alias_clean = alias.strip()
    if not alias_clean:
        raise ValueError("Alias cannot be empty.")

    alias_lookup = get_alias_lookup(connection)
    if alias_clean in alias_lookup:
        return alias_lookup[alias_clean]

    player_id = get_next_player_id(connection)
    create_player(connection, player_id)
    add_alias(connection, alias_clean, player_id)
    delete_ignored_alias(connection, alias_clean)
    connection.commit()
    return player_id


def set_primary_alias(connection, player_id: int, primary_alias: str):
    """Set the specified alias as primary for a player, unsetting any others."""
    primary_clean = primary_alias.strip()
    row = connection.execute(
        "SELECT alias FROM aliases WHERE alias = ? AND player_id = ?",
        (primary_clean, player_id),
    ).fetchone()
    if not row:
        raise ValueError(f"Alias '{primary_clean}' does not belong to player #{player_id}.")
    connection.execute(
        "UPDATE aliases SET is_primary = CASE WHEN alias = ? THEN 1 ELSE 0 END WHERE player_id = ?",
        (primary_clean, player_id),
    )
    connection.commit()


def update_alias(connection, old_alias: str, new_alias: str):
    """Rename an existing alias."""
    old_clean = old_alias.strip()
    new_clean = new_alias.strip()
    if not old_clean or not new_clean:
        raise ValueError("Alias name cannot be empty.")
    if old_clean == new_clean:
        return
    existing = connection.execute(
        "SELECT player_id FROM aliases WHERE alias = ?",
        (new_clean,),
    ).fetchone()
    if existing:
        raise ValueError(f"Alias '{new_clean}' is already in use by player #{existing[0]}.")
    connection.execute(
        "UPDATE aliases SET alias = ? WHERE alias = ?",
        (new_clean, old_clean),
    )
    connection.commit()


def delete_alias(connection, alias: str):
    """Delete an alias. Cannot delete if it is the only alias of a player."""
    alias_clean = alias.strip()
    row = connection.execute(
        "SELECT player_id, is_primary FROM aliases WHERE alias = ?",
        (alias_clean,),
    ).fetchone()
    if not row:
        raise ValueError(f"Alias '{alias_clean}' not found.")
    player_id, is_primary = row[0], row[1]
    count = connection.execute(
        "SELECT COUNT(*) FROM aliases WHERE player_id = ?",
        (player_id,),
    ).fetchone()[0]
    if count <= 1:
        raise ValueError("Cannot delete the only alias of a player. A player must have at least one alias.")
    connection.execute("DELETE FROM aliases WHERE alias = ?", (alias_clean,))
    if is_primary:
        next_alias = connection.execute(
            "SELECT alias FROM aliases WHERE player_id = ? ORDER BY rowid ASC LIMIT 1",
            (player_id,),
        ).fetchone()
        if next_alias:
            connection.execute(
                "UPDATE aliases SET is_primary = 1 WHERE alias = ?",
                (next_alias[0],),
            )
    connection.commit()


def get_player_aliases(connection, player_id: int):
    """Return all aliases of a player ordered with primary alias first."""
    rows = connection.execute("""
        SELECT alias, is_primary
        FROM aliases
        WHERE player_id = ?
        ORDER BY is_primary DESC, rowid ASC
    """, (player_id,)).fetchall()
    return [{"alias": r[0], "is_primary": bool(r[1])} for r in rows]


def get_player_primary_name(connection, player_id: int) -> str | None:
    """Return the primary alias/name of a player, or first alias, or None if not found."""
    if not player_id:
        return None
    row = connection.execute("""
        SELECT alias
        FROM aliases
        WHERE player_id = ?
        ORDER BY is_primary DESC, rowid ASC
        LIMIT 1
    """, (player_id,)).fetchone()
    return row[0] if row else None


