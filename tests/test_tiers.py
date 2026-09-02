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
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

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

        # 3. Submit wrong answers -> returns 400
        fail_resp = self.client.post("/glicko-test", data={"q1": "a", "q2": "b", "q3": "c", "q4": "b"})
        self.assertEqual(fail_resp.status_code, 400)

        # 4. Submit correct answers -> succeeds and promotes to Glicko User
        pass_resp = self.client.post("/glicko-test", data={"q1": "b", "q2": "a", "q3": "a", "q4": "a"}, follow_redirects=True)
        self.assertEqual(pass_resp.status_code, 200)

        updated = get_user(user["id"])
        self.assertEqual(updated["psychology_test_passed"], 1)

        # 5. Now model analysis is accessible
        model_resp = self.client.get("/model-analysis")
        self.assertEqual(model_resp.status_code, 200)

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


if __name__ == "__main__":
    unittest.main()
