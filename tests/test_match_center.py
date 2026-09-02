import os
import shutil
import subprocess
import time
import unittest

from scripts.accounts.auth import register_user
from scripts.accounts.database import get_accounts_connection, mark_email_verified, update_user_role
from scripts.glicko.glicko2 import TOTAL
from scripts.matchmaking.match_parser import normalize_player_name, resolve_player_names
from scripts.matchmaking.matchmaker import generate_match
from web.app import app


class MatchCenterFrontendTests(unittest.TestCase):
    def setUp(self):
        self.app = app
        unique_name = f"mc_admin_{int(time.time() * 1000000)}"
        self.admin_id, _ = register_user(unique_name, f"{unique_name}@example.com", "adminpass123", role="admin")
        conn = get_accounts_connection()
        try:
            mark_email_verified(conn, self.admin_id)
            update_user_role(conn, self.admin_id, "admin")
        finally:
            conn.close()

    def test_match_center_uses_one_frontend_implementation(self):
        with self.app.test_client() as client:
            with client.session_transaction() as sess:
                sess["user_id"] = self.admin_id

            response = client.get("/match-center")

            self.assertEqual(response.status_code, 200)
            self.assertIn(b"window.matchCenterPlayers", response.data)
            self.assertIn(b"match_center.css", response.data)
            self.assertIn(b"match_center.js", response.data)
            self.assertNotIn(b"add_player_modal.js", response.data)
            self.assertNotIn(b"match_save_feedback.js", response.data)
            self.assertNotIn(b"match_center_navigation.js", response.data)
            self.assertNotIn(b'id="use-imported"', response.data)
            self.assertNotIn(b'id="fairer-imported"', response.data)

            css_response = client.get("/static/match_center.css")
            js_response = client.get("/static/match_center.js")
            self.assertEqual(css_response.status_code, 200)
            self.assertEqual(js_response.status_code, 200)
            self.assertNotIn(b"var(--green)", css_response.data)
            self.assertNotIn(b"var(--green-dark)", css_response.data)
            css_response.close()
            js_response.close()

    def test_match_center_js_syntax_is_valid(self):
        node_path = shutil.which("node")
        if node_path:
            js_file = os.path.join(self.app.root_path, "static", "match_center.js")
            result = subprocess.run(
                [node_path, "-c", js_file],
                capture_output=True,
                text=True
            )
            self.assertEqual(
                result.returncode,
                0,
                f"JavaScript syntax error in match_center.js:\n{result.stderr}"
            )

    def test_normalize_player_name(self):
        self.assertEqual(normalize_player_name("[M] Daniel"), "Daniel")
        self.assertEqual(normalize_player_name("Daniel [M]"), "Daniel")
        self.assertEqual(normalize_player_name("  [m]  Konsti   Müller  "), "Konsti Müller")
        self.assertEqual(normalize_player_name("Dennis"), "Dennis")

    def test_resolve_player_names(self):
        players = {
            1: {"aliases": ["Daniel", "Dani"], "positions": ["MID"]},
            2: {"aliases": ["Konsti"], "positions": ["ATT"]},
            3: {"aliases": ["Konsti Müller"], "positions": ["DEF"]},
        }
        verified, conflicts, unmatched = resolve_player_names(["[M] Daniel", "Konsti", "Unknown Guy"], players)
        self.assertIn(1, verified)
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["name"], "Konsti")
        self.assertEqual(len(unmatched), 1)
        self.assertEqual(unmatched[0]["name"], "Unknown Guy")

    def test_matchmaker_generation(self):
        players = {
            1: {"aliases": ["Player 1"], "positions": ["GK"]},
            2: {"aliases": ["Player 2"], "positions": ["DEF"]},
            3: {"aliases": ["Player 3"], "positions": ["MID"]},
            4: {"aliases": ["Player 4"], "positions": ["ATT"]},
        }
        ratings = {
            1: {TOTAL: {"rating": 1500.0, "rd": 200.0, "sigma": 0.06}},
            2: {TOTAL: {"rating": 1520.0, "rd": 180.0, "sigma": 0.06}},
            3: {TOTAL: {"rating": 1480.0, "rd": 190.0, "sigma": 0.06}},
            4: {TOTAL: {"rating": 1500.0, "rd": 200.0, "sigma": 0.06}},
        }
        result = generate_match([1, 2, 3, 4], players, ratings, TOTAL, seed=42)
        self.assertIsNotNone(result)
        self.assertEqual(len(result["team_a"]) + len(result["team_b"]), 4)
        self.assertIn("rating_difference", result)
        self.assertIn("position_penalty", result)


if __name__ == "__main__":
    unittest.main()
