"""In-memory cache for expensive statistics calculations."""

import threading
from scripts.database.database import get_connection
from scripts.database.db_matches import get_player_stats
from scripts.database.db_players import get_players
from scripts.database.db_ratings import get_ratings
from scripts.analysis.achievements import get_player_achievements
from scripts.analysis.history_snapshots import compute_historical_snapshots
from scripts.analysis.streaks import get_dashboard_streaks
from scripts.analysis.synergies import get_community_synergies
from scripts.frontend.view_models import build_leaderboard, compute_leaderboard_deltas

_cache_lock = threading.Lock()
_stats_cache = None


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


def invalidate_stats_cache():
    """Clear the cached statistics data (e.g. after match recording or recalculation)."""
    global _stats_cache
    with _cache_lock:
        _stats_cache = None
