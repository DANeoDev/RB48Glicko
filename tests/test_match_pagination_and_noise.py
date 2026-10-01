import os
from pathlib import Path
import shutil
import tempfile
import time
import unittest
import sqlite3

from scripts.accounts.auth import pass_psychology_test, register_user
from scripts.accounts.database import (
    approve_user,
    get_accounts_connection,
    mark_email_verified,
    update_user_role,
    normalize_noise_page_path,
    add_noise_bubble,
    get_noise_bubbles_for_page,
    get_noise_bubble_by_id,
    set_user_noise_override,
    shift_match_history_noise_bubbles,
)
from scripts.database import get_connection
from scripts.matches.match_entry import add_match, delete_match
from web.app import app


class TestMatchPaginationAndNoise(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.test_accounts_db = Path(self.temp_dir.name) / "test_accounts.db"
        self.test_rb48_db = Path(self.temp_dir.name) / "test_rb48.db"
        prod_rb48 = Path(__file__).resolve().parents[1] / "data" / "rb48.db"
        if prod_rb48.exists():
            shutil.copy2(prod_rb48, self.test_rb48_db)

        os.environ["RB48_ACCOUNTS_DATABASE_FILE"] = str(self.test_accounts_db)
        os.environ["RB48_DATABASE_FILE"] = str(self.test_rb48_db)
        self.client = app.test_client()

    def tearDown(self):
        os.environ.pop("RB48_ACCOUNTS_DATABASE_FILE", None)
        os.environ.pop("RB48_DATABASE_FILE", None)
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def create_user_session(self, role="user"):
        unique_name = f"user_{int(time.time() * 1000000)}"
        email = f"{unique_name}@example.com"
        user_id, _ = register_user(unique_name, email, "password123", role=role)

        connection = get_accounts_connection()
        try:
            mark_email_verified(connection, user_id)
            approve_user(connection, user_id, approved=True)
            if role != "user":
                update_user_role(connection, user_id, role)
        finally:
            connection.close()

        pass_psychology_test(user_id)
        return user_id

    def test_normalize_noise_page_path(self):
        """Test normalization for /matches and its pagination variants."""
        self.assertEqual(normalize_noise_page_path(""), "/")
        self.assertEqual(normalize_noise_page_path(None), "/")
        self.assertEqual(normalize_noise_page_path("/dashboard"), "/")
        self.assertEqual(normalize_noise_page_path("/index"), "/")
        self.assertEqual(normalize_noise_page_path("/matches"), "/matches")
        self.assertEqual(normalize_noise_page_path("/matches/"), "/matches")
        self.assertEqual(normalize_noise_page_path("/matches?page=1"), "/matches")
        self.assertEqual(normalize_noise_page_path("/matches?page=2"), "/matches?page=2")
        self.assertEqual(normalize_noise_page_path("/matches?rating_type=box&page=3"), "/matches?page=3")
        self.assertEqual(normalize_noise_page_path("/matches?page=0"), "/matches")
        self.assertEqual(normalize_noise_page_path("/matches?page=abc"), "/matches")
        self.assertEqual(normalize_noise_page_path("/leaderboard"), "/leaderboard")
        self.assertEqual(normalize_noise_page_path("/rankings?view=grid"), "/rankings")

    def test_shift_match_history_noise_bubbles_math_and_overflow(self):
        """Test slot shifting, page overflow (page 1 -> page 2), and reverse pullback."""
        u_id = self.create_user_session(role="admin")
        acc_conn = get_accounts_connection()

        try:
            # Add 3 bubbles
            # Bubble 1: page 1, near top (10%)
            # Bubble 2: page 1, near bottom (95%)
            # Bubble 3: page 2, middle (20%)
            b1_id = add_noise_bubble(acc_conn, u_id, "/matches", 30.0, 10.0, "Top banter")
            b2_id = add_noise_bubble(acc_conn, u_id, "/matches", 40.0, 95.0, "Bottom banter")
            b3_id = add_noise_bubble(acc_conn, u_id, "/matches?page=2", 50.0, 20.0, "Page 2 banter")

            # Set user override for Bubble 2
            set_user_noise_override(acc_conn, u_id, b2_id, custom_x=45.0, custom_y=96.0)

            # 1. Forward shift: 1 slot added (+8.33%)
            updated = shift_match_history_noise_bubbles(acc_conn, shift_slots=1, total_slots=12)
            self.assertEqual(updated, 3)

            b1 = get_noise_bubble_by_id(acc_conn, b1_id)
            b2 = get_noise_bubble_by_id(acc_conn, b2_id)
            b3 = get_noise_bubble_by_id(acc_conn, b3_id)

            # Bubble 1 moved from 10.0 to 18.33% on page 1
            self.assertEqual(b1["page_path"], "/matches")
            self.assertAlmostEqual(b1["pos_y_percent"], 18.33, places=2)

            # Bubble 2 moved from 95.0 + 8.333 = 103.333% -> OVERFLOWS to page 2 at 3.33%
            self.assertEqual(b2["page_path"], "/matches?page=2")
            self.assertAlmostEqual(b2["pos_y_percent"], 3.33, places=2)

            # User override for Bubble 2 also shifted & wrapped to 4.33%
            row_ov = acc_conn.execute("SELECT custom_y_percent FROM user_noise_overrides WHERE bubble_id = ?", (b2_id,)).fetchone()
            self.assertAlmostEqual(row_ov["custom_y_percent"], 4.33, places=2)

            # Bubble 3 moved from 20.0 to 28.33% on page 2
            self.assertEqual(b3["page_path"], "/matches?page=2")
            self.assertAlmostEqual(b3["pos_y_percent"], 28.33, places=2)

            # 2. Reverse shift: 1 slot removed (-8.33%)
            updated_rev = shift_match_history_noise_bubbles(acc_conn, shift_slots=-1, total_slots=12)
            self.assertEqual(updated_rev, 3)

            b1_rev = get_noise_bubble_by_id(acc_conn, b1_id)
            b2_rev = get_noise_bubble_by_id(acc_conn, b2_id)
            b3_rev = get_noise_bubble_by_id(acc_conn, b3_id)

            # Bubble 1 returned to 10.0% on page 1
            self.assertEqual(b1_rev["page_path"], "/matches")
            self.assertAlmostEqual(b1_rev["pos_y_percent"], 10.0, places=2)

            # Bubble 2 pulled back from page 2 to page 1 at 95.0%
            self.assertEqual(b2_rev["page_path"], "/matches")
            self.assertAlmostEqual(b2_rev["pos_y_percent"], 95.0, places=2)

            # Override returned to 96.0%
            row_ov_rev = acc_conn.execute("SELECT custom_y_percent FROM user_noise_overrides WHERE bubble_id = ?", (b2_id,)).fetchone()
            self.assertAlmostEqual(row_ov_rev["custom_y_percent"], 96.0, places=2)

            # Bubble 3 returned to 20.0% on page 2
            self.assertEqual(b3_rev["page_path"], "/matches?page=2")
            self.assertAlmostEqual(b3_rev["pos_y_percent"], 20.0, places=2)
        finally:
            acc_conn.close()

    def test_shift_clamping_at_top_of_page_one(self):
        """Test that negative shifting cannot push bubbles before top of page 1 (clamped to 0.0%)."""
        u_id = self.create_user_session(role="admin")
        acc_conn = get_accounts_connection()
        try:
            b_id = add_noise_bubble(acc_conn, u_id, "/matches", 50.0, 3.0, "Near top")
            shift_match_history_noise_bubbles(acc_conn, shift_slots=-1, total_slots=12)

            b = get_noise_bubble_by_id(acc_conn, b_id)
            self.assertEqual(b["page_path"], "/matches")
            self.assertEqual(b["pos_y_percent"], 0.0)
        finally:
            acc_conn.close()

    def test_match_history_pagination_route(self):
        """Test that /matches slices matches to 12 per page and renders pagination controls."""
        # Ensure we have matches in the database
        db_conn = get_connection()
        match_count = db_conn.execute("SELECT COUNT(*) as c FROM matches").fetchone()["c"]
        db_conn.close()

        # Page 1
        resp = self.client.get("/matches")
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)

        if match_count > 12:
            # We expect pagination markup
            self.assertIn("class=\"match-pagination\"", html)
            self.assertIn("class=\"pagination-page-selector\"", html)
            self.assertIn("id=\"pagination-page-input\"", html)
            self.assertIn("class=\"pagination-btn pagination-next\"", html)
            self.assertIn("class=\"pagination-btn pagination-last\"", html)
            # Page 1 should NOT have prev or first
            self.assertNotIn("class=\"pagination-btn pagination-prev\"", html)
            self.assertNotIn("class=\"pagination-btn pagination-first\"", html)

            # Page 2
            resp2 = self.client.get("/matches?page=2")
            self.assertEqual(resp2.status_code, 200)
            html2 = resp2.get_data(as_text=True)
            self.assertIn("class=\"pagination-btn pagination-first\"", html2)
            self.assertIn("class=\"pagination-btn pagination-prev\"", html2)
        else:
            # If <= 12 matches, no pagination controls
            self.assertNotIn("class=\"match-pagination\"", html)

    def test_match_addition_and_deletion_triggers_bubble_shift(self):
        """Integration test: adding a match shifts bubbles, deleting restores them."""
        u_id = self.create_user_session(role="admin")
        acc_conn = get_accounts_connection()
        b_id = add_noise_bubble(acc_conn, u_id, "/matches", 50.0, 20.0, "Test integration banter")

        # Initial check
        b_init = get_noise_bubble_by_id(acc_conn, b_id)
        self.assertEqual(b_init["pos_y_percent"], 20.0)

        # Add a match
        db_conn = get_connection()
        try:
            # Find 4 valid player IDs
            p_rows = db_conn.execute("SELECT player_id FROM players LIMIT 4").fetchall()
            p_ids = [r["player_id"] for r in p_rows]
            if len(p_ids) >= 4:
                match_id = add_match(
                    db_conn,
                    "2026-09-30",
                    "box",
                    [p_ids[0], p_ids[1]],
                    [p_ids[2], p_ids[3]],
                    5,
                    3,
                )

                # Bubble should have been shifted down by 1 slot (~8.33%)
                b_after_add = get_noise_bubble_by_id(acc_conn, b_id)
                self.assertAlmostEqual(b_after_add["pos_y_percent"], 28.33, places=2)

                # Now delete the match
                delete_match(db_conn, match_id)

                # Bubble should have been shifted back up
                b_after_del = get_noise_bubble_by_id(acc_conn, b_id)
                self.assertAlmostEqual(b_after_del["pos_y_percent"], 20.0, places=2)
        finally:
            db_conn.close()
            acc_conn.close()


if __name__ == "__main__":
    unittest.main()
