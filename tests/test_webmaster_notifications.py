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
    get_webmaster_notifications,
    get_unseen_webmaster_notifications_count,
    mark_webmaster_notifications_seen,
    record_webmaster_notification,
)
from web.app import create_app


class WebmasterNotificationsTest(unittest.TestCase):
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
        unique_name = f"wm_notif_{int(time.time() * 1000000)}"
        email = f"{unique_name}@example.com"
        user_id, _ = register_user(unique_name, email, "password123", role=role)

        conn = get_accounts_connection()
        try:
            if verified:
                mark_email_verified(conn, user_id)
            if approved or role in ("admin", "webmaster"):
                approve_user(conn, user_id, approved=True)
        finally:
            conn.close()

        if psychology_passed:
            pass_psychology_test(user_id)

        return get_user(user_id)

    def test_notification_recorded_on_registration(self):
        webmaster = self.create_user(role="webmaster")
        new_user = self.create_user(role="user")

        conn = get_accounts_connection()
        try:
            notifs = get_webmaster_notifications(conn, webmaster_user_id=webmaster["id"])
            self.assertTrue(len(notifs) >= 2)
            reg_notifs = [n for n in notifs if n["event_type"] == "user_registered"]
            self.assertTrue(len(reg_notifs) >= 2)
            usernames = [n["username"] for n in reg_notifs]
            self.assertIn(new_user["username"], usernames)

            unseen_count = get_unseen_webmaster_notifications_count(conn, webmaster["id"])
            self.assertTrue(unseen_count >= 2)

            mark_webmaster_notifications_seen(conn, webmaster["id"])
            unseen_after = get_unseen_webmaster_notifications_count(conn, webmaster["id"])
            self.assertEqual(unseen_after, 0)
        finally:
            conn.close()

    def test_notification_on_opt_out_change(self):
        webmaster = self.create_user(role="webmaster")
        user = self.create_user(role="user")

        # Mark previous notifications seen
        conn = get_accounts_connection()
        try:
            mark_webmaster_notifications_seen(conn, webmaster["id"])
        finally:
            conn.close()

        with self.client.session_transaction() as sess:
            sess["user_id"] = user["id"]

        resp = self.client.post("/settings/profile", data={
            "attendance_name": user["username"],
            "glicko_opt_out": "1",
        }, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)

        conn = get_accounts_connection()
        try:
            unseen = get_unseen_webmaster_notifications_count(conn, webmaster["id"])
            self.assertEqual(unseen, 1)

            notifs = get_webmaster_notifications(conn, webmaster["id"])
            opt_notif = next((n for n in notifs if n["event_type"] == "opt_out_changed"), None)
            self.assertIsNotNone(opt_notif)
            self.assertEqual(opt_notif["username"], user["username"])
            self.assertIn("aktiviert", opt_notif["details"])
        finally:
            conn.close()

    def test_admin_users_view_and_mark_read_route(self):
        webmaster = self.create_user(role="webmaster")
        user = self.create_user(role="user")

        with self.client.session_transaction() as sess:
            sess["user_id"] = webmaster["id"]

        resp = self.client.get("/admin/users")
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn("Aktivitäten & Benachrichtigungen", html)
        self.assertIn(user["username"], html)

        # Mark all as read via POST route
        resp_mark = self.client.post("/admin/notifications/mark-read", follow_redirects=True)
        self.assertEqual(resp_mark.status_code, 200)

        conn = get_accounts_connection()
        try:
            unseen = get_unseen_webmaster_notifications_count(conn, webmaster["id"])
            self.assertEqual(unseen, 0)
        finally:
            conn.close()

    def test_delete_single_notification_route(self):
        webmaster = self.create_user(role="webmaster")
        user = self.create_user(role="user")

        conn = get_accounts_connection()
        try:
            notifs = get_webmaster_notifications(conn, webmaster["id"])
            self.assertTrue(len(notifs) >= 2)
            target_id = notifs[0]["id"]
        finally:
            conn.close()

        with self.client.session_transaction() as sess:
            sess["user_id"] = webmaster["id"]

        resp = self.client.post(f"/admin/notifications/{target_id}/delete", follow_redirects=True)
        self.assertEqual(resp.status_code, 200)

        conn = get_accounts_connection()
        try:
            notifs_after = get_webmaster_notifications(conn, webmaster["id"])
            remaining_ids = [n["id"] for n in notifs_after]
            self.assertNotIn(target_id, remaining_ids)
        finally:
            conn.close()

    def test_clear_all_notifications_route(self):
        webmaster = self.create_user(role="webmaster")
        user = self.create_user(role="user")

        with self.client.session_transaction() as sess:
            sess["user_id"] = webmaster["id"]

        resp = self.client.post("/admin/notifications/clear-all", follow_redirects=True)
        self.assertEqual(resp.status_code, 200)

        conn = get_accounts_connection()
        try:
            notifs_after = get_webmaster_notifications(conn, webmaster["id"])
            self.assertEqual(len(notifs_after), 0)
            unseen = get_unseen_webmaster_notifications_count(conn, webmaster["id"])
            self.assertEqual(unseen, 0)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
