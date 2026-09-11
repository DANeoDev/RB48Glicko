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
from scripts.accounts.database import (
    get_accounts_connection,
    get_opted_out_player_ids,
    get_user_by_player_id,
    get_user_seen_achievements,
    mark_user_achievements_seen,
)
from scripts.analysis.achievements import get_player_achievements
from scripts.analysis.history_snapshots import (
    get_matchday_metadata_map,
)
from scripts.analysis.model_analysis import analyze_model, analyze_whr_model
from scripts.analysis.synergies import get_community_synergies
from scripts.database.database import get_connection
from scripts.database.db_matches import get_player_stats
from scripts.database.db_players import get_players
from scripts.database.db_ratings import get_player_rating_history, get_ratings
from scripts.frontend.view_models import (
    build_match_history,
)
from scripts.glicko.glicko2 import BOX, HF, TOTAL
from web.services.cache import (
    get_cached_stats_data,
    get_cached_match_history,
    get_cached_whr_stats_data,
    get_cached_whr_match_history,
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
    active_model = session.get("active_model", "glicko") if has_tier(Tier.GLICKO_USER) else "glicko"
    if active_model == "whr":
        cached = get_cached_whr_stats_data()
    else:
        cached = get_cached_stats_data()

    leaderboard = [dict(p) for p in cached["leaderboard_base"]]
    synergies = cached["synergies"]
    streaks = cached["streaks"]
    historical_snapshots = cached["historical_snapshots"]

    acc_conn = get_accounts_connection()
    try:
        opted_out_player_ids = get_opted_out_player_ids(acc_conn)
    finally:
        acc_conn.close()

    if not has_tier(Tier.WEBMASTER) and opted_out_player_ids:
        leaderboard.sort(key=lambda p: (p["player_id"] in opted_out_player_ids, -p["total"]["conservative"]))

    return render_template(
        "stats.html",
        leaderboard=leaderboard,
        synergies=synergies,
        streaks=streaks,
        opted_out_player_ids=opted_out_player_ids,
        historical_snapshots=historical_snapshots,
        active_model=active_model,
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
    finally:
        acc_conn.close()

    players_map = {pid: p["aliases"][0] for pid, p in players.items()}
    is_player_opted_out = (player_id in opted_out_player_ids) and not has_tier(Tier.WEBMASTER)
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
        is_player_opted_out=is_player_opted_out,
        show_player_glicko=show_player_glicko,
    )


@stats_bp.route("/matches")
def match_history():
    selected_rating_type = request.args.get("rating_type", "total").lower()
    selected_rating_type = selected_rating_type if selected_rating_type in ("total", "box", "hf") else "total"
    active_model = session.get("active_model", "glicko") if has_tier(Tier.GLICKO_USER) else "glicko"
    if active_model == "whr":
        cached = get_cached_whr_match_history(rating_type=selected_rating_type)
    else:
        cached = get_cached_match_history(rating_type=selected_rating_type)
    matches = cached["matches"]
    months_grouped = cached["months_grouped"]
    timeline_data = cached["timeline_data"]

    acc_conn = get_accounts_connection()
    try:
        opted_out_player_ids = get_opted_out_player_ids(acc_conn)
    finally:
        acc_conn.close()

    return render_template(
        "matches.html",
        matches=matches,
        months_grouped=months_grouped,
        timeline_data=timeline_data,
        opted_out_player_ids=opted_out_player_ids,
        is_webmaster=has_tier(Tier.WEBMASTER),
        active_model=active_model,
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
    active_model = session.get("active_model", "glicko") if has_tier(Tier.GLICKO_USER) else "glicko"
    default_mode = "whr" if active_model == "whr" else "total"
    mode = request.args.get("mode", default_mode)
    mode = mode if mode in ("total", "pitch", "whr") else default_mode
    pitch = request.args.get("pitch", "total").lower()
    pitch = pitch if pitch in ("total", "box", "hf") else "total"
    connection = get_connection()
    try:
        if mode == "whr":
            whr_pitch = pitch if pitch != "total" else "total"
            analysis = analyze_whr_model(connection, mode="whr", pitch=whr_pitch)
            # Companion comparison series: Glicko for the matching pitch
            if whr_pitch == "total":
                comparison = analyze_model(connection, mode=TOTAL)
            elif whr_pitch == "box":
                comparison = analyze_model(connection, mode="pitch", pitch=BOX)
            else:
                comparison = analyze_model(connection, mode="pitch", pitch=HF)
            active_model_name = "WHR"
            comparison_model_name = "Glicko-2"
        elif mode == "pitch":
            pitch_choice = request.args.get("pitch", "box").lower()
            pitch_choice = "box" if pitch_choice not in ("box", "hf") else pitch_choice
            pitch = pitch_choice
            pitch_const = BOX if pitch_choice == "box" else HF
            analysis = analyze_model(connection, mode="pitch", pitch=pitch_const)
            comparison = analyze_whr_model(connection, mode="whr", pitch=pitch_choice)
            active_model_name = "Glicko-2"
            comparison_model_name = "WHR"
        else:
            analysis = analyze_model(connection, mode=TOTAL)
            comparison = analyze_whr_model(connection, mode="whr", pitch="total")
            active_model_name = "Glicko-2"
            comparison_model_name = "WHR"

        if comparison and "goal_diff_min" in analysis and "goal_diff_min" in comparison:
            y_min = min(analysis["goal_diff_min"], comparison["goal_diff_min"])
            y_max = max(analysis["goal_diff_max"], comparison["goal_diff_max"])
            is_box_or_total = (mode == "total" or pitch in ("total", "box"))
            step = 2 if is_box_or_total else (1 if (y_max - y_min) <= 8 else 2)
            unified_ticks = list(range(y_min, y_max + 1, step))
            analysis["goal_diff_min"] = y_min
            analysis["goal_diff_max"] = y_max
            analysis["goal_diff_ticks"] = unified_ticks

        return render_template(
            "model_analysis.html",
            analysis=analysis,
            comparison=comparison,
            mode=mode,
            pitch=pitch,
            active_model_name=active_model_name,
            comparison_model_name=comparison_model_name,
        )
    finally:
        connection.close()


@stats_bp.route("/model-comparison")
@stats_bp.route("/rating-comparison")
@require_tier(Tier.GLICKO_USER)
def rating_comparison():
    """Dedicated player-by-player rating comparison table between Glicko-2 and WHR."""
    from scripts.analysis.whr import compute_whr_ratings
    pitch = request.args.get("pitch", "total").lower()
    pitch = pitch if pitch in ("total", "box", "hf") else "total"
    pitch_const = BOX if pitch == "box" else (HF if pitch == "hf" else TOTAL)

    connection = get_connection()
    try:
        whr_data = compute_whr_ratings(connection, pitch_filter=pitch_const)
        players = whr_data.get("players", [])

        deltas = [p["delta"] for p in players if p.get("delta") is not None]
        max_gain = max(players, key=lambda p: p["delta"]) if players else None
        max_drop = min(players, key=lambda p: p["delta"]) if players else None
        avg_abs_delta = round(sum(abs(d) for d in deltas) / len(deltas), 1) if deltas else 0.0

        return render_template(
            "rating_comparison.html",
            whr_data=whr_data,
            players=players,
            pitch=pitch,
            max_gain=max_gain,
            max_drop=max_drop,
            avg_abs_delta=avg_abs_delta,
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


@stats_bp.route("/whr-documentation")
def whr_documentation():
    """Detailed technical and conceptual documentation of the team-based Whole-History Rating model."""
    from pathlib import Path
    from scripts.docs.generate_model_docs import markdown_to_html
    docs_file = Path(__file__).resolve().parent.parent.parent / "docs" / "WHR_TEAM_MODEL.md"
    if docs_file.exists():
        md_content = docs_file.read_text(encoding="utf-8")
    else:
        md_content = "# Whole-History Rating (WHR) Modell-Dokumentation\n\nDokumentation wird geladen..."
    content_html = markdown_to_html(md_content)
    return render_template(
        "model_docs.html",
        content_html=content_html,
        doc_title="The RB48 Team-Based Whole-History Rating (WHR) Engine",
        doc_subtitle="Retrospective Bayesian Global MAP Optimization & Newton-Raphson Solver",
        raw_url=url_for("stats.whr_documentation_raw"),
        back_faq_url=url_for("stats.glicko_explainer") + "#faq-whr",
    )


@stats_bp.route("/whr-documentation/raw")
def whr_documentation_raw():
    """Serve the raw markdown file of the WHR model documentation."""
    from pathlib import Path
    from flask import Response
    docs_file = Path(__file__).resolve().parent.parent.parent / "docs" / "WHR_TEAM_MODEL.md"
    if docs_file.exists():
        content = docs_file.read_text(encoding="utf-8")
    else:
        content = "# Whole-History Rating (WHR) Modell-Dokumentation"
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
    connection = get_connection()
    try:
        synergies = get_community_synergies(connection, min_games=min_games)
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


@stats_bp.route("/set-model")
def set_model():
    """Switch active rating model between Glicko-2 and WHR for Glicko-tier users."""
    model = request.args.get("model", "glicko").lower()
    if model not in ("glicko", "whr"):
        model = "glicko"

    if has_tier(Tier.GLICKO_USER):
        session["active_model"] = model

    next_url = request.args.get("next") or request.referrer
    if not next_url or not next_url.startswith("/") or next_url.startswith("//"):
        next_url = url_for("stats.dashboard")
    return redirect(next_url)
