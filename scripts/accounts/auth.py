"""Authentication, token generation, and account validation services."""

from datetime import datetime, timezone
import os

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from werkzeug.security import check_password_hash, generate_password_hash

from scripts.accounts.database import (
    create_user,
    get_accounts_connection,
    get_user_by_id,
    get_user_by_login,
    mark_email_verified,
    set_psychology_test_status,
    username_or_email_exists,
)

AUTH_SECRET_KEY = os.environ.get("RB48_AUTH_SECRET", "rb48-glicko-auth-secret-key")
VERIFICATION_SALT = "rb48-email-verification-salt"


def get_serializer(secret_key=None):
    """Return a timed serializer for secure token generation."""
    key = secret_key or AUTH_SECRET_KEY
    return URLSafeTimedSerializer(key)


def generate_verification_token(user_id, email, secret_key=None):
    """Generate a cryptographic signed token for email verification."""
    serializer = get_serializer(secret_key)
    return serializer.dumps({"user_id": user_id, "email": email.lower()}, salt=VERIFICATION_SALT)


def verify_email_token(token, max_age_seconds=86400, secret_key=None):
    """Validate token signature and expiration. Returns (payload, error)."""
    serializer = get_serializer(secret_key)
    try:
        data = serializer.loads(token, salt=VERIFICATION_SALT, max_age=max_age_seconds)
        return data, None
    except SignatureExpired:
        return None, "Verification link has expired. Please request a new one."
    except (BadSignature, Exception):
        return None, "Invalid verification token."


def verify_user_email(token, secret_key=None):
    """Verify an email token and activate the user's email_verified flag."""
    payload, error = verify_email_token(token, secret_key=secret_key)
    if error or not payload:
        return False, error or "Invalid verification token."

    user_id = payload.get("user_id")
    connection = get_accounts_connection()
    try:
        user = get_user_by_id(connection, user_id)
        if not user:
            return False, "User not found."
        mark_email_verified(connection, user_id)
        return True, "Email verified successfully!"
    finally:
        connection.close()


def pass_psychology_test(user_id):
    """Record that the user passed the Glicko psychology test."""
    connection = get_accounts_connection()
    try:
        user = get_user_by_id(connection, user_id)
        if not user:
            return False
        test_date = datetime.now(timezone.utc).isoformat(timespec="seconds")
        set_psychology_test_status(connection, user_id, passed=True, test_date=test_date)
        return True
    finally:
        connection.close()


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


def register_user(username, email, password, role="user"):
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
            role=role,
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
            return dict(user)
        return None
    finally:
        connection.close()


def get_user(user_id):
    """Return a user dict by id, or None if the account does not exist."""
    connection = get_accounts_connection()
    try:
        row = get_user_by_id(connection, user_id)
        return dict(row) if row else None
    finally:
        connection.close()
