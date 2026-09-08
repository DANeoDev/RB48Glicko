import unittest
import sqlite3
from scripts.database.database import (
    create_players_table,
    create_aliases_table,
    create_positions_table,
    create_matches_table,
    create_match_players_table,
    create_ratings_table,
    create_match_ratings_table,
    create_calibrations_table,
)
from scripts.database.db_players import create_player, add_alias
from scripts.database.db_matches import (
    create_match,
    add_match_player,
    get_all_match_players,
    get_all_match_teams,
)
from scripts.database.db_ratings import get_all_match_ratings
from web.services.cache import get_cached_stats_data, invalidate_stats_cache


class PerformanceAndCacheTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        create_players_table(self.connection)
        create_aliases_table(self.connection)
        create_positions_table(self.connection)
        create_matches_table(self.connection)
        create_match_players_table(self.connection)
        create_ratings_table(self.connection)
        create_match_ratings_table(self.connection)
        create_calibrations_table(self.connection)

        create_player(self.connection, 1)
        add_alias(self.connection, "Alice", 1)
        create_player(self.connection, 2)
        add_alias(self.connection, "Bob", 2)
        self.connection.commit()

    def tearDown(self):
        self.connection.close()
        invalidate_stats_cache()

    def test_batch_match_players_and_teams(self):
        create_match(self.connection, "101", "2026-03-01", "box", 1, 1, 3, 2)
        add_match_player(self.connection, "101", 1, "a")
        add_match_player(self.connection, "101", 2, "b")

        create_match(self.connection, "102", "2026-03-02", "hf", 1, 1, 1, 1)
        add_match_player(self.connection, "102", 2, "a")
        add_match_player(self.connection, "102", 1, "b")

        all_players = get_all_match_players(self.connection)
        self.assertIn("101", all_players)
        self.assertEqual(len(all_players["101"]), 2)
        self.assertIn("102", all_players)

        all_teams = get_all_match_teams(self.connection)
        self.assertEqual(all_teams["101"], ([1], [2]))
        self.assertEqual(all_teams["102"], ([2], [1]))

    def test_batch_match_ratings(self):
        create_match(self.connection, "101", "2026-03-01", "box", 1, 1, 3, 2)
        add_match_player(self.connection, "101", 1, "a")
        add_match_player(self.connection, "101", 2, "b")

        self.connection.execute(
            "INSERT INTO match_ratings (match_id, player_id, rating_type, rating, rd, sigma) VALUES (?, ?, ?, ?, ?, ?)",
            ("101", 1, "total", 1520.0, 320.0, 0.06),
        )
        self.connection.commit()

        all_ratings = get_all_match_ratings(self.connection)
        self.assertIn("101", all_ratings)
        self.assertIn(1, all_ratings["101"])
        self.assertEqual(all_ratings["101"][1]["total"]["rating"], 1520.0)

    def test_cache_and_invalidation(self):
        invalidate_stats_cache()
        data1 = get_cached_stats_data(self.connection)
        self.assertIsNotNone(data1)
        self.assertIn("leaderboard_base", data1)

        data2 = get_cached_stats_data(self.connection)
        self.assertIs(data1, data2)  # Should return exact cached reference

        invalidate_stats_cache()
        data3 = get_cached_stats_data(self.connection)
        self.assertIsNotNone(data3)
        self.assertIsNot(data1, data3)  # Recomputed after invalidation


if __name__ == "__main__":
    unittest.main()
