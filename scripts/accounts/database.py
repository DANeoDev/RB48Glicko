import os
from pathlib import Path
import sqlite3
from datetime import datetime, timedelta
from urllib.parse import urlparse, parse_qs
from zoneinfo import ZoneInfo
from scripts.utils.timezone import (
    COLOGNE_TZ,
    get_cologne_now,
    get_cologne_timestamp_str,
    get_cologne_file_timestamp,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def get_accounts_db_file():
    override = os.environ.get("RB48_ACCOUNTS_DATABASE_FILE")
    return Path(override) if override else PROJECT_ROOT / "data" / "accounts.db"


_INITIALIZED_ACCOUNT_DBS = set()


def get_accounts_connection():
    """Return a connection to the separate account database with foreign keys enabled."""
    db_file = get_accounts_db_file().resolve()
    db_file.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_file)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    if db_file not in _INITIALIZED_ACCOUNT_DBS:
        create_account_tables(connection)
        _INITIALIZED_ACCOUNT_DBS.add(db_file)
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
            glicko_opt_out INTEGER NOT NULL DEFAULT 0,
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
            text_color TEXT NOT NULL DEFAULT '#ffffff',
            font_family TEXT NOT NULL DEFAULT 'Inter',
            font_size INTEGER NOT NULL DEFAULT 15,
            created_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)
    connection.execute("""
        CREATE TABLE IF NOT EXISTS user_noise_overrides (
            user_id INTEGER NOT NULL,
            bubble_id INTEGER NOT NULL,
            custom_x_percent REAL,
            custom_y_percent REAL,
            is_dismissed INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (user_id, bubble_id),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (bubble_id) REFERENCES noise_bubbles(id) ON DELETE CASCADE
        )
    """)
    connection.execute("""
        CREATE TABLE IF NOT EXISTS gallery_photos (
            filename TEXT PRIMARY KEY,
            uploader_user_id INTEGER,
            uploader_username TEXT,
            capture_date TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (uploader_user_id) REFERENCES users(id) ON DELETE SET NULL
        )
    """)
    connection.execute("""
        CREATE TABLE IF NOT EXISTS user_seen_achievements (
            user_id INTEGER NOT NULL,
            achievement_key TEXT NOT NULL,
            seen_at TEXT NOT NULL,
            PRIMARY KEY (user_id, achievement_key),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)
    connection.execute("""
        CREATE TABLE IF NOT EXISTS player_unlocked_achievements (
            player_id INTEGER NOT NULL,
            achievement_key TEXT NOT NULL,
            unlocked_at TEXT NOT NULL,
            PRIMARY KEY (player_id, achievement_key)
        )
    """)
    connection.execute("""
        CREATE TABLE IF NOT EXISTS webmaster_notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            user_id INTEGER,
            username TEXT NOT NULL,
            details TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
        )
    """)
    connection.execute("""
        CREATE TABLE IF NOT EXISTS webmaster_seen_notifications (
            webmaster_user_id INTEGER NOT NULL,
            notification_id INTEGER NOT NULL,
            seen_at TEXT NOT NULL,
            PRIMARY KEY (webmaster_user_id, notification_id),
            FOREIGN KEY (webmaster_user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (notification_id) REFERENCES webmaster_notifications(id) ON DELETE CASCADE
        )
    """)
    connection.execute("""
        CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            category TEXT NOT NULL,
            message TEXT NOT NULL,
            page_url TEXT,
            viewport TEXT,
            screen_res TEXT,
            touch_support INTEGER NOT NULL DEFAULT 0,
            user_agent TEXT,
            status TEXT NOT NULL DEFAULT 'open',
            created_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
        )
    """)
    connection.execute("""
        CREATE TABLE IF NOT EXISTS match_mvp_votes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id TEXT NOT NULL,
            voter_user_id INTEGER NOT NULL,
            voted_player_id INTEGER NOT NULL,
            voted_player_id_2 INTEGER,
            voted_player_id_3 INTEGER,
            created_at TEXT NOT NULL,
            UNIQUE(match_id, voter_user_id),
            FOREIGN KEY (voter_user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)
    connection.execute("""
        CREATE INDEX IF NOT EXISTS idx_match_mvp_votes_match ON match_mvp_votes(match_id)
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
        connection.execute("ALTER TABLE users ADD COLUMN noise_display_mode TEXT NOT NULL DEFAULT 'collapsed'")
    if "glicko_opt_out" not in existing_columns:
        connection.execute("ALTER TABLE users ADD COLUMN glicko_opt_out INTEGER NOT NULL DEFAULT 0")

    bubble_cursor = connection.execute("PRAGMA table_info(noise_bubbles)")
    existing_bubble_cols = {row["name"] for row in bubble_cursor.fetchall()}
    if "text_color" not in existing_bubble_cols:
        connection.execute("ALTER TABLE noise_bubbles ADD COLUMN text_color TEXT NOT NULL DEFAULT '#ffffff'")

    mvp_cursor = connection.execute("PRAGMA table_info(match_mvp_votes)")
    existing_mvp_cols = {row["name"] for row in mvp_cursor.fetchall()}
    if "voted_player_id_2" not in existing_mvp_cols:
        connection.execute("ALTER TABLE match_mvp_votes ADD COLUMN voted_player_id_2 INTEGER")
    if "voted_player_id_3" not in existing_mvp_cols:
        connection.execute("ALTER TABLE match_mvp_votes ADD COLUMN voted_player_id_3 INTEGER")

    # Normalize existing dashboard/index bubbles to root '/'
    connection.execute("UPDATE noise_bubbles SET page_path = '/' WHERE page_path IN ('/dashboard', '/index', '/dashboard/', '/index/')")

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
            glicko_opt_out,
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
            glicko_opt_out,
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
            glicko_opt_out,
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
            pending_player_id,
            glicko_opt_out
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
            glicko_opt_out,
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


def update_user_profile(connection, user_id, attendance_name=None, avatar_file=None, glicko_opt_out=None):
    """Update general profile settings."""
    updates = []
    params = []
    if attendance_name is not None:
        updates.append("attendance_name = ?")
        params.append(attendance_name.strip())
    if avatar_file is not None:
        updates.append("avatar_file = ?")
        params.append(avatar_file if avatar_file else None)
    if glicko_opt_out is not None:
        updates.append("glicko_opt_out = ?")
        params.append(1 if glicko_opt_out else 0)

    if updates:
        params.append(user_id)
        connection.execute(
            f"UPDATE users SET {', '.join(updates)} WHERE id = ?",
            tuple(params),
        )
        connection.commit()


def get_opted_out_player_ids(connection) -> set:
    """Return set of player_ids that have opted out of Glicko-2 rating visibility."""
    rows = connection.execute(
        "SELECT player_id FROM users WHERE glicko_opt_out = 1 AND player_id IS NOT NULL"
    ).fetchall()
    return {row["player_id"] for row in rows}


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


def unlink_player(connection, user_id):
    """Remove player profile connection and pending connection for user."""
    connection.execute(
        "UPDATE users SET player_id = NULL, pending_player_id = NULL WHERE id = ?",
        (user_id,),
    )
    connection.commit()


def set_user_access_level(connection, user_id, access_level):
    """Update user access level (visitor, user, glicko_user, admin, webmaster)."""
    now_str = get_cologne_timestamp_str()

    if access_level == "visitor":
        connection.execute(
            "UPDATE users SET role = 'user', is_approved = 0 WHERE id = ?",
            (user_id,),
        )
    elif access_level == "user":
        connection.execute(
            """
            UPDATE users
            SET role = 'user', email_verified = 1, is_approved = 1, psychology_test_passed = 0, glicko_opt_out = 0
            WHERE id = ?
            """,
            (user_id,),
        )
    elif access_level == "glicko_user":
        connection.execute(
            """
            UPDATE users
            SET role = 'user', email_verified = 1, is_approved = 1, psychology_test_passed = 1, psychology_test_date = COALESCE(psychology_test_date, ?), glicko_opt_out = 0
            WHERE id = ?
            """,
            (now_str, user_id),
        )
    elif access_level == "admin":
        connection.execute(
            """
            UPDATE users
            SET role = 'admin', email_verified = 1, is_approved = 1, psychology_test_passed = 1, psychology_test_date = COALESCE(psychology_test_date, ?), glicko_opt_out = 0
            WHERE id = ?
            """,
            (now_str, user_id),
        )
    elif access_level == "webmaster":
        connection.execute(
            """
            UPDATE users
            SET role = 'webmaster', email_verified = 1, is_approved = 1, psychology_test_passed = 1, psychology_test_date = COALESCE(psychology_test_date, ?), glicko_opt_out = 0
            WHERE id = ?
            """,
            (now_str, user_id),
        )
    else:
        raise ValueError(f"Invalid access level: {access_level}")
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

    timestamp = get_cologne_file_timestamp()
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


def normalize_noise_page_path(path):
    """Normalize page paths so that root, /dashboard, and /index map to '/', and /matches preserves ?page=X (for X > 1)."""
    if not path:
        return "/"
    p = str(path).strip()
    if p in ("/dashboard", "/index", "", "/dashboard/", "/index/"):
        return "/"
    parsed = urlparse(p)
    pathname = parsed.path.rstrip("/") if (parsed.path and parsed.path != "/") else "/"
    if pathname in ("/dashboard", "/index", ""):
        return "/"
    if pathname == "/matches":
        qs = parse_qs(parsed.query)
        page_val = qs.get("page", [None])[0]
        if page_val:
            try:
                page_num = int(page_val)
                if page_num > 1:
                    return f"/matches?page={page_num}"
            except (ValueError, TypeError):
                pass
        return "/matches"
    return pathname or "/"


def add_noise_bubble(
    connection,
    user_id,
    page_path,
    pos_x_percent,
    pos_y_percent,
    content,
    match_id=None,
    bg_color="#7B52C5",
    text_color="#ffffff",
    font_family="Inter",
    font_size=15,
):
    """Add a new noise bubble on a page, applying the quota FIFO eviction for general pages."""
    from datetime import datetime, timezone

    user = get_user_by_id(connection, user_id)
    if not user:
        raise ValueError("User not found.")

    page_path = normalize_noise_page_path(page_path)

    # Quota check: bubbles on match history (/matches or match_id) stay forever without quota eviction.
    # On other pages, limit is 5 active bubbles for everyone (FIFO eviction).
    is_match_history_page = (match_id is not None) or (page_path and str(page_path).startswith("/matches"))
    if not is_match_history_page:
        max_bubbles = 5
        active_bubbles = connection.execute(
            """
            SELECT id FROM noise_bubbles
            WHERE user_id = ? AND match_id IS NULL AND page_path NOT LIKE '/matches%'
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
            content, bg_color, text_color, font_family, font_size, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            page_path,
            match_id,
            float(pos_x_percent),
            float(pos_y_percent),
            content.strip(),
            bg_color,
            text_color,
            font_family,
            int(font_size),
            now_iso,
        ),
    )
    connection.commit()
    return cursor.lastrowid


def get_noise_bubbles_for_page(connection, page_path, viewer_user_id=None, match_id=None):
    """Retrieve all noise bubbles for a specific page path, applying viewer's custom positions & dismissing."""
    page_path = normalize_noise_page_path(page_path)

    if page_path == "/":
        path_clause = "b.page_path IN ('/', '/dashboard', '/index')"
        params = [viewer_user_id]
    else:
        path_clause = "b.page_path = ?"
        params = [viewer_user_id, page_path]

    query = f"""
        SELECT
            b.id,
            b.user_id,
            b.page_path,
            b.match_id,
            COALESCE(o.custom_x_percent, b.pos_x_percent) AS pos_x_percent,
            COALESCE(o.custom_y_percent, b.pos_y_percent) AS pos_y_percent,
            b.content,
            b.bg_color,
            b.text_color,
            b.font_family,
            b.font_size,
            b.created_at,
            u.username,
            u.avatar_file,
            u.attendance_name,
            u.role
        FROM noise_bubbles b
        JOIN users u ON b.user_id = u.id
        LEFT JOIN user_noise_overrides o ON b.id = o.bubble_id AND o.user_id = ?
        WHERE {path_clause} AND (o.is_dismissed IS NULL OR o.is_dismissed = 0)
    """
    if match_id is not None:
        query += " AND b.match_id = ?"
        params.append(match_id)

    query += " ORDER BY b.id ASC"
    rows = connection.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def get_noise_bubble_by_id(connection, bubble_id, viewer_user_id=None):
    """Retrieve a single noise bubble by id."""
    row = connection.execute(
        """
        SELECT
            b.id,
            b.user_id,
            b.page_path,
            b.match_id,
            COALESCE(o.custom_x_percent, b.pos_x_percent) AS pos_x_percent,
            COALESCE(o.custom_y_percent, b.pos_y_percent) AS pos_y_percent,
            b.content,
            b.bg_color,
            b.text_color,
            b.font_family,
            b.font_size,
            b.created_at,
            u.username,
            u.avatar_file,
            u.attendance_name,
            u.role
        FROM noise_bubbles b
        JOIN users u ON b.user_id = u.id
        LEFT JOIN user_noise_overrides o ON b.id = o.bubble_id AND o.user_id = ?
        WHERE b.id = ?
        """,
        (viewer_user_id, bubble_id),
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


def set_user_noise_override(connection, user_id, bubble_id, custom_x=None, custom_y=None, is_dismissed=0):
    """Save a user's personal position override or local dismissal for a bubble."""
    connection.execute(
        """
        INSERT INTO user_noise_overrides (user_id, bubble_id, custom_x_percent, custom_y_percent, is_dismissed)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(user_id, bubble_id) DO UPDATE SET
            custom_x_percent = COALESCE(excluded.custom_x_percent, user_noise_overrides.custom_x_percent),
            custom_y_percent = COALESCE(excluded.custom_y_percent, user_noise_overrides.custom_y_percent),
            is_dismissed = excluded.is_dismissed
        """,
        (user_id, bubble_id, custom_x, custom_y, is_dismissed),
    )
    connection.commit()


def dismiss_noise_for_user(connection, user_id, bubble_id):
    """Dismiss a bubble from a specific user's view."""
    set_user_noise_override(connection, user_id, bubble_id, is_dismissed=1)


def update_noise_bubble_position(connection, bubble_id, pos_x_percent, pos_y_percent, user_id=None, is_staff=False, global_update=False):
    """Update position of a bubble. If global_update and (author or staff), updates base position; otherwise saves user override."""
    bubble = get_noise_bubble_by_id(connection, bubble_id)
    if not bubble:
        return False

    if global_update and (is_staff or bubble["user_id"] == user_id):
        connection.execute(
            """
            UPDATE noise_bubbles
            SET pos_x_percent = ?, pos_y_percent = ?
            WHERE id = ?
            """,
            (float(pos_x_percent), float(pos_y_percent), bubble_id),
        )
        connection.commit()

    if user_id:
        set_user_noise_override(connection, user_id, bubble_id, custom_x=float(pos_x_percent), custom_y=float(pos_y_percent), is_dismissed=0)

    return True


def set_user_noise_display_mode(connection, user_id, mode):
    """Update user's preferred noise display mode ('collapsed', 'expanded', 'muted')."""
    if mode in ("transparent", "smart", "always_indicators", "collapsed"):
        mode = "collapsed"
    elif mode in ("always_expanded", "always_show", "expanded"):
        mode = "expanded"
    elif mode in ("hidden", "muted"):
        mode = "muted"
    else:
        mode = "collapsed"

    connection.execute(
        "UPDATE users SET noise_display_mode = ? WHERE id = ?",
        (mode, user_id),
    )
    connection.commit()
    return mode


def get_user_authored_noise_bubbles(connection, user_id):
    """Retrieve all noise bubbles authored by a specific user."""
    rows = connection.execute(
        """
        SELECT
            id,
            user_id,
            page_path,
            match_id,
            pos_x_percent,
            pos_y_percent,
            content,
            bg_color,
            text_color,
            font_family,
            font_size,
            created_at
        FROM noise_bubbles
        WHERE user_id = ?
        ORDER BY id DESC
        """,
        (user_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def shift_match_history_noise_bubbles(connection=None, shift_slots=1, total_slots=12):
    """
    Shift all noise bubbles on the match history page by the specified number of game slots.
    Each slot corresponds to (100.0 / total_slots)% vertical distance (approx 8.333% for 12 slots).
    Positive shift_slots (e.g. +1 on match creation) pushes bubbles downward.
    If a bubble's Y position reaches or exceeds 100%, it overflows to the next page (p -> p + 1, y -> y - 100%).
    Negative shift_slots (e.g. -1 on match deletion) pulls bubbles upward.
    If a bubble's Y position falls below 0% and p > 1, it pulls back to the previous page (p -> p - 1, y -> y + 100%).
    If p == 1 and y < 0%, y is clamped to 0.0%.
    Updates both noise_bubbles base positions and any user_noise_overrides.
    """
    if shift_slots == 0:
        return 0

    close_conn = False
    if connection is None:
        connection = get_accounts_connection()
        close_conn = True

    try:
        delta_y = float(shift_slots) * (100.0 / float(total_slots))
        rows = connection.execute(
            """
            SELECT id, page_path, pos_y_percent
            FROM noise_bubbles
            WHERE page_path = '/matches' OR page_path LIKE '/matches?%'
            """
        ).fetchall()

        updated_count = 0
        for row in rows:
            b_id = row["id"]
            current_path = row["page_path"]
            current_y = float(row["pos_y_percent"])

            p = 1
            if "?page=" in current_path:
                try:
                    p = int(current_path.split("?page=")[1].split("&")[0])
                except (ValueError, IndexError):
                    p = 1

            p_old = p
            y_new = current_y + delta_y

            # Overflow: bubble pushed beneath designated game entry area
            while y_new >= 100.0:
                p += 1
                y_new -= 100.0

            # Underflow: bubble pulled above designated game entry area
            while y_new < 0.0 and p > 1:
                p -= 1
                y_new += 100.0

            if y_new < 0.0:
                y_new = 0.0

            new_y = round(y_new, 2)
            new_path = f"/matches?page={p}" if p > 1 else "/matches"

            connection.execute(
                """
                UPDATE noise_bubbles
                SET page_path = ?, pos_y_percent = ?
                WHERE id = ?
                """,
                (new_path, new_y, b_id),
            )

            # Also shift user overrides in sync
            delta_p = p - p_old
            overrides = connection.execute(
                "SELECT user_id, custom_y_percent FROM user_noise_overrides WHERE bubble_id = ? AND custom_y_percent IS NOT NULL",
                (b_id,),
            ).fetchall()
            for ov in overrides:
                u_id = ov["user_id"]
                ov_y = float(ov["custom_y_percent"])
                ov_y_new = ov_y + delta_y - (float(delta_p) * 100.0)
                ov_y_new = max(0.0, min(100.0, round(ov_y_new, 2)))
                connection.execute(
                    "UPDATE user_noise_overrides SET custom_y_percent = ? WHERE user_id = ? AND bubble_id = ?",
                    (ov_y_new, u_id, b_id),
                )

            updated_count += 1

        connection.commit()
        return updated_count
    finally:
        if close_conn:
            connection.close()


def record_gallery_photo(connection, filename, uploader_user_id=None, uploader_username=None, capture_date=None):
    """Store or update metadata for an uploaded gallery photo."""
    now_iso = get_cologne_timestamp_str()
    connection.execute("""
        INSERT INTO gallery_photos (filename, uploader_user_id, uploader_username, capture_date, created_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(filename) DO UPDATE SET
            uploader_user_id = COALESCE(excluded.uploader_user_id, gallery_photos.uploader_user_id),
            uploader_username = COALESCE(excluded.uploader_username, gallery_photos.uploader_username),
            capture_date = COALESCE(excluded.capture_date, gallery_photos.capture_date)
    """, (filename, uploader_user_id, uploader_username, capture_date, now_iso))
    connection.commit()


def get_gallery_photo_metadata(connection, filename):
    """Retrieve metadata for a specific gallery photo."""
    row = connection.execute("""
        SELECT filename, uploader_user_id, uploader_username, capture_date, created_at
        FROM gallery_photos
        WHERE filename = ?
    """, (filename,)).fetchone()
    return dict(row) if row else None


def get_all_gallery_photos_metadata(connection):
    """Retrieve all gallery photo metadata keyed by filename."""
    rows = connection.execute("""
        SELECT filename, uploader_user_id, uploader_username, capture_date, created_at
        FROM gallery_photos
    """).fetchall()
    return {r["filename"]: dict(r) for r in rows}


def update_gallery_photo_date(connection, filename, capture_date_str):
    """Update or insert the capture date for a gallery photo."""
    now_iso = get_cologne_timestamp_str()
    connection.execute("""
        INSERT INTO gallery_photos (filename, capture_date, created_at)
        VALUES (?, ?, ?)
        ON CONFLICT(filename) DO UPDATE SET
            capture_date = excluded.capture_date
    """, (filename, capture_date_str, now_iso))
    connection.commit()


def delete_gallery_photo_record(connection, filename):
    """Remove gallery photo record upon deletion."""
    connection.execute("DELETE FROM gallery_photos WHERE filename = ?", (filename,))
    connection.commit()




def get_user_seen_achievements(connection, user_id: int) -> set:
    """Return set of achievement keys that the user has already viewed."""
    rows = connection.execute("""
        SELECT achievement_key FROM user_seen_achievements WHERE user_id = ?
    """, (user_id,)).fetchall()
    return {r["achievement_key"] for r in rows}


def mark_user_achievements_seen(connection, user_id: int, achievement_keys):
    """Mark a collection of achievement keys as seen for a user."""
    if not achievement_keys:
        return
    now_iso = get_cologne_timestamp_str()
    connection.executemany("""
        INSERT OR IGNORE INTO user_seen_achievements (user_id, achievement_key, seen_at)
        VALUES (?, ?, ?)
    """, [(user_id, str(k), now_iso) for k in achievement_keys])
    connection.commit()


def get_approved_linked_players(connection) -> set:
    """Return set of player_ids for all approved users with a linked player account."""
    rows = connection.execute("""
        SELECT DISTINCT player_id FROM users
        WHERE player_id IS NOT NULL AND (is_approved = 1 OR role IN ('admin', 'webmaster'))
    """).fetchall()
    return {r["player_id"] for r in rows}


def record_player_unlocked_achievement(connection, player_id: int, achievement_key: str):
    """Record that a player has unlocked a specific achievement key."""
    if not player_id or not achievement_key:
        return
    now_iso = get_cologne_timestamp_str()
    connection.execute("""
        INSERT OR IGNORE INTO player_unlocked_achievements (player_id, achievement_key, unlocked_at)
        VALUES (?, ?, ?)
    """, (player_id, str(achievement_key), now_iso))
    connection.commit()


def has_player_unlocked_achievement(connection, player_id: int, achievement_key: str) -> bool:
    """Check if a player has ever unlocked a specific achievement key."""
    if not player_id or not achievement_key:
        return False
    row = connection.execute("""
        SELECT 1 FROM player_unlocked_achievements
        WHERE player_id = ? AND achievement_key = ?
    """, (player_id, str(achievement_key))).fetchone()
    return row is not None


def record_webmaster_notification(
    connection,
    event_type: str,
    user_id: int | None,
    username: str,
    details: str,
) -> int:
    """
    Record an administrative event for Webmaster visibility.
    event_type: 'user_registered', 'opt_out_changed', 'status_changed', 'player_link_requested', etc.
    """
    now_iso = get_cologne_timestamp_str()
    cursor = connection.execute("""
        INSERT INTO webmaster_notifications (event_type, user_id, username, details, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (event_type, user_id, username, details, now_iso))
    connection.commit()
    return cursor.lastrowid


def get_webmaster_notifications(
    connection,
    webmaster_user_id: int | None = None,
    limit: int = 50,
) -> list[dict]:
    """
    Retrieve chronological recent webmaster notifications with seen flag for a webmaster user.
    """
    if webmaster_user_id is not None:
        rows = connection.execute("""
            SELECT
                n.id,
                n.event_type,
                n.user_id,
                n.username,
                n.details,
                n.created_at,
                CASE WHEN s.seen_at IS NOT NULL THEN 1 ELSE 0 END AS is_seen
            FROM webmaster_notifications n
            LEFT JOIN webmaster_seen_notifications s
                ON n.id = s.notification_id AND s.webmaster_user_id = ?
            ORDER BY n.id DESC
            LIMIT ?
        """, (webmaster_user_id, limit)).fetchall()
    else:
        rows = connection.execute("""
            SELECT
                id,
                event_type,
                user_id,
                username,
                details,
                created_at,
                0 AS is_seen
            FROM webmaster_notifications
            ORDER BY id DESC
            LIMIT ?
        """, (limit,)).fetchall()

    return [dict(r) for r in rows]


def get_unseen_webmaster_notifications_count(connection, webmaster_user_id: int) -> int:
    """
    Count unseen webmaster notifications for a specific webmaster account.
    """
    row = connection.execute("""
        SELECT COUNT(*) AS unseen_count
        FROM webmaster_notifications n
        LEFT JOIN webmaster_seen_notifications s
            ON n.id = s.notification_id AND s.webmaster_user_id = ?
        WHERE s.seen_at IS NULL
    """, (webmaster_user_id,)).fetchone()
    return int(row["unseen_count"]) if row else 0


def mark_webmaster_notifications_seen(
    connection,
    webmaster_user_id: int,
    notification_ids: list[int] | None = None,
):
    """
    Mark specific or all webmaster notifications as seen by a webmaster user.
    """
    now_iso = get_cologne_timestamp_str()
    if notification_ids is None:
        # Mark all currently unread notifications as seen
        connection.execute("""
            INSERT OR IGNORE INTO webmaster_seen_notifications (webmaster_user_id, notification_id, seen_at)
            SELECT ?, id, ?
            FROM webmaster_notifications
        """, (webmaster_user_id, now_iso))
    else:
        if not notification_ids:
            return
        connection.executemany("""
            INSERT OR IGNORE INTO webmaster_seen_notifications (webmaster_user_id, notification_id, seen_at)
            VALUES (?, ?, ?)
        """, [(webmaster_user_id, nid, now_iso) for nid in notification_ids])
    connection.commit()


def delete_webmaster_notification(connection, notification_id: int) -> bool:
    """
    Delete a single webmaster notification record.
    """
    connection.execute("DELETE FROM webmaster_seen_notifications WHERE notification_id = ?", (notification_id,))
    cursor = connection.execute("DELETE FROM webmaster_notifications WHERE id = ?", (notification_id,))
    connection.commit()
    return cursor.rowcount > 0


def clear_all_webmaster_notifications(connection):
    """
    Delete all webmaster notification records.
    """
    connection.execute("DELETE FROM webmaster_seen_notifications")
    connection.execute("DELETE FROM webmaster_notifications")
    connection.commit()


# =========================================================================
# Feedback System Helpers
# =========================================================================

def create_feedback_entry(
    connection,
    category: str,
    message: str,
    user_id: int | None = None,
    username: str | None = None,
    page_url: str | None = None,
    viewport: str | None = None,
    screen_res: str | None = None,
    touch_support: int = 0,
    user_agent: str | None = None,
) -> int:
    """Insert a new user/visitor feedback entry into the database."""
    now_iso = get_cologne_timestamp_str()
    cursor = connection.execute("""
        INSERT INTO feedback (
            user_id, username, category, message, page_url,
            viewport, screen_res, touch_support, user_agent, status, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?)
    """, (
        user_id, username, category, message, page_url,
        viewport, screen_res, int(touch_support), user_agent, now_iso
    ))
    connection.commit()
    return cursor.lastrowid


def get_all_feedback(
    connection,
    category: str | None = None,
    status: str | None = None,
    limit: int = 150,
) -> list[dict]:
    """Retrieve feedback entries with optional filtering by category and status."""
    query = "SELECT * FROM feedback WHERE 1=1"
    params = []
    if category and category != "all":
        query += " AND category = ?"
        params.append(category)
    if status and status != "all":
        query += " AND status = ?"
        params.append(status)
    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)

    rows = connection.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def get_feedback_counts(connection) -> dict:
    """Return count of open and total feedback items per category."""
    rows = connection.execute("""
        SELECT category, status, COUNT(*) AS count
        FROM feedback
        GROUP BY category, status
    """).fetchall()

    counts = {
        "total": 0,
        "open": 0,
        "resolved": 0,
        "mobile_handling": 0,
        "general": 0,
    }
    for row in rows:
        c = row["category"]
        s = row["status"]
        cnt = int(row["count"])
        counts["total"] += cnt
        if s == "open":
            counts["open"] += cnt
            if c in counts:
                counts[c] += cnt
        elif s == "resolved":
            counts["resolved"] += cnt
    return counts


def update_feedback_status(connection, feedback_id: int, status: str) -> bool:
    """Update status of a feedback item ('open', 'resolved', 'archived')."""
    cursor = connection.execute(
        "UPDATE feedback SET status = ? WHERE id = ?",
        (status, feedback_id)
    )
    connection.commit()
    return cursor.rowcount > 0


def delete_feedback_entry(connection, feedback_id: int) -> bool:
    """Delete a single feedback entry."""
    cursor = connection.execute("DELETE FROM feedback WHERE id = ?", (feedback_id,))
    connection.commit()
    return cursor.rowcount > 0


# ---------------------------------------------------------------------------
# Match MVP Voting
# ---------------------------------------------------------------------------

def get_match_mvp_deadline(match_date_str: str) -> datetime:
    """Return the deadline for MVP voting: match_date + 1 day at 20:00 Europe/Berlin."""
    match_d = datetime.strptime(str(match_date_str)[:10], "%Y-%m-%d").date()
    deadline_date = match_d + timedelta(days=1)
    return datetime(deadline_date.year, deadline_date.month, deadline_date.day, 20, 0, 0, tzinfo=COLOGNE_TZ)


def is_match_mvp_voting_open(match_date_str: str, now_dt: datetime | None = None) -> bool:
    """Check if MVP voting is currently open (now <= match_date + 1 day 20:00 Europe/Berlin)."""
    if now_dt is None:
        now_dt = get_cologne_now()
    elif now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=COLOGNE_TZ)
    deadline = get_match_mvp_deadline(match_date_str)
    return now_dt <= deadline


def record_match_mvp_vote(
    connection,
    match_id: str,
    voter_user_id: int,
    voted_player_id: int,
    voted_player_id_2: int | None = None,
    voted_player_id_3: int | None = None,
) -> bool:
    """Record or update an anonymous ranked MVP vote (1 to 3 distinct players) for a match."""
    # Prevent self-voting if voter is linked to a player
    user_row = connection.execute(
        "SELECT player_id FROM users WHERE id = ?", (int(voter_user_id),)
    ).fetchone()
    voter_player_id = int(user_row["player_id"]) if user_row and user_row["player_id"] else None

    now_iso = get_cologne_timestamp_str()
    # Normalize: ensure no duplicates in votes
    seen = set()
    votes = []
    for pid in [voted_player_id, voted_player_id_2, voted_player_id_3]:
        if pid is not None and int(pid) > 0 and pid not in seen:
            if voter_player_id and int(pid) == voter_player_id:
                raise ValueError("Du darfst dich nicht selbst als MVP wählen.")
            seen.add(pid)
            votes.append(int(pid))

    p1 = votes[0] if len(votes) > 0 else int(voted_player_id)
    p2 = votes[1] if len(votes) > 1 else None
    p3 = votes[2] if len(votes) > 2 else None

    connection.execute("""
        INSERT INTO match_mvp_votes (match_id, voter_user_id, voted_player_id, voted_player_id_2, voted_player_id_3, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(match_id, voter_user_id) DO UPDATE SET
            voted_player_id = excluded.voted_player_id,
            voted_player_id_2 = excluded.voted_player_id_2,
            voted_player_id_3 = excluded.voted_player_id_3,
            created_at = excluded.created_at
    """, (str(match_id), int(voter_user_id), p1, p2, p3, now_iso))
    connection.commit()
    return True


def record_match_mvp_votes(
    connection,
    match_id: str,
    voter_user_id: int,
    voted_player_ids: list[int],
) -> bool:
    """Record ranked MVP votes from a list of player IDs (up to 3)."""
    p1 = voted_player_ids[0] if len(voted_player_ids) > 0 else 0
    p2 = voted_player_ids[1] if len(voted_player_ids) > 1 else None
    p3 = voted_player_ids[2] if len(voted_player_ids) > 2 else None
    return record_match_mvp_vote(connection, match_id, voter_user_id, p1, p2, p3)


def get_user_match_mvp_votes(connection, match_id: str, voter_user_id: int) -> list[int]:
    """Return the list of voted_player_ids [rank1, rank2, rank3] for a user and match."""
    row = connection.execute("""
        SELECT voted_player_id, voted_player_id_2, voted_player_id_3 FROM match_mvp_votes
        WHERE match_id = ? AND voter_user_id = ?
    """, (str(match_id), int(voter_user_id))).fetchone()
    if not row:
        return []
    votes = []
    for col in ["voted_player_id", "voted_player_id_2", "voted_player_id_3"]:
        if row[col] is not None and int(row[col]) > 0:
            votes.append(int(row[col]))
    return votes


def get_user_match_mvp_vote(connection, match_id: str, voter_user_id: int) -> int | None:
    """Return the 1st ranked voted_player_id for a user and match (or None)."""
    votes = get_user_match_mvp_votes(connection, match_id, voter_user_id)
    return votes[0] if votes else None


def get_user_mvp_votes_for_matches(connection, voter_user_id: int, match_ids: list[str]) -> dict[str, list[int]]:
    """Return {match_id: [voted_player_ids]} for a user across multiple matches."""
    if not voter_user_id or not match_ids:
        return {}
    placeholders = ",".join("?" for _ in match_ids)
    rows = connection.execute(f"""
        SELECT match_id, voted_player_id, voted_player_id_2, voted_player_id_3 FROM match_mvp_votes
        WHERE voter_user_id = ? AND match_id IN ({placeholders})
    """, [int(voter_user_id), *[str(m) for m in match_ids]]).fetchall()
    result = {}
    for row in rows:
        votes = []
        for col in ["voted_player_id", "voted_player_id_2", "voted_player_id_3"]:
            if row[col] is not None and int(row[col]) > 0:
                votes.append(int(row[col]))
        result[row["match_id"]] = votes
    return result


def get_match_mvp_podium(connection, match_ids: list[str] | None = None) -> dict[str, dict]:
    """
    Calculate and return the MVP podium for matches:
    {
        match_id: {
            "gold": [player_id, ...],
            "silver": [player_id, ...],
            "bronze": [player_id, ...],
            "details": {
                player_id: {"total": int, "rank1": int, "rank2": int, "rank3": int}
            }
        }
    }
    Sorting / tie-breaking rules:
    - Primary: Total votes (rank 1 + rank 2 + rank 3)
    - Tie-breaker 1: More rank 1 votes
    - Tie-breaker 2: More rank 2 votes
    - Tie-breaker 3: More rank 3 votes
    Medal allocation:
    - Group 1 (highest): Gold
    - If 1 Gold winner: Group 2 gets Silver. If 1 Silver winner, Group 3 gets Bronze.
    - If 2 Gold winners: Group 2 gets Bronze.
    - If 3+ Gold winners: Gold only.
    """
    query = """
        SELECT match_id, voted_player_id, voted_player_id_2, voted_player_id_3
        FROM match_mvp_votes
    """
    params = []
    if match_ids:
        placeholders = ",".join("?" for _ in match_ids)
        query += f" WHERE match_id IN ({placeholders})"
        params.extend([str(m) for m in match_ids])

    rows = connection.execute(query, params).fetchall()

    # match_id -> player_id -> {"total": 0, "rank1": 0, "rank2": 0, "rank3": 0}
    match_player_stats: dict[str, dict[int, dict[str, int]]] = {}

    for r in rows:
        m_id = r["match_id"]
        stats = match_player_stats.setdefault(m_id, {})

        # Rank 1
        p1 = r["voted_player_id"]
        if p1 is not None and int(p1) > 0:
            pid1 = int(p1)
            p_entry = stats.setdefault(pid1, {"total": 0, "rank1": 0, "rank2": 0, "rank3": 0})
            p_entry["total"] += 1
            p_entry["rank1"] += 1

        # Rank 2
        p2 = r["voted_player_id_2"]
        if p2 is not None and int(p2) > 0:
            pid2 = int(p2)
            p_entry = stats.setdefault(pid2, {"total": 0, "rank1": 0, "rank2": 0, "rank3": 0})
            p_entry["total"] += 1
            p_entry["rank2"] += 1

        # Rank 3
        p3 = r["voted_player_id_3"]
        if p3 is not None and int(p3) > 0:
            pid3 = int(p3)
            p_entry = stats.setdefault(pid3, {"total": 0, "rank1": 0, "rank2": 0, "rank3": 0})
            p_entry["total"] += 1
            p_entry["rank3"] += 1

    podium_results: dict[str, dict] = {}

    for m_id, players_dict in match_player_stats.items():
        if not players_dict:
            podium_results[m_id] = {"gold": [], "silver": [], "bronze": [], "details": {}}
            continue

        # Group players by their exact tie-break key
        # key: (total, rank1, rank2, rank3)
        grouped_by_score: dict[tuple[int, int, int, int], list[int]] = {}
        for pid, s in players_dict.items():
            if s["total"] <= 0:
                continue
            key = (s["total"], s["rank1"], s["rank2"], s["rank3"])
            grouped_by_score.setdefault(key, []).append(pid)

        # Sort score groups in descending order
        sorted_keys = sorted(grouped_by_score.keys(), reverse=True)

        gold_list: list[int] = []
        silver_list: list[int] = []
        bronze_list: list[int] = []

        if len(sorted_keys) >= 1:
            gold_list = grouped_by_score[sorted_keys[0]]

        if len(gold_list) == 1:
            if len(sorted_keys) >= 2:
                silver_list = grouped_by_score[sorted_keys[1]]
                if len(silver_list) == 1 and len(sorted_keys) >= 3:
                    bronze_list = grouped_by_score[sorted_keys[2]]
        elif len(gold_list) == 2:
            if len(sorted_keys) >= 2:
                bronze_list = grouped_by_score[sorted_keys[1]]

        podium_results[m_id] = {
            "gold": gold_list,
            "silver": silver_list,
            "bronze": bronze_list,
            "details": players_dict,
        }

    return podium_results


def get_match_mvp_winners(connection, match_ids: list[str] | None = None) -> dict[str, list[int]]:
    """
    Calculate and return the MVP winning player IDs (Gold medalists) for matches: {match_id: [winning_player_ids]}.
    Maintains backward compatibility with legacy calls.
    """
    podium = get_match_mvp_podium(connection, match_ids=match_ids)
    return {m_id: res["gold"] for m_id, res in podium.items() if res.get("gold")}


def get_mvp_medal_table(
    connection,
    all_matches_dict: dict,
    filtered_match_ids: list[str] | None = None,
) -> list[dict]:
    """
    Aggregate Gold, Silver, and Bronze MVP medals across matches.
    For Box appointments, deduplicates matches by date so each Box evening awards medals only once.
    Returns a sorted list of player records:
    [
        {
            "player_id": int,
            "gold": int,
            "silver": int,
            "bronze": int,
            "total_medals": int,
            "medal_score": int,
            "rank": int,
        }
    ]
    """
    candidate_mids = filtered_match_ids if filtered_match_ids is not None else list(all_matches_dict.keys())
    podium_map = get_match_mvp_podium(connection, match_ids=candidate_mids)

    # Filter out matches where voting is still open (akute Abstimmungen nicht involvieren!)
    valid_mids = set()
    for mid in candidate_mids:
        m = all_matches_dict.get(mid)
        if m is None:
            valid_mids.add(mid)
            continue
        m_date = m.get("date")
        if m_date:
            try:
                if is_match_mvp_voting_open(m_date):
                    continue
            except Exception:
                pass
        valid_mids.add(mid)

    player_medals: dict[int, dict[str, int]] = {}
    seen_box_dates = set()

    for m_id, p_info in sorted(podium_map.items(), key=lambda x: str(x[0])):
        if m_id not in valid_mids:
            continue
        if not p_info.get("details"):
            continue

        m = all_matches_dict.get(m_id)
        if m and str(m.get("pitch", "")).lower() == "box":
            m_date = m.get("date")
            if m_date:
                if m_date in seen_box_dates:
                    continue
                seen_box_dates.add(m_date)

        for pid in p_info.get("gold", []):
            entry = player_medals.setdefault(pid, {"gold": 0, "silver": 0, "bronze": 0})
            entry["gold"] += 1
        for pid in p_info.get("silver", []):
            entry = player_medals.setdefault(pid, {"gold": 0, "silver": 0, "bronze": 0})
            entry["silver"] += 1
        for pid in p_info.get("bronze", []):
            entry = player_medals.setdefault(pid, {"gold": 0, "silver": 0, "bronze": 0})
            entry["bronze"] += 1

    table = []
    for pid, counts in player_medals.items():
        g = counts["gold"]
        s = counts["silver"]
        b = counts["bronze"]
        total = g + s + b
        score = (g * 3) + (s * 2) + (b * 1)
        if total > 0:
            table.append({
                "player_id": pid,
                "gold": g,
                "silver": s,
                "bronze": b,
                "total_medals": total,
                "medal_score": score,
            })

    # Sort table by Gold DESC, Silver DESC, Bronze DESC, Total DESC, Medal Score DESC
    table.sort(key=lambda x: (x["gold"], x["silver"], x["bronze"], x["total_medals"], x["medal_score"]), reverse=True)

    # Assign competitive ranks (handling ties)
    for i, row in enumerate(table):
        if i > 0:
            prev = table[i - 1]
            if (row["gold"], row["silver"], row["bronze"]) == (prev["gold"], prev["silver"], prev["bronze"]):
                row["rank"] = prev["rank"]
            else:
                row["rank"] = i + 1
        else:
            row["rank"] = 1

    return table


def get_mvp_voter_activity_logs(connection, limit: int = 100) -> list[dict]:
    """
    Returns recent MVP voting activity logs for Webmaster auditing.
    STRICT PRIVACY GUARANTEE: Does NOT query or return voted_player_id* columns under any circumstances.
    """
    query = """
        SELECT v.id, v.match_id, v.voter_user_id, v.created_at,
               u.username, u.attendance_name, u.player_id
        FROM match_mvp_votes v
        LEFT JOIN users u ON v.voter_user_id = u.id
        ORDER BY v.created_at DESC, v.id DESC
        LIMIT ?
    """
    rows = connection.execute(query, [int(limit)]).fetchall()
    results = []
    for r in rows:
        results.append({
            "id": r["id"],
            "match_id": r["match_id"],
            "voter_user_id": r["voter_user_id"],
            "created_at": r["created_at"],
            "username": r["username"] or f"User #{r['voter_user_id']}",
            "attendance_name": r["attendance_name"] or "",
            "player_id": r["player_id"],
        })
    return results


def get_match_mvp_results(
    connection,
    match_id: str,
    players_dict: dict | None = None,
    match_ids: list[str] | None = None
) -> dict:
    """
    Returns aggregated MVP election results and anonymous individual ballots for a match:
    {
        "match_id": match_id,
        "total_voters": int,
        "candidates": [...],
        "ballots": [
            {
                "ballot_number": int,
                "rank1": {"player_id": int, "player_name": str},
                "rank2": {"player_id": int, "player_name": str} | None,
                "rank3": {"player_id": int, "player_name": str} | None,
            }
        ]
    }
    STRICT PRIVACY GUARANTEE: Returns only candidate vote aggregates and anonymous ballots.
    Never exposes voter identities, user IDs, or timestamps.
    """
    target_mids = [str(m) for m in match_ids] if match_ids else [str(match_id)]
    placeholders = ",".join("?" for _ in target_mids)

    cnt_row = connection.execute(
        f"SELECT COUNT(*) as cnt FROM match_mvp_votes WHERE match_id IN ({placeholders})",
        target_mids
    ).fetchone()
    total_voters = cnt_row["cnt"] if cnt_row else 0

    podium_map = get_match_mvp_podium(connection, match_ids=target_mids)
    match_podium = podium_map.get(str(match_id), {})
    if not match_podium.get("details"):
        for m in target_mids:
            if podium_map.get(m, {}).get("details"):
                match_podium = podium_map.get(m, {})
                break

    details = match_podium.get("details", {})
    gold_set = set(match_podium.get("gold", []))
    silver_set = set(match_podium.get("silver", []))
    bronze_set = set(match_podium.get("bronze", []))

    def format_player(pid):
        if pid is None or int(pid) <= 0:
            return None
        p_id = int(pid)
        p_name = f"Player {p_id}"
        if players_dict and p_id in players_dict:
            p_aliases = players_dict[p_id].get("aliases", [])
            if p_aliases:
                p_name = p_aliases[0]
        return {"player_id": p_id, "player_name": p_name}

    candidates = []
    for pid, s in details.items():
        if s.get("total", 0) <= 0:
            continue
        medal = None
        if pid in gold_set:
            medal = "gold"
        elif pid in silver_set:
            medal = "silver"
        elif pid in bronze_set:
            medal = "bronze"

        p_info = format_player(pid)
        player_name = p_info["player_name"] if p_info else f"Player {pid}"

        candidates.append({
            "player_id": pid,
            "player_name": player_name,
            "total_votes": s.get("total", 0),
            "rank1": s.get("rank1", 0),
            "rank2": s.get("rank2", 0),
            "rank3": s.get("rank3", 0),
            "medal": medal,
        })

    # Sort descending by total votes, rank 1, rank 2, rank 3
    candidates.sort(
        key=lambda c: (c["total_votes"], c["rank1"], c["rank2"], c["rank3"]),
        reverse=True
    )

    # Assign competitive ranks (handling ties)
    for i, c in enumerate(candidates):
        if i > 0:
            prev = candidates[i - 1]
            if (c["total_votes"], c["rank1"], c["rank2"], c["rank3"]) == (prev["total_votes"], prev["rank1"], prev["rank2"], prev["rank3"]):
                c["rank"] = prev["rank"]
            else:
                c["rank"] = i + 1
        else:
            c["rank"] = 1

    # Extract anonymous ballots (strictly without voter_user_id or created_at)
    ballot_rows = connection.execute(
        f"""SELECT voted_player_id, voted_player_id_2, voted_player_id_3
            FROM match_mvp_votes
            WHERE match_id IN ({placeholders})""",
        target_mids
    ).fetchall()

    raw_ballots = []
    for b in ballot_rows:
        raw_ballots.append({
            "rank1": format_player(b["voted_player_id"]),
            "rank2": format_player(b["voted_player_id_2"]),
            "rank3": format_player(b["voted_player_id_3"]),
        })

    # Sort ballots deterministically by chosen candidate names so submission sequence / time cannot be reverse-engineered
    raw_ballots.sort(key=lambda b: (
        (b["rank1"]["player_name"] if b["rank1"] else "").lower(),
        (b["rank2"]["player_name"] if b["rank2"] else "").lower(),
        (b["rank3"]["player_name"] if b["rank3"] else "").lower()
    ))

    ballots = []
    for idx, b in enumerate(raw_ballots, start=1):
        ballots.append({
            "ballot_number": idx,
            "rank1": b["rank1"],
            "rank2": b["rank2"],
            "rank3": b["rank3"],
        })

    return {
        "match_id": str(match_id),
        "total_voters": total_voters,
        "candidates": candidates,
        "ballots": ballots,
    }


def get_all_matches_mvp_summaries(connection, players_dict: dict | None = None) -> list[dict]:
    """
    Returns aggregated MVP election summaries across all matches with votes, ordered by most recent vote.
    STRICT PRIVACY GUARANTEE: Never exposes individual voter choices.
    """
    rows = connection.execute("""
        SELECT match_id, COUNT(*) as voter_count, MAX(created_at) as last_vote_at
        FROM match_mvp_votes
        GROUP BY match_id
        ORDER BY last_vote_at DESC
    """).fetchall()

    summaries = []
    for r in rows:
        m_id = r["match_id"]
        res = get_match_mvp_results(connection, m_id, players_dict=players_dict)
        res["voter_count"] = r["voter_count"]
        res["last_vote_at"] = r["last_vote_at"]
        gold_names = [c["player_name"] for c in res["candidates"] if c["medal"] == "gold"]
        silver_names = [c["player_name"] for c in res["candidates"] if c["medal"] == "silver"]
        bronze_names = [c["player_name"] for c in res["candidates"] if c["medal"] == "bronze"]
        res["gold_names"] = gold_names
        res["silver_names"] = silver_names
        res["bronze_names"] = bronze_names
        summaries.append(res)

    return summaries







