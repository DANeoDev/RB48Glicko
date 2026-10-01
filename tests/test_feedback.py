import json
import os
from pathlib import Path
import shutil
import tempfile
import time
import unittest

from scripts.accounts.auth import register_user
from scripts.accounts.database import (
    approve_user,
    create_feedback_entry,
    delete_feedback_entry,
    get_accounts_connection,
    get_all_feedback,
    get_feedback_counts,
    mark_email_verified,
    update_feedback_status,
    update_user_role,
)
from scripts.database.database import main as init_database
from web.app import create_app


class FeedbackTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_db = Path(self.temp_dir.name) / "test_rb48.db"
        self.test_accounts_db = Path(self.temp_dir.name) / "test_accounts.db"

        prod_rb48 = Path(__file__).resolve().parents[1] / "data" / "rb48.db"
        if prod_rb48.exists():
            shutil.copy2(prod_rb48, self.test_db)
        else:
            os.environ["RB48_DATABASE_FILE"] = str(self.test_db)
            init_database()

        os.environ["RB48_DATABASE_FILE"] = str(self.test_db)
        os.environ["RB48_ACCOUNTS_DATABASE_FILE"] = str(self.test_accounts_db)

        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def tearDown(self):
        os.environ.pop("RB48_DATABASE_FILE", None)
        os.environ.pop("RB48_ACCOUNTS_DATABASE_FILE", None)
        self.temp_dir.cleanup()

    def create_user(self, role="user", psychology_test_passed=True):
        u_name = f"user_{int(time.time() * 1000000)}"
        user_id, _ = register_user(u_name, f"{u_name}@example.com", "SecretPass123!")
        conn = get_accounts_connection()
        try:
            mark_email_verified(conn, user_id)
            approve_user(conn, user_id, approved=True)
            update_user_role(conn, user_id, role)
            if psychology_test_passed:
                conn.execute("UPDATE users SET psychology_test_passed = 1 WHERE id = ?", (user_id,))
                conn.commit()
        finally:
            conn.close()
        return user_id

    def login_user(self, user_id):
        with self.client.session_transaction() as sess:
            sess["user_id"] = user_id

    def test_database_feedback_helpers(self):
        conn = get_accounts_connection()
        try:
            fb_id = create_feedback_entry(
                conn,
                category="mobile_handling",
                message="Button in table difficult to click on mobile",
                username="TestUser",
                page_url="/stats",
                viewport="390x844",
                screen_res="390x844 @3x",
                touch_support=1,
                user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 16_0...)"
            )
            self.assertIsInstance(fb_id, int)

            entries = get_all_feedback(conn)
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["category"], "mobile_handling")
            self.assertEqual(entries[0]["status"], "open")
            self.assertEqual(entries[0]["touch_support"], 1)

            # Update status
            update_feedback_status(conn, fb_id, "resolved")
            entries = get_all_feedback(conn)
            self.assertEqual(entries[0]["status"], "resolved")

            # Counts
            counts = get_feedback_counts(conn)
            self.assertEqual(counts["total"], 1)
            self.assertEqual(counts["resolved"], 1)
            self.assertEqual(counts["open"], 0)

            # Delete
            delete_feedback_entry(conn, fb_id)
            self.assertEqual(len(get_all_feedback(conn)), 0)
        finally:
            conn.close()

    def test_submit_feedback_api_anonymous(self):
        resp = self.client.post("/api/feedback", json={
            "category": "mobile_handling",
            "message": "Hamburger menu covers profile settings",
            "page_url": "/matches",
            "viewport": "375x667",
            "screen_res": "375x667 @2x",
            "touch_support": 1,
            "user_agent": "Mobile Safari"
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertIn("feedback_id", data)

        conn = get_accounts_connection()
        try:
            entries = get_all_feedback(conn)
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["category"], "mobile_handling")
            self.assertEqual(entries[0]["username"], "Gast")
            self.assertEqual(entries[0]["viewport"], "375x667")
        finally:
            conn.close()

    def test_submit_feedback_api_authenticated(self):
        uid = self.create_user("user")
        self.login_user(uid)

        resp = self.client.post("/api/feedback", json={
            "category": "general",
            "message": "Great design overall, could we get dark mode toggle?",
            "page_url": "/dashboard"
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])

        conn = get_accounts_connection()
        try:
            entries = get_all_feedback(conn)
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["category"], "general")
            self.assertEqual(entries[0]["user_id"], uid)
        finally:
            conn.close()

    def test_submit_feedback_validation(self):
        # Empty message
        resp = self.client.post("/api/feedback", json={
            "category": "general",
            "message": "   "
        })
        self.assertEqual(resp.status_code, 400)

        # Invalid category fallback to 'general'
        resp2 = self.client.post("/api/feedback", json={
            "category": "non_existent_category",
            "message": "Valid text"
        })
        self.assertEqual(resp2.status_code, 200)
        conn = get_accounts_connection()
        try:
            entries = get_all_feedback(conn)
            self.assertEqual(entries[0]["category"], "general")
        finally:
            conn.close()

    def test_admin_feedback_authorization(self):
        # 1. Anonymous visitor
        resp_anon = self.client.get("/admin/feedback")
        self.assertEqual(resp_anon.status_code, 302)

        # 2. Regular user
        uid_user = self.create_user("user")
        self.login_user(uid_user)
        resp_user = self.client.get("/admin/feedback")
        self.assertEqual(resp_user.status_code, 302)
        # Location is redirecting to home/dashboard
        loc = resp_user.headers.get("Location", "")
        self.assertTrue(loc.endswith("/") or "dashboard" in loc or "home" in loc or loc == "/", f"Unexpected Location: {loc}")

        # 3. Admin
        uid_admin = self.create_user("admin")
        self.login_user(uid_admin)
        resp_admin = self.client.get("/admin/feedback")
        self.assertEqual(resp_admin.status_code, 200)
        self.assertIn("Benutzer- & Mobile-Feedback", resp_admin.get_data(as_text=True))
        self.assertIn("Logs für KI kopieren", resp_admin.get_data(as_text=True))

        # 4. Webmaster
        uid_wm = self.create_user("webmaster")
        self.login_user(uid_wm)
        resp_wm = self.client.get("/admin/feedback")
        self.assertEqual(resp_wm.status_code, 200)

    def test_admin_feedback_status_update_and_delete(self):
        conn = get_accounts_connection()
        try:
            fb_id = create_feedback_entry(
                conn,
                category="mobile_handling",
                message="Test issue",
                page_url="/"
            )
        finally:
            conn.close()

        uid_admin = self.create_user("admin")
        self.login_user(uid_admin)

        # Toggle status to resolved
        resp_status = self.client.post(f"/admin/feedback/{fb_id}/status", json={"status": "resolved"})
        self.assertEqual(resp_status.status_code, 200)

        conn = get_accounts_connection()
        try:
            entries = get_all_feedback(conn)
            self.assertEqual(entries[0]["status"], "resolved")
        finally:
            conn.close()

        # Delete entry
        resp_del = self.client.post(f"/admin/feedback/{fb_id}/delete", json={})
        self.assertEqual(resp_del.status_code, 200)

        conn = get_accounts_connection()
        try:
            self.assertEqual(len(get_all_feedback(conn)), 0)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
