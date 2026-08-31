from datetime import date, datetime, timezone
import os
import re

from flask import Flask, render_template, request, redirect, url_for, jsonify, session

from scripts.database.database import get_connection
from scripts.database.news_database import (
    get_news_connection,
    get_published_news,
    add_news_item,
    publish_news_item,
)
from scripts.database.db_ratings import get_ratings, get_player_rating_history
from scripts.database.db_players import get_players, get_alias_lookup, get_ignored_aliases, add_alias, add_ignored_alias
from scripts.database.db_matches import get_player_stats
from scripts.frontend.view_models import build_leaderboard, build_match_history
from scripts.analysis.model_analysis import analyze_model
from scripts.matches.match_entry import add_match, next_match_id, create_new_player, CALIBRATION_LEVELS, process_new_matches
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
    return {
        "kind": parsed.get("kind", "unknown"),
        "match_date": parsed.get("match_date"),
        "players": parsed_names,
        "team_a": parsed.get("team_a", []),
        "team_b": parsed.get("team_b", []),
        "team_a_ids": team_a_ids,
        "team_b_ids": team_b_ids,
        "goals_a": parsed.get("goals_a"),
        "goals_b": parsed.get("goals_b"),
        "verified_ids": verified_ids,
        "conflicts": conflicts,
        "unmatched": unmatched,
    }


def _rebuild_parser_result(form, players):
    def integer_or_none(value):
        try:
            return int(value) if value not in (None, "") else None
        except (TypeError, ValueError):
            return None

    return _build_parse_result({
        "kind": form.get("parsed_kind", "unknown"),
        "match_date": form.get("parsed_match_date") or None,
        "players": form.getlist("parsed_player"),
        "team_a": [x for x in form.get("parsed_team_a", "").split("||") if x],
        "team_b": [x for x in form.get("parsed_team_b", "").split("||") if x],
        "goals_a": integer_or_none(form.get("parsed_goals_a")),
        "goals_b": integer_or_none(form.get("parsed_goals_b")),
    }, players)


def _remove_resolved_name(parse_result, name):
    key = normalize_player_name(name).casefold()
    parse_result["conflicts"] = [c for c in parse_result["conflicts"] if c.get("name", "").casefold() != key]
    parse_result["unmatched"] = [u for u in parse_result["unmatched"] if u.get("name", "").casefold() != key]


def _get_prefilled_team_ids(form, team_name, players):
    values = form.getlist(team_name)
    if len(values) == 1 and "," in values[0]:
        values = values[0].split(",")
    return [int(pid) for pid in values if pid.isdigit() and int(pid) in players]


def _get_dashboard_news(limit=2, offset=0):
    connection = get_news_connection()
    try:
        rows = get_published_news(connection, limit=limit, offset=offset)
        all_next = get_published_news(connection, limit=1, offset=offset + limit)
        news = []
        for row in rows:
            try:
                html = render_markdown(read_news_file(row["filename"]))
            except (NewsFileError, MarkdownError):
                html = "<p>Unable to display this News entry.</p>"
            published_at = row["published_at"] or row["created_at"]
            try:
                entry_date = datetime.fromisoformat(published_at.replace("Z", "+00:00")).strftime("%Y-%m-%d")
            except (ValueError, AttributeError):
                entry_date = str(published_at)[:10]
            news.append({"id": row["id"], "filename": row["filename"], "date": entry_date, "html": html})
        return news, bool(all_next)
    finally:
        connection.close()


@app.route("/")
def home():
    return redirect(url_for("dashboard"))


@app.route("/dashboard")
def dashboard():
    news, has_more_news = _get_dashboard_news()
    return render_template("dashboard.html", news=news, has_more_news=has_more_news)


@app.route("/dashboard/news")
def get_more_news():
    try:
        offset = max(0, int(request.args.get("offset", 0)))
        limit = min(10, max(1, int(request.args.get("limit", 2))))
    except ValueError:
        return jsonify({"error": "Invalid News pagination."}), 400
    news, has_more = _get_dashboard_news(limit=limit, offset=offset)
    return jsonify({"news": news, "has_more": has_more})


@app.route("/news/format", methods=["POST"])
def format_news():
    payload = request.get_json(silent=True) or {}
    text = payload.get("text", "")
    if not isinstance(text, str) or not text.strip():
        return jsonify({"error": "Please enter some text first."}), 400
    try:
        return jsonify({"markdown": format_news_markdown(text)})
    except NewsAIError as exc:
        return jsonify({"error": str(exc)}), 502


@app.route("/news/create", methods=["POST"])
def create_news():
    markdown = request.form.get("markdown", "").strip()
    if not markdown:
        return redirect(url_for("dashboard"))
    now = datetime.now(timezone.utc)
    filename = "news_" + now.strftime("%Y%m%d_%H%M%S_%f") + ".md"
    try:
        create_news_file(filename, markdown)
        connection = get_news_connection()
        try:
            news_id = add_news_item(connection, filename, now.isoformat(timespec="seconds"), session.get("user_id"))
            publish_news_item(connection, news_id, now.isoformat(timespec="seconds"))
        finally:
            connection.close()
    except (NewsFileError, OSError):
        return redirect(url_for("dashboard"))
    return redirect(url_for("dashboard"))


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        user = authenticate(request.form.get("login", ""), request.form.get("password", ""))
        if user:
            session.clear()
            session["user_id"] = user["id"]
            return redirect(url_for("home"))
        error = "Invalid username/email or password."
    return render_template("login.html", error=error)


@app.route("/register", methods=["GET", "POST"])
def register():
    error = None
    if request.method == "POST":
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        if password != confirm_password:
            error = "Passwords do not match."
        else:
            user_id, error = register_user(
                request.form.get("username", ""),
                request.form.get("email", ""),
                password,
            )
            if user_id:
                session.clear()
                session["user_id"] = user_id
                return redirect(url_for("home"))
    return render_template("register.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))


@app.route("/stats")
def stats():
    connection = get_connection()
    ratings = get_ratings(connection)
    players = get_players(connection)
    player_stats = get_player_stats(connection)
    connection.close()
    return render_template("stats.html", leaderboard=build_leaderboard(ratings, players, player_stats))


@app.route("/player/<int:player_id>")
def player_profile(player_id):
    connection = get_connection()
    players = get_players(connection)
    ratings = get_ratings(connection)
    stats = get_player_stats(connection)
    rating_history = get_player_rating_history(connection, player_id)
    rating_extremes = {}
    for rating_type in ["total", "box", "hf"]:
        history = rating_history[rating_type]
        rating_extremes[rating_type] = {
            "peak": max(history, key=lambda entry: entry["rating"]),
            "low": min(history, key=lambda entry: entry["rating"]),
        } if history else {"peak": None, "low": None}
    selected_rating_type = request.args.get("rating_type", "total").lower()
    selected_rating_type = selected_rating_type if selected_rating_type in ("total", "box", "hf") else "total"
    matches = build_match_history(connection, players, player_id, {"total": TOTAL, "box": BOX, "hf": HF}[selected_rating_type])
    connection.close()
    matches.reverse()
    return render_template("player.html", player=players[player_id], ratings=ratings[player_id], stats=stats[player_id], rating_history=rating_history, rating_extremes=rating_extremes, matches=matches, selected_rating_type=selected_rating_type)


@app.route("/matches")
def match_history():
    connection = get_connection()
    players = get_players(connection)
    matches = build_match_history(connection, players)
    matches.reverse()
    connection.close()
    return render_template("matches.html", matches=matches)


@app.route("/model-analysis")
def model_analysis():
    mode = request.args.get("mode", "total")
    mode = mode if mode in ("total", "pitch") else "total"
    connection = get_connection()
    analysis = analyze_model(connection, mode)
    connection.close()
    return render_template("model_analysis.html", analysis=analysis, mode=mode)


@app.route("/match-center", methods=["GET", "POST"])
def match_center():
    connection = get_connection()
    players = get_players(connection)
    ratings = get_ratings(connection)
    mode = request.form.get("mode", request.args.get("mode", "total"))
    mode = mode if mode in ("total", "pitch") else "total"
    pitch = request.form.get("pitch", request.args.get("pitch", "box"))
    pitch = pitch if pitch in ("box", "hf") else "box"
    rating_type = BOX if mode == "pitch" and pitch == "box" else HF if mode == "pitch" else TOTAL
    selected_ids = request.form.getlist("players") or request.args.getlist("players")
    selected_ids = [int(pid) for pid in selected_ids if pid.isdigit() and int(pid) in players]
    result = None
    seed = None
    parse_result = _EmptyParseResult(kind="", match_date=None, players=[], team_a=[], team_b=[], team_a_ids=[], team_b_ids=[], goals_a=None, goals_b=None, verified_ids=[], conflicts=[], unmatched=[])
    parse_error = None
    parser_success = None
    success = error = calibration_message = None
    action = request.form.get("action") if request.method == "POST" else None

    if request.method == "POST" and action in ("parse_image", "parse_source"):
        try:
            if action == "parse_source" and request.form.get("match_text", "").strip():
                parsed = parse_match_text(request.form["match_text"])
            else:
                upload = request.files.get("match_image")
                if not upload or not upload.filename:
                    raise MatchParserError("Please paste a WhatsApp message or choose/paste an image first.")
                parsed = parse_match_image(upload.read(), upload.mimetype)
            parse_result = _build_parse_result(parsed, players)
            selected_ids = parse_result["verified_ids"]
            if parse_result["kind"] == "match":
                parser_success = "This looks like an already played match. Review the imported facts, or check the same players for fairer possible teams."
        except MatchParserError as exc:
            parse_error = str(exc)

    elif request.method == "POST" and action == "resolve_conflicts":
        parse_result = _rebuild_parser_result(request.form, players)
        resolve_id = request.form.get("resolve_player_id")
        resolve_name = request.form.get("resolve_name", "")
        if resolve_id and resolve_id.isdigit() and int(resolve_id) in players:
            parse_result["verified_ids"] = list(dict.fromkeys(parse_result["verified_ids"] + [int(resolve_id)]))
            _remove_resolved_name(parse_result, resolve_name)
            selected_ids = parse_result["verified_ids"]

    elif request.method == "POST" and action == "generate_teams":
        try:
            rating_type = request.form.get("rating_type", TOTAL)
            if rating_type not in (TOTAL, BOX, HF):
                rating_type = TOTAL
            result = generate_match(selected_ids, players, ratings, rating_type=rating_type)
            seed = result.get("seed")
        except ValueError as exc:
            error = str(exc)

    elif request.method == "POST" and action == "save_match":
        try:
            team_a = _get_prefilled_team_ids(request.form, "team_a", players)
            team_b = _get_prefilled_team_ids(request.form, "team_b", players)
            match_date = request.form.get("match_date", "")
            pitch = request.form.get("pitch", "box")
            goals_a = int(request.form.get("goals_a", "0"))
            goals_b = int(request.form.get("goals_b", "0"))
            external_a = int(request.form.get("external_a", "0"))
            external_b = int(request.form.get("external_b", "0"))
            if not team_a or not team_b:
                raise ValueError("Both teams need at least one registered player.")
            if pitch not in ("box", "hf"):
                raise ValueError("Invalid pitch type.")
            if external_a < 0 or external_b < 0:
                raise ValueError("Invalid external player count.")
            if not match_date:
                raise ValueError("Match date is required.")
            result = add_match(connection, match_date, pitch, team_a, team_b, goals_a, goals_b, external_a, external_b)
            process_new_matches(connection)
            connection.close()
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return jsonify({"success": True, "message": "Match added successfully"})
            return redirect(url_for("match_center"))
        except Exception as exc:
            connection.rollback()
            error = str(exc)
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                connection.close()
                return jsonify({"success": False, "error": error}), 400

    connection.close()
    return render_template("match_center.html", calibration_levels=CALIBRATION_LEVELS, players=players, ratings=ratings, selected_ids=selected_ids, result=result, seed=seed, parse_result=parse_result, parse_error=parse_error, parser_success=parser_success, success=success, error=error, calibration_message=calibration_message, selected_rating_type=rating_type)


@app.route("/match-center/team-details", methods=["POST"])
def match_center_team_details():
    try:
        team_a = [int(pid) for pid in request.form.getlist("team_a")]
        team_b = [int(pid) for pid in request.form.getlist("team_b")]
    except ValueError:
        return jsonify({"error": "Invalid team player IDs."}), 400
    connection = get_connection()
    players = get_players(connection)
    ratings = get_ratings(connection)
    if not team_a or not team_b or any(pid not in players for pid in team_a + team_b):
        connection.close()
        return jsonify({"error": "Invalid team composition."}), 400
    rating_type = TOTAL
    rating_a = _team_rating(team_a, ratings, rating_type)
    rating_b = _team_rating(team_b, ratings, rating_type)
    details = {
        "rating_a": round(rating_a.rating, 1),
        "rd_a": round(rating_a.rd, 1),
        "rating_b": round(rating_b.rating, 1),
        "rd_b": round(rating_b.rd, 1),
        "rating_difference": round(abs(rating_a.rating - rating_b.rating), 1),
        "position_penalty": _position_penalty(team_a, team_b, players),
        "positions_a": _considered_positions(team_a, players),
        "positions_b": _considered_positions(team_b, players),
    }
    connection.close()
    return jsonify(details)


@app.route("/matchmaker", methods=["GET", "POST"])
def legacy_matchmaker():
    if request.method == "GET":
        return redirect(url_for("match_center", **request.args.to_dict(flat=False)))
    return redirect(url_for("match_center"), code=307)


@app.route("/glickofaq")
def glicko_explainer():
    return render_template("glickofaq.html")


if __name__ == "__main__":
    app.run(debug=True)
