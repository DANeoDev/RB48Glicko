import os
from pathlib import Path
import shutil
import tempfile
import time
import unittest

from scripts.accounts.auth import register_user
from scripts.accounts.database import (
    approve_user,
    get_accounts_connection,
    mark_email_verified,
    update_user_role,
)
from scripts.database.database import get_connection as get_main_connection, main as init_database
from scripts.database.db_players import create_player, get_players, set_player_positions
from web.app import create_app


class PlayerPositionsTests(unittest.TestCase):
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

    def create_user(self, role="user"):
        u_name = f"user_{int(time.time() * 1000000)}"
        user_id, _ = register_user(u_name, f"{u_name}@example.com", "SecretPass123!")
        conn = get_accounts_connection()
        try:
            mark_email_verified(conn, user_id)
            approve_user(conn, user_id, approved=True)
            update_user_role(conn, user_id, role)
        finally:
            conn.close()
        return user_id

    def test_set_player_positions_database(self):
        conn = get_main_connection()
        try:
            create_player(conn, 99)

            # 1. Set GK and DEF with GK as primary
            set_player_positions(conn, 99, ["GK", "DEF"], primary_position="GK")
            players = get_players(conn)
            self.assertIn("GK*", players[99]["positions"])
            self.assertIn("DEF", players[99]["positions"])

            # 2. Overwrite with ATT only (no primary)
            set_player_positions(conn, 99, ["ATT"], primary_position=None)
            players2 = get_players(conn)
            self.assertEqual(players2[99]["positions"], ["ATT"])

            # 3. Clear all positions
            set_player_positions(conn, 99, [], primary_position=None)
            players3 = get_players(conn)
            self.assertEqual(players3[99]["positions"], [])
        finally:
            conn.close()

    def test_admin_player_positions_authorization_and_ajax(self):
        user_id = self.create_user("user")
        admin_id = self.create_user("admin")
        webmaster_id = self.create_user("webmaster")

        conn = get_main_connection()
        try:
            create_player(conn, 101)
            conn.commit()
        finally:
            conn.close()

        # Anonymous -> 302
        res_anon = self.client.get("/admin/player-positions")
        self.assertEqual(res_anon.status_code, 302)

        # User -> 302
        with self.client.session_transaction() as sess:
            sess["user_id"] = user_id
        res_user = self.client.get("/admin/player-positions")
        self.assertEqual(res_user.status_code, 302)

        # Admin -> 302 (Webmaster-exclusive feature)
        with self.client.session_transaction() as sess:
            sess["user_id"] = admin_id
        res_admin = self.client.get("/admin/player-positions")
        self.assertEqual(res_admin.status_code, 302)

        # Webmaster -> 200 HTML
        with self.client.session_transaction() as sess:
            sess["user_id"] = webmaster_id
        res_wm = self.client.get("/admin/player-positions")
        self.assertEqual(res_wm.status_code, 200)
        self.assertIn(b"Spielerpositionen", res_wm.data)

        # Webmaster POST AJAX -> 200 JSON
        res_post = self.client.post(
            "/admin/player-positions",
            json={
                "player_id": 101,
                "positions": ["MID", "ATT"],
                "primary_position": "MID",
            },
        )
        self.assertEqual(res_post.status_code, 200)
        data = res_post.get_json()
        self.assertTrue(data.get("success"))

        # Verify in DB
        conn = get_main_connection()
        try:
            players = get_players(conn)
            self.assertIn("MID*", players[101]["positions"])
            self.assertIn("ATT", players[101]["positions"])
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
