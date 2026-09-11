import os
from pathlib import Path
import shutil
import tempfile
import unittest

from scripts.database.database import get_connection
from scripts.database.db_players import get_players
from scripts.database.db_ratings import get_ratings
from scripts.frontend.view_models import (
    compute_leaderboard_deltas,
    _compute_single_game_delta,
    _compute_period_delta,
    build_leaderboard,
    TOTAL,
)


class ViewModelsTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_rb48_db = Path(self.temp_dir.name) / "test_rb48.db"
        prod_rb48 = Path(__file__).resolve().parents[1] / "data" / "rb48.db"
        if prod_rb48.exists():
            shutil.copy2(prod_rb48, self.test_rb48_db)
        os.environ["RB48_DATABASE_FILE"] = str(self.test_rb48_db)

    def tearDown(self):
        os.environ.pop("RB48_DATABASE_FILE", None)
        self.temp_dir.cleanup()

    def test_compute_single_game_delta_empty(self):
        delta = _compute_single_game_delta([], TOTAL, 1500.0, 200.0, 900.0)
        self.assertEqual(delta["games"], 0)
        self.assertEqual(delta["rating"], 0.0)
        self.assertEqual(delta["conservative"], 0.0)

    def test_compute_single_game_delta_with_win(self):
        evts = [
            {
                "date": "2026-01-01",
                "is_win": True,
                "is_loss": False,
                "rating_before_total": 1480.0,
                "rd_before_total": 100.0,
                "rating_before_pitch": 1480.0,
                "rd_before_pitch": 100.0,
            }
        ]
        curr_r = 1500.0
        curr_rd = 95.0
        curr_c = curr_r - 3 * curr_rd
        delta = _compute_single_game_delta(evts, TOTAL, curr_r, curr_rd, curr_c)
        self.assertEqual(delta["games"], 1)
        self.assertEqual(delta["wins"], 1)
        self.assertEqual(delta["losses"], 0)
        self.assertEqual(delta["win_percent"], 100.0)
        self.assertAlmostEqual(delta["rating"], 20.0)
        self.assertAlmostEqual(delta["conservative"], 35.0)

    def test_compute_period_delta_cutoff(self):
        evts = [
            {
                "date": "2026-01-01",
                "is_win": False,
                "is_loss": True,
                "rating_before_total": 1400.0,
                "rd_before_total": 100.0,
            },
            {
                "date": "2026-02-01",
                "is_win": True,
                "is_loss": False,
                "rating_before_total": 1420.0,
                "rd_before_total": 90.0,
            },
        ]
        delta_filtered = _compute_period_delta(evts, "2026-01-15", TOTAL, 1450.0, 85.0, 1195.0)
        self.assertEqual(delta_filtered["games"], 1)
        self.assertEqual(delta_filtered["wins"], 1)
        self.assertEqual(delta_filtered["losses"], 0)
        self.assertEqual(delta_filtered["win_percent"], 100.0)

    def test_compute_period_delta_inactive_player(self):
        # Inactive player with 0 events in the period
        evts = []
        curr_r = 1500.0
        curr_rd = 100.872
        curr_c = curr_r - 3 * curr_rd
        delta = _compute_period_delta(
            evts,
            "2026-01-15",
            TOTAL,
            curr_r,
            curr_rd,
            curr_c,
            baseline_r=1500.0,
            baseline_rd=100.0,
        )
        self.assertEqual(delta["games"], 0)
        self.assertEqual(delta["wins"], 0)
        self.assertEqual(delta["losses"], 0)
        self.assertEqual(delta["win_percent"], 0.0)
        self.assertAlmostEqual(delta["rating"], 0.0)
        self.assertAlmostEqual(delta["rd"], 0.872)
        self.assertAlmostEqual(delta["conservative"], -3 * 0.872)

    def test_compute_leaderboard_deltas_db(self):
        conn = get_connection()
        try:
            players = get_players(conn)
            ratings = get_ratings(conn)
            deltas = compute_leaderboard_deltas(conn, ratings, players)
            self.assertIsInstance(deltas, dict)
            has_inactive_player_with_positive_rd = False
            for pid in players:
                self.assertIn(pid, deltas)
                for pitch in ("total", "box", "hf"):
                    self.assertIn(pitch, deltas[pid])
                    for period in ("game", "month", "quarter", "year"):
                        self.assertIn(period, deltas[pid][pitch])
                        p_data = deltas[pid][pitch][period]
                        self.assertIn("conservative", p_data)
                        self.assertIn("rating", p_data)
                        self.assertIn("rd", p_data)
                        self.assertIn("games", p_data)

                month_data = deltas[pid]["total"]["month"]
                if month_data["games"] == 0 and month_data["rd"] > 0:
                    has_inactive_player_with_positive_rd = True
                    self.assertLess(month_data["conservative"], 0)
                    self.assertAlmostEqual(month_data["rating"], 0.0)

            self.assertTrue(has_inactive_player_with_positive_rd, "Expected inactive players to have positive RD delta from missed sessions.")
        finally:
            conn.close()

    def test_build_leaderboard_sorting(self):
        players = {
            1: {"aliases": ["Alice"]},
            2: {"aliases": ["Bob"]},
        }
        ratings = {
            1: {
                "total": {"rating": 1500.0, "rd": 50.0},
                "box": {"rating": 1500.0, "rd": 50.0},
                "hf": {"rating": 1500.0, "rd": 50.0},
            },
            2: {
                "total": {"rating": 1600.0, "rd": 50.0},
                "box": {"rating": 1600.0, "rd": 50.0},
                "hf": {"rating": 1600.0, "rd": 50.0},
            },
        }
        stats = {}
        board = build_leaderboard(ratings, players, stats)
        self.assertEqual(len(board), 2)
        self.assertEqual(board[0]["player_id"], 2)
        self.assertEqual(board[1]["player_id"], 1)


if __name__ == "__main__":
    unittest.main()
