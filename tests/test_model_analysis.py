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
    analyze_whr_model,
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
        baskets = _calibration_baskets(observations, basket_count=10)
        self.assertEqual(len(baskets), 3)
        # Basket 1: 50.0% – 53.0%
        self.assertEqual(baskets[0]["label"], "50.0% – 53.0%")
        self.assertEqual(baskets[0]["count"], 1)
        self.assertAlmostEqual(baskets[0]["predicted"], 0.52)
        self.assertAlmostEqual(baskets[0]["actual"], 1.0)
        self.assertAlmostEqual(baskets[0]["avg_goal_diff"], 4.0)

        # Basket 2: 53.0% – 58.0%
        self.assertEqual(baskets[1]["label"], "53.0% – 58.0%")
        self.assertEqual(baskets[1]["count"], 1)
        self.assertAlmostEqual(baskets[1]["predicted"], 0.54)
        self.assertAlmostEqual(baskets[1]["actual"], 0.0)
        self.assertAlmostEqual(baskets[1]["avg_goal_diff"], 2.0)

        # Basket 3: 58.0% – 75.0%
        self.assertEqual(baskets[2]["label"], "58.0% – 75.0%")
        self.assertEqual(baskets[2]["count"], 1)
        self.assertAlmostEqual(baskets[2]["predicted"], 0.62)
        self.assertAlmostEqual(baskets[2]["actual"], 1.0)
        self.assertAlmostEqual(baskets[2]["avg_goal_diff"], 7.5)

        # Test with 13 observations (deciles)
        obs_13 = [
            {"prediction": 0.50 + i * 0.02, "actual": 1.0 if i % 2 == 0 else 0.0, "goal_diff": float(i)}
            for i in range(13)
        ]
        baskets_13 = _calibration_baskets(obs_13, basket_count=10)
        self.assertEqual(len(baskets_13), 10)
        self.assertEqual(sum(b["count"] for b in baskets_13), 13)
        for b in baskets_13:
            self.assertIn("–", b["label"])
            self.assertGreater(b["count"], 0)

    def test_goal_diff_distribution(self):
        observations = [
            {"pitch": "box", "raw_goal_diff": -4},  # fav lost by 4
            {"pitch": "box", "raw_goal_diff": 2},   # fav won by 2
            {"pitch": "box", "raw_goal_diff": 2},   # fav won by 2
            {"pitch": "hf", "raw_goal_diff": 3},    # fav won by 3
        ]
        dist, totals = _goal_diff_distribution(observations)
        self.assertEqual(totals["box"], 3)
        self.assertEqual(totals["hf"], 1)

        box_rows = dist["box"]
        self.assertEqual(len(box_rows), 2)
        self.assertEqual(box_rows[0]["goal_diff"], -4)
        self.assertEqual(box_rows[0]["count"], 1)
        self.assertAlmostEqual(box_rows[0]["share"], 33.3333333, places=4)
        self.assertEqual(box_rows[1]["goal_diff"], 2)
        self.assertEqual(box_rows[1]["count"], 2)
        self.assertAlmostEqual(box_rows[1]["share"], 66.6666666, places=4)

    def test_linear_trend_extrapolation(self):
        observations = [
            {"prediction": 0.52 + i * 0.02, "actual": 1.0 if i % 2 == 0 else 0.0, "goal_diff": 2.0 * i - 4.0}
            for i in range(11)
        ]
        curve = _lowess(observations, value_key="goal_diff", points=21, min_val=-10.0, max_val=10.0)
        self.assertEqual(len(curve), 21)
        # Linear trendline cleanly spans the probability range [0.5, 1.0]
        self.assertAlmostEqual(curve[0]["predicted"], 0.50)
        self.assertAlmostEqual(curve[-1]["predicted"], 1.00)

    def test_analyze_model_total_vs_pitch_scaling(self):
        conn = get_connection()
        try:
            # Total mode: HF games scaled to 10 goals for winner
            res_total = analyze_model(conn, mode=TOTAL)
            self.assertIn("calibration", res_total)
            self.assertIn("goal_diff_lowess", res_total)
            self.assertIn("goal_diff_reference", res_total)
            self.assertIn("expected_accuracy", res_total)
            self.assertIsNotNone(res_total["expected_accuracy"])
            self.assertEqual(res_total["goal_diff_max"], 10)
            self.assertIn("goal_diff_min", res_total)
            self.assertIn(0, res_total["goal_diff_ticks"])

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

        pos_goal_diff = html.find('aria-label="Durchschnittliche Tordifferenz des Favoriten"')
        if pos_goal_diff == -1:
            pos_goal_diff = html.find('aria-label="Average favourite goal difference graph"')
        self.assertNotEqual(pos_goal_diff, -1)

        pos_goal_diff_table = html.find('class="analysis-table goal-diff-table"')
        self.assertNotEqual(pos_goal_diff_table, -1)

        # Verify exact order: Fav win SVG -> Calibration table -> Goal diff SVG -> Goal diff table
        self.assertLess(pos_fav_win, pos_calib_table, "Favourite win chart must precede calibration table")
        self.assertLess(pos_calib_table, pos_goal_diff, "Calibration table must precede goal difference chart")
        self.assertLess(pos_goal_diff, pos_goal_diff_table, "Goal difference chart must precede goal difference table")

        # Verify hover explanation for scaled HF matches
        self.assertIn("HF", html)
        self.assertIn("skaliert", html)

        # Verify metric explainer collapsible details and benchmarks
        self.assertIn("metric-explainer-details", html)
        self.assertIn("5.0%", html)
        self.assertIn("0.6931", html)
        self.assertIn("0.5000", html)

    def test_analyze_whr_model(self):
        conn = get_connection()
        try:
            res = analyze_whr_model(conn, mode="whr", pitch="total")
            self.assertEqual(res["mode"], "whr")
            self.assertGreater(res["games"], 0)
            self.assertIn("ece", res)
            self.assertIn("log_loss", res)
            self.assertIn("mean_absolute_error", res)
            self.assertIn("accuracy", res)
            self.assertIn("calibration", res)
            self.assertIn("lowess", res)
            self.assertIn("goal_diff_lowess", res)
            self.assertIn("goal_diff_min", res)
            self.assertIn("goal_diff_max", res)
            self.assertIn("goal_diff_ticks", res)
        finally:
            conn.close()

    def test_whr_model_analysis_page_structure_and_overlay(self):
        user_id = self.create_user_session(role="user", verified=True, approved=True, psychology_passed=True)
        with self.client.session_transaction() as sess:
            sess["user_id"] = user_id

        resp = self.client.get("/model-analysis?mode=whr&pitch=total")
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)

        # 5 KPI cards present
        self.assertIn("Kalibrierungsfehler", html)
        self.assertIn("Log-Loss", html)
        self.assertIn("Mittlerer absoluter Fehler", html)
        self.assertIn("Favoritensiege", html)
        self.assertIn("Analysierte Spiele", html)

        # Explainer accordion present
        self.assertIn("metric-explainer-details", html)

        # Graph comparison overlay switch button present
        self.assertIn("btn-graph-toggle", html)
        self.assertIn("Vergleichsmodell einblenden", html)

        # Overlay series present in SVG
        self.assertIn("comparison-series", html)
        self.assertIn("primary-series", html)

        # Link to dedicated rating comparison page present
        self.assertIn("/rating-comparison", html)

    def test_rating_comparison_page(self):
        user_id = self.create_user_session(role="user", verified=True, approved=True, psychology_passed=True)
        with self.client.session_transaction() as sess:
            sess["user_id"] = user_id

        for url in ("/rating-comparison", "/model-comparison"):
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 200)
            html = resp.get_data(as_text=True)

            self.assertIn("Modellvergleich: Glicko-2 vs. WHR", html)
            self.assertIn("Verglichene Spieler", html)
            self.assertIn("Größtes WHR-Plus", html)
            self.assertIn("Größtes WHR-Minus", html)
            self.assertIn("Ø Absolute Abweichung", html)
            self.assertIn("comparison-table", html)
            self.assertIn("comparison-player-search", html)

            # Test pitch filter
            resp_box = self.client.get(f"{url}?pitch=box")
            self.assertEqual(resp_box.status_code, 200)
            self.assertIn("BOX", resp_box.get_data(as_text=True))

    def test_navigation_structure_and_pitch_switching(self):
        user_id = self.create_user_session(role="user", verified=True, approved=True, psychology_passed=True)
        with self.client.session_transaction() as sess:
            sess["user_id"] = user_id

        # 1. Default page should show Glicko-2 active, TOTAL active
        resp = self.client.get("/model-analysis")
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn("analysis-switch", html)
        self.assertIn("pitch-switch", html)
        self.assertIn("Glicko-2", html)
        self.assertIn("WHR", html)
        self.assertIn("TOTAL", html)
        self.assertIn("BOX", html)
        self.assertIn("HF", html)

        # 2. Glicko BOX
        resp_g_box = self.client.get("/model-analysis?model=glicko&pitch=box")
        self.assertEqual(resp_g_box.status_code, 200)
        html_g_box = resp_g_box.get_data(as_text=True)
        self.assertIn("Modell: Glicko-2 (BOX)", html_g_box)

        # 3. WHR TOTAL
        resp_whr_total = self.client.get("/model-analysis?model=whr&pitch=total")
        self.assertEqual(resp_whr_total.status_code, 200)
        html_whr_total = resp_whr_total.get_data(as_text=True)
        self.assertIn("Modell: Whole-History Rating (TOTAL)", html_whr_total)

        # 4. WHR HF
        resp_whr_hf = self.client.get("/model-analysis?model=whr&pitch=hf")
        self.assertEqual(resp_whr_hf.status_code, 200)
        html_whr_hf = resp_whr_hf.get_data(as_text=True)
        self.assertIn("Modell: Whole-History Rating (HF)", html_whr_hf)


if __name__ == "__main__":
    unittest.main()
