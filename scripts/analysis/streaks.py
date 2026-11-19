"""Analysis module for active streaks, all-time win/unbeaten streaks, and 30-day improvements."""

from datetime import datetime, timedelta
from scripts.database.db_players import get_players
from scripts.database.db_ratings import get_ratings, get_player_rating_history


def _cap_all_time_streaks(streaks_list, limit=12):
    """Keep top streaks up to `limit` while preserving ties at the cutoff."""
    if len(streaks_list) > limit:
        cutoff_count = streaks_list[limit - 1]["count"]
        return [s for s in streaks_list if s["count"] >= cutoff_count]
    return streaks_list


def get_dashboard_streaks(connection):
    """Calculate active win/unbeaten streaks, record streaks, and most improved players overall and per pitch."""
    players = get_players(connection)
    rows = connection.execute("""
        SELECT m.match_id, m.date, m.pitch, m.goals_a, m.goals_b,
               mp.player_id, mp.team
        FROM matches m
        JOIN match_players mp ON m.match_id = mp.match_id
        ORDER BY m.date ASC, m.match_id ASC
    """).fetchall()

    pitch_keys = ("total", "box", "hf")
    player_streaks = {
        pkey: {
            pid: {
                "win_curr": 0,
                "win_max": 0,
                "unbeaten_curr": 0,
                "unbeaten_max": 0,
                "loss_curr": 0,
                "loss_max": 0,
            }
            for pid in players
        }
        for pkey in pitch_keys
    }
    latest_dates = {pkey: None for pkey in pitch_keys}

    for r in rows:
        pid = r["player_id"]
        m_date = r["date"]
        m_pitch = str(r["pitch"] or "").strip().lower()
        target_pkeys = ["total"] + ([m_pitch] if m_pitch in ("box", "hf") else [])

        team = r["team"]
        ga, gb = r["goals_a"], r["goals_b"]
        is_win = (team == "a" and ga > gb) or (team == "b" and gb > ga)
        is_loss = (team == "a" and ga < gb) or (team == "b" and gb < ga)

        for pkey in target_pkeys:
            if m_date and (latest_dates[pkey] is None or m_date > latest_dates[pkey]):
                latest_dates[pkey] = m_date

            p_map = player_streaks[pkey]
            if pid not in p_map:
                p_map[pid] = {
                    "win_curr": 0,
                    "win_max": 0,
                    "unbeaten_curr": 0,
                    "unbeaten_max": 0,
                    "loss_curr": 0,
                    "loss_max": 0,
                }
            ps = p_map[pid]

            if is_win:
                ps["win_curr"] += 1
                if ps["win_curr"] > ps["win_max"]:
                    ps["win_max"] = ps["win_curr"]
            else:
                ps["win_curr"] = 0

            if not is_loss:
                ps["unbeaten_curr"] += 1
                if ps["unbeaten_curr"] > ps["unbeaten_max"]:
                    ps["unbeaten_max"] = ps["unbeaten_curr"]
            else:
                ps["unbeaten_curr"] = 0

            if is_loss:
                ps["loss_curr"] += 1
                if ps["loss_curr"] > ps["loss_max"]:
                    ps["loss_max"] = ps["loss_curr"]
            else:
                ps["loss_curr"] = 0

    ratings = get_ratings(connection)
    rating_histories = {pid: get_player_rating_history(connection, pid) for pid in players}

    overall_latest = latest_dates["total"]
    by_pitch = {}

    for pkey in pitch_keys:
        p_map = player_streaks[pkey]

        active_win = []
        all_time_win = []
        active_unbeaten = []
        all_time_unbeaten = []
        active_loss = []
        all_time_loss = []

        for pid, ps in p_map.items():
            alias = players[pid]["aliases"][0] if pid in players and players[pid].get("aliases") else f"Player #{pid}"
            if ps["win_curr"] >= 2:
                active_win.append({"player_id": pid, "name": alias, "count": ps["win_curr"]})
            if ps["win_max"] >= 3:
                all_time_win.append({"player_id": pid, "name": alias, "count": ps["win_max"]})
            if ps["unbeaten_curr"] >= 2:
                active_unbeaten.append({"player_id": pid, "name": alias, "count": ps["unbeaten_curr"]})
            if ps["unbeaten_max"] >= 3:
                all_time_unbeaten.append({"player_id": pid, "name": alias, "count": ps["unbeaten_max"]})
            if ps["loss_curr"] >= 2:
                active_loss.append({"player_id": pid, "name": alias, "count": ps["loss_curr"]})
            if ps["loss_max"] >= 3:
                all_time_loss.append({"player_id": pid, "name": alias, "count": ps["loss_max"]})

        active_win.sort(key=lambda s: (-s["count"], s["name"].lower()))
        all_time_win.sort(key=lambda s: (-s["count"], s["name"].lower()))
        active_unbeaten.sort(key=lambda s: (-s["count"], s["name"].lower()))
        all_time_unbeaten.sort(key=lambda s: (-s["count"], s["name"].lower()))
        active_loss.sort(key=lambda s: (-s["count"], s["name"].lower()))
        all_time_loss.sort(key=lambda s: (-s["count"], s["name"].lower()))

        all_time_win = _cap_all_time_streaks(all_time_win)
        all_time_unbeaten = _cap_all_time_streaks(all_time_unbeaten)
        all_time_loss = _cap_all_time_streaks(all_time_loss)

        # Most improved player in past 30 days (anchored to latest match date for this pitch or overall)
        anchor_str = latest_dates[pkey] or overall_latest
        if anchor_str:
            try:
                ref_date = datetime.strptime(anchor_str, "%Y-%m-%d")
            except ValueError:
                ref_date = datetime.now()
        else:
            ref_date = datetime.now()
        cutoff_date = (ref_date - timedelta(days=30)).strftime("%Y-%m-%d")

        improved_list = []
        for pid in players:
            hist = rating_histories.get(pid, {}).get(pkey, [])
            dated_hist = [hr for hr in hist if hr.get("date")]
            if not dated_hist:
                continue

            curr_r = ratings.get(pid, {}).get(pkey, {}).get("rating", dated_hist[-1]["rating"])
            past_r = None
            for hr in reversed(dated_hist):
                if hr["date"] <= cutoff_date:
                    past_r = hr["rating"]
                    break
            if past_r is None and len(hist) > 1:
                past_r = dated_hist[0]["rating"]

            if past_r is not None:
                delta = curr_r - past_r
                if delta > 0:
                    alias = players[pid]["aliases"][0] if players[pid].get("aliases") else f"Player #{pid}"
                    improved_list.append({
                        "player_id": pid,
                        "name": alias,
                        "rating_delta": delta,
                        "current_rating": curr_r,
                        "past_rating": past_r,
                    })

        improved_list.sort(key=lambda x: -x["rating_delta"])
        by_pitch[pkey] = {
            "active_win_streaks": active_win,
            "all_time_win_streaks": all_time_win,
            "active_unbeaten_streaks": active_unbeaten,
            "all_time_unbeaten_streaks": all_time_unbeaten,
            "active_loss_streaks": active_loss,
            "all_time_loss_streaks": all_time_loss,
            "most_improved": improved_list[:5],
        }

    return {
        "active_win_streaks": by_pitch["total"]["active_win_streaks"],
        "all_time_win_streaks": by_pitch["total"]["all_time_win_streaks"],
        "active_unbeaten_streaks": by_pitch["total"]["active_unbeaten_streaks"],
        "all_time_unbeaten_streaks": by_pitch["total"]["all_time_unbeaten_streaks"],
        "active_loss_streaks": by_pitch["total"]["active_loss_streaks"],
        "all_time_loss_streaks": by_pitch["total"]["all_time_loss_streaks"],
        "most_improved": by_pitch["total"]["most_improved"],
        "by_pitch": by_pitch,
    }
