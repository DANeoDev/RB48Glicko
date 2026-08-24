from datetime import date

from flask import Flask, render_template, request

from scripts.database import get_connection
from scripts.db_ratings import get_ratings, get_player_rating_history
from scripts.db_players import get_players
from scripts.db_matches import get_player_stats
from scripts.view_models import build_leaderboard, build_match_history
from scripts.model_analysis import analyze_model
from scripts.match_entry import add_match, next_match_id, import_uploaded_matches, create_new_player, CALIBRATION_LEVELS
from scripts.matchhistory_sync import sync_matchhistory_csv
from scripts.matchmaker import generate_match
from scripts.glicko2 import TOTAL, BOX, HF


app = Flask(__name__)


@app.route("/")
def home():
    connection = get_connection()
    ratings = get_ratings(connection)
    players = get_players(connection)
    stats = get_player_stats(connection)
    connection.close()
    leaderboard = build_leaderboard(ratings, players, stats)
    return render_template("index.html", leaderboard=leaderboard)


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
        if history:
            peak = max(history, key=lambda entry: entry["rating"])
            low = min(history, key=lambda entry: entry["rating"])
            rating_extremes[rating_type] = {"peak": peak, "low": low}
        else:
            rating_extremes[rating_type] = {"peak": None, "low": None}
    matches = build_match_history(connection, players, player_id)
    connection.close()
    matches.reverse()
    return render_template(
        "player.html",
        player=players[player_id],
        ratings=ratings[player_id],
        stats=stats[player_id],
        rating_history=rating_history,
        rating_extremes=rating_extremes,
        matches=matches
    )


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
    if mode not in ("total", "pitch"):
        mode = "total"
    connection = get_connection()
    analysis = analyze_model(connection, mode)
    connection.close()
    return render_template("model_analysis.html", analysis=analysis, mode=mode)


@app.route("/matchmaker", methods=["GET", "POST"])
def matchmaker():
    connection = get_connection()
    players = get_players(connection)
    ratings = get_ratings(connection)

    mode = request.form.get("mode", request.args.get("mode", "total"))
    if mode not in ("total", "pitch"):
        mode = "total"

    rating_type = TOTAL
    if mode == "pitch":
        pitch = request.form.get("pitch", request.args.get("pitch", "box"))
        if pitch not in ("box", "hf"):
            pitch = "box"
        rating_type = BOX if pitch == "box" else HF
    else:
        pitch = None

    selected_ids = request.form.getlist("players")
    if not selected_ids:
        selected_ids = request.args.getlist("players")
    selected_ids = [
        int(player_id)
        for player_id in selected_ids
        if player_id.isdigit() and int(player_id) in players
    ]

    result = None
    seed = None
    if request.method == "POST" and request.form.get("action") in ("generate", "reroll"):
        seed_value = request.form.get("seed")
        try:
            seed = int(seed_value) if seed_value is not None else None
        except ValueError:
            seed = None
        if len(selected_ids) >= 2:
            result = generate_match(selected_ids, players, ratings, rating_type, seed=seed)

    connection.close()

    return render_template(
        "matchmaker.html",
        players=players,
        ratings=ratings,
        selected_ids=selected_ids,
        result=result,
        mode=mode,
        pitch=pitch,
        seed=seed,
    )


@app.route("/match-entry", methods=["GET", "POST"])
def match_entry():
    connection = get_connection()
    players = get_players(connection)
    match_date = request.form.get("date", request.args.get("date", date.today().isoformat()))
    pitch = request.form.get("pitch", request.args.get("pitch", "box"))
    pitch = pitch if pitch in ("box", "hf") else "box"
    team_a = [int(pid) for pid in request.form.getlist("team_a") if pid.isdigit() and int(pid) in players]
    team_b = [int(pid) for pid in request.form.getlist("team_b") if pid.isdigit() and int(pid) in players]
    goals_a = request.form.get("goals_a", "0")
    goals_b = request.form.get("goals_b", "0")
    success = error = calibration_message = None

    if request.method == "POST" and request.form.get("action") == "create_player":
        try:
            alias = request.form.get("new_alias", "")
            positions = request.form.getlist("new_positions")
            calibration = request.form.get("calibration", "average")
            created_id, values = create_new_player(connection, alias, positions, calibration)
            if request.form.get("target_team") == "b":
                team_b.append(created_id)
                target = "B"
            else:
                team_a.append(created_id)
                target = "A"
            success = f"Created {alias.strip()} and added them to Team {target}."
            calibration_message = f"Calibration rating: {values['rating']:.1f} (RD {values['rd']:.1f})."
            players = get_players(connection)
        except ValueError as exc:
            error = str(exc)

    elif request.method == "POST" and request.form.get("action") == "upload":
        upload = request.files.get("match_file")
        if not upload or not upload.filename:
            error = "Please choose a CSV file."
        else:
            try:
                imported, processed = import_uploaded_matches(connection, upload.read())
                sync_matchhistory_csv(connection)
                success = f"Imported {len(imported)} match{'es' if len(imported) != 1 else ''} and updated Glicko for {processed} new match{'es' if processed != 1 else ''}."
            except (ValueError, RuntimeError) as exc:
                error = str(exc)

    elif request.method == "POST" and request.form.get("action") == "save":
        try:
            if not team_a or not team_b:
                raise ValueError("Both teams need at least one player.")
            if len(team_a) != len(set(team_a)) or len(team_b) != len(set(team_b)):
                raise ValueError("A player cannot appear more than once on the same team.")
            if set(team_a) & set(team_b):
                raise ValueError("A player cannot be on both teams.")
            goals_a_int, goals_b_int = int(goals_a), int(goals_b)
            if goals_a_int < 0 or goals_b_int < 0:
                raise ValueError("Goals cannot be negative.")
            try:
                date.fromisoformat(match_date)
            except ValueError:
                raise ValueError("Invalid match date.")
            match_id = add_match(connection, match_date, pitch, team_a, team_b, goals_a_int, goals_b_int)
            from scripts.match_entry import process_new_matches
            processed = process_new_matches(connection)
            sync_matchhistory_csv(connection)
            success = f"Saved {match_id} and updated Glicko ({processed} match processed)."
            goals_a, goals_b = "0", "0"
        except (ValueError, RuntimeError) as exc:
            error = str(exc)

    player_names = {pid: (data["aliases"][0] if data["aliases"] else f"Player {pid}") for pid, data in players.items()}
    player_search_data = [{"id": pid, "name": player_names[pid]} for pid in players]
    next_id = next_match_id(connection, match_date)
    connection.close()
    return render_template(
        "match_entry_v3.html",
        players=players,
        player_names=player_names,
        player_search_data=player_search_data,
        team_a=team_a,
        team_b=team_b,
        match_date=match_date,
        pitch=pitch,
        goals_a=goals_a,
        goals_b=goals_b,
        next_match_id=next_id,
        success=success,
        error=error,
        calibration_message=calibration_message,
        calibration_levels=CALIBRATION_LEVELS
    )


@app.route("/glickofaq")
def glicko_explainer():
    return render_template("glickofaq.html")


if __name__ == "__main__":
    app.run(debug=True)
