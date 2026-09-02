"""Noise bubbles API routes for spatial banter across RB48 pages."""

import html
from flask import Blueprint, flash, jsonify, redirect, request, url_for

from scripts.accounts.auth import get_user
from scripts.accounts.database import (
    add_noise_bubble,
    delete_noise_bubble,
    dismiss_noise_for_user,
    get_accounts_connection,
    get_noise_bubble_by_id,
    get_noise_bubbles_for_page,
    set_user_noise_display_mode,
    set_user_noise_override,
    update_noise_bubble_position,
)
from web.services.security import Tier, get_current_user, require_tier

noise_bp = Blueprint("noise", __name__)


@noise_bp.route("/api/noise", methods=["GET"])
def get_noise():
    """Retrieve all noise bubbles for a given page path (registered users only)."""
    user = get_current_user()
    if not user or not user.get("email_verified") or not user.get("is_approved"):
        return jsonify({"success": True, "bubbles": []})

    page_path = request.args.get("path", "/").strip()
    match_id = request.args.get("match_id", type=int)

    conn = get_accounts_connection()
    try:
        bubbles = get_noise_bubbles_for_page(conn, page_path, viewer_user_id=user["id"], match_id=match_id)
    finally:
        conn.close()

    return jsonify({"success": True, "bubbles": bubbles})


@noise_bp.route("/api/noise", methods=["POST"])
@require_tier(Tier.USER)
def create_noise():
    """Create a new spatial noise bubble on a page."""
    user = get_current_user()
    if not user:
        return jsonify({"success": False, "error": "Authentication required."}), 401

    data = request.get_json(silent=True) or request.form

    content = str(data.get("content", "")).strip()
    if not content:
        return jsonify({"success": False, "error": "Message content cannot be empty."}), 400
    if len(content) > 160:
        return jsonify({"success": False, "error": "Message cannot exceed 160 characters."}), 400

    page_path = str(data.get("page_path", "/")).strip()
    match_id = data.get("match_id")
    match_id = int(match_id) if match_id is not None and str(match_id).isdigit() else None

    try:
        pos_x_percent = float(data.get("pos_x_percent", 50.0))
        pos_y_percent = float(data.get("pos_y_percent", 50.0))
    except (ValueError, TypeError):
        return jsonify({"success": False, "error": "Invalid coordinates."}), 400

    pos_x_percent = max(0.0, min(100.0, pos_x_percent))
    pos_y_percent = max(0.0, min(100.0, pos_y_percent))

    bg_color = str(data.get("bg_color", "#7B52C5")).strip()
    font_family = str(data.get("font_family", "Inter")).strip()
    try:
        font_size = int(data.get("font_size", 15))
    except (ValueError, TypeError):
        font_size = 15

    font_size = max(11, min(32, font_size))

    conn = get_accounts_connection()
    try:
        bubble_id = add_noise_bubble(
            conn,
            user_id=user["id"],
            page_path=page_path,
            pos_x_percent=pos_x_percent,
            pos_y_percent=pos_y_percent,
            content=content,
            match_id=match_id,
            bg_color=bg_color,
            font_family=font_family,
            font_size=font_size,
        )
        bubble = get_noise_bubble_by_id(conn, bubble_id, viewer_user_id=user["id"])
    finally:
        conn.close()

    return jsonify({"success": True, "bubble": bubble}), 201


@noise_bp.route("/api/noise/<int:bubble_id>/move", methods=["POST"])
@require_tier(Tier.USER)
def move_noise(bubble_id):
    """Update position coordinates of an existing bubble (per-user override and optional global author update)."""
    user = get_current_user()
    if not user:
        return jsonify({"success": False, "error": "Authentication required."}), 401

    data = request.get_json(silent=True) or request.form
    try:
        pos_x_percent = float(data.get("pos_x_percent", 50.0))
        pos_y_percent = float(data.get("pos_y_percent", 50.0))
    except (ValueError, TypeError):
        return jsonify({"success": False, "error": "Invalid coordinates."}), 400

    pos_x_percent = max(0.0, min(100.0, pos_x_percent))
    pos_y_percent = max(0.0, min(100.0, pos_y_percent))
    global_update = bool(data.get("global_update", False))

    is_staff = user.get("role") in ("admin", "webmaster")

    conn = get_accounts_connection()
    try:
        ok = update_noise_bubble_position(
            conn,
            bubble_id=bubble_id,
            pos_x_percent=pos_x_percent,
            pos_y_percent=pos_y_percent,
            user_id=user["id"],
            is_staff=is_staff,
            global_update=global_update,
        )
    finally:
        conn.close()

    if not ok:
        return jsonify({"success": False, "error": "Bubble not found."}), 404

    return jsonify({"success": True, "bubble_id": bubble_id, "pos_x_percent": pos_x_percent, "pos_y_percent": pos_y_percent})


@noise_bp.route("/api/noise/<int:bubble_id>/dismiss", methods=["POST"])
@require_tier(Tier.USER)
def dismiss_noise(bubble_id):
    """Dismiss a bubble from the current user's view."""
    user = get_current_user()
    if not user:
        return jsonify({"success": False, "error": "Authentication required."}), 401

    conn = get_accounts_connection()
    try:
        dismiss_noise_for_user(conn, user_id=user["id"], bubble_id=bubble_id)
    finally:
        conn.close()

    return jsonify({"success": True, "dismissed_id": bubble_id})


@noise_bp.route("/api/noise/<int:bubble_id>", methods=["DELETE", "POST"])
@require_tier(Tier.USER)
def delete_noise(bubble_id):
    """Delete a noise bubble."""
    user = get_current_user()
    if not user:
        return jsonify({"success": False, "error": "Authentication required."}), 401

    is_staff = user.get("role") in ("admin", "webmaster")

    conn = get_accounts_connection()
    try:
        ok = delete_noise_bubble(
            conn,
            bubble_id=bubble_id,
            user_id=user["id"],
            is_staff=is_staff,
        )
    finally:
        conn.close()

    if not ok:
        return jsonify({"success": False, "error": "Permission denied or bubble not found."}), 403

    return jsonify({"success": True, "deleted_id": bubble_id})


@noise_bp.route("/settings/noise-mode", methods=["POST"])
@require_tier(Tier.USER)
def update_noise_display_mode():
    """Update user's noise display mode preference."""
    user = get_current_user()
    mode = request.form.get("noise_display_mode", "smart").strip()

    conn = get_accounts_connection()
    try:
        set_user_noise_display_mode(conn, user["id"], mode)
        flash("Noise display mode updated!", "success")
    finally:
        conn.close()

    return redirect(url_for("auth.settings"))
