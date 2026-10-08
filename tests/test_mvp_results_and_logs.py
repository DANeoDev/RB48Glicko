import json
import os
from pathlib import Path
import shutil
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from scripts.accounts.auth import register_user
from scripts.accounts.database import (
    approve_user,
    get_accounts_connection,
    link_user_to_player,
    mark_email_verified,
    record_match_mvp_votes,
    update_user_role,
    get_mvp_voter_activity_logs,
    get_match_mvp_results,
    get_all_matches_mvp_summaries,
    get_mvp_medal_table,
)
from scripts.database.database import get_connection, main as init_database
from scripts.database.db_matches import get_matches
from scripts.database.db_players import get_players
from web.app import create_app
from web.services.cache import invalidate_stats_cache


class MvpResultsAndLogsTests(unittest.TestCase):
    def setUp(self):
        invalidate_stats_cache()
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
        invalidate_stats_cache()
        os.environ.pop("RB48_DATABASE_FILE", None)
        os.environ.pop("RB48_ACCOUNTS_DATABASE_FILE", None)
        self.temp_dir.cleanup()

    def create_user(self, role="user", linked_player_id=None, attendance_name=""):
        u_name = f"user_{int(time.time() * 1000000)}_{os.urandom(2).hex()}"
        user_id, _ = register_user(u_name, f"{u_name}@example.com", "SecretPass123!")
        conn = get_accounts_connection()
        try:
            mark_email_verified(conn, user_id)
            approve_user(conn, user_id, approved=True)
            update_user_role(conn, user_id, role)
            conn.execute("UPDATE users SET psychology_test_passed = 1 WHERE id = ?", (user_id,))
            if linked_player_id:
                link_user_to_player(conn, user_id, linked_player_id)
            if attendance_name:
                conn.execute("UPDATE users SET attendance_name = ? WHERE id = ?", (attendance_name, user_id))
            conn.commit()
        finally:
            conn.close()
        return user_id, u_name

    def login_user(self, user_id):
        with self.client.session_transaction() as sess:
            sess["user_id"] = user_id

    def test_mvp_voter_activity_logs_strict_anonymity(self):
        """Webmaster activity logs must reveal WHO voted and WHEN, but STRICTLY NEVER which candidates they chose."""
        u1_id, u1_name = self.create_user(role="user", attendance_name="Voter One")
        u2_id, u2_name = self.create_user(role="user", attendance_name="Voter Two")

        conn = get_accounts_connection()
        try:
            record_match_mvp_votes(conn, "2026-07-08-1", u1_id, [1, 2, 3])
            record_match_mvp_votes(conn, "2026-07-08-1", u2_id, [2, 1])

            logs = get_mvp_voter_activity_logs(conn, limit=10)
            self.assertEqual(len(logs), 2)

            for entry in logs:
                self.assertIn("voter_user_id", entry)
                self.assertIn("username", entry)
                self.assertIn("match_id", entry)
                self.assertIn("created_at", entry)
                self.assertIn("attendance_name", entry)

                # STRICT INVARIANT: Ensure candidate choices are NEVER present in voter activity logs
                self.assertNotIn("voted_player_id", entry)
                self.assertNotIn("voted_player_id_2", entry)
                self.assertNotIn("voted_player_id_3", entry)
                self.assertNotIn("candidate_id", entry)
                self.assertNotIn("candidates", entry)

            usernames = [entry["username"] for entry in logs]
            self.assertIn(u1_name, usernames)
            self.assertIn(u2_name, usernames)
        finally:
            conn.close()

    def test_get_match_mvp_results_and_podium(self):
        """Test match election results aggregate correctly and return medals without individual voter linkages."""
        u1_id, _ = self.create_user(role="user")
        u2_id, _ = self.create_user(role="user")
        u3_id, _ = self.create_user(role="user")

        conn = get_accounts_connection()
        main_conn = get_connection()
        try:
            players = get_players(main_conn)

            # u1 votes: 1 (Gold), 2 (Silver), 3 (Bronze)
            record_match_mvp_votes(conn, "2026-07-08-1", u1_id, [1, 2, 3])
            # u2 votes: 1 (Gold), 3 (Silver)
            record_match_mvp_votes(conn, "2026-07-08-1", u2_id, [1, 3])
            # u3 votes: 2 (Gold), 1 (Silver)
            record_match_mvp_votes(conn, "2026-07-08-1", u3_id, [2, 1])

            results = get_match_mvp_results(conn, "2026-07-08-1", players_dict=players)
            self.assertEqual(results["match_id"], "2026-07-08-1")
            self.assertEqual(results["total_voters"], 3)

            candidates = results["candidates"]
            self.assertTrue(len(candidates) >= 3)

            # Candidate 1: 3 votes (2x rank1, 1x rank2) -> Gold winner
            p1 = next(c for c in candidates if c["player_id"] == 1)
            self.assertEqual(p1["total_votes"], 3)
            self.assertEqual(p1["rank1"], 2)
            self.assertEqual(p1["rank2"], 1)
            self.assertEqual(p1["medal"], "gold")
            self.assertEqual(p1["rank"], 1)

            # Check that results contains anonymous ballots
            self.assertIn("ballots", results)
            self.assertEqual(len(results["ballots"]), 3)
            for b in results["ballots"]:
                self.assertIn("ballot_number", b)
                self.assertIn("rank1", b)
                self.assertNotIn("voter_user_id", b)
                self.assertNotIn("created_at", b)

            # Check that results contains NO voter references
            self.assertNotIn("voters", results)
            self.assertNotIn("voter_user_id", results)
        finally:
            conn.close()
            main_conn.close()

    def test_get_all_matches_mvp_summaries(self):
        """Test multi-match election summaries for webmaster dashboard."""
        u1_id, _ = self.create_user(role="user")
        conn = get_accounts_connection()
        main_conn = get_connection()
        try:
            players = get_players(main_conn)
            record_match_mvp_votes(conn, "2026-07-08-1", u1_id, [1, 2])
            record_match_mvp_votes(conn, "2026-07-15-1", u1_id, [3])

            summaries = get_all_matches_mvp_summaries(conn, players_dict=players)
            self.assertEqual(len(summaries), 2)
            m_ids = [s["match_id"] for s in summaries]
            self.assertIn("2026-07-08-1", m_ids)
            self.assertIn("2026-07-15-1", m_ids)

            for s in summaries:
                self.assertIn("voter_count", s)
                self.assertIn("candidates", s)
                self.assertIn("gold_names", s)
        finally:
            conn.close()
            main_conn.close()

    def test_api_mvp_results_endpoint(self):
        """Test GET /api/matches/<match_id>/mvp-results endpoint."""
        # Non-existent match returns 404
        res = self.client.get("/api/matches/9999-99-99-1/mvp-results")
        self.assertEqual(res.status_code, 404)

        # 2026-07-08-1 is a past match, voting is closed
        u1_id, _ = self.create_user(role="user")
        conn = get_accounts_connection()
        try:
            record_match_mvp_votes(conn, "2026-07-08-1", u1_id, [1])
        finally:
            conn.close()

        res = self.client.get("/api/matches/2026-07-08-1/mvp-results")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["match_id"], "2026-07-08-1")
        self.assertFalse(data["is_open"])
        self.assertEqual(data["total_voters"], 1)
        self.assertEqual(len(data["candidates"]), 1)
        self.assertEqual(data["candidates"][0]["player_id"], 1)
        self.assertEqual(data["candidates"][0]["medal"], "gold")
        self.assertIn("ballots", data)
        self.assertEqual(len(data["ballots"]), 1)
        self.assertEqual(data["ballots"][0]["ballot_number"], 1)
        self.assertEqual(data["ballots"][0]["rank1"]["player_id"], 1)

    def test_admin_users_mvp_tabs(self):
        """Test that Webmasters see User Management on default tab and MVP Logs on mvp tab."""
        wm_id, wm_name = self.create_user(role="webmaster")
        u_id, u_name = self.create_user(role="user")

        # Cast a vote to populate logs
        conn = get_accounts_connection()
        try:
            record_match_mvp_votes(conn, "2026-07-08-1", u_id, [1, 2])
        finally:
            conn.close()

        # Regular user cannot access /admin/users or /admin/mvp-logs
        self.login_user(u_id)
        res_user = self.client.get("/admin/users")
        self.assertIn(res_user.status_code, (302, 403))
        res_user_mvp = self.client.get("/admin/mvp-logs")
        self.assertIn(res_user_mvp.status_code, (302, 403))

        # Webmaster on /admin/users sees User Management table
        self.login_user(wm_id)
        res_wm_users = self.client.get("/admin/users")
        self.assertEqual(res_wm_users.status_code, 200)
        self.assertIn(b"User Management", res_wm_users.data)
        self.assertNotIn(b"Abstimmungs-Aktivit", res_wm_users.data)

        # Webmaster on /admin/mvp-logs or /admin/users?tab=mvp sees MVP election results, strictly NO voter activity logs and NO user names
        res_wm_mvp = self.client.get("/admin/mvp-logs")
        self.assertEqual(res_wm_mvp.status_code, 200)
        self.assertIn("Match-Wahlergebnisse".encode("utf-8"), res_wm_mvp.data)
        self.assertNotIn(u_name.encode("utf-8"), res_wm_mvp.data)
        self.assertNotIn(b"confirm_delete", res_wm_mvp.data)

        res_wm_mvp2 = self.client.get("/admin/users?tab=mvp")
        self.assertEqual(res_wm_mvp2.status_code, 200)
        self.assertIn("Match-Wahlergebnisse".encode("utf-8"), res_wm_mvp2.data)
        self.assertNotIn(u_name.encode("utf-8"), res_wm_mvp2.data)

    def test_medaillenspiegel_excludes_open_voting_matches(self):
        """Matches with voting currently open must NOT show up in MVP-Medaillenspiegel."""
        u_id, _ = self.create_user(role="user")
        today_str = datetime.now(ZoneInfo("Europe/Berlin")).strftime("%Y-%m-%d")
        conn = get_accounts_connection()
        try:
            # Active match (today)
            record_match_mvp_votes(conn, "today-1", u_id, [10])
            # Closed match (2026-07-08)
            record_match_mvp_votes(conn, "closed-1", u_id, [20])

            matches_dict = {
                "today-1": {"date": today_str},
                "closed-1": {"date": "2026-07-08"},
            }

            table = get_mvp_medal_table(conn, matches_dict)
            pids = [entry["player_id"] for entry in table]
            self.assertIn(20, pids)
            self.assertNotIn(10, pids)
        finally:
            conn.close()

    def test_win_probabilities_sum_to_100(self):
        """Win probabilities in calculate_match_details must sum exactly to 1.0 (100%)."""
        from scripts.frontend.view_models import calculate_match_details
        from scripts.glicko.glicko2 import TOTAL
        match = {
            "date": "2026-07-08",
            "goals_a": 5,
            "goals_b": 3,
            "players_a": 2,
            "players_b": 2,
        }
        team_a = [1, 2]
        team_b = [3, 4]
        ratings = {
            1: {TOTAL: {"rating": 1600.0, "rd": 80.0, "sigma": 0.06}},
            2: {TOTAL: {"rating": 1550.0, "rd": 120.0, "sigma": 0.06}},
            3: {TOTAL: {"rating": 1400.0, "rd": 300.0, "sigma": 0.06}},
            4: {TOTAL: {"rating": 1350.0, "rd": 280.0, "sigma": 0.06}},
        }
        details = calculate_match_details(match, team_a, team_b, ratings, TOTAL)
        self.assertIsNotNone(details["team_a_expected"])
        self.assertIsNotNone(details["team_b_expected"])
        self.assertAlmostEqual(details["team_a_expected"] + details["team_b_expected"], 1.0, places=6)

    def test_matches_page_shows_results_button_when_votes_exist(self):
        """Expired matches with votes must display the MVP results button."""
        u_id, _ = self.create_user(role="user")
        conn = get_accounts_connection()
        try:
            record_match_mvp_votes(conn, "2026-09-02-2", u_id, [1])
        finally:
            conn.close()

        res = self.client.get("/matches")
        self.assertEqual(res.status_code, 200)
        # Should contain match-mvp-btn results button with openMvpResultsModal call
        self.assertIn(b"openMvpResultsModal", res.data)
        self.assertIn(b"match-mvp-btn results", res.data)


if __name__ == "__main__":
    unittest.main()
