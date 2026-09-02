"""Access tier resolution, Webmaster view simulation, and permission decorators."""

from enum import IntEnum
from functools import wraps

from flask import flash, has_request_context, redirect, request, session, url_for

from scripts.accounts.auth import get_user


class Tier(IntEnum):
    """The 5 progressive access tiers of RB48Glicko."""
    VISITOR = 1
    USER = 2
    GLICKO_USER = 3
    ADMIN = 4
    WEBMASTER = 5


TIER_NAMES = {
    Tier.VISITOR: "visitor",
    Tier.USER: "user",
    Tier.GLICKO_USER: "glicko_user",
    Tier.ADMIN: "admin",
    Tier.WEBMASTER: "webmaster",
}

TIER_BY_NAME = {v: k for k, v in TIER_NAMES.items()}

_UNSET = object()


def get_current_user():
    """Return the currently authenticated user dictionary or None."""
    if not has_request_context():
        return None
    user_id = session.get("user_id")
    if not user_id:
        return None
    return get_user(user_id)


def get_actual_tier(user=_UNSET) -> Tier:
    """Compute the actual database authorization tier of the user."""
    if user is _UNSET:
        user = get_current_user()

    if not user:
        return Tier.VISITOR

    role = user.get("role", "user")
    if role == "webmaster":
        return Tier.WEBMASTER
    if role == "admin":
        return Tier.ADMIN

    if not user.get("email_verified") or not user.get("is_approved"):
        return Tier.VISITOR

    if user.get("psychology_test_passed"):
        return Tier.GLICKO_USER

    return Tier.USER


def get_effective_tier() -> Tier:
    """Compute the effective tier (accounting for Webmaster view-simulation)."""
    user = get_current_user()
    actual = get_actual_tier(user)

    if user and user.get("role") == "webmaster":
        simulated_name = session.get("simulated_tier")
        if simulated_name in TIER_BY_NAME:
            return TIER_BY_NAME[simulated_name]

    return actual


def has_tier(required_tier, effective=True) -> bool:
    """Check if current context meets or exceeds the required tier."""
    if isinstance(required_tier, str):
        required_tier = TIER_BY_NAME.get(required_tier.lower(), Tier.VISITOR)

    current = get_effective_tier() if effective else get_actual_tier()
    return current >= required_tier


def require_tier(required_tier):
    """Decorator requiring a minimum effective tier to access an endpoint."""
    if isinstance(required_tier, str):
        required_tier = TIER_BY_NAME.get(required_tier.lower(), Tier.VISITOR)

    def decorator(view_func):
        @wraps(view_func)
        def wrapper(*args, **kwargs):
            if not has_tier(required_tier, effective=True):
                user = get_current_user()
                if not user:
                    flash("Please log in to view this content.", "info")
                    return redirect(url_for("auth.login", next=request.path))

                if not user.get("email_verified"):
                    flash("Please verify your email address to access this feature.", "warning")
                    return redirect(url_for("auth.resend_verification"))

                if not user.get("is_approved") and user.get("role") == "user":
                    flash("Your account is pending manual approval by the Webmaster.", "info")
                    return redirect(url_for("stats.home"))

                if required_tier >= Tier.GLICKO_USER and not user.get("psychology_test_passed"):
                    flash("Please complete the sportsmanship questionnaire to unlock Glicko ratings.", "info")
                    return redirect(url_for("auth.glicko_test", next=request.path))

                flash("You do not have permission to access this page.", "danger")
                return redirect(url_for("stats.home"))
            return view_func(*args, **kwargs)
        return wrapper
    return decorator


def require_admin(view_func):
    """Decorator requiring actual admin or webmaster role (immune to simulated view)."""
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        user = get_current_user()
        if not user or user.get("role") not in ("admin", "webmaster"):
            flash("Administrator privileges are required for this action.", "danger")
            return redirect(url_for("stats.home"))
        return view_func(*args, **kwargs)
    return wrapper


def require_webmaster(view_func):
    """Decorator requiring actual webmaster role."""
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        user = get_current_user()
        if not user or user.get("role") != "webmaster":
            flash("Webmaster privileges are required for this action.", "danger")
            return redirect(url_for("stats.home"))
        return view_func(*args, **kwargs)
    return wrapper
