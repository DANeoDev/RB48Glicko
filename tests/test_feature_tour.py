import os
import tempfile
import unittest
from pathlib import Path

from scripts.accounts.auth import register_user, get_user
from scripts.accounts.database import (
    mark_email_verified,
    approve_user,
    get_accounts_connection,
)
from web.app import create_app


class FeatureTourTest(unittest.TestCase):
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

    def create_test_user(self, role="user", verified=True, approved=True):
        user_id, _ = register_user("tour_tester", "tour@example.com", "password123", role=role)
        conn = get_accounts_connection()
        try:
            if verified:
                mark_email_verified(conn, user_id)
            if approved:
                approve_user(conn, user_id, approved=True)
        finally:
            conn.close()
        return get_user(user_id)

    def test_tour_static_assets(self):
        """Verify feature_tour.css and feature_tour.js are present and served correctly."""
        resp_css = self.client.get("/static/feature_tour.css")
        self.assertEqual(resp_css.status_code, 200)
        self.assertIn("rb48-tour-card", resp_css.data.decode("utf-8"))

        resp_js = self.client.get("/static/feature_tour.js")
        self.assertEqual(resp_js.status_code, 200)
        js_content = resp_js.data.decode("utf-8")
        self.assertIn("RB48Tour", js_content)
        self.assertIn("TOUR_STEPS", js_content)
        self.assertIn("positions", js_content)
        self.assertIn("glicko_opt_out", js_content)
        self.assertIn("stats_opt_out", js_content)

    def test_tour_links_rendered_in_base_template(self):
        """Verify feature tour trigger is rendered in profile dropdown for visitors and users."""
        # 1. Visitor view
        resp_vis = self.client.get("/")
        self.assertEqual(resp_vis.status_code, 200)
        html_vis = resp_vis.data.decode("utf-8")
        self.assertIn("feature_tour.css", html_vis)
        self.assertIn("feature_tour.js", html_vis)
        self.assertIn("RB48Tour.start(0)", html_vis)

        # 2. Authenticated user view
        user = self.create_test_user()
        with self.client.session_transaction() as sess:
            sess["user_id"] = user["id"]

        resp_user = self.client.get("/settings")
        self.assertEqual(resp_user.status_code, 200)
        html_user = resp_user.data.decode("utf-8")
        self.assertIn("RB48Tour.start(0)", html_user)

    def test_tour_target_elements_exist_on_pages(self):
        """Verify target elements and container IDs exist across destination pages."""
        user = self.create_test_user()
        with self.client.session_transaction() as sess:
            sess["user_id"] = user["id"]

        # 1. /stats targets
        resp_stats = self.client.get("/stats")
        self.assertEqual(resp_stats.status_code, 200)
        html_stats = resp_stats.data.decode("utf-8")
        self.assertIn('id="leaderboard"', html_stats)
        self.assertIn("stats-table-header", html_stats)

        # 2. /stats/mvp-medals targets
        resp_medals = self.client.get("/stats/mvp-medals")
        self.assertEqual(resp_medals.status_code, 200)
        html_medals = resp_medals.data.decode("utf-8")
        self.assertIn("medals-table-container", html_medals)

        # 3. /settings targets
        resp_settings = self.client.get("/settings")
        self.assertEqual(resp_settings.status_code, 200)
        html_settings = resp_settings.data.decode("utf-8")
        self.assertIn('id="glicko-assessment-card"', html_settings)
        self.assertIn('id="glicko-opt-out-box"', html_settings)
        self.assertIn('id="stats-opt-out-box"', html_settings)

        # 4. /glickofaq targets
        resp_faq = self.client.get("/glickofaq")
        self.assertEqual(resp_faq.status_code, 200)
        html_faq = resp_faq.data.decode("utf-8")
        self.assertIn('id="faq-content"', html_faq)


if __name__ == "__main__":
    unittest.main()
