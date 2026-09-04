"""Tests for personal player stats navigation and teammate/opponent filtering."""

import os
from pathlib import Path
import shutil
import tempfile
import time
import unittest

from scripts.accounts.auth import pass_psychology_test, register_user
from scripts.accounts.database import approve_user, get_accounts_connection, mark_email_verified, update_user_role
from scripts.database.database import get_connection
from scripts.database.db_players import get_players
from scripts.frontend.view_models import build_match_history
from scripts.glicko.glicko2 import TOTAL
from web.app import app


class TestPlayerFilters(unittest.TestCase):
    """Test suite for /my-stats, player profile filters, and structured match history metadata."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
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
        self.temp_dir.cleanup()

    def create_user_session(self, role="user", verified=True, approved=True, psychology_passed=True, player_id=None):
        unique_name = f"filter_user_{int(time.time() * 1000000)}"
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
            if player_id is not None:
                connection.execute("UPDATE users SET player_id = ? WHERE id = ?", (player_id, user_id))
                connection.commit()
        finally:
            connection.close()

        if psychology_passed:
            pass_psychology_test(user_id)

        return user_id

    def test_my_stats_redirect_unlinked(self):
        user_id = self.create_user_session(player_id=None)
        with self.client.session_transaction() as sess:
            sess["user_id"] = user_id

        resp = self.client.get("/my-stats", follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/settings", resp.location)

    def test_my_stats_redirect_linked(self):
        user_id = self.create_user_session(player_id=1)
        with self.client.session_transaction() as sess:
            sess["user_id"] = user_id

        resp = self.client.get("/my-stats", follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/player/1", resp.location)

    def test_build_match_history_player_metadata(self):
        conn = get_connection()
        try:
            players = get_players(conn)
            matches = build_match_history(conn, players, player_id=1, rating_type=TOTAL)
            self.assertGreater(len(matches), 0)
            for m in matches:
                self.assertIn("own_team_ids", m)
                self.assertIn("opp_team_ids", m)
                self.assertIn("is_win", m)
                self.assertIn("is_loss", m)
                self.assertIn("is_draw", m)
                self.assertNotIn(1, m["own_team_ids"])
                self.assertNotIn(1, m["opp_team_ids"])
                if m["is_win"]:
                    self.assertGreater(m["goals_for"], m["goals_against"])
                elif m["is_loss"]:
                    self.assertLess(m["goals_for"], m["goals_against"])
        finally:
            conn.close()

    def test_player_profile_filter_card_rendering(self):
        user_id = self.create_user_session(player_id=1)
        with self.client.session_transaction() as sess:
            sess["user_id"] = user_id

        resp = self.client.get("/player/1")
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)

        self.assertIn("filter-drawer", html)
        self.assertIn("btn-add-teammate", html)
        self.assertIn("btn-add-opponent", html)
        self.assertIn("active-filters-banner", html)
        self.assertIn("PlayerFilter", html)

    def test_player_profile_with_filter_query_params(self):
        user_id = self.create_user_session(player_id=1)
        with self.client.session_transaction() as sess:
            sess["user_id"] = user_id

        resp = self.client.get("/player/1?teammates=2&opponents=9")
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn("Performance Übersicht", html)
        self.assertIn("Persönliche Spielhistorie", html)


if __name__ == "__main__":
    unittest.main()
