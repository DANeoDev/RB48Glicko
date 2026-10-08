import datetime
import os
import sqlite3
import unittest

from scripts.database.database import (
    create_aliases_table,
    create_calibrations_table,
    create_match_players_table,
    create_match_ratings_table,
    create_matches_table,
    create_player_calibrated_priors_table,
    create_players_table,
    create_ratings_table,
)
from scripts.database.db_matches import (
    add_match_player,
    create_match,
    get_all_match_teams,
)
from scripts.database.db_players import add_alias, create_player
from scripts.database.db_ratings import (
    get_all_match_ratings,
    get_player_calibrated_priors,
    save_player_calibrated_priors,
)
from scripts.frontend.view_models import build_leaderboard
from scripts.glicko.glicko2 import (
    DEFAULT_RATING,
    DEFAULT_RD,
    DEFAULT_SIGMA,
    BOX,
    HF,
    TOTAL,
    Rating,
)
from scripts.glicko.glicko2_calculator import (
    CALIBRATION_THRESHOLD,
    compute_player_thresholds,
    recalculate_glicko2_ratings,
    run_recalibration_pass1,
)


class TestRecalibrationDualCriterion(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        create_players_table(self.conn)
        create_aliases_table(self.conn)
        create_matches_table(self.conn)
        create_match_players_table(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_active_player_below_threshold(self):
        """Active players with < CALIBRATION_THRESHOLD games retain threshold = 15."""
        create_player(self.conn, 1)
        add_alias(self.conn, "Active Rookie", 1)
        create_player(self.conn, 99)
        add_alias(self.conn, "Opponent", 99)

        recent_date = (datetime.date.today() - datetime.timedelta(days=10)).isoformat()
        for i in range(1, 6):
            mid = f"rec-match-{i}"
            create_match(self.conn, mid, recent_date, "box", 1, 1, 3, 2)
            add_match_player(self.conn, mid, 1, "a")
            add_match_player(self.conn, mid, 99, "b")

        thresholds = compute_player_thresholds(
            self.conn, standard_threshold=15, inactivity_days=365
        )
        self.assertEqual(thresholds[1], 15)

    def test_inactive_historical_player_criterion(self):
        """Historical players inactive for > 365 days graduate at career games count."""
        create_player(self.conn, 2)
        add_alias(self.conn, "Old Legend", 2)
        create_player(self.conn, 99)
        add_alias(self.conn, "Opponent", 99)

        old_date = (datetime.date.today() - datetime.timedelta(days=450)).isoformat()
        for i in range(1, 8):
            mid = f"hist-match-{i}"
            create_match(self.conn, mid, old_date, "box", 1, 1, 3, 2)
            add_match_player(self.conn, mid, 2, "a")
            add_match_player(self.conn, mid, 99, "b")

        thresholds = compute_player_thresholds(
            self.conn, standard_threshold=15, inactivity_days=365
        )
        # 7 games, inactive > 365 days -> threshold is max(1, 7) = 7
        self.assertEqual(thresholds[2], 7)

    def test_inactive_player_zero_games(self):
        """Inactive player with zero games defaults to standard threshold."""
        create_player(self.conn, 3)
        add_alias(self.conn, "Ghost Player", 3)

        thresholds = compute_player_thresholds(
            self.conn, standard_threshold=15, inactivity_days=365
        )
        self.assertEqual(thresholds[3], 15)


class TestRecalibrationDatabasePersistence(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        create_players_table(self.conn)
        create_aliases_table(self.conn)
        create_calibrations_table(self.conn)
        create_player_calibrated_priors_table(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_save_and_get_calibrated_priors(self):
        """Test persisting and fetching calibrated priors across tracks."""
        create_player(self.conn, 1)
        add_alias(self.conn, "Player One", 1)

        priors = {
            1: {
                TOTAL: Rating(rating=1620.5, rd=95.0, sigma=0.058),
                BOX: Rating(rating=1640.0, rd=110.0, sigma=0.06),
                HF: Rating(rating=1600.0, rd=130.0, sigma=0.06),
            }
        }
        thresholds = {1: 15}

        save_player_calibrated_priors(self.conn, priors, thresholds=thresholds)

        loaded = get_player_calibrated_priors(self.conn)
        self.assertIn(1, loaded)
        self.assertIn(TOTAL, loaded[1])
        self.assertAlmostEqual(loaded[1][TOTAL]["rating"], 1620.5)
        self.assertAlmostEqual(loaded[1][TOTAL]["rd"], 95.0)
        self.assertAlmostEqual(loaded[1][TOTAL]["sigma"], 0.058)
        self.assertEqual(loaded[1][TOTAL]["threshold"], 15)

        # Verify mirroring into legacy calibrations table
        cursor = self.conn.cursor()
        cursor.execute("SELECT rating, rd, sigma FROM calibrations WHERE player_id = 1")
        row = cursor.fetchone()
        self.assertIsNotNone(row)
        self.assertAlmostEqual(row["rating"], 1620.5)
        self.assertAlmostEqual(row["rd"], 95.0)


class TestRecalibrationEnginePasses(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        create_players_table(self.conn)
        create_aliases_table(self.conn)
        create_matches_table(self.conn)
        create_match_players_table(self.conn)
        create_ratings_table(self.conn)
        create_match_ratings_table(self.conn)
        create_calibrations_table(self.conn)
        create_player_calibrated_priors_table(self.conn)

    def tearDown(self):
        self.conn.close()

    def _setup_players_and_matches(self, num_matches=16):
        for pid, name in [(1, "P1"), (2, "P2"), (3, "P3"), (4, "P4")]:
            create_player(self.conn, pid)
            add_alias(self.conn, name, pid)

        for m_idx in range(1, num_matches + 1):
            date_str = f"2026-01-{m_idx:02d}"
            mid = f"match-{m_idx:02d}"
            # Team 1 (P1, P2) beats Team 2 (P3, P4) 10 to 5
            create_match(self.conn, mid, date_str, "box", 2, 2, 10, 5)
            add_match_player(self.conn, mid, 1, "a")
            add_match_player(self.conn, mid, 2, "a")
            add_match_player(self.conn, mid, 3, "b")
            add_match_player(self.conn, mid, 4, "b")

    def test_run_recalibration_pass1_emergent_discovery(self):
        """Pass 1 discovers emergent priors at exact threshold T."""
        self._setup_players_and_matches(16)
        match_teams_map = get_all_match_teams(self.conn)

        from scripts.database.db_matches import get_matches
        matches = get_matches(self.conn)
        thresholds = {1: 15, 2: 15, 3: 15, 4: 15}

        discovered = run_recalibration_pass1(
            self.conn, matches, match_teams_map=match_teams_map, player_thresholds=thresholds
        )

        for pid in [1, 2, 3, 4]:
            self.assertIn(pid, discovered)
            self.assertIn(TOTAL, discovered[pid])
            self.assertIn(BOX, discovered[pid])
            if pid in [1, 2]:
                self.assertGreater(discovered[pid][TOTAL].rating, DEFAULT_RATING)
                self.assertLess(discovered[pid][TOTAL].rd, DEFAULT_RD)
            else:
                self.assertLess(discovered[pid][TOTAL].rating, DEFAULT_RATING)
                self.assertLess(discovered[pid][TOTAL].rd, DEFAULT_RD)

    def test_pass2_option_a_anchors_and_graduates(self):
        """Pass 2 anchors games 1..T at calibrated prior and updates games > T."""
        self._setup_players_and_matches(16)

        # Recalculate with retro_calibrated=True
        recalculate_glicko2_ratings(self.conn, create_backup=False, retro_calibrated=True)

        priors = get_player_calibrated_priors(self.conn)
        self.assertEqual(len(priors), 4)
        for pid in [1, 2, 3, 4]:
            self.assertIn(pid, priors)
            self.assertEqual(priors[pid][TOTAL]["threshold"], 15)

        # Check match_ratings historical table: at match 15, player 1 rating was calibrated prior
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT match_id, rating, rd FROM match_ratings WHERE player_id = 1 AND rating_type = 'total' ORDER BY match_id ASC"
        )
        rows = cursor.fetchall()
        self.assertEqual(len(rows), 16)
        calibrated_r = priors[1][TOTAL]["rating"]
        # Match 15 (0-indexed 14) pre-match snapshot was calibrated prior
        self.assertAlmostEqual(rows[14]["rating"], calibrated_r, places=3)

    def test_retro_calibrated_false_fallback(self):
        """retro_calibrated=False runs classic 1-pass execution for backwards compatibility."""
        create_player(self.conn, 1)
        add_alias(self.conn, "P1", 1)
        create_player(self.conn, 2)
        add_alias(self.conn, "P2", 2)

        create_match(self.conn, "single-1", "2026-03-01", "box", 1, 1, 10, 5)
        add_match_player(self.conn, "single-1", 1, "a")
        add_match_player(self.conn, "single-1", 2, "b")

        recalculate_glicko2_ratings(self.conn, create_backup=False, retro_calibrated=False)

        cursor = self.conn.cursor()
        cursor.execute("SELECT rating, rd FROM ratings WHERE player_id = 1 AND rating_type = 'total'")
        row = cursor.fetchone()
        self.assertIsNotNone(row)
        self.assertGreater(row["rating"], DEFAULT_RATING)


class TestLeaderboardViewModelProvisionalFlags(unittest.TestCase):
    def test_build_leaderboard_provisional_enrichment(self):
        """Leaderboard properly tags provisional and calibrated players."""
        ratings = {
            1: {
                "total": {"rating": 1650.0, "rd": 80.0},
                "box": {"rating": 1650.0, "rd": 80.0},
                "hf": {"rating": 1650.0, "rd": 80.0},
            },
            2: {
                "total": {"rating": 1520.0, "rd": 200.0},
                "box": {"rating": 1520.0, "rd": 200.0},
                "hf": {"rating": 1520.0, "rd": 200.0},
            },
        }
        players = {
            1: {"aliases": ["Veteran"]},
            2: {"aliases": ["Rookie"]},
        }
        stats = {
            1: {"total": {"games": 18}},
            2: {"total": {"games": 5}},
        }
        calibrated_priors = {
            1: {TOTAL: {"rating": 1640.0, "rd": 85.0, "sigma": 0.06, "threshold": 15}},
        }

        leaderboard = build_leaderboard(
            ratings, players, stats, calibrated_priors=calibrated_priors
        )

        self.assertEqual(len(leaderboard), 2)
        vet = next(p for p in leaderboard if p["player_id"] == 1)
        rookie = next(p for p in leaderboard if p["player_id"] == 2)

        # Veteran has 18 games and threshold 15 -> calibrated
        self.assertTrue(vet["is_calibrated"])
        self.assertFalse(vet["is_provisional"])
        self.assertEqual(vet["calibration_threshold"], 15)
        self.assertEqual(vet["calibration_progress"], 15)

        # Rookie has 5 games and threshold 15 -> provisional
        self.assertFalse(rookie["is_calibrated"])
        self.assertTrue(rookie["is_provisional"])
        self.assertEqual(rookie["calibration_threshold"], 15)
        self.assertEqual(rookie["calibration_progress"], 5)


if __name__ == "__main__":
    unittest.main()
