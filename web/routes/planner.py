"""Routes and business logic for the Attendance Planner tool."""

from datetime import datetime, timedelta, timezone
from flask import Blueprint, flash, redirect, render_template, request, url_for

from scripts.accounts.database import get_accounts_connection, get_user_by_id, set_user_attendance_name
from scripts.database.database import get_connection as get_main_connection
from scripts.database.db_players import get_alias_lookup
from scripts.matchmaking.match_parser import normalize_player_name
from scripts.planner.database import (
    add_guest_rsvp,
    add_standard_wednesday_events,
    cancel_user_rsvp,
    create_event,
    delete_event,
    get_attendee_by_id,
    get_event_attendees,
    get_event_by_id,
    get_planner_connection,
    get_upcoming_events,
    get_user_event_rsvp,
    get_user_registered_guests,
    remove_attendee,
    set_user_rsvp,
    update_attendee,
)
from web.services.security import Tier, get_current_user, has_tier, require_admin, require_tier, require_webmaster
from web.services.translations import format_date_localized, get_current_lang, t

planner_bp = Blueprint("planner", __name__)


def calculate_guest_unlock_time(event_date_str):
    """Calculate the Sunday at 00:00:00 directly preceding the match date."""
    try:
        if "T" in event_date_str:
            dt = datetime.fromisoformat(event_date_str)
        elif " " in event_date_str:
            dt = datetime.strptime(event_date_str, "%Y-%m-%d %H:%M")
        else:
            dt = datetime.strptime(event_date_str, "%Y-%m-%d")
    except (ValueError, TypeError):
        dt = datetime.now()

    # weekday(): 0=Monday ... 5=Saturday, 6=Sunday
    weekday = dt.weekday()
    days_back = (weekday + 1) if weekday != 6 else 0
    sunday = (dt - timedelta(days=days_back)).replace(hour=0, minute=0, second=0, microsecond=0)
    return sunday


def is_guest_registration_unlocked(event_date_str):
    """Return whether current local time is past the preceding Sunday 00:00."""
    unlock_time = calculate_guest_unlock_time(event_date_str)
    return datetime.now() >= unlock_time


def resolve_active_roster_player_ids(active_roster, alias_lookup, acc_conn):
    """Resolve matched player IDs in RB48 database for attendees in active roster."""
    resolved_ids = []
    norm_lookup = {normalize_player_name(a).casefold(): pid for a, pid in alias_lookup.items()}

    for a in active_roster:
        pid = None
        if a["user_id"]:
            u = get_user_by_id(acc_conn, a["user_id"])
            if u and u["player_id"]:
                pid = u["player_id"]

        if not pid:
            raw_name = a["name"].split("(")[0].strip()
            norm = normalize_player_name(raw_name).casefold()
            pid = norm_lookup.get(norm)

        if pid and pid not in resolved_ids:
            resolved_ids.append(pid)

    return resolved_ids


def format_event_view_data(event, current_user, attendees, alias_lookup=None, acc_conn=None):
    """Prepare view data for an event, including roster split, preselected player IDs, and guest permissions."""
    attending = [a for a in attendees if a["status"] == "attending"]
    declined = [a for a in attendees if a["status"] == "declined"]
    capacity = event["max_players"]

    active_roster = attending[:capacity]
    waiting_list = attending[capacity:]

    unlock_time = calculate_guest_unlock_time(event["event_date"])
    guest_unlocked = datetime.now() >= unlock_time

    matched_player_ids = []
    if alias_lookup and acc_conn:
        matched_player_ids = resolve_active_roster_player_ids(active_roster, alias_lookup, acc_conn)

    user_rsvp = None
    user_guests = []
    if current_user:
        for a in attendees:
            if a["user_id"] == current_user["id"] and not a["is_guest"]:
                user_rsvp = a["status"]
            if a["registered_by_user_id"] == current_user["id"]:
                user_guests.append(a)

    try:
        formatted_date = format_date_localized(event["event_date"])
        formatted_time = event["event_date"][11:16] if len(event["event_date"]) > 10 else "18:30"
    except Exception:
        formatted_date = event["event_date"]
        formatted_time = "18:30"

    custom_title = event["title"].strip() if event.get("title") and str(event["title"]).strip() else None
    badge_label = custom_title if custom_title else event["pitch"].upper()

    lang = get_current_lang()
    unlock_time_suffix = " um 00:00 Uhr" if lang == "de" else " at 00:00"
    guest_unlock_time_formatted = f"{format_date_localized(unlock_time)}{unlock_time_suffix}"

    return {
        "id": event["id"],
        "event_date": event["event_date"],
        "formatted_date": formatted_date,
        "formatted_time": formatted_time,
        "pitch": event["pitch"].upper(),
        "pitch_lower": event["pitch"].lower(),
        "badge_label": badge_label,
        "max_players": capacity,
        "title": custom_title or f"{event['pitch'].upper()}",
        "location": event["location"] or "Standard",
        "active_roster": active_roster,
        "waiting_list": waiting_list,
        "attending_count": len(attending),
        "declined_list": declined,
        "declined_count": len(declined),
        "guest_unlocked": guest_unlocked,
        "guest_unlock_time_formatted": guest_unlock_time_formatted,
        "matched_player_ids_str": ",".join(map(str, matched_player_ids)),
        "user_rsvp": user_rsvp,
        "user_guests": user_guests,
    }


@planner_bp.route("/planner")
def planner():
    """Main Attendance Planner overview showing upcoming game dates."""
    user = get_current_user()
    connection = get_planner_connection()
    main_conn = get_main_connection()
    acc_conn = get_accounts_connection()
    try:
        alias_lookup = get_alias_lookup(main_conn)
        events = get_upcoming_events(connection, limit=None)
        events_data = []
        for evt in events:
            attendees = [dict(a) for a in get_event_attendees(connection, evt["id"])]
            events_data.append(format_event_view_data(dict(evt), user, attendees, alias_lookup, acc_conn))
    finally:
        connection.close()
        main_conn.close()
        acc_conn.close()

    # Determine which match is the actual next upcoming match (datewise)
    # A match has passed when the matchday has passed (event_date < today)
    today_str = datetime.now().strftime("%Y-%m-%d")
    next_upcoming_found = False
    for evt in events_data:
        evt_date_prefix = evt["event_date"][:10]
        if not next_upcoming_found and evt_date_prefix >= today_str:
            evt["is_next_upcoming"] = True
            next_upcoming_found = True
        else:
            evt["is_next_upcoming"] = False

    # If all events in list are in the past, default to expanding the first event
    if not next_upcoming_found and events_data:
        events_data[0]["is_next_upcoming"] = True

    user_attendance_name = (user.get("attendance_name") or user.get("username")) if user else ""
    return render_template(
        "planner.html",
        events=events_data,
        user_attendance_name=user_attendance_name,
    )


@planner_bp.route("/planner/<int:event_id>/rsvp", methods=["POST"])
@require_tier(Tier.USER)
def rsvp_event(event_id):
    """Submit member self-RSVP (attending or declined). Cancel/reset is restricted."""
    user = get_current_user()
    action = request.form.get("status", "").lower()

    connection = get_planner_connection()
    try:
        event = get_event_by_id(connection, event_id)
        if not event:
            flash("Match event not found.", "danger")
            return redirect(url_for("planner.planner"))

        display_name = user.get("attendance_name") or user.get("username")

        if action == "cancel":
            if has_tier(Tier.ADMIN):
                cancel_user_rsvp(connection, event_id, user["id"])
                flash("Your RSVP has been removed.", "info")
            else:
                flash(t("planner.cannot_cancel_direct", "Deregistration is only possible by choosing 'Nicht dabei' (Declined)."), "warning")
        elif action in ("attending", "declined"):
            set_user_rsvp(connection, event_id, user["id"], display_name, action)
            msg = "You are marked as attending!" if action == "attending" else "You are marked as declined."
            flash(msg, "success" if action == "attending" else "info")
        else:
            flash("Invalid RSVP status.", "danger")
    finally:
        connection.close()

    return redirect(url_for("planner.planner"))


@planner_bp.route("/planner/<int:event_id>/guest", methods=["POST"])
def add_guest(event_id):
    """Add a guest player (for visitor, registered member, or admin)."""
    user = get_current_user()
    guest_name = request.form.get("guest_name", "").strip()

    if not guest_name:
        flash("Please enter a guest name.", "warning")
        return redirect(url_for("planner.planner"))

    connection = get_planner_connection()
    try:
        event = get_event_by_id(connection, event_id)
        if not event:
            flash("Match event not found.", "danger")
            return redirect(url_for("planner.planner"))

        # Check Sunday time lock (Admins & Webmasters are exempt)
        is_admin = has_tier(Tier.ADMIN)
        if not is_admin and not is_guest_registration_unlocked(event["event_date"]):
            unlock_time = calculate_guest_unlock_time(event["event_date"])
            formatted = unlock_time.strftime("%A, %d.%m.%Y at 00:00")
            flash(f"Guest player registration for this match opens on {formatted}.", "warning")
            return redirect(url_for("planner.planner"))

        if user:
            registered_by_id = user["id"]
            reg_name = user.get("attendance_name") or user.get("username")
            add_guest_rsvp(connection, event_id, guest_name, registered_by_id, reg_name)
            flash(f"Guest '{guest_name}' has been added.", "success")
        else:
            add_guest_rsvp(connection, event_id, guest_name, None, None)
            flash(f"Guest player '{guest_name}' has been registered.", "success")
    finally:
        connection.close()

    return redirect(url_for("planner.planner"))


@planner_bp.route("/planner/<int:event_id>/attendee/<int:attendee_id>/edit", methods=["POST"])
@require_admin
def edit_event_attendee(event_id, attendee_id):
    """Admin & Webmaster tool: Edit an attendee entry (name, status) on a matchday."""
    new_name = request.form.get("name", "").strip()
    new_status = request.form.get("status", "").strip().lower()

    if not new_name or new_status not in ("attending", "declined"):
        flash("Please provide a valid name and status.", "danger")
        return redirect(url_for("planner.planner"))

    connection = get_planner_connection()
    try:
        attendee = get_attendee_by_id(connection, attendee_id)
        if not attendee or attendee["event_id"] != event_id:
            flash("Attendee entry not found.", "danger")
            return redirect(url_for("planner.planner"))

        update_attendee(connection, attendee_id, name=new_name, status=new_status)
        flash(f"Updated entry for '{new_name}'.", "success")
    finally:
        connection.close()

    return redirect(url_for("planner.planner"))


@planner_bp.route("/planner/<int:event_id>/attendee/<int:attendee_id>/remove", methods=["POST"])
def remove_event_attendee(event_id, attendee_id):
    """Remove an attendee entry (admin/webmaster override, or own registered guest)."""
    user = get_current_user()
    connection = get_planner_connection()
    try:
        attendees = get_event_attendees(connection, event_id)
        target = next((a for a in attendees if a["id"] == attendee_id), None)
        if not target:
            flash("Attendee entry not found.", "danger")
            return redirect(url_for("planner.planner"))

        is_admin = has_tier(Tier.ADMIN)
        is_guest_owner = user and target["is_guest"] and target["registered_by_user_id"] == user["id"]

        if is_admin or is_guest_owner:
            remove_attendee(connection, attendee_id)
            flash(f"Removed '{target['name']}' from the list.", "info")
        else:
            flash("You do not have permission to remove this attendee. Please select 'Nicht dabei' to decline.", "danger")
    finally:
        connection.close()

    return redirect(url_for("planner.planner"))


@planner_bp.route("/planner/events/create", methods=["POST"])
@require_admin
def create_event_route():
    """Schedule a new upcoming match event."""
    event_date_raw = request.form.get("event_date", "").strip()
    date_only = request.form.get("event_date_only", "").strip()
    time_only = request.form.get("event_time_only", "").strip()

    if date_only and time_only:
        event_date = f"{date_only} {time_only}"
    elif date_only:
        event_date = date_only
    elif "T" in event_date_raw:
        event_date = event_date_raw.replace("T", " ")
    else:
        event_date = event_date_raw

    pitch = request.form.get("pitch", "box").lower()
    title = request.form.get("title", "").strip()
    location = request.form.get("location", "").strip()
    max_players_raw = request.form.get("max_players", "").strip()
    max_players = int(max_players_raw) if max_players_raw.isdigit() and int(max_players_raw) > 0 else None

    if not event_date or pitch not in ("box", "hf", "custom"):
        flash("Please provide a valid date and pitch type (BOX, HF, or Custom).", "danger")
        return redirect(url_for("planner.planner"))

    connection = get_planner_connection()
    try:
        create_event(
            connection,
            event_date=event_date,
            pitch=pitch,
            title=title or None,
            location=location or None,
            max_players=max_players,
        )
        flash(f"New {pitch.upper()} matchday scheduled for {event_date}!", "success")
    finally:
        connection.close()

    return redirect(url_for("planner.planner"))


@planner_bp.route("/planner/events/auto-seed", methods=["POST"])
@require_admin
def auto_seed_events():
    """Add 4 standard alternating Wednesday matchdays."""
    connection = get_planner_connection()
    try:
        created_ids = add_standard_wednesday_events(connection, count=4)
        flash(f"Successfully added {len(created_ids)} standard Wednesday matchdays!", "success")
    finally:
        connection.close()

    return redirect(url_for("planner.planner"))


@planner_bp.route("/planner/events/clear-dates", methods=["POST"])
@planner_bp.route("/planner/events/clear-all", methods=["POST"])
@require_webmaster
def clear_dates():
    """Webmaster tool: Wipe selected upcoming matchdates with 2-step verification after saving a backup."""
    from scripts.planner.database import backup_and_clear_events

    confirm_text = request.form.get("confirm_text", "").strip().upper()
    if not confirm_text:
        confirm_text = request.form.get("confirm_2", "").strip().upper()

    if confirm_text not in ("CLEAR DATES", "CLEAR ALL DATES"):
        flash("Two-step verification failed. Please type CLEAR DATES to confirm.", "warning")
        return redirect(url_for("planner.planner"))

    event_ids = request.form.getlist("event_ids")
    if not event_ids and request.form.get("confirm_1") == "yes":
        event_ids = None
    elif not event_ids:
        flash("No match dates were selected to be cleared.", "info")
        return redirect(url_for("planner.planner"))

    connection = get_planner_connection()
    try:
        backup_name, cleared_count = backup_and_clear_events(connection, event_ids=event_ids)
        if cleared_count == "all":
            msg = f"All match dates archived to data/backups/upcoming_matchdates/{backup_name} and planner reset to clean state."
        else:
            msg = f"Successfully cleared {cleared_count} match date(s) (archived to data/backups/upcoming_matchdates/{backup_name})."
        flash(msg, "success")
    finally:
        connection.close()

    return redirect(url_for("planner.planner"))


@planner_bp.route("/planner/events/<int:event_id>/delete", methods=["POST"])
@require_admin
def delete_event_route(event_id):
    """Cancel and delete an upcoming match event."""
    connection = get_planner_connection()
    try:
        delete_event(connection, event_id)
        flash("Match event has been cancelled and removed.", "info")
    finally:
        connection.close()

    return redirect(url_for("planner.planner"))


@planner_bp.route("/settings/attendance-name", methods=["POST"])
@require_tier(Tier.USER)
def update_attendance_name():
    """Update member's attendance display name."""
    user = get_current_user()
    new_name = request.form.get("attendance_name", "").strip()

    if not new_name:
        flash("Attendance name cannot be empty.", "warning")
        return redirect(request.referrer or url_for("planner.planner"))

    connection = get_accounts_connection()
    try:
        set_user_attendance_name(connection, user["id"], new_name)
        flash(f"Your attendance display name has been updated to '{new_name}'.", "success")
    finally:
        connection.close()

    return redirect(request.referrer or url_for("planner.planner"))


@planner_bp.route("/planner/export.ics")
@require_tier(Tier.USER)
def export_ics():
    """Export upcoming match events as an iCalendar (.ics) file."""
    from flask import Response
    connection = get_planner_connection()
    try:
        events = get_upcoming_events(connection)
    finally:
        connection.close()

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//RB48 Köln e.V.//Matchday Planner//DE",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:RB48 Spieltage",
        "X-WR-TIMEZONE:Europe/Berlin",
    ]
    
    now_utc_str = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    
    for row in events:
        ev = dict(row)
        date_val = ev.get("event_date", "")
        try:
            if "T" in date_val:
                dt = datetime.fromisoformat(date_val)
            elif " " in date_val:
                dt = datetime.strptime(date_val, "%Y-%m-%d %H:%M")
            else:
                dt = datetime.strptime(date_val, "%Y-%m-%d")
        except Exception:
            continue
            
        dt_start_str = dt.strftime("%Y%m%dT%H%M%S")
        dt_end = dt + timedelta(hours=2)
        dt_end_str = dt_end.strftime("%Y%m%dT%H%M%S")
        title = ev.get("title") or "Kickoff"
        summary = f"RB48 Spieltag - {title}"
        location = ev.get("location") or "SoccerWorld Köln"
        max_p = ev.get("max_players", 10)
        description = f"RB48 Kickoff Spieltag. Max Spieler: {max_p}"
        uid = f"rb48-event-{ev.get('id', 0)}@rb48.de"
        
        lines.extend([
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{now_utc_str}",
            f"DTSTART;TZID=Europe/Berlin:{dt_start_str}",
            f"DTEND;TZID=Europe/Berlin:{dt_end_str}",
            f"SUMMARY:{summary}",
            f"LOCATION:{location}",
            f"DESCRIPTION:{description}",
            "STATUS:CONFIRMED",
            "END:VEVENT",
        ])
        
    lines.append("END:VCALENDAR")
    ics_data = "\r\n".join(lines) + "\r\n"
    return Response(
        ics_data,
        mimetype="text/calendar",
        headers={"Content-Disposition": "attachment; filename=rb48_matchdays.ics"}
    )
