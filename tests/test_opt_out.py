import os
from pathlib import Path
import tempfile
import time
import unittest

from scripts.accounts.auth import register_user, get_user, pass_psychology_test
from scripts.accounts.database import (
    get_accounts_connection,
    mark_email_verified,
    approve_user,
    link_user_to_player,
    update_user_profile,
    get_opted_out_player_ids,
)
from web.app import create_app
from web.services.security import Tier, get_actual_tier


class GlickoOptOutTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_accounts_db = Path(self.temp_dir.name) / "test_accounts.db"
        os.environ["RB48_ACCOUNTS_DATABASE_FILE"] = str(self.test_accounts_db)

        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def tearDown(self):
        os.environ.pop("RB48_ACCOUNTS_DATABASE_FILE", None)
        self.temp_dir.cleanup()

    def create_user(self, role="user", verified=True, approved=True, psychology_passed=True, player_id=None, opt_out=0):
        unique_name = f"opt_usr_{int(time.time() * 1000000)}"
        email = f"{unique_name}@example.com"
        user_id, _ = register_user(unique_name, email, "password123", role=role)

        conn = get_accounts_connection()
        try:
            if verified:
                mark_email_verified(conn, user_id)
            if approved or role in ("admin", "webmaster"):
                approve_user(conn, user_id, approved=True)
            if player_id:
                link_user_to_player(conn, user_id, player_id)
            if opt_out:
                update_user_profile(conn, user_id, glicko_opt_out=1)
        finally:
            conn.close()

        if psychology_passed:
            pass_psychology_test(user_id)

        return get_user(user_id)

    def test_settings_profile_toggle_opt_out(self):
        user = self.create_user(verified=True, approved=True, psychology_passed=True, opt_out=0)
        self.assertEqual(user["glicko_opt_out"], 0)
        self.assertEqual(get_actual_tier(user), Tier.GLICKO_USER)

        with self.client.session_transaction() as sess:
            sess["user_id"] = user["id"]

        # POST to toggle opt-out ON
        resp = self.client.post("/settings/profile", data={
            "attendance_name": "TestPlayer",
            "glicko_opt_out": "1",
        }, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)

        updated = get_user(user["id"])
        self.assertEqual(updated["glicko_opt_out"], 1)
        self.assertEqual(get_actual_tier(updated), Tier.USER)

        # POST without glicko_opt_out -> toggles OFF
        resp2 = self.client.post("/settings/profile", data={
            "attendance_name": "TestPlayer",
        }, follow_redirects=True)
        self.assertEqual(resp2.status_code, 200)

        restored = get_user(user["id"])
        self.assertEqual(restored["glicko_opt_out"], 0)
        self.assertEqual(get_actual_tier(restored), Tier.GLICKO_USER)

    def test_opted_out_player_ids_helper(self):
        u1 = self.create_user(player_id=1, opt_out=1)
        u2 = self.create_user(player_id=2, opt_out=0)

        conn = get_accounts_connection()
        try:
            opted_out = get_opted_out_player_ids(conn)
            self.assertIn(1, opted_out)
            self.assertNotIn(2, opted_out)
        finally:
            conn.close()

    def test_stats_leaderboard_masking_and_sorting(self):
        # Link user 1 to player 1 and opt out
        self.create_user(player_id=1, opt_out=1)

        # Viewer is a Glicko user (not webmaster)
        viewer = self.create_user(role="user", psychology_passed=True, opt_out=0)
        with self.client.session_transaction() as sess:
            sess["user_id"] = viewer["id"]

        resp = self.client.get("/stats")
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode("utf-8")

        # Player 1 row should have data-opted-out="true"
        self.assertIn('data-opted-out="true"', html)

        # Webmaster sees 🔒 Opt-out
        wm = self.create_user(role="webmaster")
        with self.client.session_transaction() as sess:
            sess["user_id"] = wm["id"]

        wm_resp = self.client.get("/stats")
        self.assertEqual(wm_resp.status_code, 200)
        wm_html = wm_resp.data.decode("utf-8")
        self.assertIn("🔒 Opt-out", wm_html)

    def test_match_history_rating_masking(self):
        self.create_user(player_id=1, opt_out=1)
        viewer = self.create_user(role="user", psychology_passed=True, opt_out=0)
        with self.client.session_transaction() as sess:
            sess["user_id"] = viewer["id"]

        resp = self.client.get("/matches")
        self.assertEqual(resp.status_code, 200)

    def test_player_profile_opt_out_view(self):
        self.create_user(player_id=1, opt_out=1)
        viewer = self.create_user(role="user", psychology_passed=True, opt_out=0)
        with self.client.session_transaction() as sess:
            sess["user_id"] = viewer["id"]

        resp = self.client.get("/player/1")
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode("utf-8")
        self.assertTrue("deaktiviert" in html or "opted out" in html)
        self.assertNotIn("totalChart", html)

    def test_api_players_list_masks_opted_out_ratings(self):
        self.create_user(player_id=1, opt_out=1)
        viewer = self.create_user(role="user", psychology_passed=True, opt_out=0)
        with self.client.session_transaction() as sess:
            sess["user_id"] = viewer["id"]

        resp = self.client.get("/api/players-list")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        p1 = next((p for p in data if p["id"] == 1), None)
        if p1:
            self.assertIsNone(p1["rating"])

    def test_faq_opt_out_reference_for_visitor(self):
        resp = self.client.get("/glickofaq")
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode("utf-8")
        self.assertIn("faq-opt-out", html)
        self.assertIn("/settings", html)
        self.assertIn("Performance-Analyse", html)
        self.assertIn("Glicko Opt-Out", html)

    def test_faq_opt_out_reference_for_standard_user(self):
        user = self.create_user(role="user", psychology_passed=False, opt_out=0)
        with self.client.session_transaction() as sess:
            sess["user_id"] = user["id"]

        resp = self.client.get("/glickofaq")
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode("utf-8")
        self.assertIn("faq-opt-out", html)
        self.assertIn("/settings", html)
        self.assertIn("Privatsphäre", html)
        # Check that members tab also has opt-out reference
        self.assertIn("Glicko-2 Opt-Out", html)

    def test_faq_opt_out_reference_for_opted_out_user(self):
        user = self.create_user(role="user", psychology_passed=True, opt_out=1)
        with self.client.session_transaction() as sess:
            sess["user_id"] = user["id"]

        resp = self.client.get("/glickofaq")
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode("utf-8")
        self.assertIn("Opt-Out aktiv", html)
        self.assertIn("/settings", html)

    def test_faq_opt_out_reference_in_english(self):
        resp = self.client.get("/set-language/en?next=/glickofaq", follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode("utf-8")
        self.assertIn("Can I hide my performance analysis and rating? (Glicko Opt-Out)", html)
        self.assertIn("Profile Settings", html)
        self.assertIn("/settings", html)


if __name__ == "__main__":
    unittest.main()
