from flask import Blueprint, render_template, request
from scripts.database.database import get_connection
from scripts.database.db_ratings import get_ratings, get_player_rating_history
from scripts.database.db_players import get_players
from scripts.database.db_matches import get_player_stats
from scripts.frontend.view_models import build_leaderboard, build_match_history
from scripts.analysis.model_analysis import analyze_model
from scripts.glicko.glicko2 import TOTAL, BOX, HF
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
def stats():
    connection = get_connection()
    ratings = get_ratings(connection)
    players = get_players(connection)
    player_stats = get_player_stats(connection)
    connection.close()
    return render_template("stats.html", leaderboard=build_leaderboard(ratings, players, player_stats))


@stats_bp.route("/player/<int:player_id>")
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
    connection.close()
    matches.reverse()
    return render_template(
        "player.html",
        player=players[player_id],
        ratings=ratings[player_id],
        stats=player_stats[player_id],
        rating_history=rating_history,
        rating_extremes=rating_extremes,
        matches=matches,
        selected_rating_type=selected_rating_type,
        player_id=player_id
    )


@stats_bp.route("/matches")
def match_history():
    connection = get_connection()
    players = get_players(connection)
    matches = build_match_history(connection, players)
    matches.reverse()
    connection.close()
    return render_template("matches.html", matches=matches)


@stats_bp.route("/model-analysis")
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
