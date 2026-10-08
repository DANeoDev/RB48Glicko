from flask import (
    Blueprint,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
import math
from datetime import datetime
from zoneinfo import ZoneInfo
from scripts.utils.timezone import COLOGNE_TZ, get_cologne_now
from scripts.accounts.database import (
    get_accounts_connection,
    get_opted_out_player_ids,
    get_stats_opted_out_player_ids,
    get_user_by_player_id,
    get_user_seen_achievements,
    mark_user_achievements_seen,
    get_match_mvp_podium,
    get_mvp_medal_table,
    get_user_mvp_votes_for_matches,
    record_match_mvp_votes,
    get_user_match_mvp_votes,
    get_match_mvp_deadline,
    is_match_mvp_voting_open,
    get_match_mvp_results,
)
from scripts.analysis.achievements import get_player_achievements
from scripts.analysis.history_snapshots import (
    get_matchday_metadata_map,
)
from scripts.analysis.model_analysis import analyze_model
from scripts.analysis.synergies import get_community_synergies, filter_synergies_by_excluded_players
from scripts.database.database import get_connection
from scripts.database.db_matches import (
    get_player_stats,
    get_matches,
    get_match_teams,
    get_all_match_players,
    get_canonical_mvp_match_id,
    get_box_session_matches,
    get_box_session_participants,
    natural_match_sort_key,
)
from scripts.database.db_players import get_players
from scripts.database.db_ratings import get_player_rating_history, get_ratings
from scripts.frontend.view_models import (
    build_match_history,
)
from scripts.glicko.glicko2 import BOX, HF, TOTAL
from web.services.cache import (
    get_cached_stats_data,
    get_cached_match_history,
)
from web.services.security import (
    Tier,
    get_current_user,
    has_tier,
    require_tier,
)
from .news import get_dashboard_news

stats_bp = Blueprint("stats", __name__)


@stats_bp.route("/")
def home():
    news, has_more_news = get_dashboard_news()
    return render_template("dashboard.html", news=news, has_more_news=has_more_news)


@stats_bp.route("/dashboard")
def dashboard():
    news, has_more_news = get_dashboard_news()
    return render_template("dashboard.html", news=news, has_more_news=has_more_news)


@stats_bp.route("/stats")
@require_tier(Tier.USER)
def stats():
    cached = get_cached_stats_data()

    leaderboard = [dict(p) for p in cached["leaderboard_base"]]
    streaks = cached["streaks"]
    historical_snapshots = cached["historical_snapshots"]

    acc_conn = get_accounts_connection()
    try:
        opted_out_player_ids = get_opted_out_player_ids(acc_conn)
        stats_opted_out_player_ids = get_stats_opted_out_player_ids(acc_conn)
    finally:
        acc_conn.close()

    synergies = filter_synergies_by_excluded_players(cached["synergies"], stats_opted_out_player_ids)
    if stats_opted_out_player_ids:
        streaks = {
            "active_win_streaks": [s for s in streaks.get("active_win_streaks", []) if s["player_id"] not in stats_opted_out_player_ids],
            "all_time_win_streaks": [s for s in streaks.get("all_time_win_streaks", []) if s["player_id"] not in stats_opted_out_player_ids],
            "most_improved": streaks.get("most_improved", [])
        }

    curr_user = get_current_user()
    user_has_opt_out = bool(curr_user and curr_user.get("glicko_opt_out"))

    if user_has_opt_out:
        leaderboard.sort(key=lambda p: -p["total"].get("games", 0))
    elif not has_tier(Tier.WEBMASTER) and opted_out_player_ids:
        leaderboard.sort(key=lambda p: (p["player_id"] in opted_out_player_ids, -p["total"]["conservative"]))

    return render_template(
        "stats.html",
        leaderboard=leaderboard,
        synergies=synergies,
        streaks=streaks,
        opted_out_player_ids=opted_out_player_ids,
        stats_opted_out_player_ids=stats_opted_out_player_ids,
        historical_snapshots=historical_snapshots,
    )


@stats_bp.route("/my-stats")
@require_tier(Tier.USER)
def my_stats():
    user = get_current_user()
    if user and user.get("player_id"):
        return redirect(url_for("stats.player_profile", player_id=user["player_id"]))
    flash("Bitte verknüpfe dein Benutzerkonto in den Einstellungen mit einem Spieler, um deine persönlichen Statistiken direkt aufzurufen.", "info")
    return redirect(url_for("auth.settings"))


@stats_bp.route("/player/<int:player_id>")
@require_tier(Tier.USER)
def player_profile(player_id):
    pitch_map = {"total": TOTAL, "box": BOX, "hf": HF}
    connection = get_connection()
    try:
        players = get_players(connection)
        ratings = get_ratings(connection)
        player_stats = get_player_stats(connection)
        rating_history = get_player_rating_history(connection, player_id)
        selected_rating_type = request.args.get("rating_type", "total").lower()
        selected_rating_type = selected_rating_type if selected_rating_type in ("total", "box", "hf") else "total"
        matches = build_match_history(connection, players, player_id, pitch_map[selected_rating_type])
        metadata_map = get_matchday_metadata_map(connection)
    finally:
        connection.close()

    rating_extremes = {}
    for rating_type in ["total", "box", "hf"]:
        history = rating_history[rating_type]
        rating_extremes[rating_type] = {
            "peak": max(history, key=lambda entry: entry["rating"]),
            "low": min(history, key=lambda entry: entry["rating"])
        } if history else {"peak": None, "low": None}

    # Enrich each match with metadata
    for m in matches:
        meta = metadata_map.get(m["date"], {})
        m["date_formatted"] = meta.get("date_formatted", m["date"])
        m["matchday_number"] = meta.get("matchday_number", 1)
        m["season"] = meta.get("season", 2026)
        m["matchday_label"] = meta.get("label", f"{meta.get('matchday_number', 1)}. Spieltag")
        m["short_label"] = meta.get("short_label", f"{meta.get('matchday_number', 1)}. Spieltag")
        m["month_key"] = meta.get("month_key", m["date"][:7])
        m["month_label"] = meta.get("month_label", m["date"][:7])
        m["month_vertical"] = meta.get("month_vertical", m["date"][:7])

    matches.reverse()

    # Group matches by month
    months_dict = {}
    for m in matches:
        mkey = m["month_key"]
        if mkey not in months_dict:
            months_dict[mkey] = {
                "month_key": mkey,
                "month_label": m["month_label"],
                "month_vertical": m["month_vertical"],
                "matches": [],
            }
        months_dict[mkey]["matches"].append(m)

    months_grouped = list(months_dict.values())

    # Build timeline items (newest at top of the scrollbar)
    distinct_dates_seen = set()
    timeline_matchdays = []
    for m in matches:
        d = m["date"]
        if d not in distinct_dates_seen:
            distinct_dates_seen.add(d)
            meta = metadata_map.get(d, {})
            day_matches = [x for x in matches if x["date"] == d]
            pitches = sorted(list(set(x["pitch"].upper() for x in day_matches)))
            timeline_matchdays.append({
                "id": f"d-{d}",
                "date": d,
                "date_formatted": meta.get("date_formatted", d),
                "season": meta.get("season", 2026),
                "matchday_number": meta.get("matchday_number", 1),
                "label": meta.get("label", f"{meta.get('matchday_number', 1)}. Spieltag"),
                "short_label": meta.get("short_label", f"{meta.get('matchday_number', 1)}. Spieltag"),
                "month_key": meta.get("month_key", d[:7]),
                "month_label": meta.get("month_label", d[:7]),
                "matches_count": len(day_matches),
                "pitch_types": pitches,
            })

    timeline_months = []
    for mg in months_grouped:
        m_matches = mg["matches"]
        pitches = sorted(list(set(x["pitch"].upper() for x in m_matches)))
        timeline_months.append({
            "id": f"m-{mg['month_key']}",
            "month_key": mg["month_key"],
            "month_label": mg["month_label"],
            "month_vertical": mg["month_vertical"],
            "date": m_matches[0]["date"],
            "date_formatted": m_matches[0]["date_formatted"],
            "label": mg["month_label"],
            "short_label": mg["month_label"],
            "matches_count": len(m_matches),
            "pitch_types": pitches,
        })

    timeline_data = {
        "matchdays": timeline_matchdays,
        "months": timeline_months,
    }

    acc_conn = get_accounts_connection()
    try:
        linked_user = get_user_by_player_id(acc_conn, player_id)
        linked_user = dict(linked_user) if linked_user else None
        opted_out_player_ids = get_opted_out_player_ids(acc_conn)
        stats_opted_out_player_ids = get_stats_opted_out_player_ids(acc_conn)
    finally:
        acc_conn.close()

    players_map = {pid: p["aliases"][0] for pid, p in players.items()}
    is_player_opted_out = (player_id in opted_out_player_ids) and not has_tier(Tier.WEBMASTER)
    is_player_stats_opted_out = player_id in stats_opted_out_player_ids
    show_player_glicko = has_tier(Tier.GLICKO_USER) and not is_player_opted_out

    return render_template(
        "player.html",
        player=players[player_id],
        ratings=ratings[player_id],
        stats=player_stats[player_id],
        rating_history=rating_history,
        rating_extremes=rating_extremes,
        matches=matches,
        months_grouped=months_grouped,
        timeline_data=timeline_data,
        selected_rating_type=selected_rating_type,
        player_id=player_id,
        linked_user=linked_user,
        players_map=players_map,
        opted_out_player_ids=opted_out_player_ids,
        stats_opted_out_player_ids=stats_opted_out_player_ids,
        is_player_opted_out=is_player_opted_out,
        is_player_stats_opted_out=is_player_stats_opted_out,
        show_player_glicko=show_player_glicko,
    )


@stats_bp.route("/matches")
def match_history():
    selected_rating_type = request.args.get("rating_type", "total").lower()
    selected_rating_type = selected_rating_type if selected_rating_type in ("total", "box", "hf") else "total"
    cached = get_cached_match_history(rating_type=selected_rating_type)
    matches = cached["matches"]
    months_grouped = cached["months_grouped"]
    timeline_data = cached["timeline_data"]

    curr_user = get_current_user()
    curr_user_player_id = curr_user.get("player_id") if curr_user else None

    # Group Box matches by date to resolve unified Box evening MVP appointments
    date_box_matches = {}
    for m in matches:
        if str(m.get("pitch", "")).lower() == "box":
            date_box_matches.setdefault(m["date"], []).append(m)

    match_canonical_id = {}
    box_evening_participants = {}
    for m in matches:
        mid = m["match_id"]
        if str(m.get("pitch", "")).lower() == "box":
            b_list = sorted(date_box_matches[m["date"]], key=natural_match_sort_key)
            can_id = b_list[-1]["match_id"]
            match_canonical_id[mid] = can_id
            if can_id not in box_evening_participants:
                p_set = set()
                for bm in b_list:
                    p_set.update(bm.get("team_a_ids", []))
                    p_set.update(bm.get("team_b_ids", []))
                box_evening_participants[can_id] = p_set
        else:
            match_canonical_id[mid] = mid

    all_needed_mids = list(set(list(match_canonical_id.keys()) + list(match_canonical_id.values())))

    acc_conn = get_accounts_connection()
    try:
        opted_out_player_ids = get_opted_out_player_ids(acc_conn)
        all_mvp_podiums = get_match_mvp_podium(acc_conn, match_ids=all_needed_mids)
        user_mvp_votes = {}
        if curr_user and curr_user.get("id"):
            user_mvp_votes = get_user_mvp_votes_for_matches(acc_conn, curr_user["id"], match_ids=all_needed_mids)
    finally:
        acc_conn.close()

    now_dt = get_cologne_now()
    match_voting_status = {}
    for m in matches:
        mid = m["match_id"]
        can_id = match_canonical_id[mid]
        is_box = (str(m.get("pitch", "")).lower() == "box")
        m_date = m.get("date", "")
        deadline = get_match_mvp_deadline(m_date)
        is_open = now_dt <= deadline

        # For Box matches, only the last match of the day displays the MVP voting UI (card & symbol)
        is_last_match_of_day = (mid == can_id) if is_box else True

        if is_box:
            participant_ids = box_evening_participants.get(can_id, set())
        else:
            participant_ids = set(m.get("team_a_ids", []) + m.get("team_b_ids", []))

        can_vote = bool(is_open and curr_user_player_id and curr_user_player_id in participant_ids and is_last_match_of_day)
        show_voting_ui = bool(is_open and is_last_match_of_day)
        if can_vote:
            restriction_reason = None
        elif not curr_user:
            restriction_reason = "not_logged_in"
        elif not curr_user_player_id:
            restriction_reason = "not_linked"
        elif curr_user_player_id not in participant_ids:
            restriction_reason = "not_participant"
        else:
            restriction_reason = "not_eligible"

        user_votes_list = user_mvp_votes.get(can_id, [])
        if not user_votes_list and is_box:
            for bm in date_box_matches.get(m_date, []):
                if user_mvp_votes.get(bm["match_id"]):
                    user_votes_list = user_mvp_votes.get(bm["match_id"])
                    break
        user_vote_1 = user_votes_list[0] if user_votes_list else None

        # MVP podium: shown once voting is closed
        raw_podium = all_mvp_podiums.get(can_id, {})
        if not raw_podium.get("details") and is_box:
            for bm in date_box_matches.get(m_date, []):
                if all_mvp_podiums.get(bm["match_id"], {}).get("details"):
                    raw_podium = all_mvp_podiums.get(bm["match_id"], {})
                    break
        has_votes = bool(raw_podium.get("details") and is_last_match_of_day)
        podium = raw_podium if not is_open else {}
        gold_ids = podium.get("gold", [])
        silver_ids = podium.get("silver", [])
        bronze_ids = podium.get("bronze", [])

        match_voting_status[mid] = {
            "is_open": is_open,
            "can_vote": can_vote,
            "show_voting_ui": show_voting_ui,
            "restriction_reason": restriction_reason,
            "has_votes": has_votes,
            "user_vote": user_vote_1,
            "user_votes": user_votes_list,
            "mvp_player_ids": gold_ids,
            "gold_player_ids": gold_ids,
            "silver_player_ids": silver_ids,
            "bronze_player_ids": bronze_ids,
            "deadline_str": deadline.strftime("%d.%m.%Y um %H:%M Uhr"),
            "deadline_short": deadline.strftime("%d.%m., %H:%M"),
            "is_box_session": is_box,
            "is_last_match_of_day": is_last_match_of_day,
            "canonical_match_id": can_id,
        }

    GAMES_PER_PAGE = 12
    raw_page = request.args.get("page", 1, type=int)
    total_games = len(matches)
    max_page = max(1, math.ceil(total_games / GAMES_PER_PAGE))
    page = max(1, min(raw_page if raw_page is not None else 1, max_page))

    start_idx = (page - 1) * GAMES_PER_PAGE
    end_idx = start_idx + GAMES_PER_PAGE
    page_matches = matches[start_idx:end_idx]

    # Re-group page matches into month groups for this page slice
    page_months_dict = {}
    for m in page_matches:
        mkey = m.get("month_key", m.get("date", "")[:7])
        if mkey not in page_months_dict:
            page_months_dict[mkey] = {
                "month_key": mkey,
                "month_label": m.get("month_label", mkey),
                "month_vertical": m.get("month_vertical", mkey),
                "matches": [],
            }
        page_months_dict[mkey]["matches"].append(m)
    page_months_grouped = list(page_months_dict.values())

    # Build timeline_data for page matches
    page_dates = set(m["date"] for m in page_matches)
    page_timeline_matchdays = [d for d in timeline_data.get("matchdays", []) if d["date"] in page_dates]
    page_month_keys = set(page_months_dict.keys())
    page_timeline_months = [m for m in timeline_data.get("months", []) if m["month_key"] in page_month_keys]
    page_timeline_data = {
        "matchdays": page_timeline_matchdays,
        "months": page_timeline_months,
    }

    pagination = {
        "page": page,
        "max_page": max_page,
        "total_games": total_games,
        "per_page": GAMES_PER_PAGE,
        "has_prev": page > 1,
        "has_next": page < max_page,
        "prev_page": page - 1 if page > 1 else None,
        "next_page": page + 1 if page < max_page else None,
    }

    return render_template(
        "matches.html",
        matches=page_matches,
        months_grouped=page_months_grouped,
        timeline_data=page_timeline_data,
        pagination=pagination,
        selected_rating_type=selected_rating_type,
        opted_out_player_ids=opted_out_player_ids,
        is_webmaster=has_tier(Tier.WEBMASTER),
        match_voting_status=match_voting_status,
        curr_user=curr_user,
    )


@stats_bp.route("/api/matches/<match_id>/mvp-vote", methods=["POST"])
def cast_mvp_vote(match_id):
    user = get_current_user()
    if not user:
        return jsonify({"success": False, "error": "Bitte melde dich an, um abzustimmen."}), 401

    player_id = user.get("player_id")
    if not player_id:
        return jsonify({"success": False, "error": "Dein Benutzerkonto muss mit einem Spieler verknüpft sein, um abzustimmen."}), 403

    data = request.get_json(silent=True) or request.form
    voted_player_ids = []

    # Support multiple ballot formats: array 'voted_player_ids' or single 'voted_player_id' or distinct slots 'voted_player_id_1', etc.
    if "voted_player_ids" in data:
        raw_list = data.get("voted_player_ids")
        if isinstance(raw_list, list):
            for v in raw_list:
                if v is not None and str(v).strip():
                    try:
                        voted_player_ids.append(int(v))
                    except (ValueError, TypeError):
                        pass
    elif "voted_player_id" in data:
        raw_v = data.get("voted_player_id")
        if raw_v is not None and str(raw_v).strip():
            try:
                voted_player_ids.append(int(raw_v))
            except (ValueError, TypeError):
                pass
    else:
        for slot in ("voted_player_id_1", "voted_player_id_2", "voted_player_id_3"):
            raw_v = data.get(slot)
            if raw_v is not None and str(raw_v).strip():
                try:
                    voted_player_ids.append(int(raw_v))
                except (ValueError, TypeError):
                    pass

    if not voted_player_ids:
        return jsonify({"success": False, "error": "Bitte wähle mindestens einen Spieler für deinen MVP-Vote aus."}), 400

    if len(voted_player_ids) > 3:
        return jsonify({"success": False, "error": "Du kannst maximal 3 Stimmen vergeben."}), 400

    # Ensure all votes are for distinct players
    if len(voted_player_ids) != len(set(voted_player_ids)):
        return jsonify({"success": False, "error": "Die Stimmen müssen an verschiedene Spieler vergeben werden."}), 400

    # Disallow self-voting
    if player_id in voted_player_ids:
        return jsonify({"success": False, "error": "Du darfst dich nicht selbst als MVP wählen."}), 400

    conn = get_connection()
    try:
        matches = get_matches(conn)
        match = matches.get(match_id)
        if not match:
            return jsonify({"success": False, "error": f"Match '{match_id}' wurde nicht gefunden."}), 404

        is_box = (str(match.get("pitch", "")).lower() == "box")
        if is_box:
            box_matches = get_box_session_matches(matches, match_id)
            canonical_match_id = box_matches[-1]["match_id"] if box_matches else match_id
            box_mids = [m["match_id"] for m in box_matches]
            all_players_map = get_all_match_players(conn)
            participants = set()
            for bmid in box_mids:
                for p in all_players_map.get(bmid, []):
                    participants.add(int(p["player_id"]))
        else:
            canonical_match_id = match_id
            box_mids = [match_id]
            team_a, team_b = get_match_teams(conn, match_id)
            participants = set(team_a + team_b)
    finally:
        conn.close()

    if player_id not in participants:
        err_msg = "Nur Spieler, die an diesem Box-Abend teilgenommen haben, dürfen für den MVP stimmen." if is_box else "Nur Spieler, die an diesem Match teilgenommen haben, dürfen für den MVP stimmen."
        return jsonify({"success": False, "error": err_msg}), 403

    match_date = match["date"]
    if not is_match_mvp_voting_open(match_date):
        deadline_str = get_match_mvp_deadline(match_date).strftime("%d.%m.%Y um %H:%M Uhr")
        return jsonify({"success": False, "error": f"Die Abstimmung für dieses Match ist seit dem {deadline_str} beendet."}), 400

    for pid in voted_player_ids:
        if pid not in participants:
            err_msg = "Alle gewählten Spieler müssen an diesem Box-Abend teilgenommen haben." if is_box else "Alle gewählten Spieler müssen an diesem Match teilgenommen haben."
            return jsonify({"success": False, "error": err_msg}), 400

    acc_conn = get_accounts_connection()
    try:
        record_match_mvp_votes(acc_conn, canonical_match_id, user["id"], voted_player_ids, session_match_ids=box_mids)
    except ValueError as ve:
        return jsonify({"success": False, "error": str(ve)}), 400
    finally:
        acc_conn.close()

    msg = "Deine Stimmen für den Box-Abend wurden erfolgreich und anonym gespeichert!" if is_box else "Deine Stimmen wurden erfolgreich und anonym gespeichert!"
    return jsonify({
        "success": True,
        "match_id": match_id,
        "canonical_match_id": canonical_match_id,
        "is_box_session": is_box,
        "box_matches": box_mids,
        "voted_player_ids": voted_player_ids,
        "voted_player_id": voted_player_ids[0] if voted_player_ids else None,
        "message": msg,
    })


@stats_bp.route("/api/matches/<match_id>/mvp-status", methods=["GET"])
def get_mvp_status(match_id):
    user = get_current_user()
    curr_user_player_id = user.get("player_id") if user else None

    conn = get_connection()
    try:
        matches = get_matches(conn)
        match = matches.get(match_id)
        if not match:
            return jsonify({"success": False, "error": f"Match '{match_id}' wurde nicht gefunden."}), 404

        players = get_players(conn)
        is_box = (str(match.get("pitch", "")).lower() == "box")
        if is_box:
            box_matches = get_box_session_matches(matches, match_id)
            canonical_match_id = box_matches[-1]["match_id"] if box_matches else match_id
            box_mids = [m["match_id"] for m in box_matches]
            all_players_map = get_all_match_players(conn)
            all_part_ids = set()
            for bmid in box_mids:
                for p in all_players_map.get(bmid, []):
                    all_part_ids.add(int(p["player_id"]))
            participants = list(all_part_ids)
            team_a, team_b = [], []
        else:
            canonical_match_id = match_id
            box_mids = [match_id]
            team_a, team_b = get_match_teams(conn, match_id)
            participants = team_a + team_b
    finally:
        conn.close()

    match_date = match["date"]
    deadline = get_match_mvp_deadline(match_date)
    is_open = is_match_mvp_voting_open(match_date)

    acc_conn = get_accounts_connection()
    try:
        user_votes = get_user_match_mvp_votes(acc_conn, canonical_match_id, user["id"]) if user and user.get("id") else []
        if not user_votes and is_box and user and user.get("id"):
            for bmid in box_mids:
                user_votes = get_user_match_mvp_votes(acc_conn, bmid, user["id"])
                if user_votes:
                    break
        elif not user_votes and canonical_match_id != match_id and user and user.get("id"):
            user_votes = get_user_match_mvp_votes(acc_conn, match_id, user["id"])
        podium_map = get_match_mvp_podium(acc_conn, match_ids=list(set([canonical_match_id, match_id] + box_mids)))
        podium = podium_map.get(canonical_match_id, {})
        if not podium.get("details") and is_box:
            for bmid in box_mids:
                if podium_map.get(bmid, {}).get("details"):
                    podium = podium_map.get(bmid, {})
                    break
        elif not podium.get("details"):
            podium = podium_map.get(match_id, {})
        if is_open:
            podium = {}
    finally:
        acc_conn.close()

    can_vote = bool(is_open and curr_user_player_id and curr_user_player_id in participants)
    if can_vote:
        restriction_reason = None
    elif not user:
        restriction_reason = "not_logged_in"
    elif not curr_user_player_id:
        restriction_reason = "not_linked"
    elif curr_user_player_id not in participants:
        restriction_reason = "not_participant"
    else:
        restriction_reason = "not_eligible"

    def player_info(pid):
        aliases = players.get(pid, {}).get("aliases", [])
        return {"id": pid, "name": aliases[0] if aliases else f"Player {pid}"}

    # Filter out current user from candidate choices (no self-voting)
    if is_box:
        box_candidate_ids = sorted(
            [pid for pid in participants if pid != curr_user_player_id],
            key=lambda pid: (players.get(pid, {}).get("aliases", [f"Player {pid}"])[0]).lower()
        )
        box_players = [player_info(pid) for pid in box_candidate_ids]
        team_a_players = box_players
        team_b_players = []
    else:
        team_a_players = [player_info(pid) for pid in team_a if pid != curr_user_player_id]
        team_b_players = [player_info(pid) for pid in team_b if pid != curr_user_player_id]
        box_players = []

    return jsonify({
        "success": True,
        "match_id": match_id,
        "canonical_match_id": canonical_match_id,
        "is_box_session": is_box,
        "box_matches": box_mids,
        "match_date": match_date,
        "is_open": is_open,
        "deadline_iso": deadline.isoformat(),
        "deadline_formatted": deadline.strftime("%d.%m.%Y um %H:%M Uhr"),
        "can_vote": can_vote,
        "restriction_reason": restriction_reason,
        "user_vote": user_votes[0] if user_votes else None,
        "user_votes": user_votes,
        "mvp_player_ids": podium.get("gold", []),
        "gold_player_ids": podium.get("gold", []),
        "silver_player_ids": podium.get("silver", []),
        "bronze_player_ids": podium.get("bronze", []),
        "team_a_players": team_a_players,
        "team_b_players": team_b_players,
        "box_players": box_players,
    })


@stats_bp.route("/api/matches/<match_id>/mvp-results", methods=["GET"])
def get_mvp_results(match_id):
    """
    Returns aggregated MVP election results for a match once voting has concluded.
    Strictly preserves voter ballot secrecy.
    """
    conn = get_connection()
    try:
        matches = get_matches(conn)
        match = matches.get(match_id)
        if not match:
            return jsonify({"success": False, "error": f"Match '{match_id}' wurde nicht gefunden."}), 404
        players = get_players(conn)
        is_box = (str(match.get("pitch", "")).lower() == "box")
        if is_box:
            box_matches = get_box_session_matches(matches, match_id)
            canonical_match_id = box_matches[-1]["match_id"] if box_matches else match_id
            box_mids = [m["match_id"] for m in box_matches]
        else:
            canonical_match_id = match_id
            box_mids = [match_id]
    finally:
        conn.close()

    match_date = match["date"]
    deadline = get_match_mvp_deadline(match_date)
    is_open = is_match_mvp_voting_open(match_date)

    acc_conn = get_accounts_connection()
    try:
        target_mids = box_mids if is_box else [match_id]
        res = get_match_mvp_results(acc_conn, canonical_match_id, players_dict=players, match_ids=target_mids)
        if res.get("total_voters", 0) == 0 and is_box:
            for bmid in box_mids:
                alt_res = get_match_mvp_results(acc_conn, bmid, players_dict=players, match_ids=[bmid])
                if alt_res.get("total_voters", 0) > 0:
                    res = alt_res
                    break
        elif res.get("total_voters", 0) == 0 and canonical_match_id != match_id:
            alt_res = get_match_mvp_results(acc_conn, match_id, players_dict=players, match_ids=[match_id])
            if alt_res.get("total_voters", 0) > 0:
                res = alt_res
    finally:
        acc_conn.close()

    if is_open:
        return jsonify({
            "success": False,
            "error": f"Die MVP-Wahlergebnisse werden nach Fristende ({deadline.strftime('%d.%m.%Y um %H:%M Uhr')}) veröffentlicht.",
            "is_open": True,
            "deadline_formatted": deadline.strftime("%d.%m.%Y um %H:%M Uhr"),
        }), 400

    return jsonify({
        "success": True,
        "match_id": match_id,
        "canonical_match_id": canonical_match_id,
        "is_box_session": is_box,
        "box_matches": box_mids,
        "match_date": match_date,
        "is_open": False,
        "deadline_formatted": deadline.strftime("%d.%m.%Y um %H:%M Uhr"),
        "total_voters": res["total_voters"],
        "candidates": res["candidates"],
        "ballots": res.get("ballots", []),
    })


@stats_bp.route("/stats/mvp-medals")
@require_tier(Tier.USER)
def mvp_medals():
    """MVP Medal table filtered by year and time period (Quarters, Half-years, All-time)."""
    selected_year = request.args.get("year", "all").strip()
    selected_period = request.args.get("period", "all").strip().upper()

    conn = get_connection()
    try:
        matches = get_matches(conn)
        players = get_players(conn)
    finally:
        conn.close()

    # Extract all distinct years from recorded matches
    available_years = sorted(
        list({m["date"][:4] for m in matches.values() if m.get("date") and len(m["date"]) >= 4}),
        reverse=True,
    )

    # Filter match IDs by year and period
    filtered_match_ids = []
    for mid, m in matches.items():
        m_date = m.get("date", "")
        if not m_date or len(m_date) < 7:
            continue
        m_year = m_date[:4]
        m_month = m_date[5:7]

        # Year check
        if selected_year != "all" and m_year != selected_year:
            continue

        # Period check
        if selected_period == "Q1" and m_month not in ("01", "02", "03"):
            continue
        elif selected_period == "Q2" and m_month not in ("04", "05", "06"):
            continue
        elif selected_period == "Q3" and m_month not in ("07", "08", "09"):
            continue
        elif selected_period == "Q4" and m_month not in ("10", "11", "12"):
            continue
        elif selected_period == "H1" and m_month not in ("01", "02", "03", "04", "05", "06"):
            continue
        elif selected_period == "H2" and m_month not in ("07", "08", "09", "10", "11", "12"):
            continue

        filtered_match_ids.append(mid)

    acc_conn = get_accounts_connection()
    try:
        opted_out_player_ids = get_opted_out_player_ids(acc_conn)
        medal_table = get_mvp_medal_table(acc_conn, matches, filtered_match_ids=filtered_match_ids)
    finally:
        acc_conn.close()

    # Enrich medal table with player details
    total_gold_awarded = 0
    total_silver_awarded = 0
    total_bronze_awarded = 0

    for row in medal_table:
        pid = row["player_id"]
        p = players.get(pid, {})
        aliases = p.get("aliases", [])
        row["player_name"] = aliases[0] if aliases else f"Player {pid}"
        total_gold_awarded += row["gold"]
        total_silver_awarded += row["silver"]
        total_bronze_awarded += row["bronze"]

    return render_template(
        "mvp_medals.html",
        medal_table=medal_table,
        available_years=available_years,
        selected_year=selected_year,
        selected_period=selected_period,
        filtered_matches_count=len(filtered_match_ids),
        total_gold_awarded=total_gold_awarded,
        total_silver_awarded=total_silver_awarded,
        total_bronze_awarded=total_bronze_awarded,
        opted_out_player_ids=opted_out_player_ids,
        is_webmaster=has_tier(Tier.WEBMASTER),
    )


@stats_bp.route("/matches/delete", methods=["POST"])
@require_tier(Tier.ADMIN)
def delete_match_endpoint():
    match_id = None
    if request.is_json:
        data = request.get_json(silent=True) or {}
        match_id = data.get("match_id")
    if not match_id:
        match_id = request.form.get("match_id")

    is_xhr = request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.is_json

    if not match_id:
        if is_xhr:
            return jsonify({"success": False, "error": "Match ID is required."}), 400
        flash("Match ID is required.", "error")
        return redirect(url_for("stats.match_history"))

    from scripts.matches.match_entry import delete_match
    from web.services.cache import invalidate_stats_cache

    connection = get_connection()
    try:
        del_result = delete_match(connection, match_id)
        invalidate_stats_cache()
    except (ValueError, Exception) as exc:
        if is_xhr:
            return jsonify({"success": False, "error": str(exc)}), 400
        flash(str(exc), "error")
        return redirect(url_for("stats.match_history"))
    finally:
        connection.close()

    backup_info = ""
    if isinstance(del_result, dict) and del_result.get("backup_file"):
        backup_info = f" (Matchday CSV-Backup: data/backups/matches/{del_result['backup_file']})"
    success_msg = f"Match '{match_id}' wurde erfolgreich gelöscht und alle Glicko-Ratings neu berechnet.{backup_info}"
    if is_xhr:
        return jsonify({
            "success": True,
            "message": success_msg,
            "deleted_match_id": match_id,
            "backup_file": del_result.get("backup_file") if isinstance(del_result, dict) else None,
        })
    flash(success_msg, "success")
    return redirect(url_for("stats.match_history"))


@stats_bp.route("/admin/recalculate-glicko", methods=["POST"])
@require_tier(Tier.WEBMASTER)
def recalculate_glicko_endpoint():
    is_xhr = request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.is_json
    from scripts.glicko.glicko2_calculator import recalculate_glicko2_ratings
    from web.services.cache import invalidate_stats_cache

    try:
        result = recalculate_glicko2_ratings(create_backup=True)
        invalidate_stats_cache()
    except Exception as exc:
        if is_xhr:
            return jsonify({"success": False, "error": str(exc)}), 500
        flash(f"Fehler bei der Neuberechnung: {exc}", "error")
        return redirect(request.referrer or url_for("stats.match_history"))

    backup_file = result.get("backup_file")
    matches_count = result.get("matches_count", 0)
    players_count = result.get("players_count", 0)
    backup_note = f" (Datenbank-Backup archiviert unter data/backups/{backup_file})" if backup_file else ""
    success_msg = f"Glicko-2 Tabelle erfolgreich neu berechnet ({matches_count} Spiele, {players_count} Spieler).{backup_note}"

    if is_xhr:
        return jsonify({
            "success": True,
            "message": success_msg,
            "backup_file": backup_file,
            "matches_count": matches_count,
            "players_count": players_count,
        })

    flash(success_msg, "success")
    return redirect(request.referrer or url_for("stats.match_history"))


@stats_bp.route("/model-analysis")
@require_tier(Tier.GLICKO_USER)
def model_analysis():
    pitch = request.args.get("pitch", "total").lower()
    if pitch not in ("total", "box", "hf"):
        pitch = "total"

    mode = "total" if pitch == "total" else "pitch"
    connection = get_connection()
    try:
        if pitch == "total":
            analysis = analyze_model(connection, mode=TOTAL)
        elif pitch == "box":
            analysis = analyze_model(connection, mode="pitch", pitch=BOX)
        else:
            analysis = analyze_model(connection, mode="pitch", pitch=HF)

        return render_template(
            "model_analysis.html",
            analysis=analysis,
            mode=mode,
            pitch=pitch,
        )
    finally:
        connection.close()


@stats_bp.route("/glickofaq")
def glicko_explainer():
    return render_template("glickofaq.html")


@stats_bp.route("/model-documentation")
def model_documentation():
    """Detailed technical and conceptual documentation of the team-based Glicko-2 model."""
    from pathlib import Path
    from scripts.docs.generate_model_docs import markdown_to_html, update_docs_file
    docs_file = Path(__file__).resolve().parent.parent.parent / "docs" / "GLICKO2_TEAM_MODEL.md"
    if not docs_file.exists():
        update_docs_file()
    md_content = docs_file.read_text(encoding="utf-8")
    content_html = markdown_to_html(md_content)
    return render_template("model_docs.html", content_html=content_html)


@stats_bp.route("/model-documentation/raw")
def model_documentation_raw():
    """Serve the raw markdown file of the model documentation."""
    from pathlib import Path
    from flask import Response
    docs_file = Path(__file__).resolve().parent.parent.parent / "docs" / "GLICKO2_TEAM_MODEL.md"
    if not docs_file.exists():
        from scripts.docs.generate_model_docs import update_docs_file
        update_docs_file()
    content = docs_file.read_text(encoding="utf-8")
    return Response(content, mimetype="text/markdown; charset=utf-8")


@stats_bp.route("/about")
def about():
    """About RB 48 Köln e.V. history, formats, and community philosophy."""
    return render_template("about.html")


@stats_bp.route("/api/players-list")
@require_tier(Tier.USER)
def api_players_list():
    """Return all active players for global search and autocomplete."""
    connection = get_connection()
    try:
        players = get_players(connection)
        ratings = get_ratings(connection)
    finally:
        connection.close()

    acc_conn = get_accounts_connection()
    try:
        opted_out_player_ids = get_opted_out_player_ids(acc_conn)
    finally:
        acc_conn.close()

    can_view_glicko = has_tier(Tier.GLICKO_USER)
    is_webmaster = has_tier(Tier.WEBMASTER)

    result = []
    for pid, p in players.items():
        show_rating = can_view_glicko and (is_webmaster or pid not in opted_out_player_ids)
        r = ratings.get(pid, {}).get("total", {}).get("rating") if show_rating else None
        result.append({
            "id": pid,
            "name": p["aliases"][0],
            "rating": round(r, 1) if r else None
        })
    result.sort(key=lambda x: x["name"].lower())
    return jsonify(result)


@stats_bp.route("/api/community-synergies")
@require_tier(Tier.USER)
def api_community_synergies():
    """Return community synergy duos and rivalries."""
    min_games = request.args.get("min_games", 5, type=int)
    acc_conn = get_accounts_connection()
    try:
        stats_opted_out_player_ids = get_stats_opted_out_player_ids(acc_conn)
    finally:
        acc_conn.close()

    connection = get_connection()
    try:
        synergies = get_community_synergies(connection, min_games=min_games, exclude_player_ids=stats_opted_out_player_ids)
    finally:
        connection.close()
    return jsonify(synergies)


@stats_bp.route("/achievements")
@require_tier(Tier.USER)
def achievements_overview():
    user = get_current_user()
    if not user:
        return redirect(url_for("auth.login", next=request.path))
    if user.get("player_id"):
        return redirect(url_for("stats.player_achievements", player_id=user["player_id"]))
    if has_tier(Tier.WEBMASTER):
        connection = get_connection()
        try:
            players = get_players(connection)
        finally:
            connection.close()
        first_pid = next(iter(players.keys()), 1)
        return redirect(url_for("stats.player_achievements", player_id=first_pid))
    flash("Bitte verknüpfe dein Profil in den Einstellungen mit einem Spieler, um deine Auszeichnungen zu sehen.", "info")
    return redirect(url_for("auth.settings"))


@stats_bp.route("/achievements/<int:player_id>")
@require_tier(Tier.USER)
def player_achievements(player_id: int):
    user = get_current_user()
    if not user:
        return redirect(url_for("auth.login", next=request.path))

    is_webmaster = has_tier(Tier.WEBMASTER)
    if not is_webmaster and user.get("player_id") != player_id:
        if user.get("player_id"):
            flash("Du kannst nur deine eigenen Auszeichnungen einsehen.", "info")
            return redirect(url_for("stats.player_achievements", player_id=user["player_id"]))
        else:
            flash("Bitte verknüpfe dein Profil in den Einstellungen mit einem Spieler, um deine Auszeichnungen zu sehen.", "info")
            return redirect(url_for("auth.settings"))

    connection = get_connection()
    try:
        players = get_players(connection)
        if player_id not in players:
            return redirect(url_for("stats.achievements_overview"))
        user_has_glicko = has_tier(Tier.GLICKO_USER)

        is_own_profile = (user.get("player_id") == player_id)
        acc_conn = get_accounts_connection()
        try:
            seen_keys = get_user_seen_achievements(acc_conn, user["id"]) if is_own_profile else set()
            cached_data = get_cached_stats_data(connection)
            historical_snapshots = cached_data.get("historical_snapshots") if cached_data else None
            achievements = get_player_achievements(
                connection,
                player_id,
                user_has_glicko_tier=user_has_glicko,
                accounts_connection=acc_conn,
                historical_snapshots=historical_snapshots,
            )
            all_unlocked_keys = []
            for a in achievements:
                if a.get("unlocked") and a.get("tier") != "neutral":
                    k = f"{a['id']}:{a.get('tier', '')}"
                    all_unlocked_keys.append(k)
                    if is_own_profile and k not in seen_keys:
                        a["is_new"] = True

            if is_own_profile and all_unlocked_keys:
                mark_user_achievements_seen(acc_conn, user["id"], all_unlocked_keys)
                session["unseen_achievements_count"] = 0
        finally:
            acc_conn.close()
    finally:
        connection.close()

    players_map = {pid: p["aliases"][0] for pid, p in players.items()}
    unlocked_count = sum(1 for a in achievements if a.get("unlocked"))
    total_count = len(achievements)

    # Regular users only see unlocked achievements; Webmaster sees all
    if not is_webmaster:
        achievements = [a for a in achievements if a.get("unlocked")]

    return render_template(
        "achievements.html",
        player=players[player_id],
        player_id=player_id,
        players_map=players_map,
        achievements=achievements,
        unlocked_count=unlocked_count,
        total_count=total_count,
        is_webmaster=is_webmaster,
    )
