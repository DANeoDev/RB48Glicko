from datetime import datetime, timezone

from werkzeug.security import check_password_hash, generate_password_hash

from scripts.accounts.database import (
    create_user,
    get_accounts_connection,
    get_user_by_id,
    get_user_by_login,
    username_or_email_exists,
)


def validate_registration(username, email, password):
    """Return an error message or None for valid initial registration data."""
    username = username.strip()
    email = email.strip().lower()

    if not 3 <= len(username) <= 30:
        return "Username must be between 3 and 30 characters."
    if not email or "@" not in email or len(email) > 254:
        return "Please enter a valid email address."
    if len(password) < 8:
        return "Password must be at least 8 characters long."
    return None


def register_user(username, email, password):
    """Create a standard, initially unverified user account."""
    username = username.strip()
    email = email.strip().lower()
    error = validate_registration(username, email, password)
    if error:
        return None, error

    connection = get_accounts_connection()
    try:
        if username_or_email_exists(connection, username, email):
            return None, "That username or email address is already registered."
        user_id = create_user(
            connection,
            username,
            email,
            generate_password_hash(password),
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
        return user_id, None
    finally:
        connection.close()


def authenticate(login, password):
    """Return the matching user, or None when credentials are invalid."""
    connection = get_accounts_connection()
    try:
        user = get_user_by_login(connection, login.strip())
        if user and check_password_hash(user["password_hash"], password):
            return user
        return None
    finally:
        connection.close()


def get_user(user_id):
    """Return a user by id, or None if the account no longer exists."""
    connection = get_accounts_connection()
    try:
        return get_user_by_id(connection, user_id)
    finally:
        connection.close()
