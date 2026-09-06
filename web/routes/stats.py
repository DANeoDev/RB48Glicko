from flask import Blueprint, render_template, request, jsonify, redirect, url_for, session
from scripts.database.database import get_connection
from scripts.database.db_ratings import get_ratings, get_player_rating_history
from scripts.database.db_players import get_players
from scripts.database.db_matches import get_player_stats
from scripts.frontend.view_models import build_leaderboard, build_match_history, compute_leaderboard_deltas
from scripts.analysis.model_analysis import analyze_model
from scripts.analysis.synergies import get_community_synergies
from scripts.analysis.streaks import get_dashboard_streaks
from scripts.analysis.achievements import get_player_achievements
from scripts.glicko.glicko2 import TOTAL, BOX, HF
from web.services.security import Tier, require_tier, has_tier, get_current_user
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
    connection = get_connection()
    ratings = get_ratings(connection)
    players = get_players(connection)
    player_stats = get_player_stats(connection)
    deltas = compute_leaderboard_deltas(connection, ratings, players)
    synergies = get_community_synergies(connection, min_games=5)
    streaks = get_dashboard_streaks(connection)
    connection.close()

    from scripts.accounts.database import get_accounts_connection, get_opted_out_player_ids
    acc_conn = get_accounts_connection()
    try:
        opted_out_player_ids = get_opted_out_player_ids(acc_conn)
    finally:
        acc_conn.close()

    leaderboard = build_leaderboard(ratings, players, player_stats, deltas=deltas)

    if not has_tier(Tier.WEBMASTER) and opted_out_player_ids:
        leaderboard.sort(key=lambda p: (p["player_id"] in opted_out_player_ids, -p["total"]["conservative"]))

    return render_template(
        "stats.html",
        leaderboard=leaderboard,
        synergies=synergies,
        streaks=streaks,
        opted_out_player_ids=opted_out_player_ids,
    )


@stats_bp.route("/my-stats")
@require_tier(Tier.USER)
def my_stats():
    from web.services.security import get_current_user
    from flask import redirect, url_for, flash
    user = get_current_user()
    if user and user.get("player_id"):
        return redirect(url_for("stats.player_profile", player_id=user["player_id"]))
    flash("Bitte verknüpfe dein Benutzerkonto in den Einstellungen mit einem Spieler, um deine persönlichen Statistiken direkt aufzurufen.", "info")
    return redirect(url_for("auth.settings"))


@stats_bp.route("/player/<int:player_id>")
@require_tier(Tier.USER)
def player_profile(player_id):
    connection = get_connection()
    players = get_players(connection)
    ratings = get_ratings(connection)
    player_stats = get_player_stats(connection)
    rating_history = get_player_rating_history(connection, player_id)
    rating_extremes = {}
    for rating_type in ["total", "box", "hf"]:
        history = rating_history[rating_type]
        rating_extremes[rating_type] = {
            "peak": max(history, key=lambda entry: entry["rating"]),
            "low": min(history, key=lambda entry: entry["rating"])
        } if history else {"peak": None, "low": None}
    selected_rating_type = request.args.get("rating_type", "total").lower()
    selected_rating_type = selected_rating_type if selected_rating_type in ("total", "box", "hf") else "total"
    matches = build_match_history(connection, players, player_id, {"total": TOTAL, "box": BOX, "hf": HF}[selected_rating_type])
    
    # achievements moved to dedicated route
    connection.close()
    matches.reverse()

    from scripts.accounts.database import get_accounts_connection, get_user_by_player_id, get_opted_out_player_ids
    acc_conn = get_accounts_connection()
    try:
        linked_user = get_user_by_player_id(acc_conn, player_id)
        linked_user = dict(linked_user) if linked_user else None
        opted_out_player_ids = get_opted_out_player_ids(acc_conn)
    finally:
        acc_conn.close()

    players_map = {pid: p["aliases"][0] for pid, p in players.items()}

    return render_template(
        "player.html",
        player=players[player_id],
        ratings=ratings[player_id],
        stats=player_stats[player_id],
        rating_history=rating_history,
        rating_extremes=rating_extremes,
        matches=matches,
        selected_rating_type=selected_rating_type,
        player_id=player_id,
        linked_user=linked_user,
        players_map=players_map,
        opted_out_player_ids=opted_out_player_ids,
    )


@stats_bp.route("/matches")
def match_history():
    connection = get_connection()
    players = get_players(connection)
    matches = build_match_history(connection, players)
    matches.reverse()
    connection.close()

    from scripts.accounts.database import get_accounts_connection, get_opted_out_player_ids
    acc_conn = get_accounts_connection()
    try:
        opted_out_player_ids = get_opted_out_player_ids(acc_conn)
    finally:
        acc_conn.close()

    return render_template("matches.html", matches=matches, opted_out_player_ids=opted_out_player_ids)


@stats_bp.route("/model-analysis")
@require_tier(Tier.GLICKO_USER)
def model_analysis():
    mode = request.args.get("mode", "total")
    mode = mode if mode in ("total", "pitch") else "total"
    connection = get_connection()
    analysis = analyze_model(connection, mode)
    connection.close()
    return render_template("model_analysis.html", analysis=analysis, mode=mode)


@stats_bp.route("/glickofaq")
def glicko_explainer():
    return render_template("glickofaq.html")


@stats_bp.route("/about")
def about():
    """About RB 48 Köln e.V. history, formats, and community philosophy."""
    return render_template("about.html")


@stats_bp.route("/api/players-list")
@require_tier(Tier.USER)
def api_players_list():
    """Return all active players for global search and autocomplete."""
    connection = get_connection()
    players = get_players(connection)
    ratings = get_ratings(connection)
    connection.close()

    from scripts.accounts.database import get_accounts_connection, get_opted_out_player_ids
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
    synergies = get_community_synergies(connection, min_games=min_games)
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
    if user.get("role") == "webmaster":
        connection = get_connection()
        players = get_players(connection)
        connection.close()
        first_pid = next(iter(players.keys()), 1)
        return redirect(url_for("stats.player_achievements", player_id=first_pid))
    from flask import flash
    flash("Bitte verknüpfe dein Profil in den Einstellungen mit einem Spieler, um deine Auszeichnungen zu sehen.", "info")
    return redirect(url_for("auth.settings"))


@stats_bp.route("/achievements/<int:player_id>")
@require_tier(Tier.USER)
def player_achievements(player_id: int):
    user = get_current_user()
    if not user:
        return redirect(url_for("auth.login", next=request.path))
    
    is_webmaster = (user.get("role") == "webmaster")
    if not is_webmaster and user.get("player_id") != player_id:
        from flask import flash
        if user.get("player_id"):
            flash("Du kannst nur deine eigenen Auszeichnungen einsehen.", "info")
            return redirect(url_for("stats.player_achievements", player_id=user["player_id"]))
        else:
            flash("Bitte verknüpfe dein Profil in den Einstellungen mit einem Spieler, um deine Auszeichnungen zu sehen.", "info")
            return redirect(url_for("auth.settings"))

    connection = get_connection()
    players = get_players(connection)
    if player_id not in players:
        connection.close()
        return redirect(url_for("stats.achievements_overview"))
    user_has_glicko = has_tier(Tier.GLICKO_USER)

    from scripts.accounts.database import (
        get_accounts_connection,
        get_user_seen_achievements,
        mark_user_achievements_seen,
    )

    is_own_profile = (user.get("player_id") == player_id)
    acc_conn = get_accounts_connection()
    try:
        seen_keys = get_user_seen_achievements(acc_conn, user["id"]) if is_own_profile else set()
        achievements = get_player_achievements(
            connection,
            player_id,
            user_has_glicko_tier=user_has_glicko,
            accounts_connection=acc_conn,
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
