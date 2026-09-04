"""Tests for model analysis, goal difference scaling, and template rendering."""

import os
from pathlib import Path
import shutil
import tempfile
import time
import unittest

from scripts.accounts.auth import pass_psychology_test, register_user
from scripts.accounts.database import approve_user, get_accounts_connection, mark_email_verified, update_user_role
from scripts.analysis.model_analysis import (
    _calibration_baskets,
    _goal_diff_distribution,
    _lowess,
    analyze_model,
)
from scripts.database.database import get_connection
from scripts.glicko.glicko2 import BOX, HF, TOTAL
from web.app import app


class TestModelAnalysis(unittest.TestCase):
    """Test suite for pre-match model evaluation and calibration."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_accounts_db = Path(self.temp_dir.name) / "test_accounts.db"
        self.test_rb48_db = Path(self.temp_dir.name) / "test_rb48.db"
        prod_rb48 = Path(__file__).resolve().parents[1] / "data" / "rb48.db"
        if prod_rb48.exists():
            shutil.copy2(prod_rb48, self.test_rb48_db)
        os.environ["RB48_ACCOUNTS_DATABASE_FILE"] = str(self.test_accounts_db)
        os.environ["RB48_DATABASE_FILE"] = str(self.test_rb48_db)
        self.client = app.test_client()

    def tearDown(self):
        os.environ.pop("RB48_ACCOUNTS_DATABASE_FILE", None)
        os.environ.pop("RB48_DATABASE_FILE", None)
        self.temp_dir.cleanup()

    def create_user_session(self, role="user", verified=True, approved=True, psychology_passed=True):
        unique_name = f"ma_user_{int(time.time() * 1000000)}"
        email = f"{unique_name}@example.com"
        user_id, _ = register_user(unique_name, email, "password123", role=role)

        connection = get_accounts_connection()
        try:
            if verified:
                mark_email_verified(connection, user_id)
            if approved or role in ("admin", "webmaster"):
                approve_user(connection, user_id, approved=True)
            if role != "user":
                update_user_role(connection, user_id, role)
        finally:
            connection.close()

        if psychology_passed:
            pass_psychology_test(user_id)

        return user_id

    def test_calibration_baskets_and_scaled_goal_diff(self):
        observations = [
            {"prediction": 0.52, "actual": 1.0, "goal_diff": 4.0},
            {"prediction": 0.54, "actual": 0.0, "goal_diff": 2.0},
            {"prediction": 0.62, "actual": 1.0, "goal_diff": 7.5},
        ]
        baskets = _calibration_baskets(observations, step=0.05)
        self.assertEqual(len(baskets), 2)
        # Basket 1: 50% - 55%
        self.assertEqual(baskets[0]["label"], "50% – 55%")
        self.assertEqual(baskets[0]["count"], 2)
        self.assertAlmostEqual(baskets[0]["predicted"], 0.53)
        self.assertAlmostEqual(baskets[0]["actual"], 0.5)
        self.assertAlmostEqual(baskets[0]["avg_goal_diff"], 3.0)

        # Basket 2: 60% - 65%
        self.assertEqual(baskets[1]["label"], "60% – 65%")
        self.assertEqual(baskets[1]["count"], 1)
        self.assertAlmostEqual(baskets[1]["predicted"], 0.62)
        self.assertAlmostEqual(baskets[1]["actual"], 1.0)
        self.assertAlmostEqual(baskets[1]["avg_goal_diff"], 7.5)

    def test_goal_diff_distribution(self):
        matches = [
            {"pitch": "box", "goals_a": 10, "goals_b": 6},  # diff 4
            {"pitch": "box", "goals_a": 10, "goals_b": 8},  # diff 2
            {"pitch": "box", "goals_a": 10, "goals_b": 8},  # diff 2
            {"pitch": "hf", "goals_a": 4, "goals_b": 1},   # diff 3
        ]
        dist, totals = _goal_diff_distribution(matches)
        self.assertEqual(totals["box"], 3)
        self.assertEqual(totals["hf"], 1)

        box_rows = dist["box"]
        self.assertEqual(len(box_rows), 2)
        self.assertEqual(box_rows[0]["goal_diff"], 2)
        self.assertEqual(box_rows[0]["count"], 2)
        self.assertAlmostEqual(box_rows[0]["share"], 66.6666666, places=4)
        self.assertEqual(box_rows[1]["goal_diff"], 4)
        self.assertEqual(box_rows[1]["count"], 1)
        self.assertAlmostEqual(box_rows[1]["share"], 33.3333333, places=4)

    def test_analyze_model_total_vs_pitch_scaling(self):
        conn = get_connection()
        try:
            # Total mode: HF games scaled to 10 goals for winner
            res_total = analyze_model(conn, mode=TOTAL)
            self.assertIn("calibration", res_total)
            self.assertIn("goal_diff_lowess", res_total)
            self.assertIn("goal_diff_reference", res_total)
            self.assertEqual(res_total["goal_diff_max"], 10)
            self.assertEqual(res_total["goal_diff_ticks"], [0, 2, 4, 6, 8, 10])

            # Pitch mode for BOX
            res_box = analyze_model(conn, mode="pitch", pitch=BOX)
            self.assertEqual(res_box["pitch"], BOX)

            # Pitch mode for HF
            res_hf = analyze_model(conn, mode="pitch", pitch=HF)
            self.assertEqual(res_hf["pitch"], HF)
        finally:
            conn.close()

    def test_model_analysis_page_layout_order(self):
        user_id = self.create_user_session(role="user", verified=True, approved=True, psychology_passed=True)
        with self.client.session_transaction() as sess:
            sess["user_id"] = user_id

        resp = self.client.get("/model-analysis")
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)

        pos_fav_win = html.find('aria-label="Kalibrierung des Favoritensiegs"')
        if pos_fav_win == -1:
            pos_fav_win = html.find('aria-label="Favourite win calibration graph"')
        self.assertNotEqual(pos_fav_win, -1)

        pos_calib_table = html.find('<table class="analysis-table">')
        self.assertNotEqual(pos_calib_table, -1)

        pos_goal_diff = html.find('aria-label="Durchschnittliche Tordifferenz"')
        if pos_goal_diff == -1:
            pos_goal_diff = html.find('aria-label="Average goal difference graph"')
        self.assertNotEqual(pos_goal_diff, -1)

        pos_ref_table = html.find('class="analysis-table reference-table"')
        self.assertNotEqual(pos_ref_table, -1)

        # Verify exact order: Fav win SVG -> Calibration table -> Goal diff SVG -> Reference table
        self.assertLess(pos_fav_win, pos_calib_table, "Favourite win chart must precede calibration table")
        self.assertLess(pos_calib_table, pos_goal_diff, "Calibration table must precede goal difference chart")
        self.assertLess(pos_goal_diff, pos_ref_table, "Goal difference chart must precede distribution reference table")

        # Verify hover explanation for scaled HF matches
        self.assertIn("HF", html)
        self.assertIn("skaliert", html)

        # Verify metric explainer collapsible details and benchmarks
        self.assertIn("metric-explainer-details", html)
        self.assertIn("0.2500", html)
        self.assertIn("0.6931", html)
        self.assertIn("0.5000", html)


if __name__ == "__main__":
    unittest.main()
