import json
import os
from pathlib import Path
import shutil
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
        self.test_rb48_db = Path(self.temp_dir.name) / "test_rb48.db"
        prod_rb48 = Path(__file__).resolve().parents[1] / "data" / "rb48.db"
        if prod_rb48.exists():
            shutil.copy2(prod_rb48, self.test_rb48_db)
        os.environ["RB48_ACCOUNTS_DATABASE_FILE"] = str(self.test_accounts_db)
        os.environ["RB48_DATABASE_FILE"] = str(self.test_rb48_db)

        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def tearDown(self):
        os.environ.pop("RB48_ACCOUNTS_DATABASE_FILE", None)
        os.environ.pop("RB48_DATABASE_FILE", None)
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

    def test_webmaster_manual_verify_email(self):
        wm = self.create_user(role="webmaster")
        target = self.create_user(role="user", verified=False)
        self.assertFalse(target["email_verified"])

        with self.client.session_transaction() as sess:
            sess["user_id"] = wm["id"]

        # View admin_users page -> target should have verification link and manual verify button
        resp_view = self.client.get("/admin/users")
        self.assertEqual(resp_view.status_code, 200)
        html_view = resp_view.data.decode("utf-8")
        self.assertIn("verify-email-manual", html_view)

        # Execute manual verification
        resp = self.client.post(
            f"/admin/users/{target['id']}/verify-email-manual",
            follow_redirects=True,
        )
        self.assertEqual(resp.status_code, 200)
        updated = get_user(target["id"])
        self.assertEqual(updated["email_verified"], 1)

        # Non-webmaster forbidden (redirects to home)
        reg_user = self.create_user(role="user")
        with self.client.session_transaction() as sess:
            sess["user_id"] = reg_user["id"]
        resp_forbidden = self.client.post(f"/admin/users/{target['id']}/verify-email-manual")
        self.assertEqual(resp_forbidden.status_code, 302)

    def test_admin_player_aliases_tab(self):
        wm = self.create_user(role="webmaster")
        with self.client.session_transaction() as sess:
            sess["user_id"] = wm["id"]

        resp = self.client.get("/admin/users?tab=aliases")
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode("utf-8")
        self.assertIn("alias-table-body", html)
        self.assertIn("alias-filter-input", html)
        self.assertIn("alias-editor-modal", html)

        # Direct convenience route
        resp_direct = self.client.get("/admin/player-aliases")
        self.assertEqual(resp_direct.status_code, 200)

    def test_manage_player_aliases_crud_and_primary(self):
        wm = self.create_user(role="webmaster")
        with self.client.session_transaction() as sess:
            sess["user_id"] = wm["id"]

        # GET player 1 aliases
        resp = self.client.get("/admin/players/1/aliases", headers={"X-Requested-With": "XMLHttpRequest"})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("success"))
        initial_aliases = data.get("aliases", [])
        self.assertGreater(len(initial_aliases), 0)
        initial_primary = next(a["alias"] for a in initial_aliases if a["is_primary"])

        # Add new secondary alias
        test_alias = f"TestAlias_{int(time.time() * 1000)}"
        resp_add = self.client.post(
            "/admin/players/1/aliases",
            json={"action": "add", "alias": test_alias, "set_primary": False},
            headers={"X-Requested-With": "XMLHttpRequest"}
        )
        self.assertEqual(resp_add.status_code, 200)
        data_add = resp_add.get_json()
        self.assertTrue(data_add.get("success"))
        aliases_after_add = data_add.get("aliases", [])
        self.assertTrue(any(a["alias"] == test_alias and not a["is_primary"] for a in aliases_after_add))

        # Set new alias as primary
        resp_pri = self.client.post(
            "/admin/players/1/aliases",
            json={"action": "set_primary", "primary_alias": test_alias},
            headers={"X-Requested-With": "XMLHttpRequest"}
        )
        self.assertEqual(resp_pri.status_code, 200)
        data_pri = resp_pri.get_json()
        self.assertTrue(data_pri.get("success"))
        aliases_after_pri = data_pri.get("aliases", [])
        self.assertTrue(any(a["alias"] == test_alias and a["is_primary"] for a in aliases_after_pri))

        # Edit/rename the alias
        renamed_alias = f"{test_alias}_renamed"
        resp_edit = self.client.post(
            "/admin/players/1/aliases",
            json={"action": "edit", "old_alias": test_alias, "new_alias": renamed_alias},
            headers={"X-Requested-With": "XMLHttpRequest"}
        )
        self.assertEqual(resp_edit.status_code, 200)
        data_edit = resp_edit.get_json()
        self.assertTrue(data_edit.get("success"))
        aliases_after_edit = data_edit.get("aliases", [])
        self.assertTrue(any(a["alias"] == renamed_alias for a in aliases_after_edit))

        # Restore initial primary
        self.client.post(
            "/admin/players/1/aliases",
            json={"action": "set_primary", "primary_alias": initial_primary},
            headers={"X-Requested-With": "XMLHttpRequest"}
        )

        # Delete the test alias
        resp_del = self.client.post(
            "/admin/players/1/aliases",
            json={"action": "delete", "alias": renamed_alias},
            headers={"X-Requested-With": "XMLHttpRequest"}
        )
        self.assertEqual(resp_del.status_code, 200)
        data_del = resp_del.get_json()
        self.assertTrue(data_del.get("success"))
        self.assertFalse(any(a["alias"] == renamed_alias for a in data_del.get("aliases", [])))

    def test_non_webmaster_cannot_access_aliases_api(self):
        reg_user = self.create_user(role="user")
        with self.client.session_transaction() as sess:
            sess["user_id"] = reg_user["id"]

        resp_get = self.client.get("/admin/players/1/aliases")
        self.assertEqual(resp_get.status_code, 302)

        resp_post = self.client.post("/admin/players/1/aliases", json={"action": "add", "alias": "Hacker"})
        self.assertEqual(resp_post.status_code, 302)


if __name__ == "__main__":
    unittest.main()
