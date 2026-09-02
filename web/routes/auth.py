"""Authentication, email verification, psychology test gating, and Webmaster view switching."""

import os
from pathlib import Path
import time
from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from scripts.accounts.auth import (
    authenticate,
    generate_verification_token,
    get_user,
    pass_psychology_test,
    register_user,
    verify_user_email,
)
from scripts.accounts.database import (
    approve_player_link,
    approve_user,
    get_accounts_connection,
    get_all_users,
    get_user_by_email,
    get_user_by_id,
    link_user_to_player,
    reject_player_link,
    request_player_link,
    update_user_password,
    update_user_profile,
)
from scripts.database.database import get_connection as get_main_connection
from scripts.database.db_players import get_players
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

        session["user_id"] = user["id"]
        session.pop("simulated_tier", None)

        if not user["email_verified"]:
            return render_template("verification_required.html", user=user)

        next_url = request.args.get("next") or url_for("stats.home")
        return redirect(next_url)

    return render_template("login.html")


@auth_bp.route("/logout")
def logout():
    """Clear session and log user out."""
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("stats.home"))


@auth_bp.route("/verify-email/<token>")
def verify_email(token):
    """Verify account email via secure HMAC token."""
    user = verify_user_email(token)
    if not user:
        return render_template("verify_result.html", success=False, error="Invalid or expired verification link.")

    return render_template("verify_result.html", success=True, username=user["username"])


@auth_bp.route("/resend-verification", methods=["GET", "POST"])
def resend_verification():
    """Resend email verification token."""
    email = request.form.get("email", "").strip() or request.args.get("email", "").strip()
    if email:
        connection = get_accounts_connection()
        try:
            user = get_user_by_email(connection, email)
        finally:
            connection.close()

        if user and not user["email_verified"]:
            token = generate_verification_token(user["id"], user["email"])
            verification_url = url_for("auth.verify_email", token=token, _external=True)
            send_verification_email(user["email"], user["username"], verification_url)

    return render_template("verification_sent.html", email=email, resend=True)


@auth_bp.route("/glicko-test", methods=["GET", "POST"])
@require_tier(Tier.USER)
def glicko_test():
    """Glicko sportsmanship and personality assessment (Jagged Alliance 2 I.M.P. style)."""
    from datetime import datetime, timezone
    from scripts.accounts.database import get_accounts_connection, set_user_persona
    from scripts.accounts.psychology import IMP_QUESTIONS, PSYCHOLOGY_PERSONAS, evaluate_psychology_submission

    user = get_current_user()
    step = request.args.get("step", "intro")

    # If POST -> evaluate questionnaire
    if request.method == "POST":
        persona, scores = evaluate_psychology_submission(request.form)
        now_str = datetime.now(timezone.utc).isoformat(timespec="seconds")

        conn = get_accounts_connection()
        try:
            set_user_persona(conn, user["id"], persona["key"], persona["passed"], now_str)
        finally:
            conn.close()

        if persona["passed"]:
            flash(f"Assessment Passed! You have been certified as: {persona['title']}.", "success")
        else:
            flash(f"Assessment Inconclusive: Assigned archetype '{persona['title']}'. Glicko clearance denied.", "warning")

        status_code = 200 if persona["passed"] else 400
        return render_template(
            "psychology_test.html",
            stage="result",
            persona=persona,
            scores=scores,
            user=user,
            questions=IMP_QUESTIONS,
        ), status_code

    # If GET and user already has an assigned persona and didn't request a retake/assessment step
    if user.get("psychology_persona") and step == "intro":
        existing_persona = PSYCHOLOGY_PERSONAS.get(user["psychology_persona"], PSYCHOLOGY_PERSONAS["legend"])
        return render_template(
            "psychology_test.html",
            stage="result",
            persona=existing_persona,
            scores={},
            user=user,
            questions=IMP_QUESTIONS,
            existing=True,
        )

    # Render intro or questionnaire assessment
    return render_template(
        "psychology_test.html",
        stage="assessment" if step == "assessment" else "intro",
        questions=IMP_QUESTIONS,
        user=user,
    )


@auth_bp.route("/switch-view", methods=["POST"])
@require_webmaster
def switch_view():
    """Simulate different tier access levels for Webmaster testing."""
    target_mode = request.form.get("view_mode", "").lower()

    if target_mode == "reset":
        session.pop("simulated_tier", None)
        flash("View mode reset to actual Webmaster permissions.", "info")
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
    """User management dashboard to review and approve registrations and player links."""
    connection = get_accounts_connection()
    main_conn = get_main_connection()
    try:
        users = [dict(row) for row in get_all_users(connection)]
        players = get_players(main_conn)
        return render_template("admin_users.html", users=users, players=players)
    finally:
        connection.close()
        main_conn.close()


@auth_bp.route("/admin/users/<int:user_id>/approval", methods=["POST"])
@require_webmaster
def toggle_approval(user_id):
    """Toggle manual Webmaster approval for an account."""
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


@auth_bp.route("/admin/users/<int:user_id>/player-link", methods=["POST"])
@require_webmaster
def handle_player_link(user_id):
    """Approve or reject a requested player profile connection."""
    action = request.form.get("action", "approve")
    connection = get_accounts_connection()
    try:
        user = get_user_by_id(connection, user_id)
        if not user:
            flash("User not found.", "danger")
            return redirect(url_for("auth.admin_users"))

        if action == "approve":
            approve_player_link(connection, user_id)
            flash(f"Approved player profile connection for '{user['username']}'.", "success")
        else:
            reject_player_link(connection, user_id)
            flash(f"Rejected player link request for '{user['username']}'.", "info")
        return redirect(url_for("auth.admin_users"))
    finally:
        connection.close()


@auth_bp.route("/settings")
@require_tier(Tier.USER)
def settings():
    """Profile & account settings page."""
    user = get_current_user()
    main_conn = get_main_connection()
    try:
        players = get_players(main_conn)
    finally:
        main_conn.close()

    return render_template("settings.html", user=user, players=players)


@auth_bp.route("/settings/profile", methods=["POST"])
@require_tier(Tier.USER)
def update_profile():
    """Update profile attendance name, player connection request, and avatar picture."""
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
            avatar_file=avatar_file,
        )

        # Handle player profile connection logic
        current_linked_id = user.get("player_id")
        current_pending_id = user.get("pending_player_id")

        if player_id != current_linked_id:
            if user.get("role") == "webmaster":
                link_user_to_player(conn, user["id"], player_id)
                flash("Profile settings and player connection updated!", "success")
            else:
                request_player_link(conn, user["id"], player_id)
                if player_id:
                    flash("Profile saved! Your player connection request has been sent for Webmaster approval.", "info")
                else:
                    flash("Player profile disconnected.", "info")
        else:
            flash("Profile settings updated successfully!", "success")
    finally:
        conn.close()

    return redirect(url_for("auth.settings"))


@auth_bp.route("/settings/password", methods=["POST"])
@require_tier(Tier.USER)
def update_password():
    """Change account password."""
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
