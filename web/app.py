from datetime import date

from flask import Flask, render_template, request

from scripts.database.database import get_connection
from scripts.database.db_ratings import get_ratings, get_player_rating_history
from scripts.database.db_players import get_players, get_alias_lookup, add_alias
from scripts.database.db_matches import get_player_stats
from scripts.frontend.view_models import build_leaderboard, build_match_history
from scripts.analysis.model_analysis import analyze_model
from scripts.matches.match_entry import add_match, next_match_id, import_uploaded_matches, create_new_player, CALIBRATION_LEVELS, process_new_matches
from scripts.matches.matchhistory_sync import sync_matchhistory_csv
from scripts.matchmaking.matchmaker import generate_match
from scripts.matchmaking.image_parser import parse_match_image, resolve_player_names, normalize_player_name, MatchImageParserError
from scripts.glicko.glicko2 import TOTAL, BOX, HF

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024


def _build_parse_result(parsed_names, match_date, players):
    verified_ids, conflicts, unmatched = resolve_player_names(parsed_names, players)
    return {"match_date": match_date, "players": parsed_names, "verified_ids": verified_ids, "conflicts": conflicts, "unmatched": unmatched}


def _rebuild_parser_result(form, players):
    parsed_names = form.getlist("parsed_player")
    match_date = form.get("parsed_match_date") or None
    return _build_parse_result(parsed_names, match_date, players)


def _remove_resolved_name(parse_result, name):
    key = normalize_player_name(name).casefold()
    parse_result["conflicts"] = [c for c in parse_result["conflicts"] if c.get("name", "").casefold() != key]
    parse_result["unmatched"] = [u for u in parse_result["unmatched"] if u.get("name", "").casefold() != key]


def _get_prefilled_team_ids(form, team_name, players):
    values = form.getlist(team_name)
    if len(values) == 1 and "," in values[0]:
        values = values[0].split(",")
    return [int(pid) for pid in values if pid.isdigit() and int(pid) in players]


@app.route("/")
def home():
    connection = get_connection(); ratings = get_ratings(connection); players = get_players(connection); stats = get_player_stats(connection); connection.close()
    return render_template("index.html", leaderboard=build_leaderboard(ratings, players, stats))


@app.route("/player/<int:player_id>")
def player_profile(player_id):
    connection = get_connection(); players = get_players(connection); ratings = get_ratings(connection); stats = get_player_stats(connection); rating_history = get_player_rating_history(connection, player_id)
    rating_extremes = {}
    for rating_type in ["total", "box", "hf"]:
        history = rating_history[rating_type]
        if history:
            peak = max(history, key=lambda entry: entry["rating"]); low = min(history, key=lambda entry: entry["rating"])
            rating_extremes[rating_type] = {"peak": peak, "low": low}
        else: rating_extremes[rating_type] = {"peak": None, "low": None}
    matches = build_match_history(connection, players, player_id); connection.close(); matches.reverse()
    return render_template("player.html", player=players[player_id], ratings=ratings[player_id], stats=stats[player_id], rating_history=rating_history, rating_extremes=rating_extremes, matches=matches)


@app.route("/matches")
def match_history():
    connection = get_connection(); players = get_players(connection); matches = build_match_history(connection, players); matches.reverse(); connection.close()
    return render_template("matches.html", matches=matches)


@app.route("/model-analysis")
def model_analysis():
    mode = request.args.get("mode", "total"); mode = mode if mode in ("total", "pitch") else "total"
    connection = get_connection(); analysis = analyze_model(connection, mode); connection.close()
    return render_template("model_analysis.html", analysis=analysis, mode=mode)


@app.route("/matchmaker", methods=["GET", "POST"])
def matchmaker():
    connection = get_connection(); players = get_players(connection); ratings = get_ratings(connection)
    mode = request.form.get("mode", request.args.get("mode", "total")); mode = mode if mode in ("total", "pitch") else "total"
    if mode == "pitch":
        pitch = request.form.get("pitch", request.args.get("pitch", "box")); pitch = pitch if pitch in ("box", "hf") else "box"; rating_type = BOX if pitch == "box" else HF
    else: pitch = None; rating_type = TOTAL

    selected_ids = request.form.getlist("players") or request.args.getlist("players")
    selected_ids = [int(pid) for pid in selected_ids if pid.isdigit() and int(pid) in players]
    result = None; seed = None; parse_result = None; parse_error = None; parser_success = None
    action = request.form.get("action") if request.method == "POST" else None

    if request.method == "POST" and action == "parse_image":
        upload = request.files.get("match_image")
        if not upload or not upload.filename: parse_error = "Please choose or paste an image first."
        else:
            try:
                parsed = parse_match_image(upload.read(), upload.mimetype)
                parse_result = _build_parse_result(parsed["players"], parsed["match_date"], players)
                selected_ids = parse_result["verified_ids"]
            except MatchImageParserError as exc: parse_error = str(exc)

    elif request.method == "POST" and action == "resolve_conflicts":
        parse_result = _rebuild_parser_result(request.form, players)
        selected_ids = list(parse_result["verified_ids"])
        alias_lookup = {}
        for player_id, player in players.items():
            for alias in player.get("aliases", []): alias_lookup.setdefault(alias.strip().casefold(), []).append(player_id)
        remaining_conflicts = []
        for index, conflict in enumerate(parse_result["conflicts"]):
            detail = normalize_player_name(request.form.get(f"conflict_detail_{index}", ""))
            if not detail:
                remaining_conflicts.append(conflict); continue
            candidates = alias_lookup.get(detail.casefold(), [])
            if len(candidates) == 1:
                if candidates[0] not in selected_ids: selected_ids.append(candidates[0])
            elif len(candidates) > 1:
                remaining_conflicts.append({"name": conflict["name"], "candidate_ids": candidates, "detail": detail})
            else:
                parse_result["unmatched"].append({"name": detail, "verified": False})
        parse_result["conflicts"] = remaining_conflicts
        parser_success = "Name conflicts resolved. All uniquely identified identities are now trusted." if not remaining_conflicts else None

    elif request.method == "POST" and action == "add_parser_alias":
        parse_result = _rebuild_parser_result(request.form, players); alias = normalize_player_name(request.form.get("new_alias", ""))
        try:
            player_id = int(request.form.get("target_player_id", ""))
            if player_id not in players: raise ValueError("Selected player does not exist.")
            if not alias: raise ValueError("Alias cannot be empty.")
            lookup = get_alias_lookup(connection)
            if alias in lookup: raise ValueError(f"The alias '{alias}' already exists.")
            add_alias(connection, alias, player_id); connection.commit(); players = get_players(connection)
            selected_ids = list(dict.fromkeys(selected_ids + [player_id])); parse_result = _rebuild_parser_result(request.form, players); _remove_resolved_name(parse_result, alias)
            parser_success = f"Added '{alias}' as an alias and selected the player."
        except (ValueError, TypeError) as exc: parse_error = str(exc)

    elif request.method == "POST" and action == "create_parser_player":
        alias = normalize_player_name(request.form.get("new_alias", "")); positions = request.form.getlist("new_positions"); calibration = request.form.get("calibration", "average")
        try:
            created_id, _ = create_new_player(connection, alias, positions, calibration)
            players = get_players(connection); selected_ids = list(dict.fromkeys(selected_ids + [created_id]))
            parse_result = _rebuild_parser_result(request.form, players); _remove_resolved_name(parse_result, alias)
            parser_success = f"Created {alias} and selected them."
        except ValueError as exc: parse_error = str(exc); parse_result = _rebuild_parser_result(request.form, players)

    elif request.method == "POST" and action in ("generate", "reroll"):
        try: seed = int(request.form.get("seed")) if request.form.get("seed") is not None else None
        except ValueError: seed = None
        if len(selected_ids) >= 2: result = generate_match(selected_ids, players, ratings, rating_type, seed=seed)

    matchmaker_date = request.form.get("parsed_match_date") or date.today().isoformat()
    connection.close()
    return render_template("matchmaker.html", players=players, ratings=ratings, selected_ids=selected_ids, result=result, mode=mode, pitch=pitch, seed=seed, parse_result=parse_result, parse_error=parse_error, parser_success=parser_success, calibration_levels=CALIBRATION_LEVELS, matchmaker_date=matchmaker_date)


@app.route("/match-entry", methods=["GET", "POST"])
def match_entry():
    connection = get_connection(); players = get_players(connection)
    match_date = request.form.get("date", request.args.get("date", date.today().isoformat())); pitch = request.form.get("pitch", request.args.get("pitch", "box")); pitch = pitch if pitch in ("box", "hf") else "box"
    if request.method == "POST":
        team_a = _get_prefilled_team_ids(request.form, "team_a", players)
        team_b = _get_prefilled_team_ids(request.form, "team_b", players)
    else:
        team_a = _get_prefilled_team_ids(request.args, "team_a", players)
        team_b = _get_prefilled_team_ids(request.args, "team_b", players)
    goals_a = request.form.get("goals_a", "0"); goals_b = request.form.get("goals_b", "0"); success = error = calibration_message = None
    if request.method == "POST" and request.form.get("action") == "create_player":
        try:
            alias = request.form.get("new_alias", ""); positions = request.form.getlist("new_positions"); calibration = request.form.get("calibration", "average"); created_id, values = create_new_player(connection, alias, positions, calibration)
            if request.form.get("target_team") == "b": team_b.append(created_id); target = "B"
            else: team_a.append(created_id); target = "A"
            success = f"Created {alias.strip()} and added them to Team {target}."; calibration_message = f"Calibration rating: {values['rating']:.1f} (RD {values['rd']:.1f})."; players = get_players(connection)
        except ValueError as exc: error = str(exc)
    elif request.method == "POST" and request.form.get("action") == "upload":
        upload = request.files.get("match_file")
        if not upload or not upload.filename: error = "Please choose a CSV file."
        else:
            try:
                imported, processed = import_uploaded_matches(connection, upload.read()); sync_matchhistory_csv(connection); success = f"Imported {len(imported)} match{'es' if len(imported) != 1 else ''} and updated Glicko for {processed} new match{'es' if processed != 1 else ''}."
            except (ValueError, RuntimeError) as exc: error = str(exc)
    elif request.method == "POST" and request.form.get("action") == "save":
        try:
            if not team_a or not team_b: raise ValueError("Both teams need at least one player.")
            if len(team_a) != len(set(team_a)) or len(team_b) != len(set(team_b)): raise ValueError("A player cannot appear more than once on the same team.")
            if set(team_a) & set(team_b): raise ValueError("A player cannot be on both teams.")
            goals_a_int, goals_b_int = int(goals_a), int(goals_b)
            if goals_a_int < 0 or goals_b_int < 0: raise ValueError("Goals cannot be negative.")
            try: date.fromisoformat(match_date)
            except ValueError: raise ValueError("Invalid match date.")
            match_id = add_match(connection, match_date, pitch, team_a, team_b, goals_a_int, goals_b_int); processed = process_new_matches(connection); sync_matchhistory_csv(connection); success = f"Saved {match_id} and updated Glicko ({processed} match processed)."; goals_a, goals_b = "0", "0"
        except (ValueError, RuntimeError) as exc: error = str(exc)
    player_names = {pid: (data["aliases"][0] if data["aliases"] else f"Player {pid}") for pid, data in players.items()}; player_search_data = [{"id": pid, "name": player_names[pid]} for pid in players]; next_id = next_match_id(connection, match_date); connection.close()
    return render_template("match_entry_v3.html", players=players, player_names=player_names, player_search_data=player_search_data, team_a=team_a, team_b=team_b, match_date=match_date, pitch=pitch, goals_a=goals_a, goals_b=goals_b, next_match_id=next_id, success=success, error=error, calibration_message=calibration_message, calibration_levels=CALIBRATION_LEVELS)


@app.route("/glickofaq")
def glicko_explainer(): return render_template("glickofaq.html")

if __name__ == "__main__": app.run(debug=True)
