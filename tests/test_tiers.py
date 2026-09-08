import os
from pathlib import Path
import tempfile
import time
import unittest
from flask import session

from scripts.accounts.auth import register_user, get_user, pass_psychology_test
from scripts.accounts.database import get_accounts_connection, mark_email_verified, update_user_role, approve_user
from web.app import create_app
from web.services.security import (
    Tier,
    get_actual_tier,
    get_effective_tier,
    has_tier,
)


class AccessTiersTest(unittest.TestCase):
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

    def create_test_user(self, role="user", verified=False, approved=False, psychology_passed=False):
        unique_name = f"tier_usr_{int(time.time() * 1000000)}"
        email = f"{unique_name}@example.com"
        user_id, _ = register_user(unique_name, email, "securepass123", role=role)

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

        return get_user(user_id)

    def test_actual_tier_resolution(self):
        # 1. Unauthenticated Visitor
        self.assertEqual(get_actual_tier(None), Tier.VISITOR)

        # 2. Registered but Unverified User -> VISITOR
        unverified = self.create_test_user(verified=False, approved=False)
        self.assertEqual(get_actual_tier(unverified), Tier.VISITOR)

        # 3. Verified but Unapproved User -> VISITOR
        unapproved = self.create_test_user(verified=True, approved=False)
        self.assertEqual(get_actual_tier(unapproved), Tier.VISITOR)

        # 4. Verified & Approved User without test -> USER
        verified = self.create_test_user(verified=True, approved=True, psychology_passed=False)
        self.assertEqual(get_actual_tier(verified), Tier.USER)

        # 5. Glicko User (passed test) -> GLICKO_USER
        glicko_user = self.create_test_user(verified=True, approved=True, psychology_passed=True)
        self.assertEqual(get_actual_tier(glicko_user), Tier.GLICKO_USER)

        # 6. Admin -> ADMIN
        admin = self.create_test_user(role="admin", verified=True)
        self.assertEqual(get_actual_tier(admin), Tier.ADMIN)

        # 7. Webmaster -> WEBMASTER
        webmaster = self.create_test_user(role="webmaster", verified=True)
        self.assertEqual(get_actual_tier(webmaster), Tier.WEBMASTER)

    def test_glicko_opt_out_tier_downgrade(self):
        # User who passed psychology test but opted out of Glicko
        glicko_user = self.create_test_user(verified=True, approved=True, psychology_passed=True)
        self.assertEqual(get_actual_tier(glicko_user), Tier.GLICKO_USER)

        conn = get_accounts_connection()
        try:
            from scripts.accounts.database import update_user_profile
            update_user_profile(conn, glicko_user["id"], glicko_opt_out=1)
        finally:
            conn.close()

        opted_out_user = get_user(glicko_user["id"])
        self.assertEqual(opted_out_user["glicko_opt_out"], 1)
        self.assertEqual(get_actual_tier(opted_out_user), Tier.USER)

        # Admin who opted out of Glicko -> downgraded to USER
        admin = self.create_test_user(role="admin", verified=True)
        self.assertEqual(get_actual_tier(admin), Tier.ADMIN)

        conn = get_accounts_connection()
        try:
            update_user_profile(conn, admin["id"], glicko_opt_out=1)
        finally:
            conn.close()

        opted_out_admin = get_user(admin["id"])
        self.assertEqual(get_actual_tier(opted_out_admin), Tier.USER)

        # Re-enabling Glicko visibility (opt_out=0) restores tier
        conn = get_accounts_connection()
        try:
            update_user_profile(conn, glicko_user["id"], glicko_opt_out=0)
        finally:
            conn.close()

        restored_user = get_user(glicko_user["id"])
        self.assertEqual(get_actual_tier(restored_user), Tier.GLICKO_USER)

        # Webmaster remains WEBMASTER even with opt_out
        webmaster = self.create_test_user(role="webmaster", verified=True)
        conn = get_accounts_connection()
        try:
            update_user_profile(conn, webmaster["id"], glicko_opt_out=1)
        finally:
            conn.close()
        opted_out_wm = get_user(webmaster["id"])
        self.assertEqual(get_actual_tier(opted_out_wm), Tier.WEBMASTER)

    def test_webmaster_view_simulation(self):
        webmaster = self.create_test_user(role="webmaster", verified=True)

        with self.app.test_request_context():
            session["user_id"] = webmaster["id"]

            # Actual & default effective is WEBMASTER
            self.assertEqual(get_actual_tier(), Tier.WEBMASTER)
            self.assertEqual(get_effective_tier(), Tier.WEBMASTER)

            # Simulate Visitor
            session["simulated_tier"] = "visitor"
            self.assertEqual(get_effective_tier(), Tier.VISITOR)
            self.assertEqual(get_actual_tier(), Tier.WEBMASTER) # Real authority preserved
            self.assertFalse(has_tier(Tier.USER))
            self.assertTrue(has_tier(Tier.USER, effective=False))

            # Simulate User
            session["simulated_tier"] = "user"
            self.assertEqual(get_effective_tier(), Tier.USER)
            self.assertTrue(has_tier(Tier.USER))
            self.assertFalse(has_tier(Tier.GLICKO_USER))

            # Simulate Glicko User
            session["simulated_tier"] = "glicko_user"
            self.assertEqual(get_effective_tier(), Tier.GLICKO_USER)
            self.assertTrue(has_tier(Tier.GLICKO_USER))

            # Reset Simulation
            session.pop("simulated_tier", None)
            self.assertEqual(get_effective_tier(), Tier.WEBMASTER)

    def test_psychology_test_route_unlock(self):
        user = self.create_test_user(verified=True, approved=True, psychology_passed=False)

        # 1. Login user
        with self.client.session_transaction() as sess:
            sess["user_id"] = user["id"]

        # 2. Accessing model analysis should redirect to glicko-test
        resp = self.client.get("/model-analysis", follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/glicko-test", resp.headers["Location"])

        # 3. Submit tryhard/toxic answers -> assigned tryhard persona, clearance denied (returns 400)
        fail_resp = self.client.post("/glicko-test", data={"q1": "a", "q2": "c", "q3": "b", "q4": "d", "q5": "d", "q6": "b", "q7": "a"})
        self.assertEqual(fail_resp.status_code, 400)
        self.assertTrue(b"Stat-St" in fail_resp.data or b"Stat-Striker" in fail_resp.data)

        updated_fail = get_user(user["id"])
        self.assertEqual(updated_fail["psychology_test_passed"], 0)
        self.assertEqual(updated_fail["psychology_persona"], "tryhard")

        # 4. Submit sportsmanship/legend answers -> succeeds and promotes to Glicko User
        pass_resp = self.client.post("/glicko-test", data={"q1": "d", "q2": "b", "q3": "c", "q4": "b", "q5": "a", "q6": "d", "q7": "b"}, follow_redirects=True)
        self.assertEqual(pass_resp.status_code, 200)
        self.assertTrue(b"Kabinenlegende" in pass_resp.data or b"Locker Room Legend" in pass_resp.data)
        self.assertIn("/glickofaq#webmaster-project", pass_resp.data.decode("utf-8"))

        updated = get_user(user["id"])
        self.assertEqual(updated["psychology_test_passed"], 1)
        self.assertEqual(updated["psychology_persona"], "legend")

        # 5. Now model analysis is accessible
        model_resp = self.client.get("/model-analysis")
        self.assertEqual(model_resp.status_code, 200)

    def test_webmaster_project_moved_to_glickofaq(self):
        # 1. /about no longer contains "Projekt des Webmasters" / "Webmaster Project"
        resp_about = self.client.get("/about")
        self.assertEqual(resp_about.status_code, 200)
        about_html = resp_about.data.decode("utf-8")
        self.assertNotIn("webmaster-project", about_html)
        self.assertNotIn("Projekt des Webmasters", about_html)
        self.assertNotIn("Webmaster Project", about_html)

        # 2. /glickofaq contains webmaster-project section
        resp_faq = self.client.get("/glickofaq")
        self.assertEqual(resp_faq.status_code, 200)
        faq_html = resp_faq.data.decode("utf-8")
        self.assertIn("webmaster-project", faq_html)
        self.assertTrue("Projekt des Webmasters" in faq_html or "Webmaster Project" in faq_html)
        self.assertTrue("Dabei gilt:" in faq_html or "Please note:" in faq_html)

    def test_webmaster_manual_approval_endpoint(self):
        webmaster = self.create_test_user(role="webmaster", verified=True)
        new_user = self.create_test_user(role="user", verified=True, approved=False)

        with self.client.session_transaction() as sess:
            sess["user_id"] = webmaster["id"]

        # View user list
        resp = self.client.get("/admin/users")
        self.assertEqual(resp.status_code, 200)

        # Approve new user
        approve_resp = self.client.post(f"/admin/users/{new_user['id']}/approval", data={"action": "approve"}, follow_redirects=True)
        self.assertEqual(approve_resp.status_code, 200)

        updated = get_user(new_user["id"])
        self.assertEqual(updated["is_approved"], 1)

    def test_webmaster_delete_user_with_backup_and_2step_verification(self):
        webmaster = self.create_test_user(role="webmaster", verified=True)
        target_user = self.create_test_user(role="user", verified=True, approved=True)

        with self.client.session_transaction() as sess:
            sess["user_id"] = webmaster["id"]

        # 1. Self deletion should be blocked
        self_del = self.client.post(f"/admin/users/{webmaster['id']}/delete", data={"confirm_1": "yes", "confirm_username": webmaster["username"]}, follow_redirects=True)
        self.assertIn(b"cannot delete your own active Webmaster account", self_del.data)

        # 2. Failed verification (wrong username)
        fail_del = self.client.post(f"/admin/users/{target_user['id']}/delete", data={"confirm_1": "yes", "confirm_username": "wrong_name"}, follow_redirects=True)
        self.assertIn(b"Two-step verification failed", fail_del.data)
        self.assertIsNotNone(get_user(target_user["id"]))

        # 3. Successful deletion with automatic backup
        success_del = self.client.post(f"/admin/users/{target_user['id']}/delete", data={"confirm_1": "yes", "confirm_username": target_user["username"]}, follow_redirects=True)
        self.assertEqual(success_del.status_code, 200)
        self.assertIn(b"was wiped", success_del.data)
        self.assertIn(b"Backup archived to data/backups/accounts/", success_del.data)

        # Confirm user is permanently gone from DB
        self.assertIsNone(get_user(target_user["id"]))

    def test_webmaster_view_simulation_ui_mismatches_fixed(self):
        """Verify that simulating 'user' hides webmaster tools (like planner clear dates, user management, and player switcher)."""
        from scripts.planner.database import create_event, get_planner_connection
        p_conn = get_planner_connection()
        try:
            create_event(p_conn, "2026-12-15 20:00", "box")
        finally:
            p_conn.close()

        webmaster = self.create_test_user(role="webmaster", verified=True)

        # 1. Actual Webmaster View: Clear Dates button & modal, User Management, and Player Switcher are visible
        with self.client.session_transaction() as sess:
            sess["user_id"] = webmaster["id"]
            sess.pop("simulated_tier", None)

        resp_wm = self.client.get("/planner")
        self.assertEqual(resp_wm.status_code, 200)
        html_wm = resp_wm.data.decode("utf-8")
        self.assertIn("open-clear-all-modal-btn", html_wm)
        self.assertIn("clear-all-modal", html_wm)
        self.assertIn("admin/users", html_wm)
        self.assertIn('role: "webmaster"', html_wm)

        # 2. Simulated User View: Clear Dates button & modal and User Management MUST BE HIDDEN
        with self.client.session_transaction() as sess:
            sess["user_id"] = webmaster["id"]
            sess["simulated_tier"] = "user"

        resp_user_sim = self.client.get("/planner")
        self.assertEqual(resp_user_sim.status_code, 200)
        html_user_sim = resp_user_sim.data.decode("utf-8")
        self.assertNotIn("open-clear-all-modal-btn", html_user_sim)
        self.assertNotIn("clear-all-modal", html_user_sim)
        self.assertNotIn("admin/users", html_user_sim)
        self.assertIn('role: "user"', html_user_sim)

        # 3. Simulated Visitor View: Clear Dates button & modal and User Management MUST BE HIDDEN
        with self.client.session_transaction() as sess:
            sess["user_id"] = webmaster["id"]
            sess["simulated_tier"] = "visitor"

        resp_vis_sim = self.client.get("/planner")
        self.assertEqual(resp_vis_sim.status_code, 200)
        html_vis_sim = resp_vis_sim.data.decode("utf-8")
        self.assertNotIn("open-clear-all-modal-btn", html_vis_sim)
        self.assertNotIn("clear-all-modal", html_vis_sim)
        self.assertNotIn("admin/users", html_vis_sim)


if __name__ == "__main__":
    unittest.main()

