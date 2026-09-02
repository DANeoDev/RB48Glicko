import os
from pathlib import Path
import sqlite3

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def get_accounts_db_file():
    override = os.environ.get("RB48_ACCOUNTS_DATABASE_FILE")
    return Path(override) if override else PROJECT_ROOT / "data" / "accounts.db"


def get_accounts_connection():
    """Return a connection to the separate account database with foreign keys enabled."""
    db_file = get_accounts_db_file()
    db_file.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_file)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    create_account_tables(connection)
    return connection


def create_account_tables(connection):
    """Create the initial account tables if they do not exist yet and run migrations."""
    connection.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user'
                CHECK (role IN ('user', 'admin', 'webmaster')),
            email_verified INTEGER NOT NULL DEFAULT 0,
            is_approved INTEGER NOT NULL DEFAULT 0,
            attendance_name TEXT,
            avatar_file TEXT,
            psychology_test_passed INTEGER NOT NULL DEFAULT 0,
            psychology_test_date TEXT,
            psychology_persona TEXT,
            player_id INTEGER,
            pending_player_id INTEGER,
            created_at TEXT NOT NULL
        )
    """)
    connection.execute("""
        CREATE TABLE IF NOT EXISTS email_verification_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            token_hash TEXT NOT NULL UNIQUE,
            expires_at TEXT NOT NULL,
            used_at TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)
    connection.execute("""
        CREATE TABLE IF NOT EXISTS noise_bubbles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            page_path TEXT NOT NULL,
            match_id INTEGER,
            pos_x_percent REAL NOT NULL,
            pos_y_percent REAL NOT NULL,
            content TEXT NOT NULL,
            bg_color TEXT NOT NULL DEFAULT '#7B52C5',
            font_family TEXT NOT NULL DEFAULT 'Inter',
            font_size INTEGER NOT NULL DEFAULT 15,
            created_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)

    # Column migrations for existing tables
    cursor = connection.execute("PRAGMA table_info(users)")
    existing_columns = {row["name"] for row in cursor.fetchall()}

    if "is_approved" not in existing_columns:
        connection.execute("ALTER TABLE users ADD COLUMN is_approved INTEGER NOT NULL DEFAULT 0")
        connection.execute("UPDATE users SET is_approved = 1 WHERE role IN ('admin', 'webmaster')")
    if "attendance_name" not in existing_columns:
        connection.execute("ALTER TABLE users ADD COLUMN attendance_name TEXT")
    if "avatar_file" not in existing_columns:
        connection.execute("ALTER TABLE users ADD COLUMN avatar_file TEXT")
    if "psychology_test_passed" not in existing_columns:
        connection.execute("ALTER TABLE users ADD COLUMN psychology_test_passed INTEGER NOT NULL DEFAULT 0")
    if "psychology_test_date" not in existing_columns:
        connection.execute("ALTER TABLE users ADD COLUMN psychology_test_date TEXT")
    if "psychology_persona" not in existing_columns:
        connection.execute("ALTER TABLE users ADD COLUMN psychology_persona TEXT")
    if "player_id" not in existing_columns:
        connection.execute("ALTER TABLE users ADD COLUMN player_id INTEGER")
    if "pending_player_id" not in existing_columns:
        connection.execute("ALTER TABLE users ADD COLUMN pending_player_id INTEGER")
    if "noise_display_mode" not in existing_columns:
        connection.execute("ALTER TABLE users ADD COLUMN noise_display_mode TEXT NOT NULL DEFAULT 'smart'")

    connection.commit()


def get_user_by_id(connection, user_id):
    """Retrieve full user profile by user id."""
    return connection.execute(
        """
        SELECT
            id,
            username,
            email,
            password_hash,
            role,
            email_verified,
            is_approved,
            attendance_name,
            avatar_file,
            psychology_test_passed,
            psychology_test_date,
            psychology_persona,
            player_id,
            pending_player_id,
            noise_display_mode,
            created_at
        FROM users
        WHERE id = ?
        """,
        (user_id,),
    ).fetchone()


def get_user_by_login(connection, login):
    """Retrieve user profile by username or email."""
    return connection.execute(
        """
        SELECT
            id,
            username,
            email,
            password_hash,
            role,
            email_verified,
            is_approved,
            attendance_name,
            avatar_file,
            psychology_test_passed,
            psychology_test_date,
            psychology_persona,
            player_id,
            pending_player_id,
            noise_display_mode,
            created_at
        FROM users
        WHERE lower(username) = lower(?) OR lower(email) = lower(?)
        """,
        (login, login),
    ).fetchone()


def get_user_by_email(connection, email):
    """Retrieve user profile by exact email."""
    return connection.execute(
        """
        SELECT
            id,
            username,
            email,
            password_hash,
            role,
            email_verified,
            is_approved,
            attendance_name,
            avatar_file,
            psychology_test_passed,
            psychology_test_date,
            psychology_persona,
            player_id,
            pending_player_id,
            noise_display_mode,
            created_at
        FROM users
        WHERE lower(email) = lower(?)
        """,
        (email,),
    ).fetchone()


def get_user_by_player_id(connection, player_id):
    """Retrieve user account linked to a specific player ID."""
    return connection.execute(
        """
        SELECT
            id,
            username,
            email,
            role,
            email_verified,
            is_approved,
            attendance_name,
            avatar_file,
            psychology_persona,
            player_id,
            pending_player_id
        FROM users
        WHERE player_id = ?
        LIMIT 1
        """,
        (player_id,),
    ).fetchone()


def get_all_users(connection):
    """Retrieve all users ordered by creation date."""
    return connection.execute(
        """
        SELECT
            id,
            username,
            email,
            role,
            email_verified,
            is_approved,
            attendance_name,
            avatar_file,
            psychology_test_passed,
            psychology_persona,
            player_id,
            pending_player_id,
            created_at
        FROM users
        ORDER BY id DESC
        """
    ).fetchall()


def get_pending_users(connection):
    """Retrieve verified users waiting for manual Webmaster approval."""
    return connection.execute(
        """
        SELECT
            id,
            username,
            email,
            role,
            email_verified,
            attendance_name,
            pending_player_id,
            created_at
        FROM users
        WHERE is_approved = 0 AND role = 'user'
        ORDER BY id DESC
        """
    ).fetchall()


def create_user(connection, username, email, password_hash, created_at, role="user", is_approved=0, attendance_name=None):
    """Insert a new user account."""
    if role in ("admin", "webmaster"):
        is_approved = 1
    if not attendance_name:
        attendance_name = username
    cursor = connection.execute(
        """
        INSERT INTO users (
            username,
            email,
            password_hash,
            role,
            is_approved,
            attendance_name,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (username, email, password_hash, role, is_approved, attendance_name, created_at),
    )
    connection.commit()
    return cursor.lastrowid


def username_or_email_exists(connection, username, email):
    """Check if username or email already exists."""
    row = connection.execute(
        """
        SELECT 1
        FROM users
        WHERE lower(username) = lower(?) OR lower(email) = lower(?)
        LIMIT 1
        """,
        (username, email),
    ).fetchone()
    return row is not None


def mark_email_verified(connection, user_id):
    """Mark an account as email verified."""
    connection.execute(
        "UPDATE users SET email_verified = 1 WHERE id = ?",
        (user_id,),
    )
    connection.commit()


def approve_user(connection, user_id, approved=True):
    """Grant or revoke manual Webmaster approval for a user."""
    connection.execute(
        "UPDATE users SET is_approved = ? WHERE id = ?",
        (1 if approved else 0, user_id),
    )
    connection.commit()


def set_user_attendance_name(connection, user_id, attendance_name):
    """Update user's attendance display name."""
    connection.execute(
        "UPDATE users SET attendance_name = ? WHERE id = ?",
        (attendance_name.strip(), user_id),
    )
    connection.commit()


def update_user_profile(connection, user_id, attendance_name=None, avatar_file=None):
    """Update general profile settings."""
    updates = []
    params = []
    if attendance_name is not None:
        updates.append("attendance_name = ?")
        params.append(attendance_name.strip())
    if avatar_file is not None:
        updates.append("avatar_file = ?")
        params.append(avatar_file if avatar_file else None)

    if updates:
        params.append(user_id)
        connection.execute(
            f"UPDATE users SET {', '.join(updates)} WHERE id = ?",
            tuple(params),
        )
        connection.commit()


def request_player_link(connection, user_id, player_id):
    """Submit a request to link account to a player ID (or disconnect)."""
    if not player_id:
        connection.execute(
            "UPDATE users SET player_id = NULL, pending_player_id = NULL WHERE id = ?",
            (user_id,),
        )
    else:
        connection.execute(
            "UPDATE users SET pending_player_id = ? WHERE id = ?",
            (player_id, user_id),
        )
    connection.commit()


def approve_player_link(connection, user_id):
    """Webmaster approves pending player link."""
    connection.execute(
        """
        UPDATE users
        SET player_id = pending_player_id, pending_player_id = NULL
        WHERE id = ? AND pending_player_id IS NOT NULL
        """,
        (user_id,),
    )
    connection.commit()


def reject_player_link(connection, user_id):
    """Webmaster rejects pending player link."""
    connection.execute(
        "UPDATE users SET pending_player_id = NULL WHERE id = ?",
        (user_id,),
    )
    connection.commit()


def update_user_password(connection, user_id, password_hash):
    """Update user account password."""
    connection.execute(
        "UPDATE users SET password_hash = ? WHERE id = ?",
        (password_hash, user_id),
    )
    connection.commit()


def set_psychology_test_status(connection, user_id, passed, test_date):
    """Update user's psychology test status and date."""
    connection.execute(
        """
        UPDATE users
        SET psychology_test_passed = ?, psychology_test_date = ?
        WHERE id = ?
        """,
        (1 if passed else 0, test_date, user_id),
    )
    connection.commit()


def set_user_persona(connection, user_id, persona_key, passed, test_date):
    """Update user's assigned psychology persona archetype, pass status, and test date."""
    connection.execute(
        """
        UPDATE users
        SET psychology_persona = ?, psychology_test_passed = ?, psychology_test_date = ?
        WHERE id = ?
        """,
        (persona_key, 1 if passed else 0, test_date, user_id),
    )
    connection.commit()


def update_user_role(connection, user_id, role):
    """Update a user's role (user, admin, webmaster)."""
    if role not in ("user", "admin", "webmaster"):
        raise ValueError(f"Invalid role: {role}")
    connection.execute(
        """
        UPDATE users
        SET role = ?, is_approved = CASE WHEN ? IN ('admin', 'webmaster') THEN 1 ELSE is_approved END
        WHERE id = ?
        """,
        (role, role, user_id),
    )
    connection.commit()


def link_user_to_player(connection, user_id, player_id):
    """Directly link a user account to a player ID."""
    connection.execute(
        "UPDATE users SET player_id = ?, pending_player_id = NULL WHERE id = ?",
        (player_id, user_id),
    )
    connection.commit()


def backup_and_delete_user(connection, user_id):
    """Save an archival SQLite backup to data/backups/accounts/ and delete the user account."""
    from datetime import datetime

    user = get_user_by_id(connection, user_id)
    if not user:
        return None, None

    db_file = get_accounts_db_file()
    backup_dir = PROJECT_ROOT / "data" / "backups" / "accounts"
    backup_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_filename = f"accounts_backup_{timestamp}.db"
    backup_path = backup_dir / backup_filename

    # Commit any active transactions
    connection.commit()

    # Create full SQLite backup
    if db_file.exists():
        backup_conn = sqlite3.connect(backup_path)
        connection.backup(backup_conn)
        backup_conn.close()

    # Delete verification tokens and user
    connection.execute("DELETE FROM email_verification_tokens WHERE user_id = ?", (user_id,))
    connection.execute("DELETE FROM users WHERE id = ?", (user_id,))
    connection.commit()

    return user, backup_filename


def add_noise_bubble(
    connection,
    user_id,
    page_path,
    pos_x_percent,
    pos_y_percent,
    content,
    match_id=None,
    bg_color="#7B52C5",
    font_family="Inter",
    font_size=15,
):
    """Add a new noise bubble on a page, applying the 3-bubble quota FIFO eviction for regular users."""
    from datetime import datetime, timezone

    user = get_user_by_id(connection, user_id)
    if not user:
        raise ValueError("User not found.")

    # Quota check: regular users max 3, staff max 5 active non-match bubbles
    if match_id is None:
        max_bubbles = 5 if user["role"] in ("admin", "webmaster") else 3
        active_bubbles = connection.execute(
            """
            SELECT id FROM noise_bubbles
            WHERE user_id = ? AND match_id IS NULL
            ORDER BY id ASC
            """,
            (user_id,),
        ).fetchall()

        # If already at max (or more), evict oldest so total remains at max after insert
        if len(active_bubbles) >= max_bubbles:
            to_remove_count = len(active_bubbles) - (max_bubbles - 1)
            to_remove_ids = [b["id"] for b in active_bubbles[:to_remove_count]]
            for b_id in to_remove_ids:
                connection.execute("DELETE FROM noise_bubbles WHERE id = ?", (b_id,))

    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    cursor = connection.execute(
        """
        INSERT INTO noise_bubbles (
            user_id, page_path, match_id, pos_x_percent, pos_y_percent,
            content, bg_color, font_family, font_size, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            page_path,
            match_id,
            float(pos_x_percent),
            float(pos_y_percent),
            content.strip(),
            bg_color,
            font_family,
            int(font_size),
            now_iso,
        ),
    )
    connection.commit()
    return cursor.lastrowid


def get_noise_bubbles_for_page(connection, page_path, match_id=None):
    """Retrieve all noise bubbles for a specific page path or match."""
    query = """
        SELECT
            b.id,
            b.user_id,
            b.page_path,
            b.match_id,
            b.pos_x_percent,
            b.pos_y_percent,
            b.content,
            b.bg_color,
            b.font_family,
            b.font_size,
            b.created_at,
            u.username,
            u.avatar_file,
            u.attendance_name,
            u.role
        FROM noise_bubbles b
        JOIN users u ON b.user_id = u.id
        WHERE b.page_path = ?
    """
    params = [page_path]
    if match_id is not None:
        query += " AND b.match_id = ?"
        params.append(match_id)

    query += " ORDER BY b.id ASC"
    rows = connection.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def get_noise_bubble_by_id(connection, bubble_id):
    """Retrieve a single noise bubble by id."""
    row = connection.execute(
        """
        SELECT
            b.id,
            b.user_id,
            b.page_path,
            b.match_id,
            b.pos_x_percent,
            b.pos_y_percent,
            b.content,
            b.bg_color,
            b.font_family,
            b.font_size,
            b.created_at,
            u.username,
            u.avatar_file,
            u.attendance_name,
            u.role
        FROM noise_bubbles b
        JOIN users u ON b.user_id = u.id
        WHERE b.id = ?
        """,
        (bubble_id,),
    ).fetchone()
    return dict(row) if row else None


def delete_noise_bubble(connection, bubble_id, user_id=None, is_staff=False):
    """Delete a noise bubble if requested by its author or staff (admin/webmaster)."""
    bubble = get_noise_bubble_by_id(connection, bubble_id)
    if not bubble:
        return False

    if not is_staff and bubble["user_id"] != user_id:
        return False

    connection.execute("DELETE FROM noise_bubbles WHERE id = ?", (bubble_id,))
    connection.commit()
    return True


def update_noise_bubble_position(connection, bubble_id, pos_x_percent, pos_y_percent, user_id=None, is_staff=False):
    """Update position of a bubble if user is author or staff."""
    bubble = get_noise_bubble_by_id(connection, bubble_id)
    if not bubble:
        return False

    if not is_staff and bubble["user_id"] != user_id:
        return False

    connection.execute(
        """
        UPDATE noise_bubbles
        SET pos_x_percent = ?, pos_y_percent = ?
        WHERE id = ?
        """,
        (float(pos_x_percent), float(pos_y_percent), bubble_id),
    )
    connection.commit()
    return True


def set_user_noise_display_mode(connection, user_id, mode):
    """Update user's preferred noise display mode ('transparent', 'always_expanded', 'hidden')."""
    if mode in ("smart", "always_indicators"):
        mode = "transparent"
    elif mode == "always_show":
        mode = "always_expanded"
    valid_modes = ("transparent", "always_expanded", "hidden")
    mode = mode if mode in valid_modes else "transparent"
    connection.execute(
        "UPDATE users SET noise_display_mode = ? WHERE id = ?",
        (mode, user_id),
    )
    connection.commit()


