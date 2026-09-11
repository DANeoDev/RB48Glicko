import json
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
from scripts.glicko.glicko2_calculator import recalculate_glicko2_ratings
from scripts.matches.match_entry import add_match, delete_match, get_matches_dir, get_match_backup_dir
from web.app import app


class BackupAndRecalcTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)

        self.test_accounts_db = self.temp_path / "test_accounts.db"
        self.test_rb48_db = self.temp_path / "test_rb48.db"
        self.test_db_backups = self.temp_path / "db_backups"
        self.test_matches_dir = self.temp_path / "matches"
        self.test_match_backups = self.temp_path / "match_backups"

        self.test_db_backups.mkdir(parents=True, exist_ok=True)
        self.test_matches_dir.mkdir(parents=True, exist_ok=True)
        self.test_match_backups.mkdir(parents=True, exist_ok=True)

        prod_rb48 = Path(__file__).resolve().parents[1] / "data" / "rb48.db"
        if prod_rb48.exists():
            shutil.copy2(prod_rb48, self.test_rb48_db)

        os.environ["RB48_ACCOUNTS_DATABASE_FILE"] = str(self.test_accounts_db)
        os.environ["RB48_DATABASE_FILE"] = str(self.test_rb48_db)
        os.environ["RB48_DATABASE_BACKUP_DIR"] = str(self.test_db_backups)
        os.environ["RB48_MATCHES_DIR"] = str(self.test_matches_dir)
        os.environ["RB48_MATCH_BACKUP_DIR"] = str(self.test_match_backups)

        self.client = app.test_client()

    def tearDown(self):
        os.environ.pop("RB48_ACCOUNTS_DATABASE_FILE", None)
        os.environ.pop("RB48_DATABASE_FILE", None)
        os.environ.pop("RB48_DATABASE_BACKUP_DIR", None)
        os.environ.pop("RB48_MATCHES_DIR", None)
        os.environ.pop("RB48_MATCH_BACKUP_DIR", None)
        self.temp_dir.cleanup()

    def create_user_session(self, role="user", verified=True, approved=True, psychology_passed=True):
        unique_name = f"recalc_u_{int(time.time() * 1000000)}"
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
        finally:
            connection.close()

        if psychology_passed:
            pass_psychology_test(user_id)

        return user_id

    def test_recalculate_glicko2_ratings_creates_backup_and_updates_db(self):
        result = recalculate_glicko2_ratings(create_backup=True)
        self.assertTrue(result["success"])
        self.assertIsNotNone(result["backup_file"])
        self.assertGreater(result["matches_count"], 0)
        self.assertGreater(result["players_count"], 0)

        # Verify backup was created in configured directory
        backup_path = self.test_db_backups / result["backup_file"]
        self.assertTrue(backup_path.exists())
        self.assertGreater(backup_path.stat().st_size, 0)

        # Verify ratings exist in database
        conn = get_connection()
        try:
            ratings_count = conn.execute("SELECT count(*) FROM ratings").fetchone()[0]
            self.assertGreater(ratings_count, 0)
        finally:
            conn.close()

    def test_delete_match_creates_csv_backup_and_audit_log(self):
        conn = get_connection()
        try:
            players = get_players(conn)
            pids = list(players.keys())[:2]
            match_id = add_match(
                conn,
                "2026-11-25",
                "box",
                [pids[0]],
                [pids[1]],
                7,
                5,
            )
        finally:
            conn.close()

        # Check that matchday CSV was written to test_matches_dir
        match_csv = self.test_matches_dir / "2026-11-25.csv"
        self.assertTrue(match_csv.exists())
        content_before = match_csv.read_text(encoding="utf-8")
        self.assertIn(match_id, content_before)

        # Delete the match
        conn = get_connection()
        try:
            del_result = delete_match(conn, match_id)
            self.assertTrue(del_result["success"])
            self.assertEqual(del_result["match_id"], match_id)
            self.assertIsNotNone(del_result["backup_file"])
        finally:
            conn.close()

        # Verify CSV backup file exists in test_match_backups
        backup_csv = self.test_match_backups / del_result["backup_file"]
        self.assertTrue(backup_csv.exists())
        self.assertIn(match_id, backup_csv.read_text(encoding="utf-8"))

        # Verify audit log exists
        audit_csv = self.test_match_backups / "deleted_matches.csv"
        self.assertTrue(audit_csv.exists())
        audit_text = audit_csv.read_text(encoding="utf-8")
        self.assertIn(match_id, audit_text)
        self.assertIn("2026-11-25", audit_text)
        self.assertIn(del_result["backup_file"], audit_text)

        # Verify match no longer in DB
        conn = get_connection()
        try:
            row = conn.execute("SELECT 1 FROM matches WHERE match_id = ?", (match_id,)).fetchone()
            self.assertIsNone(row)
        finally:
            conn.close()

    def test_recalculate_endpoint_tier_security(self):
        # 1. Unauthenticated visitor -> redirect to login
        res_visitor = self.client.post("/admin/recalculate-glicko")
        self.assertEqual(res_visitor.status_code, 302)
        self.assertIn("/login", res_visitor.headers.get("Location", ""))

        # 2. Regular user (Tier.USER) -> redirect / denied
        user_id = self.create_user_session(role="user")
        with self.client.session_transaction() as sess:
            sess["user_id"] = user_id
        res_user = self.client.post("/admin/recalculate-glicko")
        self.assertEqual(res_user.status_code, 302)

        # 3. Admin user (Tier.ADMIN) -> denied (strict Webmaster requirement)
        admin_id = self.create_user_session(role="admin")
        with self.client.session_transaction() as sess:
            sess["user_id"] = admin_id
        res_admin = self.client.post("/admin/recalculate-glicko")
        self.assertEqual(res_admin.status_code, 302)

        # 4. Webmaster user (Tier.WEBMASTER) via XHR -> 200 JSON with backup_file
        wm_id = self.create_user_session(role="webmaster")
        with self.client.session_transaction() as sess:
            sess["user_id"] = wm_id
        res_wm_xhr = self.client.post(
            "/admin/recalculate-glicko",
            headers={"X-Requested-With": "XMLHttpRequest"}
        )
        self.assertEqual(res_wm_xhr.status_code, 200)
        data = res_wm_xhr.get_json()
        self.assertTrue(data.get("success"))
        self.assertIsNotNone(data.get("backup_file"))
        self.assertGreater(data.get("matches_count", 0), 0)

        # Check backup file exists
        backup_path = self.test_db_backups / data["backup_file"]
        self.assertTrue(backup_path.exists())

        # 5. Webmaster form POST -> 302 with flash redirect
        res_wm_form = self.client.post("/admin/recalculate-glicko", follow_redirects=True)
        self.assertEqual(res_wm_form.status_code, 200)
        self.assertIn("Glicko-2 Tabelle erfolgreich neu berechnet", res_wm_form.get_data(as_text=True))

    def test_delete_match_endpoint_returns_backup_details(self):
        conn = get_connection()
        try:
            players = get_players(conn)
            pids = list(players.keys())[:2]
            match_id = add_match(
                conn,
                "2026-11-26",
                "box",
                [pids[0]],
                [pids[1]],
                4,
                2,
            )
        finally:
            conn.close()

        admin_id = self.create_user_session(role="admin")
        with self.client.session_transaction() as sess:
            sess["user_id"] = admin_id

        res = self.client.post(
            "/matches/delete",
            data=json.dumps({"match_id": match_id}),
            content_type="application/json",
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data.get("deleted_match_id"), match_id)
        self.assertIsNotNone(data.get("backup_file"))
        self.assertTrue((self.test_match_backups / data["backup_file"]).exists())

    def test_recalculate_button_location(self):
        # Visitor on /matches and /stats
        res_matches_vis = self.client.get("/matches")
        self.assertNotIn("btn-open-recalc-modal", res_matches_vis.get_data(as_text=True))
        res_stats_vis = self.client.get("/stats")
        self.assertNotIn("btn-open-recalc-modal", res_stats_vis.get_data(as_text=True))

        # Webmaster session
        wm_id = self.create_user_session(role="webmaster")
        with self.client.session_transaction() as sess:
            sess["user_id"] = wm_id

        # 1. Matches page must NOT have recalculate button
        res_matches_wm = self.client.get("/matches")
        self.assertNotIn("btn-open-recalc-modal", res_matches_wm.get_data(as_text=True))

        # 2. Stats page (default Glicko) MUST have recalculate button and modal
        res_stats_wm = self.client.get("/stats")
        self.assertIn("btn-open-recalc-modal", res_stats_wm.get_data(as_text=True))
        self.assertIn("recalc-glicko-modal", res_stats_wm.get_data(as_text=True))

        # 3. Stats page with WHR active model in session must NOT have Glicko recalculate button
        with self.client.session_transaction() as sess:
            sess["active_model"] = "whr"
        res_stats_whr = self.client.get("/stats")
        self.assertNotIn("btn-open-recalc-modal", res_stats_whr.get_data(as_text=True))
        self.assertNotIn("recalc-glicko-modal", res_stats_whr.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()

