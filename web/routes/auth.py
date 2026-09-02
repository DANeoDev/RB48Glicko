"""Authentication, email verification, psychology test gating, and Webmaster view switching."""

from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from scripts.accounts.auth import (
    authenticate,
    generate_verification_token,
    get_user,
    pass_psychology_test,
    register_user,
    verify_user_email,
)
from scripts.accounts.database import get_accounts_connection, get_user_by_email
from web.services.email_service import is_smtp_configured, send_verification_email
from web.services.security import (
    Tier,
    TIER_BY_NAME,
    get_current_user,
    require_tier,
    require_webmaster,
)

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    """Register a new user and dispatch email verification."""
    if request.method == "POST":
        username = request.form.get("username", "")
        email = request.form.get("email", "")
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if password != confirm_password:
            return render_template("register.html", error="Passwords do not match."), 400

        user_id, error = register_user(username, email, password)
        if error:
            return render_template("register.html", error=error), 400

        token = generate_verification_token(user_id, email)
        verification_url = url_for("auth.verify_email", token=token, _external=True)
        send_verification_email(email, username, verification_url)

        dev_url = verification_url if not is_smtp_configured() else None
        return render_template("verification_sent.html", email=email, dev_verification_url=dev_url)

    return render_template("register.html")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    """Authenticate user credentials and start a session."""
    if request.method == "POST":
        login_input = request.form.get("login", "")
        password = request.form.get("password", "")
        user = authenticate(login_input, password)
        if not user:
            return render_template("login.html", error="Invalid username/email or password."), 401

        session.clear()
        session["user_id"] = user["id"]

        next_url = request.args.get("next") or request.form.get("next")
        if not next_url or not next_url.startswith("/"):
            next_url = url_for("stats.home")

        if not user.get("email_verified"):
            flash("Your account email is unverified. Please check your inbox or resend verification.", "warning")

        return redirect(next_url)

    return render_template("login.html", next_url=request.args.get("next", ""))


@auth_bp.route("/logout")
def logout():
    """Clear session and log out."""
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("stats.home"))


@auth_bp.route("/verify-email/<token>")
def verify_email(token):
    """Validate token and activate account email verification."""
    success, message = verify_user_email(token)
    if success:
        flash(message, "success")
        from scripts.accounts.auth import verify_email_token
        payload, _ = verify_email_token(token)
        if payload and payload.get("user_id"):
            session["user_id"] = payload["user_id"]
        return redirect(url_for("stats.home"))

    flash(message, "danger")
    return redirect(url_for("auth.resend_verification"))


@auth_bp.route("/resend-verification", methods=["GET", "POST"])
def resend_verification():
    """Request a fresh verification link."""
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        connection = get_accounts_connection()
        try:
            user = get_user_by_email(connection, email)
            if user:
                if user["email_verified"]:
                    flash("This email address is already verified. You can log in.", "info")
                    return redirect(url_for("auth.login"))

                token = generate_verification_token(user["id"], user["email"])
                verification_url = url_for("auth.verify_email", token=token, _external=True)
                send_verification_email(user["email"], user["username"], verification_url)
                dev_url = verification_url if not is_smtp_configured() else None
                return render_template("verification_sent.html", email=email, dev_verification_url=dev_url)
            else:
                flash("If an account exists with that email, a verification link has been sent.", "info")
                return render_template("resend_verification.html", success="Verification link sent.")
        finally:
            connection.close()

    return render_template("resend_verification.html")


@auth_bp.route("/glicko-test", methods=["GET", "POST"])
@require_tier(Tier.USER)
def glicko_test():
    """Glicko sportsmanship and variance questionnaire to unlock ratings tier."""
    user = get_current_user()
    next_url = request.args.get("next") or request.form.get("next") or url_for("stats.home")

    if user and user.get("psychology_test_passed"):
        flash("You have already completed the sportsmanship questionnaire and unlocked Glicko ratings.", "info")
        return redirect(next_url)

    if request.method == "POST":
        q1 = request.form.get("q1")
        q2 = request.form.get("q2")
        q3 = request.form.get("q3")
        q4 = request.form.get("q4")

        # Correct answers: q1='b', q2='a', q3='a', q4='a'
        if q1 == "b" and q2 == "a" and q3 == "a" and q4 == "a":
            pass_psychology_test(user["id"])
            flash("Congratulations! You have passed the questionnaire and unlocked full Glicko ratings & rankings.", "success")
            return redirect(next_url)

        error_msg = (
            "One or more answers did not reflect the required sportsmanship or understanding of rating variance. "
            "Please review the questions and select answers that emphasize recreational fun, statistical awareness, and teamwork."
        )
        return render_template("psychology_test.html", error=error_msg, next_url=next_url), 400

    return render_template("psychology_test.html", next_url=next_url)


@auth_bp.route("/switch-view", methods=["POST"])
@require_webmaster
def switch_view():
    """Allow webmaster to simulate different access tiers for UI testing."""
    target_mode = request.form.get("view_mode", "").lower()

    if target_mode == "reset" or not target_mode:
        session.pop("simulated_tier", None)
        flash("Webmaster view mode reset to standard view.", "info")
    elif target_mode in TIER_BY_NAME:
        session["simulated_tier"] = target_mode
        flash(f"Simulating view mode: {target_mode.replace('_', ' ').title()}", "info")
    else:
        flash("Invalid view mode requested.", "danger")

    redirect_target = request.form.get("redirect_to") or request.referrer or url_for("stats.home")
    return redirect(redirect_target)
