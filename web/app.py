from datetime import date, datetime, timezone
import os
import re

from flask import Flask, render_template, request, redirect, url_for, jsonify, session

from scripts.database.database import get_connection
from scripts.database.news_database import get_news_connection, get_published_news, add_news_item, publish_news_item
from scripts.database.db_ratings import get_ratings, get_player_rating_history
from scripts.database.db_players import get_players, get_alias_lookup, get_ignored_aliases, add_alias, add_ignored_alias
from scripts.database.db_matches import get_player_stats
from scripts.frontend.view_models import build_leaderboard, build_match_history
from scripts.analysis.model_analysis import analyze_model
from scripts.matches.match_entry import add_match, next_match_id, import_uploaded_matches, create_new_player, CALIBRATION_LEVELS, process_new_matches
from scripts.matchmaking.matchmaker import generate_match, _team_rating, _position_penalty, _considered_positions
from scripts.matchmaking.match_parser import parse_match_image, parse_match_text, resolve_player_names, normalize_player_name, MatchParserError
from scripts.glicko.glicko2 import TOTAL, BOX, HF
from scripts.accounts.auth import authenticate, get_user, register_user
from web.services.ai_service import NewsAIError, format_news_markdown
from web.services.markdown_service import render_markdown, MarkdownError
from web.services.news_service import NewsFileError, create_news_file, read_news_file

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024
app.secret_key = os.environ.get("RB48_SECRET_KEY") or os.urandom(32)


@app.context_processor
def inject_current_user():
    """Make the authenticated account available to every template."""
    user_id = session.get("user_id")
    return {"current_user": get_user(user_id) if user_id else None}


class _EmptyParseResult(dict):
    """Falsey parse-result placeholder so templates can safely access its fields."""
    def __bool__(self):
        return False


def _alias_candidates(players):
    lookup = {}
    for player_id, player in players.items():
        for alias in player.get("aliases", []):
            lookup.setdefault(normalize_player_name(alias).casefold(), []).append(player_id)
    return lookup


def _build_parse_result(parsed, players):
    parsed_names = parsed.get("players", [])
    verified_ids, conflicts, unmatched = resolve_player_names(parsed_names, players)
    lookup = _alias_candidates(players)
    team_a_ids = [ids[0] for raw in parsed.get("team_a", []) if len(ids := lookup.get(normalize_player_name(raw).casefold(), [])) == 1]
    team_b_ids = [ids[0] for raw in parsed.get("team_b", []) if len(ids := lookup.get(normalize_player_name(raw).casefold(), [])) == 1]
    return {"kind": parsed.get("kind", "unknown"), "match_date": parsed.get("match_date"), "players": parsed_names, "team_a": parsed.get("team_a", []), "team_b": parsed.get("team_b", []), "team_a_ids": team_a_ids, "team_b_ids": team_b_ids, "goals_a": parsed.get("goals_a"), "goals_b": parsed.get("goals_b"), "verified_ids": verified_ids, "conflicts": conflicts, "unmatched": unmatched}


def _rebuild_parser_result(form, players):
    def integer_or_none(value):
        try:
            return int(value) if value not in (None, "") else None
        except (TypeError, ValueError):
            return None
    return _build_parse_result({"kind": form.get("parsed_kind", "unknown"), "match_date": form.get("parsed_match_date") or None, "players": form.getlist("parsed_player"), "team_a": [x for x in form.get("parsed_team_a", "").split("||") if x], "team_b": [x for x in form.get("parsed_team_b", "").split("||") if x], "goals_a": integer_or_none(form.get("parsed_goals_a")), "goals_b": integer_or_none(form.get("parsed_goals_b"))}, players)


def _remove_resolved_name(parse_result, name):
    key = normalize_player_name(name).casefold()
    parse_result["conflicts"] = [c for c in parse_result["conflicts"] if c.get("name", "").casefold() != key]
    parse_result["unmatched"] = [u for u in parse_result["unmatched"] if u.get("name", "").casefold() != key]


def _get_prefilled_team_ids(form, team_name, players):
    values = form.getlist(team_name)
    if len(values) == 1 and "," in values[0]:
        values = values[0].split(",")
    return [int(pid) for pid in values if pid.isdigit() and int(pid) in players]


def _render_news_items(news_items):
    """Read and render a sequence of News metadata rows."""
    rendered = []
    for news_item in news_items:
        try:
            markdown = read_news_file(news_item["filename"])
            published_at = news_item["published_at"] or news_item["created_at"]
            try:
                entry_date = datetime.fromisoformat(published_at).strftime("%d.%m.%Y")
            except (TypeError, ValueError):
                entry_date = str(published_at).split("T", 1)[0]
            rendered.append({"id": news_item["id"], "html": render_markdown(markdown), "date": entry_date})
        except (NewsFileError, MarkdownError):
            continue
    return rendered


def _get_dashboard_news(offset=0, limit=2):
    """Return a page of published News items, newest first."""
    connection = get_news_connection()
    try:
        published_news = get_published_news(connection, limit=limit, offset=offset)
        next_news = get_published_news(connection, limit=1, offset=offset + limit)
    finally:
        connection.close()
    return _render_news_items(published_news), bool(next_news)


def _news_filename(markdown, timestamp):
    """Create a readable, safe filename from the first Markdown heading/content."""
    heading = re.search(r"^#{1,2}\s+(.+?)\s*$", markdown, re.MULTILINE)
    source = heading.group(1) if heading else next((line.strip() for line in markdown.splitlines() if line.strip()), "news")
    source = re.sub(r"[^A-Za-z0-9]+", "-", source).strip("-").lower() or "news"
    return f"{timestamp:%Y%m%d-%H%M%S}-{source}.md"


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        if password != confirm_password:
            return render_template("register.html", error="Passwords do not match."), 400
        user_id, error = register_user(
            request.form.get("username", ""),
            request.form.get("email", ""),
            password,
        )
        if error:
            return render_template("register.html", error=error), 400
        session.clear()
        session["user_id"] = user_id
        return redirect(url_for("home"))
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = authenticate(request.form.get("login", ""), request.form.get("password", ""))
        if not user:
            return render_template("login.html", error="Invalid username/email or password."), 401
        session.clear()
        session["user_id"] = user["id"]
        return redirect(url_for("home"))
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))


@app.route("/news/format", methods=["POST"])
def format_news():
    """Format plain News text through the configured Gemini API."""
    payload = request.get_json(silent=True) or {}
    text = payload.get("text", "")
    try:
        markdown = format_news_markdown(text)
    except NewsAIError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"markdown": markdown})


@app.route("/news/items")
def get_more_news():
    """Return the next page of published News items."""
    try:
        offset = max(0, int(request.args.get("offset", 0)))
        limit = min(10, max(1, int(request.args.get("limit", 2))))
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid News pagination parameters."}), 400

    news, has_more = _get_dashboard_news(offset=offset, limit=limit)
    return jsonify({"news": news, "has_more": has_more})


@app.route("/news/create", methods=["POST"])
def create_news():
    """Create and immediately publish a News Markdown file."""
    markdown = request.form.get("markdown", "").strip()
    if not markdown:
        return redirect(url_for("home"))

    now = datetime.now(timezone.utc)
    filename = _news_filename(markdown, now)
    try:
        create_news_file(filename, markdown)
        connection = get_news_connection()
        try:
            news_id = add_news_item(connection, filename, now.isoformat(timespec="seconds"), None)
            publish_news_item(connection, news_id, now.isoformat(timespec="seconds"))
        finally:
            connection.close()
    except (NewsFileError, OSError):
        return redirect(url_for("home"))
    return redirect(url_for("home"))


@app.route("/")
def home():
    news, has_more_news = _get_dashboard_news()
    return render_template("dashboard.html", news=news, has_more_news=has_more_news)


@app.route("/dashboard")
def dashboard():
    news, has_more_news = _get_dashboard_news()
    return render_template("dashboard.html", news=news, has_more_news=has_more_news)


@app.route("/stats")
def stats():
    connection = get_connection()
    ratings = get_ratings(connection)
    players = get_players(connection)
    stats = get_player_stats(connection)
    connection.close()
    return render_template("stats.html", leaderboard=build_leaderboard(ratings, players, stats))


@app.route("/player/<int:player_id>")
def player_profile(player_id):
    connection = get_connection(); players = get_players(connection); ratings = get_ratings(connection); stats = get_player_stats(connection); rating_history = get_player_rating_history(connection, player_id); rating_extremes = {}
    for rating_type in ["total", "box", "hf"]:
        history = rating_history[rating_type]
        rating_extremes[rating_type] = {"peak": max(history, key=lambda entry: entry["rating"]), "low": min(history, key=lambda entry: entry["rating"])} if history else {"peak": None, "low": None}
    selected_rating_type = request.args.get("rating_type", "total").lower()
    selected_rating_type = selected_rating_type if selected_rating_type in ("total", "box", "hf") else "total"
    matches = build_match_history(connection, players, player_id, {"total": TOTAL, "box": BOX, "hf": HF}[selected_rating_type]); connection.close(); matches.reverse()
    return render_template("player.html", player=players[player_id], ratings=ratings[player_id], stats=stats[player_id], rating_history=rating_history, rating_extremes=rating_extremes, matches=matches, selected_rating_type=selected_rating_type)


@app.route("/matches")
def match_history():
    connection = get_connection(); players = get_players(connection); matches = build_match_history(connection, players); matches.reverse(); connection.close()
    return render_template("matches.html", matches=matches)


@app.route("/model-analysis")
def model_analysis():
    connection = get_connection()
    analysis = analyze_model(connection)
    connection.close()
    return render_template("model_analysis.html", analysis=analysis)


@app.route("/glickofaq")
def glicko_explainer():
    return render_template("glickofaq.html")


@app.route("/matchmaker", methods=["GET", "POST"])
def matchmaker():
    if request.method == "POST":
        connection = get_connection(); players = get_players(connection); connection.close()
        selected = request.form.getlist("players")
        result = generate_match([int(player_id) for player_id in selected], players)
        return render_template("matchmaker.html", players=players, result=result)
    connection = get_connection(); players = get_players(connection); connection.close()
    return render_template("matchmaker.html", players=players)


@app.route("/match-center", methods=["GET", "POST"])
def match_center():
    connection = get_connection(); players = get_players(connection)
    if request.method == "GET":
        connection.close()
        return render_template("match_center.html", players=players, parse_result=_EmptyParseResult(), calibration_levels=CALIBRATION_LEVELS)
    try:
        parse_result = _rebuild_parser_result(request.form, players)
        connection.close()
        return render_template("match_center.html", players=players, parse_result=parse_result, calibration_levels=CALIBRATION_LEVELS)
    except Exception:
        connection.close()
        raise


if __name__ == "__main__":
    app.run(debug=True)
