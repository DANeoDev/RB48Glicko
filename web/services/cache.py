"""In-memory cache for expensive statistics and match history calculations."""

import threading
from scripts.database.database import get_connection
from scripts.database.db_matches import get_player_stats
from scripts.database.db_players import get_players
from scripts.database.db_ratings import get_ratings
from scripts.analysis.history_snapshots import compute_historical_snapshots, get_matchday_metadata_map
from scripts.analysis.streaks import get_dashboard_streaks
from scripts.analysis.synergies import get_community_synergies
from scripts.frontend.view_models import build_leaderboard, compute_leaderboard_deltas, build_match_history

_cache_lock = threading.Lock()
_stats_cache = None
_match_history_cache = {}


def get_cached_stats_data(connection=None):
    """
    Return cached computations for leaderboard, synergies, streaks, and snapshots.
    If cache is empty, computes everything in a single pass and caches the result.
    """
    global _stats_cache
    with _cache_lock:
        if _stats_cache is not None:
            return _stats_cache

        close_conn = False
        if connection is None:
            connection = get_connection()
            close_conn = True

        try:
            ratings = get_ratings(connection)
            players = get_players(connection)
            player_stats = get_player_stats(connection)
            deltas = compute_leaderboard_deltas(connection, ratings, players)
            synergies = get_community_synergies(connection, min_games=5)
            streaks = get_dashboard_streaks(connection)
            historical_snapshots = compute_historical_snapshots(connection)
            leaderboard_base = build_leaderboard(ratings, players, player_stats, deltas=deltas)

            _stats_cache = {
                "ratings": ratings,
                "players": players,
                "player_stats": player_stats,
                "deltas": deltas,
                "synergies": synergies,
                "streaks": streaks,
                "historical_snapshots": historical_snapshots,
                "leaderboard_base": leaderboard_base,
            }
            return _stats_cache
        finally:
            if close_conn:
                connection.close()


def get_cached_match_history(rating_type="total", connection=None):
    """
    Return cached computations for the global match history page for a given rating_type.
    """
    global _match_history_cache
    rating_type_key = str(rating_type).lower()
    with _cache_lock:
        if rating_type_key in _match_history_cache:
            return _match_history_cache[rating_type_key]

        close_conn = False
        if connection is None:
            connection = get_connection()
            close_conn = True

        try:
            players = get_players(connection)
            matches = build_match_history(connection, players, rating_type=rating_type)
            metadata_map = get_matchday_metadata_map(connection, matches=matches)

            for m in matches:
                meta = metadata_map.get(m["date"], {})
                m["date_formatted"] = meta.get("date_formatted", m["date"])
                m["matchday_number"] = meta.get("matchday_number", 1)
                m["season"] = meta.get("season", 2026)
                m["matchday_label"] = meta.get("label", f"{meta.get('matchday_number', 1)}. Spieltag")
                m["short_label"] = meta.get("short_label", f"{meta.get('matchday_number', 1)}. Spieltag")
                m["month_key"] = meta.get("month_key", m["date"][:7])
                m["month_label"] = meta.get("month_label", m["date"][:7])
                m["month_vertical"] = meta.get("month_vertical", m["date"][:7])

            matches.reverse()

            months_dict = {}
            for m in matches:
                mkey = m["month_key"]
                if mkey not in months_dict:
                    months_dict[mkey] = {
                        "month_key": mkey,
                        "month_label": m["month_label"],
                        "month_vertical": m["month_vertical"],
                        "matches": [],
                    }
                months_dict[mkey]["matches"].append(m)

            months_grouped = list(months_dict.values())

            distinct_dates_seen = set()
            timeline_matchdays = []
            for m in matches:
                d = m["date"]
                if d not in distinct_dates_seen:
                    distinct_dates_seen.add(d)
                    meta = metadata_map.get(d, {})
                    day_matches = [x for x in matches if x["date"] == d]
                    pitches = sorted(list(set(x["pitch"].upper() for x in day_matches)))
                    timeline_matchdays.append({
                        "id": f"d-{d}",
                        "date": d,
                        "date_formatted": meta.get("date_formatted", d),
                        "season": meta.get("season", 2026),
                        "matchday_number": meta.get("matchday_number", 1),
                        "label": meta.get("label", f"{meta.get('matchday_number', 1)}. Spieltag"),
                        "short_label": meta.get("short_label", f"{meta.get('matchday_number', 1)}. Spieltag"),
                        "month_key": meta.get("month_key", d[:7]),
                        "month_label": meta.get("month_label", d[:7]),
                        "matches_count": len(day_matches),
                        "pitch_types": pitches,
                    })

            timeline_months = []
            for mg in months_grouped:
                m_matches = mg["matches"]
                pitches = sorted(list(set(x["pitch"].upper() for x in m_matches)))
                timeline_months.append({
                    "id": f"m-{mg['month_key']}",
                    "month_key": mg["month_key"],
                    "month_label": mg["month_label"],
                    "month_vertical": mg["month_vertical"],
                    "date": m_matches[0]["date"],
                    "date_formatted": m_matches[0]["date_formatted"],
                    "label": mg["month_label"],
                    "short_label": mg["month_label"],
                    "matches_count": len(m_matches),
                    "pitch_types": pitches,
                })

            result = {
                "matches": matches,
                "months_grouped": months_grouped,
                "timeline_data": {
                    "matchdays": timeline_matchdays,
                    "months": timeline_months,
                },
            }
            _match_history_cache[rating_type_key] = result
            return result
        finally:
            if close_conn:
                connection.close()


def invalidate_stats_cache():
    """Clear all cached statistics and match history data."""
    global _stats_cache, _match_history_cache
    with _cache_lock:
        _stats_cache = None
        _match_history_cache = {}
