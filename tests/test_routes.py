import os
from pathlib import Path
import shutil
import tempfile
import time
import unittest

from scripts.accounts.auth import pass_psychology_test, register_user
from scripts.accounts.database import approve_user, get_accounts_connection, mark_email_verified, update_user_role
from web.app import app


class RouteTests(unittest.TestCase):
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
        unique_name = f"rt_user_{int(time.time() * 1000000)}"
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

    def test_public_routes_render(self):
        public_routes = [
            "/",
            "/dashboard",
            "/matches",
            "/glickofaq",
            "/about",
            "/login",
            "/register",
            "/resend-verification",
        ]
        for route in public_routes:
            with self.subTest(route=route):
                response = self.client.get(route)
                self.assertEqual(response.status_code, 200)

    def test_protected_routes_redirect_unauthenticated(self):
        # Visitor trying to access stats, model analysis, or match center
        resp_stats = self.client.get("/stats")
        self.assertEqual(resp_stats.status_code, 302)

        resp_model = self.client.get("/model-analysis")
        self.assertEqual(resp_model.status_code, 302)

        resp_mc = self.client.get("/match-center")
        self.assertEqual(resp_mc.status_code, 302)

    def test_authenticated_approved_user_can_access_stats(self):
        user_id = self.create_user_session(role="user", verified=True, approved=True, psychology_passed=False)
        with self.client.session_transaction() as sess:
            sess["user_id"] = user_id

        resp_stats = self.client.get("/stats")
        self.assertEqual(resp_stats.status_code, 200)
        stats_html = resp_stats.get_data(as_text=True)
        self.assertIn("time-rail-title-badge", stats_html)
        self.assertIn("Rating<br>Geschichte", stats_html)

        # Check matches timeline top scroll button
        resp_matches = self.client.get("/matches")
        self.assertEqual(resp_matches.status_code, 200)
        self.assertIn("Nach oben scrollen", resp_matches.get_data(as_text=True))

        # But cannot access model analysis yet (requires psychology test)
        resp_model = self.client.get("/model-analysis")
        self.assertEqual(resp_model.status_code, 302)

    def test_authenticated_glicko_user_access(self):
        user_id = self.create_user_session(role="user", verified=True, approved=True, psychology_passed=True)
        with self.client.session_transaction() as sess:
            sess["user_id"] = user_id

        # Glicko user can access stats and model analysis
        resp_stats = self.client.get("/stats")
        self.assertEqual(resp_stats.status_code, 200)

        resp = self.client.get("/model-analysis")
        self.assertEqual(resp.status_code, 200)

        # But Glicko user cannot access Match Center (Admin only)
        resp_mc = self.client.get("/match-center")
        self.assertEqual(resp_mc.status_code, 302)

    def test_admin_access(self):
        admin_id = self.create_user_session(role="admin", verified=True, approved=True, psychology_passed=True)
        with self.client.session_transaction() as sess:
            sess["user_id"] = admin_id

        resp = self.client.get("/match-center")
        self.assertEqual(resp.status_code, 200)

    def test_news_pagination_api(self):
        response = self.client.get("/news/items?offset=0&limit=2")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIn("news", data)
        self.assertIn("has_more", data)

    def test_stats_page_renders_delta_selector_and_data_attributes(self):
        user_id = self.create_user_session(role="user", verified=True, approved=True, psychology_passed=True)
        with self.client.session_transaction() as sess:
            sess["user_id"] = user_id

        response = self.client.get("/stats")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("delta-mode-select", html)
        self.assertIn("delta-toggle-btn", html)
        self.assertTrue("Letztes Spiel" in html or "Last Game" in html)
        self.assertTrue("Letzter Monat" in html or "Last Month" in html)

        # Also verify player profile timeline
        resp_player = self.client.get("/player/1")
        self.assertEqual(resp_player.status_code, 200)
        self.assertIn("Nach oben scrollen", resp_player.get_data(as_text=True))
        self.assertTrue("Letztes Quartal" in html or "Last Quarter" in html)
        self.assertTrue("Letztes Jahr" in html or "Last Year" in html)
        self.assertTrue("Δ C-Rating" in html or "Δ C Rating" in html)
        self.assertTrue("Δ E-Rating" in html or "Δ E Rating" in html)
        self.assertIn("Δ RD", html)
        self.assertTrue("Δ S" in html or "Δ G" in html)
        self.assertTrue("Δ Sg" in html or "Δ W" in html)
        self.assertTrue("Δ Nd" in html or "Δ L" in html)
        self.assertTrue("Δ S%" in html or "Δ W%" in html)
        self.assertIn("data-total-delta-game-conservative", html)
        self.assertIn("data-total-delta-game-rating", html)
        self.assertIn("data-total-delta-game-rd", html)
        self.assertIn("data-total-delta-month-games", html)
        self.assertIn('const isGlickoUser = true;', html)
        self.assertIn('let currentSortColumn = isGlickoUser ? "conservative" : "games";', html)

    def test_stats_sorting_for_regular_user_defaults_to_games(self):
        user_id = self.create_user_session(role="user", verified=True, approved=True, psychology_passed=False)
        with self.client.session_transaction() as sess:
            sess["user_id"] = user_id

        response = self.client.get("/stats")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('const isGlickoUser = false;', html)
        self.assertIn('let currentSortColumn = isGlickoUser ? "conservative" : "games";', html)

    def test_match_center_create_player_ajax(self):
        admin_id = self.create_user_session(role="admin", verified=True, approved=True, psychology_passed=True)
        with self.client.session_transaction() as sess:
            sess["user_id"] = admin_id

        # First verify match center renders + Add new player button and modal
        get_res = self.client.get("/match-center")
        self.assertEqual(get_res.status_code, 200)
        self.assertTrue("+ Neuen Spieler" in get_res.get_data(as_text=True) or "+ Add new player" in get_res.get_data(as_text=True))
        self.assertIn("add-modal", get_res.get_data(as_text=True))

        # Test AJAX player creation
        import time
        unique_name = f"AjaxPlayer_{int(time.time() * 1000)}"
        post_res = self.client.post(
            "/match-center",
            data={
                "action": "create_player",
                "new_alias": unique_name,
                "new_positions": ["MID", "ATT"],
                "main_position": "ATT",
                "calibration": "average",
                "certainty": "uncertain",
                "target_team": "a",
            },
            headers={"X-Requested-With": "XMLHttpRequest"}
        )
        self.assertEqual(post_res.status_code, 200)
        data = post_res.get_json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data.get("alias"), unique_name)
        self.assertEqual(data.get("target_team"), "a")
        self.assertIn("player_id", data)


if __name__ == "__main__":
    unittest.main()
