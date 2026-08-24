from flask import Flask, render_template

from scripts.database import get_connection
from scripts.db_ratings import get_ratings, get_player_rating_history
from scripts.db_players import get_players
from scripts.db_matches import get_player_stats, get_matches, get_match_teams
from scripts.view_models import build_leaderboard, build_match_history, build_model_analysis


app = Flask(__name__)



@app.route("/")
def home():

    connection = get_connection()

    ratings = get_ratings(connection)
    players = get_players(connection)
    stats = get_player_stats(connection)

    connection.close()

    leaderboard = build_leaderboard(
        ratings,
        players,
        stats
    )

    return render_template(
        "index.html",
        leaderboard=leaderboard
    )



@app.route("/player/<int:player_id>")
def player_profile(player_id):

    connection = get_connection()

    players = get_players(connection)
    ratings = get_ratings(connection)
    stats = get_player_stats(connection)

    rating_history = get_player_rating_history(
        connection,
        player_id
    )

    rating_extremes = {}

    for rating_type in ["total", "box", "hf"]:
        history = rating_history[rating_type]

        if history:
            peak = max(history, key=lambda entry: entry["rating"])
            low = min(history, key=lambda entry: entry["rating"])

            rating_extremes[rating_type] = {
                "peak": peak,
                "low": low
            }
        else:
            rating_extremes[rating_type] = {
                "peak": None,
                "low": None
            }

    matches = build_match_history(
        connection,
        players,
        player_id
    )
    
    connection.close()

    player = players[player_id]
    player_ratings = ratings[player_id]
    player_stats = stats[player_id]

    matches.reverse()



    return render_template(
        "player.html",
        player=player,
        ratings=player_ratings,
        stats=player_stats,
        rating_history=rating_history,
        rating_extremes=rating_extremes,
        matches=matches
    )

@app.route("/matches")
def match_history():

    connection = get_connection()

    players = get_players(connection)

    matches = build_match_history(
        connection,
        players
    )
    matches.reverse()
    connection.close()

    return render_template(
        "matches.html",
        matches=matches
    )


@app.route("/model-analysis")
def model_analysis():

    connection = get_connection()

    players = get_players(connection)

    matches = build_match_history(
        connection,
        players
    )

    connection.close()

    analysis = build_model_analysis(matches)

    return render_template(
        "model_analysis.html",
        analysis=analysis
    )


@app.route("/glickofaq")
def glicko_explainer():
    return render_template("glickofaq.html")


if __name__ == "__main__":
    app.run(debug=True)