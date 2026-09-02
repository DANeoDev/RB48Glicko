import time
import unittest

from scripts.accounts.auth import pass_psychology_test, register_user
from scripts.accounts.database import approve_user, get_accounts_connection, mark_email_verified, update_user_role
from web.app import app


class RouteTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

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


if __name__ == "__main__":
    unittest.main()
