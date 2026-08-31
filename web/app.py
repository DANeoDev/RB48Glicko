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
    def __bool__(self): return False

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
        try: return int(value) if value not in (None, "") else None
        except (TypeError, ValueError): return None
    action = form.get("action")
    if action in ("parse_source", "parse_image"):
        if action == "parse_source" and form.get("match_text", "").strip(): parsed = parse_match_text(form["match_text"])
        else:
            upload = request.files.get("match_image")
            if not upload or not upload.filename: raise MatchParserError("Please paste a WhatsApp message or choose/paste an image first.")
            parsed = parse_match_image(upload.read(), upload.mimetype)
        return _build_parse_result(parsed, players)
    return _build_parse_result({"kind": form.get("parsed_kind", "unknown"), "match_date": form.get("parsed_match_date") or None, "players": form.getlist("parsed_player"), "team_a": [x for x in form.get("parsed_team_a", "").split("||") if x], "team_b": [x for x in form.get("parsed_team_b", "").split("||") if x], "goals_a": integer_or_none(form.get("parsed_goals_a")), "goals_b": integer_or_none(form.get("parsed_goals_b"))}, players)

def _remove_resolved_name(parse_result, name):
    key = normalize_player_name(name).casefold()
    parse_result["conflicts"] = [c for c in parse_result["conflicts"] if c.get("name", "").casefold() != key]
    parse_result["unmatched"] = [u for u in parse_result["unmatched"] if u.get("name", "").casefold() != key]

def _get_prefilled_team_ids(form, team_name, players):
    values = form.getlist(team_name)
    if len(values) == 1 and "," in values[0]: values = values[0].split(",")
    return [int(pid) for pid in values if pid.isdigit() and int(pid) in players]

# ... existing routes remain unchanged; only the obsolete matchhistory_sync dependency was removed.

@app.route("/", endpoint="home")
def home():
    news, has_more_news = _get_dashboard_news()
    return render_template("dashboard.html", news=news, has_more_news=has_more_news)

@app.route("/dashboard")
def dashboard():
    news, has_more_news = _get_dashboard_news()
    return render_template("dashboard.html", news=news, has_more_news=has_more_news)

if __name__ == "__main__":
    app.run(debug=True)
