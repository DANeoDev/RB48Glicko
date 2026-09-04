"""Analysis module for active streaks, all-time win streaks, and 30-day improvements."""

from datetime import datetime, timedelta
from scripts.database.db_players import get_players
from scripts.database.db_ratings import get_ratings, get_player_rating_history


def get_dashboard_streaks(connection):
    """Calculate active win streaks, record win streaks, and most improved players."""
    players = get_players(connection)
    rows = connection.execute("""
        SELECT m.match_id, m.date, m.goals_a, m.goals_b,
               mp.player_id, mp.team
        FROM matches m
        JOIN match_players mp ON m.match_id = mp.match_id
        ORDER BY m.date ASC, m.match_id ASC
    """).fetchall()

    player_streaks = {pid: {"current_type": None, "current_count": 0, "max_win_streak": 0} for pid in players}

    for r in rows:
        pid = r["player_id"]
        if pid not in player_streaks:
            player_streaks[pid] = {"current_type": None, "current_count": 0, "max_win_streak": 0}

        team = r["team"]
        ga, gb = r["goals_a"], r["goals_b"]
        is_win = (team == "a" and ga > gb) or (team == "b" and gb > ga)
        is_loss = (team == "a" and ga < gb) or (team == "b" and gb < ga)
        is_draw = ga == gb

        result_type = "W" if is_win else ("L" if is_loss else "D")
        ps = player_streaks[pid]

        if ps["current_type"] == result_type:
            ps["current_count"] += 1
        else:
            ps["current_type"] = result_type
            ps["current_count"] = 1

        if result_type == "W" and ps["current_count"] > ps["max_win_streak"]:
            ps["max_win_streak"] = ps["current_count"]

    # Active win streaks (count >= 2)
    active_win_streaks = []
    for pid, ps in player_streaks.items():
        if ps["current_type"] == "W" and ps["current_count"] >= 2:
            alias = players[pid]["aliases"][0] if pid in players else f"Player #{pid}"
            active_win_streaks.append({
                "player_id": pid,
                "name": alias,
                "count": ps["current_count"]
            })
    active_win_streaks.sort(key=lambda s: -s["count"])

    # All-time win streaks
    all_time_win_streaks = []
    for pid, ps in player_streaks.items():
        if ps["max_win_streak"] >= 3:
            alias = players[pid]["aliases"][0] if pid in players else f"Player #{pid}"
            all_time_win_streaks.append({
                "player_id": pid,
                "name": alias,
                "count": ps["max_win_streak"]
            })
    all_time_win_streaks.sort(key=lambda s: -s["count"])
    all_time_win_streaks = all_time_win_streaks[:6]

    # Most improved player in past 30 days
    now = datetime.now()
    cutoff_date = (now - timedelta(days=30)).strftime("%Y-%m-%d")

    ratings = get_ratings(connection)
    improved_list = []

    for pid in players:
        hist = get_player_rating_history(connection, pid).get("total", [])
        if not hist:
            continue

        curr_r = ratings.get(pid, {}).get("total", {}).get("rating", hist[-1]["rating"])
        past_r = None
        for hr in reversed(hist):
            if hr["date"] <= cutoff_date:
                past_r = hr["rating"]
                break
        if past_r is None and len(hist) > 1:
            past_r = hist[0]["rating"]

        if past_r is not None:
            delta = curr_r - past_r
            if delta > 0:
                alias = players[pid]["aliases"][0] if pid in players else f"Player #{pid}"
                improved_list.append({
                    "player_id": pid,
                    "name": alias,
                    "rating_delta": delta,
                    "current_rating": curr_r,
                    "past_rating": past_r
                })

    improved_list.sort(key=lambda x: -x["rating_delta"])
    most_improved = improved_list[:5]

    return {
        "active_win_streaks": active_win_streaks,
        "all_time_win_streaks": all_time_win_streaks,
        "most_improved": most_improved
    }
