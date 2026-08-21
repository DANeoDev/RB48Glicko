from flask import Flask, render_template

from scripts.database import get_connection
from scripts.db_ratings import get_ratings, get_player_rating_history
from scripts.db_players import get_players
from scripts.db_matches import get_player_stats, get_matches, get_match_teams
from scripts.view_models import build_leaderboard, build_match_history


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

    matches = build_match_history(
        connection,
        players,
        player_id
    )

    connection.close()

    player = players[player_id]
    player_ratings = ratings[player_id]
    player_stats = stats[player_id]

    return render_template(
        "player.html",
        player=player,
        ratings=player_ratings,
        stats=player_stats,
        rating_history=rating_history,
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


@app.route("/glickofaq")
def glicko_explainer():
    return render_template("glickofaq.html")


if __name__ == "__main__":
    app.run(debug=True)