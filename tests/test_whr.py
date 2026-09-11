"""Unit tests for Whole-History Rating (WHR) team engine."""

import unittest
import numpy as np

from scripts.analysis.whr import (
    TeamWHR,
    compute_whr_ratings,
    solve_tridiagonal,
    tridiagonal_inverse_diagonal,
)
from scripts.database.database import get_connection
from scripts.glicko.glicko2 import TOTAL, BOX, HF


class TestTeamWHR(unittest.TestCase):
    """Test suite for TeamWHR algorithms and integration."""

    def test_solve_tridiagonal(self):
        """Test Thomas algorithm on known tridiagonal system."""
        # Matrix A:
        # [ 4 -1  0 ]
        # [-1  4 -1 ]
        # [ 0 -1  4 ]
        diag = np.array([4.0, 4.0, 4.0])
        off_diag = np.array([-1.0, -1.0])
        rhs = np.array([2.0, 4.0, 6.0])

        x = solve_tridiagonal(diag, off_diag, rhs)

        # Check A * x = rhs
        A = np.array([
            [4.0, -1.0, 0.0],
            [-1.0, 4.0, -1.0],
            [0.0, -1.0, 4.0],
        ])
        np.testing.assert_allclose(A @ x, rhs, atol=1e-8)

    def test_tridiagonal_inverse_diagonal(self):
        """Test inverse diagonal extraction on known matrix."""
        diag = np.array([2.0, 2.0])
        off_diag = np.array([-1.0])
        # A = [[2, -1], [-1, 2]], det = 3
        # A^-1 = 1/3 * [[2, 1], [1, 2]] -> diag = [2/3, 2/3]
        variances = tridiagonal_inverse_diagonal(diag, off_diag)
        np.testing.assert_allclose(variances, np.array([2.0 / 3.0, 2.0 / 3.0]), atol=1e-6)

    def test_synthetic_whr_symmetry(self):
        """Verify that two identical teams trading wins remain symmetric at 1500."""
        whr = TeamWHR(default_rating=1500.0, default_rd=350.0)
        # Synthetic match setup:
        # Player 1 & 2 vs Player 3 & 4
        # Match 1: Team A wins
        # Match 2: Team B wins
        whr.players = {1: "A1", 2: "A2", 3: "B1", 4: "B2"}
        whr.player_dates = {
            1: ["2026-01-01", "2026-01-08"],
            2: ["2026-01-01", "2026-01-08"],
            3: ["2026-01-01", "2026-01-08"],
            4: ["2026-01-01", "2026-01-08"],
        }
        whr.r_profile = {pid: np.full(2, 1500.0) for pid in range(1, 5)}
        whr.rd_profile = {pid: np.full(2, 350.0) for pid in range(1, 5)}

        whr.matches = [
            {
                "match_id": 1,
                "date": "2026-01-01",
                "pitch": "box",
                "team_a": [1, 2],
                "team_b": [3, 4],
                "total_a": 2,
                "total_b": 2,
                "score_a": 1.0,
            },
            {
                "match_id": 2,
                "date": "2026-01-08",
                "pitch": "box",
                "team_a": [1, 2],
                "team_b": [3, 4],
                "total_a": 2,
                "total_b": 2,
                "score_a": 0.0,
            },
        ]

        iters = whr.solve(max_iterations=30)
        self.assertGreater(iters, 0)

        # Team A won game 1, so on date 1 they should be higher than Team B
        self.assertGreater(whr.r_profile[1][0], 1500.0)
        self.assertLess(whr.r_profile[3][0], 1500.0)

        # After both games (1 win each), final ratings should balance back to ~1500
        self.assertAlmostEqual(whr.r_profile[1][1], 1500.0, delta=2.0)
        self.assertAlmostEqual(whr.r_profile[3][1], 1500.0, delta=2.0)

    def test_compute_whr_ratings_database(self):
        """Test WHR execution on live database for TOTAL, BOX, and HF pitches."""
        conn = get_connection()
        try:
            for pitch in [TOTAL, BOX, HF]:
                with self.subTest(pitch=pitch):
                    report = compute_whr_ratings(conn, pitch_filter=pitch)
                    self.assertIn("players", report)
                    self.assertIn("iterations", report)
                    self.assertIn("metrics", report)
                    self.assertGreaterEqual(report["iterations"], 1)

                    players = report["players"]
                    if pitch == TOTAL:
                        self.assertGreater(len(players), 0)
                        # Check player dict structure
                        p0 = players[0]
                        self.assertIn("player_id", p0)
                        self.assertIn("alias", p0)
                        self.assertIn("whr_rating", p0)
                        self.assertIn("whr_rd", p0)
                        self.assertIn("glicko_rating", p0)
                        self.assertIn("delta", p0)
                        self.assertIn("history", p0)
                        self.assertIsInstance(p0["history"], list)
                        self.assertGreater(len(p0["history"]), 0)

                        # Ratings must be in valid football range
                        for p in players:
                            self.assertGreater(p["whr_rating"], 500.0)
                            self.assertLess(p["whr_rating"], 2500.0)
                            self.assertGreater(p["whr_rd"], 10.0)
                            self.assertLess(p["whr_rd"], 500.0)
        finally:
            conn.close()

    def test_get_whr_ratings_dict(self):
        """Test that get_whr_ratings_dict returns valid format matching get_ratings."""
        from scripts.analysis.whr import get_whr_ratings_dict
        from scripts.database.db_players import get_players

        conn = get_connection()
        try:
            players = get_players(conn)
            ratings = get_whr_ratings_dict(conn)
            self.assertEqual(len(ratings), len(players))
            for pid in players:
                self.assertIn(pid, ratings)
                for ptype in (TOTAL, BOX, HF):
                    self.assertIn(ptype, ratings[pid])
                    entry = ratings[pid][ptype]
                    self.assertIn("rating", entry)
                    self.assertIn("rd", entry)
                    self.assertIn("sigma", entry)
                    self.assertIsInstance(entry["rating"], float)
                    self.assertIsInstance(entry["rd"], float)
        finally:
            conn.close()

    def test_build_whr_match_history(self):
        """Test build_whr_match_history on live database."""
        from scripts.analysis.whr import build_whr_match_history
        from scripts.database.db_players import get_players

        conn = get_connection()
        try:
            players = get_players(conn)
            matches = build_whr_match_history(conn, players, rating_type=TOTAL)
            self.assertGreater(len(matches), 0)
            m0 = matches[0]
            self.assertIn("match_id", m0)
            self.assertIn("team_a_rating", m0)
            self.assertIn("team_b_rating", m0)
            self.assertIn("team_a_expected", m0)
            self.assertIn("team_b_expected", m0)
            self.assertAlmostEqual(m0["team_a_expected"] + m0["team_b_expected"], 1.0, places=4)
        finally:
            conn.close()

    def test_cached_whr_data(self):
        """Test WHR cache functions and invalidation."""
        from web.services.cache import (
            get_cached_whr_stats_data,
            get_cached_whr_match_history,
            invalidate_stats_cache,
        )

        invalidate_stats_cache()
        stats_data = get_cached_whr_stats_data()
        self.assertIn("leaderboard_base", stats_data)
        self.assertIn("ratings", stats_data)
        self.assertGreater(len(stats_data["leaderboard_base"]), 0)

        match_hist = get_cached_whr_match_history("total")
        self.assertIn("matches", match_hist)
        self.assertIn("months_grouped", match_hist)
        self.assertIn("timeline_data", match_hist)

    def test_get_whr_state_at(self):
        """Test continuous-time WHR state evaluation, bridge interpolation, and drift."""
        from scripts.analysis.whr import _get_whr_state_at

        whr = TeamWHR(default_rating=1500.0, default_rd=350.0)
        whr.date_to_idx = {
            "2026-01-01": 0,
            "2026-01-08": 1,
            "2026-01-15": 2,
            "2026-01-22": 3,
            "2026-01-29": 4,
        }
        whr.player_dates = {
            1: ["2026-01-08", "2026-01-22"]
        }
        whr.r_profile = {1: np.array([1600.0, 1700.0])}
        whr.rd_profile = {1: np.array([150.0, 140.0])}

        # 1. Before first game
        r_pre, rd_pre = _get_whr_state_at(whr, 1, "2026-01-01", default_r=1500.0, default_rd=350.0)
        self.assertEqual(r_pre, 1500.0)
        self.assertEqual(rd_pre, 350.0)

        # 2. Exact match date
        r_exact, rd_exact = _get_whr_state_at(whr, 1, "2026-01-08")
        self.assertEqual(r_exact, 1600.0)
        self.assertEqual(rd_exact, 150.0)

        # 3. Brownian bridge interpolation between matchdays
        r_mid, rd_mid = _get_whr_state_at(whr, 1, "2026-01-15")
        self.assertAlmostEqual(r_mid, 1650.0, places=2)
        # alpha = 0.5, bridge_var = 0.25 * 2 * 50 = 25
        # var = 0.5 * 150^2 + 0.5 * 140^2 + 25 = 21075 -> sqrt(21075) ≈ 145.17
        self.assertAlmostEqual(rd_mid, np.sqrt(21075), places=2)

        # 4. Brownian drift after last match
        r_post, rd_post = _get_whr_state_at(whr, 1, "2026-01-29")
        self.assertEqual(r_post, 1700.0)
        # var = 140^2 + 50 * 1 = 19650 -> sqrt(19650) ≈ 140.18
        self.assertAlmostEqual(rd_post, np.sqrt(19650), places=2)

    def test_compute_whr_historical_snapshots(self):
        """Test compute_whr_historical_snapshots and deltas generation."""
        from scripts.analysis.whr import (
            compute_whr_historical_snapshots,
            compute_whr_leaderboard_deltas,
        )

        conn = get_connection()
        try:
            snaps = compute_whr_historical_snapshots(conn)
            self.assertIn("matchdays", snaps)
            self.assertIn("months", snaps)
            self.assertGreater(len(snaps["matchdays"]), 0)
            self.assertGreater(len(snaps["months"]), 0)

            latest_snap = snaps["matchdays"][0]
            self.assertIn("leaderboard", latest_snap)
            self.assertGreater(len(latest_snap["leaderboard"]), 0)

            top_p = latest_snap["leaderboard"][0]
            self.assertIn("player_id", top_p)
            self.assertIn("alias", top_p)
            for pkey in (TOTAL, BOX, HF):
                self.assertIn(pkey, top_p)
                p_track = top_p[pkey]
                self.assertIn("rating", p_track)
                self.assertIn("rd", p_track)
                self.assertIn("conservative", p_track)
                self.assertIn("games", p_track)
                self.assertIn("deltas", p_track)
                self.assertIn("game", p_track["deltas"])
                self.assertIn("month", p_track["deltas"])
                self.assertIn("quarter", p_track["deltas"])
                self.assertIn("year", p_track["deltas"])

            deltas = compute_whr_leaderboard_deltas(conn, snapshots=snaps)
            self.assertGreater(len(deltas), 0)
            first_pid = top_p["player_id"]
            self.assertIn(first_pid, deltas)
            self.assertIn("total", deltas[first_pid])
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
