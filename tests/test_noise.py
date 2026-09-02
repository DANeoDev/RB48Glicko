import os
from pathlib import Path
import tempfile
import time
import unittest

from scripts.accounts.auth import register_user
from scripts.accounts.database import (
    add_noise_bubble,
    approve_user,
    delete_noise_bubble,
    get_accounts_connection,
    get_noise_bubbles_for_page,
    get_user_by_id,
    mark_email_verified,
    set_user_noise_display_mode,
    update_noise_bubble_position,
    update_user_role,
)
from web.app import app


class NoiseBubblesTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_accounts_db = Path(self.temp_dir.name) / "test_accounts.db"
        os.environ["RB48_ACCOUNTS_DATABASE_FILE"] = str(self.test_accounts_db)
        self.client = app.test_client()

    def tearDown(self):
        os.environ.pop("RB48_ACCOUNTS_DATABASE_FILE", None)
        self.temp_dir.cleanup()

    def create_user(self, role="user"):
        unique_name = f"u_{role[:3]}_{int(time.time() * 1000)}"
        user_id, err = register_user(unique_name, f"{unique_name}@example.com", "password123", role=role)
        if err:
            raise ValueError(f"Registration failed: {err}")
        conn = get_accounts_connection()
        try:
            mark_email_verified(conn, user_id)
            approve_user(conn, user_id, approved=True)
            if role != "user":
                update_user_role(conn, user_id, role)
            user = get_user_by_id(conn, user_id)
        finally:
            conn.close()
        return dict(user)

    def test_regular_user_quota_fifo_eviction(self):
        user = self.create_user(role="user")
        with self.client.session_transaction() as sess:
            sess["user_id"] = user["id"]

        # Post 3 bubbles
        for i in range(1, 4):
            resp = self.client.post(
                "/api/noise",
                json={
                    "page_path": "/stats",
                    "pos_x_percent": 10 * i,
                    "pos_y_percent": 20 * i,
                    "content": f"Banter #{i}",
                    "bg_color": "#7B52C5",
                },
            )
            self.assertEqual(resp.status_code, 201)

        conn = get_accounts_connection()
        try:
            bubbles = get_noise_bubbles_for_page(conn, "/stats")
            self.assertEqual(len(bubbles), 3)
            self.assertEqual(bubbles[0]["content"], "Banter #1")

            # Post 4th bubble -> Banter #1 should be evicted (FIFO)
            resp4 = self.client.post(
                "/api/noise",
                json={
                    "page_path": "/stats",
                    "pos_x_percent": 50,
                    "pos_y_percent": 50,
                    "content": "Banter #4",
                },
            )
            self.assertEqual(resp4.status_code, 201)

            bubbles_after = get_noise_bubbles_for_page(conn, "/stats")
            self.assertEqual(len(bubbles_after), 3)
            contents = [b["content"] for b in bubbles_after]
            self.assertNotIn("Banter #1", contents)
            self.assertIn("Banter #2", contents)
            self.assertIn("Banter #3", contents)
            self.assertIn("Banter #4", contents)
        finally:
            conn.close()

    def test_match_targeted_noise_exempt_from_eviction(self):
        user = self.create_user(role="user")
        with self.client.session_transaction() as sess:
            sess["user_id"] = user["id"]

        # Post a match-targeted noise bubble
        resp_match = self.client.post(
            "/api/noise",
            json={
                "page_path": "/matches",
                "match_id": 42,
                "pos_x_percent": 15,
                "pos_y_percent": 15,
                "content": "Match 42 was historic!",
            },
        )
        self.assertEqual(resp_match.status_code, 201)

        # Post 3 general bubbles on /stats
        for i in range(1, 4):
            self.client.post(
                "/api/noise",
                json={
                    "page_path": "/stats",
                    "pos_x_percent": 10 * i,
                    "pos_y_percent": 20 * i,
                    "content": f"General Banter #{i}",
                },
            )

        # Post 4th general bubble
        self.client.post(
            "/api/noise",
            json={
                "page_path": "/stats",
                "pos_x_percent": 80,
                "pos_y_percent": 80,
                "content": "General Banter #4",
            },
        )

        # Post 4 bubbles on /matches directly (page_path = '/matches')
        for i in range(1, 5):
            self.client.post(
                "/api/noise",
                json={
                    "page_path": "/matches",
                    "pos_x_percent": 15 * i,
                    "pos_y_percent": 15 * i,
                    "content": f"Match history banter #{i}",
                },
            )

        conn = get_accounts_connection()
        try:
            # Match 42 bubble should still exist!
            match_bubbles = get_noise_bubbles_for_page(conn, "/matches", match_id=42)
            self.assertEqual(len(match_bubbles), 1)
            self.assertEqual(match_bubbles[0]["content"], "Match 42 was historic!")

            # /matches page bubbles should all 5 still exist!
            matches_page_bubbles = get_noise_bubbles_for_page(conn, "/matches")
            self.assertEqual(len(matches_page_bubbles), 5)

            # Stats general bubbles should have 3 (FIFO capped)
            stats_bubbles = get_noise_bubbles_for_page(conn, "/stats")
            self.assertEqual(len(stats_bubbles), 3)
        finally:
            conn.close()

    def test_staff_quota_limit_of_five(self):
        webmaster = self.create_user(role="webmaster")
        with self.client.session_transaction() as sess:
            sess["user_id"] = webmaster["id"]

        # Post 5 bubbles
        for i in range(1, 6):
            resp = self.client.post(
                "/api/noise",
                json={
                    "page_path": "/dashboard",
                    "pos_x_percent": 10 * i,
                    "pos_y_percent": 10 * i,
                    "content": f"Staff announcement #{i}",
                },
            )
            self.assertEqual(resp.status_code, 201)

        conn = get_accounts_connection()
        try:
            bubbles = get_noise_bubbles_for_page(conn, "/dashboard")
            self.assertEqual(len(bubbles), 5)
            self.assertEqual(bubbles[0]["content"], "Staff announcement #1")

            # Post 6th bubble -> Staff announcement #1 evicted (FIFO)
            resp6 = self.client.post(
                "/api/noise",
                json={
                    "page_path": "/dashboard",
                    "pos_x_percent": 70,
                    "pos_y_percent": 70,
                    "content": "Staff announcement #6",
                },
            )
            self.assertEqual(resp6.status_code, 201)

            bubbles_after = get_noise_bubbles_for_page(conn, "/dashboard")
            self.assertEqual(len(bubbles_after), 5)
            contents = [b["content"] for b in bubbles_after]
            self.assertNotIn("Staff announcement #1", contents)
            self.assertIn("Staff announcement #6", contents)
        finally:
            conn.close()

    def test_visitors_cannot_see_noise(self):
        user = self.create_user(role="user")
        with self.client.session_transaction() as sess:
            sess["user_id"] = user["id"]

        self.client.post(
            "/api/noise",
            json={
                "page_path": "/stats",
                "pos_x_percent": 20,
                "pos_y_percent": 20,
                "content": "Secret member banter",
            },
        )

        # Clear session (visitor)
        with self.client.session_transaction() as sess:
            sess.clear()

        resp = self.client.get("/api/noise?path=/stats")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["bubbles"], [])

    def test_deletion_and_permissions(self):
        user_a = self.create_user(role="user")
        user_b = self.create_user(role="user")
        admin = self.create_user(role="admin")

        # User A creates a bubble
        with self.client.session_transaction() as sess:
            sess["user_id"] = user_a["id"]

        resp_create = self.client.post(
            "/api/noise",
            json={
                "page_path": "/planner",
                "pos_x_percent": 30,
                "pos_y_percent": 40,
                "content": "User A banter",
            },
        )
        bubble_id = resp_create.get_json()["bubble"]["id"]

        # 1. User B tries to delete User A's bubble -> 403 Forbidden
        with self.client.session_transaction() as sess:
            sess["user_id"] = user_b["id"]
        resp_del_b = self.client.delete(f"/api/noise/{bubble_id}")
        self.assertEqual(resp_del_b.status_code, 403)

        # 2. Admin deletes User A's bubble -> Success
        with self.client.session_transaction() as sess:
            sess["user_id"] = admin["id"]
        resp_del_admin = self.client.delete(f"/api/noise/{bubble_id}")
        self.assertEqual(resp_del_admin.status_code, 200)

        conn = get_accounts_connection()
        try:
            self.assertEqual(len(get_noise_bubbles_for_page(conn, "/planner")), 0)
        finally:
            conn.close()

    def test_move_position_endpoint(self):
        user = self.create_user(role="user")
        with self.client.session_transaction() as sess:
            sess["user_id"] = user["id"]

        resp_create = self.client.post(
            "/api/noise",
            json={
                "page_path": "/stats",
                "pos_x_percent": 20,
                "pos_y_percent": 30,
                "content": "Draggable banter",
            },
        )
        bubble_id = resp_create.get_json()["bubble"]["id"]

        # Move to (75.5, 85.2)
        resp_move = self.client.post(
            f"/api/noise/{bubble_id}/move",
            json={"pos_x_percent": 75.5, "pos_y_percent": 85.2},
        )
        self.assertEqual(resp_move.status_code, 200)

        conn = get_accounts_connection()
        try:
            bubbles = get_noise_bubbles_for_page(conn, "/stats", viewer_user_id=user["id"])
            self.assertAlmostEqual(bubbles[0]["pos_x_percent"], 75.5)
            self.assertAlmostEqual(bubbles[0]["pos_y_percent"], 85.2)
        finally:
            conn.close()

    def test_per_user_distinct_positions(self):
        user_a = self.create_user(role="user")
        user_b = self.create_user(role="user")

        # User A creates a bubble at (20, 30)
        with self.client.session_transaction() as sess:
            sess["user_id"] = user_a["id"]
        resp_create = self.client.post(
            "/api/noise",
            json={
                "page_path": "/stats",
                "pos_x_percent": 20,
                "pos_y_percent": 30,
                "content": "Shared banter",
            },
        )
        bubble_id = resp_create.get_json()["bubble"]["id"]

        # User B moves the bubble to (65, 85) for User B's view
        with self.client.session_transaction() as sess:
            sess["user_id"] = user_b["id"]
        resp_move_b = self.client.post(
            f"/api/noise/{bubble_id}/move",
            json={"pos_x_percent": 65, "pos_y_percent": 85},
        )
        self.assertEqual(resp_move_b.status_code, 200)

        # Query as User B -> should see (65, 85)
        resp_b_view = self.client.get("/api/noise?path=/stats")
        bubbles_b = resp_b_view.get_json()["bubbles"]
        self.assertEqual(len(bubbles_b), 1)
        self.assertAlmostEqual(bubbles_b[0]["pos_x_percent"], 65)
        self.assertAlmostEqual(bubbles_b[0]["pos_y_percent"], 85)

        # Query as User A -> should see original (20, 30)
        with self.client.session_transaction() as sess:
            sess["user_id"] = user_a["id"]
        resp_a_view = self.client.get("/api/noise?path=/stats")
        bubbles_a = resp_a_view.get_json()["bubbles"]
        self.assertEqual(len(bubbles_a), 1)
        self.assertAlmostEqual(bubbles_a[0]["pos_x_percent"], 20)
        self.assertAlmostEqual(bubbles_a[0]["pos_y_percent"], 30)

    def test_per_user_dismissal(self):
        user_a = self.create_user(role="user")
        user_b = self.create_user(role="user")

        # User A creates a bubble
        with self.client.session_transaction() as sess:
            sess["user_id"] = user_a["id"]
        resp_create = self.client.post(
            "/api/noise",
            json={
                "page_path": "/planner",
                "pos_x_percent": 15,
                "pos_y_percent": 25,
                "content": "Banter to dismiss",
            },
        )
        bubble_id = resp_create.get_json()["bubble"]["id"]

        # User B dismisses the bubble from their view
        with self.client.session_transaction() as sess:
            sess["user_id"] = user_b["id"]
        resp_dismiss = self.client.post(f"/api/noise/{bubble_id}/dismiss")
        self.assertEqual(resp_dismiss.status_code, 200)

        # User B cannot see the bubble
        resp_b_view = self.client.get("/api/noise?path=/planner")
        self.assertEqual(len(resp_b_view.get_json()["bubbles"]), 0)

        # User A STILL sees the bubble
        with self.client.session_transaction() as sess:
            sess["user_id"] = user_a["id"]
        resp_a_view = self.client.get("/api/noise?path=/planner")
        self.assertEqual(len(resp_a_view.get_json()["bubbles"]), 1)

    def test_noise_display_mode_settings(self):
        user = self.create_user(role="user")
        with self.client.session_transaction() as sess:
            sess["user_id"] = user["id"]

        resp = self.client.post(
            "/settings/noise-mode",
            data={"noise_display_mode": "transparent"},
            follow_redirects=True,
        )
        self.assertEqual(resp.status_code, 200)

        conn = get_accounts_connection()
        try:
            updated = get_user_by_id(conn, user["id"])
            self.assertEqual(updated["noise_display_mode"], "transparent")
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
