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
    unlink_player,
    set_user_access_level,
)
from web.app import create_app
from web.services.security import Tier, get_actual_tier


class AdminUserManagementTest(unittest.TestCase):
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

    def create_user(self, role="user", verified=True, approved=True, psychology_passed=False, player_id=None):
        unique_name = f"adm_usr_{int(time.time() * 1000000)}"
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
        finally:
            conn.close()

        if psychology_passed:
            pass_psychology_test(user_id)

        return get_user(user_id)

    def test_unlink_player_db_function(self):
        user = self.create_user(player_id=5)
        self.assertEqual(user["player_id"], 5)

        conn = get_accounts_connection()
        try:
            unlink_player(conn, user["id"])
        finally:
            conn.close()

        updated = get_user(user["id"])
        self.assertIsNone(updated["player_id"])
        self.assertIsNone(updated["pending_player_id"])

    def test_set_user_access_level_db_function(self):
        user = self.create_user(role="user", verified=True, approved=True, psychology_passed=False)
        self.assertEqual(get_actual_tier(user), Tier.USER)

        conn = get_accounts_connection()
        try:
            # Promote to glicko_user
            set_user_access_level(conn, user["id"], "glicko_user")
            self.assertEqual(get_actual_tier(get_user(user["id"])), Tier.GLICKO_USER)

            # Promote to admin
            set_user_access_level(conn, user["id"], "admin")
            self.assertEqual(get_actual_tier(get_user(user["id"])), Tier.ADMIN)

            # Promote to webmaster
            set_user_access_level(conn, user["id"], "webmaster")
            self.assertEqual(get_actual_tier(get_user(user["id"])), Tier.WEBMASTER)

            # Demote to visitor
            set_user_access_level(conn, user["id"], "visitor")
            self.assertEqual(get_actual_tier(get_user(user["id"])), Tier.VISITOR)

            # Demote/set to standard user
            set_user_access_level(conn, user["id"], "user")
            self.assertEqual(get_actual_tier(get_user(user["id"])), Tier.USER)

            # Invalid access level raises ValueError
            with self.assertRaises(ValueError):
                set_user_access_level(conn, user["id"], "superman")
        finally:
            conn.close()

    def test_admin_users_view_renders_table(self):
        wm = self.create_user(role="webmaster")
        target = self.create_user(role="user", player_id=2)

        with self.client.session_transaction() as sess:
            sess["user_id"] = wm["id"]

        resp = self.client.get("/admin/users")
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode("utf-8")
        self.assertIn("Access Level", html)
        self.assertIn(target["username"], html)
        self.assertIn("name=\"access_level\"", html)
        self.assertIn("Aufheben", html)

    def test_webmaster_unlink_player_route(self):
        wm = self.create_user(role="webmaster")
        target = self.create_user(role="user", player_id=3)
        self.assertEqual(target["player_id"], 3)

        with self.client.session_transaction() as sess:
            sess["user_id"] = wm["id"]

        resp = self.client.post(
            f"/admin/users/{target['id']}/player-link",
            data={"action": "unlink"},
            follow_redirects=True,
        )
        self.assertEqual(resp.status_code, 200)

        updated = get_user(target["id"])
        self.assertIsNone(updated["player_id"])

    def test_webmaster_assign_player_route(self):
        wm = self.create_user(role="webmaster")
        target = self.create_user(role="user", player_id=None)
        self.assertIsNone(target["player_id"])

        with self.client.session_transaction() as sess:
            sess["user_id"] = wm["id"]

        # Assign player 4
        resp = self.client.post(
            f"/admin/users/{target['id']}/assign-player",
            data={"player_id": "4"},
            follow_redirects=True,
        )
        self.assertEqual(resp.status_code, 200)

        updated = get_user(target["id"])
        self.assertEqual(updated["player_id"], 4)

        # Clear assignment by submitting empty player_id
        resp2 = self.client.post(
            f"/admin/users/{target['id']}/assign-player",
            data={"player_id": ""},
            follow_redirects=True,
        )
        self.assertEqual(resp2.status_code, 200)

        updated2 = get_user(target["id"])
        self.assertIsNone(updated2["player_id"])

    def test_webmaster_update_access_level_route(self):
        wm = self.create_user(role="webmaster")
        target = self.create_user(role="user", verified=True, approved=True)

        with self.client.session_transaction() as sess:
            sess["user_id"] = wm["id"]

        # Change to glicko_user
        resp = self.client.post(
            f"/admin/users/{target['id']}/access-level",
            data={"access_level": "glicko_user"},
            follow_redirects=True,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(get_actual_tier(get_user(target["id"])), Tier.GLICKO_USER)

        # Change to admin
        resp = self.client.post(
            f"/admin/users/{target['id']}/access-level",
            data={"access_level": "admin"},
            follow_redirects=True,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(get_actual_tier(get_user(target["id"])), Tier.ADMIN)

        # Change to visitor
        resp = self.client.post(
            f"/admin/users/{target['id']}/access-level",
            data={"access_level": "visitor"},
            follow_redirects=True,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(get_actual_tier(get_user(target["id"])), Tier.VISITOR)

    def test_webmaster_self_demotion_prevention(self):
        wm = self.create_user(role="webmaster")

        with self.client.session_transaction() as sess:
            sess["user_id"] = wm["id"]

        resp = self.client.post(
            f"/admin/users/{wm['id']}/access-level",
            data={"access_level": "user"},
            follow_redirects=True,
        )
        self.assertEqual(resp.status_code, 200)
        # Webmaster tier must remain unchanged
        self.assertEqual(get_actual_tier(get_user(wm["id"])), Tier.WEBMASTER)
        html = resp.data.decode("utf-8")
        self.assertIn("cannot demote your own active Webmaster account", html)


if __name__ == "__main__":
    unittest.main()
