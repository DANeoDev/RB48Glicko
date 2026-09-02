from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import sqlite3

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def get_planner_db_file():
    override = os.environ.get("RB48_PLANNER_DATABASE_FILE")
    return Path(override) if override else PROJECT_ROOT / "data" / "planner.db"


def get_planner_connection():
    """Return a connection to the planner database with foreign keys enabled."""
    db_file = get_planner_db_file()
    db_file.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_file)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    create_planner_tables(connection)
    return connection


def create_planner_tables(connection):
    """Create events and attendees tables if they do not exist."""
    connection.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_date TEXT NOT NULL,
            pitch TEXT NOT NULL CHECK (pitch IN ('box', 'hf', 'custom')),
            max_players INTEGER NOT NULL,
            title TEXT,
            location TEXT,
            status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'completed', 'cancelled')),
            created_at TEXT NOT NULL
        )
    """)

    # Migrate legacy events table if pitch constraint only allowed ('box', 'hf')
    table_sql = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='events'"
    ).fetchone()
    if table_sql and table_sql[0] and "CHECK (pitch IN ('box', 'hf'))" in table_sql[0]:
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute("ALTER TABLE events RENAME TO events_old")
        connection.execute("""
            CREATE TABLE events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_date TEXT NOT NULL,
                pitch TEXT NOT NULL CHECK (pitch IN ('box', 'hf', 'custom')),
                max_players INTEGER NOT NULL,
                title TEXT,
                location TEXT,
                status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'completed', 'cancelled')),
                created_at TEXT NOT NULL
            )
        """)
        connection.execute("INSERT INTO events SELECT * FROM events_old")
        connection.execute("DROP TABLE events_old")
        connection.execute("PRAGMA foreign_keys = ON")
        connection.commit()

    connection.execute("""
        CREATE TABLE IF NOT EXISTS attendees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id INTEGER NOT NULL,
            user_id INTEGER,
            name TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('attending', 'declined')),
            is_guest INTEGER NOT NULL DEFAULT 0,
            registered_by_user_id INTEGER,
            guest_index INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE
        )
    """)
    connection.commit()


def create_event(connection, event_date, pitch, title=None, location=None, max_players=None, created_at=None):
    """Create a new upcoming match event."""
    pitch = pitch.lower()
    if pitch not in ("box", "hf", "custom"):
        raise ValueError(f"Invalid pitch type: {pitch}")
    if max_players is None:
        if pitch == "box":
            max_players = 12
        elif pitch == "hf":
            max_players = 18
        else:
            max_players = 12
    if created_at is None:
        created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    cursor = connection.execute(
        """
        INSERT INTO events (event_date, pitch, max_players, title, location, status, created_at)
        VALUES (?, ?, ?, ?, ?, 'open', ?)
        """,
        (event_date, pitch, max_players, title, location, created_at),
    )
    connection.commit()
    return cursor.lastrowid


def add_standard_wednesday_events(connection, count=4):
    """Add standard Wednesday matchdays starting with alternating pitch after the latest open event.

    - BOX: 20:00 at Soccerbox - Uni Sport (capacity: 12)
    - HF: 20:30 at Halbfeld - Zülpicher Wall 5 (capacity: 18)
    """
    latest_event = connection.execute(
        """
        SELECT event_date, pitch
        FROM events
        WHERE status = 'open'
        ORDER BY event_date DESC, id DESC
        LIMIT 1
        """
    ).fetchone()

    if latest_event:
        try:
            date_str = latest_event["event_date"]
            if "T" in date_str:
                last_dt = datetime.fromisoformat(date_str)
            elif " " in date_str:
                last_dt = datetime.strptime(date_str, "%Y-%m-%d %H:%M")
            else:
                last_dt = datetime.strptime(date_str, "%Y-%m-%d")
        except Exception:
            last_dt = datetime.now()

        base_date = last_dt.date()
        last_pitch = latest_event["pitch"].lower()
        next_pitch = "hf" if last_pitch == "box" else "box"
    else:
        base_date = datetime.now().date()
        next_pitch = "box"

    # Find the first Wednesday strictly after base_date (weekday 2)
    days_ahead = (2 - base_date.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7

    first_wed = base_date + timedelta(days=days_ahead)
    created_ids = []

    current_pitch = next_pitch
    for i in range(count):
        wed_date = first_wed + timedelta(weeks=i)
        if current_pitch == "box":
            time_str = "20:00"
            location = "Soccerbox - Uni Sport"
            max_players = 12
            title = "RB48 BOX Matchday"
        else:
            time_str = "20:30"
            location = "Halbfeld - Zülpicher Wall 5"
            max_players = 18
            title = "RB48 HF Matchday"

        date_formatted = f"{wed_date.strftime('%Y-%m-%d')} {time_str}"
        event_id = create_event(
            connection,
            event_date=date_formatted,
            pitch=current_pitch,
            title=title,
            location=location,
            max_players=max_players,
        )
        created_ids.append(event_id)
        current_pitch = "hf" if current_pitch == "box" else "box"

    return created_ids


def get_upcoming_events(connection, limit=10):
    """Retrieve upcoming open events ordered by event_date ASC."""
    return connection.execute(
        """
        SELECT id, event_date, pitch, max_players, title, location, status, created_at
        FROM events
        WHERE status = 'open'
        ORDER BY event_date ASC, id ASC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()


def get_event_by_id(connection, event_id):
    """Retrieve a single event by ID."""
    return connection.execute(
        """
        SELECT id, event_date, pitch, max_players, title, location, status, created_at
        FROM events
        WHERE id = ?
        """,
        (event_id,),
    ).fetchone()


def delete_event(connection, event_id):
    """Delete an event and its attendees."""
    connection.execute("DELETE FROM events WHERE id = ?", (event_id,))
    connection.commit()


def get_event_attendees(connection, event_id):
    """Retrieve all attendee records for an event ordered chronologically."""
    return connection.execute(
        """
        SELECT id, event_id, user_id, name, status, is_guest, registered_by_user_id, guest_index, created_at
        FROM attendees
        WHERE event_id = ?
        ORDER BY created_at ASC, id ASC
        """,
        (event_id,),
    ).fetchall()


def get_user_event_rsvp(connection, event_id, user_id):
    """Get the specific member's direct RSVP for an event."""
    return connection.execute(
        """
        SELECT id, event_id, user_id, name, status, is_guest, created_at
        FROM attendees
        WHERE event_id = ? AND user_id = ? AND is_guest = 0
        LIMIT 1
        """,
        (event_id, user_id),
    ).fetchone()


def get_user_registered_guests(connection, event_id, user_id):
    """Get the list of guests registered by a specific member for an event."""
    return connection.execute(
        """
        SELECT id, event_id, user_id, name, status, is_guest, registered_by_user_id, guest_index, created_at
        FROM attendees
        WHERE event_id = ? AND registered_by_user_id = ? AND is_guest = 1
        ORDER BY guest_index ASC, id ASC
        """,
        (event_id, user_id),
    ).fetchall()


def set_user_rsvp(connection, event_id, user_id, display_name, status):
    """Set or update a member's direct attendance status (attending or declined)."""
    if status not in ("attending", "declined"):
        raise ValueError(f"Invalid status: {status}")

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    existing = get_user_event_rsvp(connection, event_id, user_id)

    if existing:
        connection.execute(
            """
            UPDATE attendees
            SET status = ?, name = ?, created_at = ?
            WHERE id = ?
            """,
            (status, display_name, now, existing["id"]),
        )
    else:
        connection.execute(
            """
            INSERT INTO attendees (event_id, user_id, name, status, is_guest, registered_by_user_id, guest_index, created_at)
            VALUES (?, ?, ?, ?, 0, NULL, 0, ?)
            """,
            (event_id, user_id, display_name, status, now),
        )
    connection.commit()


def cancel_user_rsvp(connection, event_id, user_id):
    """Remove a member's direct RSVP record."""
    connection.execute(
        """
        DELETE FROM attendees
        WHERE event_id = ? AND user_id = ? AND is_guest = 0
        """,
        (event_id, user_id),
    )
    connection.commit()


def add_guest_rsvp(connection, event_id, guest_name, registered_by_user_id=None, registered_by_name=None):
    """Add a guest player to the event.

    - If visitor: guest_name + ' (Guest)'
    - If registered by user: guest_name + ' (registered_by_name +N)'
    """
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    if registered_by_user_id:
        # Count existing guests registered by this user for this event to determine +1, +2 etc
        existing_guests = get_user_registered_guests(connection, event_id, registered_by_user_id)
        next_index = len(existing_guests) + 1
        formatted_name = f"{guest_name} ({registered_by_name} +{next_index})"
    else:
        next_index = 0
        formatted_name = f"{guest_name} (Guest)"

    cursor = connection.execute(
        """
        INSERT INTO attendees (event_id, user_id, name, status, is_guest, registered_by_user_id, guest_index, created_at)
        VALUES (?, NULL, ?, 'attending', 1, ?, ?, ?)
        """,
        (event_id, formatted_name, registered_by_user_id, next_index, now),
    )
    connection.commit()
    return cursor.lastrowid


def remove_attendee(connection, attendee_id):
    """Delete a specific attendee entry by attendee ID."""
    connection.execute("DELETE FROM attendees WHERE id = ?", (attendee_id,))
    connection.commit()


def backup_and_clear_all_events(connection):
    """Back up planner database to data/backups/upcoming_matchdates/ and wipe working copy."""
    from datetime import datetime

    db_file = get_planner_db_file()
    backup_dir = PROJECT_ROOT / "data" / "backups" / "upcoming_matchdates"
    backup_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_filename = f"planner_backup_{timestamp}.db"
    backup_path = backup_dir / backup_filename

    # Commit any active transactions
    connection.commit()

    # Create full SQLite backup
    if db_file.exists():
        backup_conn = sqlite3.connect(backup_path)
        connection.backup(backup_conn)
        backup_conn.close()

    # Wipe working copy
    connection.execute("DELETE FROM attendees")
    connection.execute("DELETE FROM events")
    connection.commit()
    connection.execute("VACUUM")

    return backup_filename

