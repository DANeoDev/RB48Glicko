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


@auth_bp.route("/admin/users")
@require_webmaster
def admin_users():
    """User management dashboard to review and approve registrations."""
    from scripts.accounts.database import get_accounts_connection, get_all_users
    connection = get_accounts_connection()
    try:
        users = [dict(row) for row in get_all_users(connection)]
        return render_template("admin_users.html", users=users)
    finally:
        connection.close()


@auth_bp.route("/admin/users/<int:user_id>/approval", methods=["POST"])
@require_webmaster
def toggle_approval(user_id):
    """Toggle manual Webmaster approval for an account."""
    from scripts.accounts.database import get_accounts_connection, approve_user, get_user_by_id
    action = request.form.get("action", "approve")
    connection = get_accounts_connection()
    try:
        user = get_user_by_id(connection, user_id)
        if not user:
            flash("User not found.", "danger")
            return redirect(url_for("auth.admin_users"))

        if action == "approve":
            approve_user(connection, user_id, approved=True)
            flash(f"Account '{user['username']}' has been approved.", "success")
        else:
            approve_user(connection, user_id, approved=False)
            flash(f"Approval for '{user['username']}' has been revoked.", "warning")
        return redirect(url_for("auth.admin_users"))
    finally:
        connection.close()


@auth_bp.route("/settings")
@require_tier(Tier.USER)
def settings():
    """Profile & account settings page."""
    user = get_current_user()
    from scripts.database.database import get_connection as get_main_connection
    from scripts.database.db_players import get_players

    main_conn = get_main_connection()
    try:
        players = get_players(main_conn)
    finally:
        main_conn.close()

    return render_template("settings.html", user=user, players=players)


@auth_bp.route("/settings/profile", methods=["POST"])
@require_tier(Tier.USER)
def update_profile():
    """Update profile attendance name, player connection, and avatar picture."""
    import os
    import time
    from pathlib import Path
    from werkzeug.utils import secure_filename
    from scripts.accounts.database import get_accounts_connection, update_user_profile

    user = get_current_user()
    attendance_name = request.form.get("attendance_name", "").strip()
    player_id_raw = request.form.get("player_id", "")
    player_id = int(player_id_raw) if player_id_raw.isdigit() and int(player_id_raw) > 0 else None

    avatar_file = user.get("avatar_file")
    avatar_upload = request.files.get("avatar")

    if avatar_upload and avatar_upload.filename:
        ext = avatar_upload.filename.rsplit(".", 1)[-1].lower() if "." in avatar_upload.filename else ""
        if ext in ("png", "jpg", "jpeg", "webp", "gif"):
            upload_dir = Path(__file__).resolve().parents[2] / "web" / "static" / "uploads" / "avatars"
            upload_dir.mkdir(parents=True, exist_ok=True)
            filename = f"user_{user['id']}_{int(time.time())}.{ext}"
            filepath = upload_dir / filename
            avatar_upload.save(str(filepath))
            avatar_file = f"uploads/avatars/{filename}"
        else:
            flash("Invalid image format. Supported formats: PNG, JPG, WEBP, GIF.", "warning")

    conn = get_accounts_connection()
    try:
        update_user_profile(
            conn,
            user["id"],
            attendance_name=attendance_name if attendance_name else user["username"],
            player_id=player_id,
            avatar_file=avatar_file,
        )
        flash("Profile settings updated successfully!", "success")
    finally:
        conn.close()

    return redirect(url_for("auth.settings"))


@auth_bp.route("/settings/password", methods=["POST"])
@require_tier(Tier.USER)
def update_password():
    """Change account password."""
    from werkzeug.security import check_password_hash, generate_password_hash
    from scripts.accounts.database import get_accounts_connection, update_user_password

    user = get_current_user()
    current_password = request.form.get("current_password", "")
    new_password = request.form.get("new_password", "")
    confirm_password = request.form.get("confirm_password", "")

    if not check_password_hash(user["password_hash"], current_password):
        flash("Current password is incorrect.", "danger")
        return redirect(url_for("auth.settings"))

    if len(new_password) < 8:
        flash("New password must be at least 8 characters long.", "warning")
        return redirect(url_for("auth.settings"))

    if new_password != confirm_password:
        flash("New passwords do not match.", "warning")
        return redirect(url_for("auth.settings"))

    conn = get_accounts_connection()
    try:
        update_user_password(conn, user["id"], generate_password_hash(new_password))
        flash("Your password has been changed successfully.", "success")
    finally:
        conn.close()

    return redirect(url_for("auth.settings"))
