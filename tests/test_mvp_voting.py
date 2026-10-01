from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
import unittest
from zoneinfo import ZoneInfo

from scripts.accounts.auth import register_user
from scripts.accounts.database import (
    approve_user,
    get_accounts_connection,
    get_match_mvp_deadline,
    get_match_mvp_winners,
    get_user_match_mvp_vote,
    get_user_mvp_votes_for_matches,
    is_match_mvp_voting_open,
    link_user_to_player,
    mark_email_verified,
    record_match_mvp_vote,
    update_user_role,
)
from scripts.database.database import get_connection, main as init_database
from web.app import create_app
from web.services.cache import invalidate_stats_cache


class MvpVotingTests(unittest.TestCase):
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

    def create_user(self, role="user", linked_player_id=None):
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
            conn.commit()
        finally:
            conn.close()
        return user_id, u_name

    def login_user(self, user_id):
        with self.client.session_transaction() as sess:
            sess["user_id"] = user_id

    def test_deadline_calculation_and_open_status(self):
        # 1. Check deadline logic
        deadline = get_match_mvp_deadline("2026-05-10")
        self.assertEqual(deadline.year, 2026)
        self.assertEqual(deadline.month, 5)
        self.assertEqual(deadline.day, 11)
        self.assertEqual(deadline.hour, 20)
        self.assertEqual(deadline.minute, 0)
        self.assertEqual(deadline.tzinfo, ZoneInfo("Europe/Berlin"))

        # Past match is closed
        self.assertFalse(is_match_mvp_voting_open("2020-01-01"))

        # Future match is open
        tz = ZoneInfo("Europe/Berlin")
        today_str = datetime.now(tz).strftime("%Y-%m-%d")
        self.assertTrue(is_match_mvp_voting_open(today_str))

    def test_database_vote_recording_upsert_and_winners(self):
        u1, _ = self.create_user()
        u2, _ = self.create_user()
        u3, _ = self.create_user()
        u4, _ = self.create_user()

        conn = get_accounts_connection()
        try:
            # User 1 votes for player 100
            vote_id = record_match_mvp_vote(conn, "M001", u1, 100)
            self.assertIsNotNone(vote_id)

            # Check user 1's vote
            voted = get_user_match_mvp_vote(conn, "M001", u1)
            self.assertEqual(voted, 100)

            # User 1 changes vote to player 200 (upsert)
            record_match_mvp_vote(conn, "M001", u1, 200)
            voted_updated = get_user_match_mvp_vote(conn, "M001", u1)
            self.assertEqual(voted_updated, 200)

            # User 2 votes for player 200
            record_match_mvp_vote(conn, "M001", u2, 200)

            # User 3 votes for player 300
            record_match_mvp_vote(conn, "M001", u3, 300)

            # Check batch votes for user 1
            votes_map = get_user_mvp_votes_for_matches(conn, u1, ["M001", "M002"])
            self.assertEqual(votes_map, {"M001": [200]})

            # Check winner: Player 200 has 2 votes, Player 300 has 1 vote -> Player 200 wins
            winners = get_match_mvp_winners(conn, ["M001"])
            self.assertEqual(winners.get("M001"), [200])

            # Test tie: User 4 votes for player 300 -> 2 votes each
            record_match_mvp_vote(conn, "M001", u4, 300)
            tied_winners = get_match_mvp_winners(conn, ["M001"])
            self.assertEqual(sorted(tied_winners.get("M001")), [200, 300])
        finally:
            conn.close()

    def ensure_player(self, main_conn, player_id, name):
        main_conn.execute("INSERT OR IGNORE INTO players (player_id) VALUES (?)", (player_id,))
        main_conn.execute("INSERT OR REPLACE INTO aliases (alias, player_id) VALUES (?, ?)", (name, player_id))
        main_conn.commit()

    def test_api_auth_and_eligibility(self):
        # Insert a test match in rb48.db
        main_conn = get_connection()
        tz = ZoneInfo("Europe/Berlin")
        today_str = datetime.now(tz).strftime("%Y-%m-%d")
        test_mid = "TEST_MVP_01"
        try:
            for pid in (101, 102, 103, 104, 999):
                self.ensure_player(main_conn, pid, f"P_{pid}")
            main_conn.execute("INSERT OR REPLACE INTO matches (match_id, date, pitch, players_a, players_b, goals_a, goals_b) VALUES (?, ?, 'box', 2, 2, 5, 3)", (test_mid, today_str))
            # Players: 101, 102 in Team A; 103, 104 in Team B
            main_conn.execute("DELETE FROM match_players WHERE match_id = ?", (test_mid,))
            main_conn.execute("INSERT INTO match_players (match_id, player_id, team) VALUES (?, 101, 'a')", (test_mid,))
            main_conn.execute("INSERT INTO match_players (match_id, player_id, team) VALUES (?, 102, 'a')", (test_mid,))
            main_conn.execute("INSERT INTO match_players (match_id, player_id, team) VALUES (?, 103, 'b')", (test_mid,))
            main_conn.execute("INSERT INTO match_players (match_id, player_id, team) VALUES (?, 104, 'b')", (test_mid,))
            main_conn.commit()
        finally:
            main_conn.close()

        # 1. Unauthenticated vote -> 401
        res = self.client.post(f"/api/matches/{test_mid}/mvp-vote", json={"voted_player_id": 101})
        self.assertEqual(res.status_code, 401)

        # 2. Authenticated user without linked player -> 403
        uid_unlinked, _ = self.create_user(role="user", linked_player_id=None)
        self.login_user(uid_unlinked)
        res = self.client.post(f"/api/matches/{test_mid}/mvp-vote", json={"voted_player_id": 101})
        self.assertEqual(res.status_code, 403)
        self.assertIn("verknüpft", res.get_json()["error"])

        # 3. Authenticated user linked to non-participating player (999) -> 403
        uid_non_part, _ = self.create_user(role="user", linked_player_id=999)
        self.login_user(uid_non_part)
        res = self.client.post(f"/api/matches/{test_mid}/mvp-vote", json={"voted_player_id": 101})
        self.assertEqual(res.status_code, 403)
        self.assertIn("teilgenommen", res.get_json()["error"])

        # 4. Authenticated participant (player 101) votes for non-participant (999) -> 400
        uid_part, _ = self.create_user(role="user", linked_player_id=101)
        self.login_user(uid_part)
        res = self.client.post(f"/api/matches/{test_mid}/mvp-vote", json={"voted_player_id": 999})
        self.assertEqual(res.status_code, 400)
        self.assertIn("teilgenommen", res.get_json()["error"])

        # 5. Valid vote for participant 103 -> 200
        res = self.client.post(f"/api/matches/{test_mid}/mvp-vote", json={"voted_player_id": 103})
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()["success"])

        # 6. Check status endpoint for participant
        res_status = self.client.get(f"/api/matches/{test_mid}/mvp-status")
        self.assertEqual(res_status.status_code, 200)
        data = res_status.get_json()
        self.assertTrue(data["is_open"])
        self.assertTrue(data["can_vote"])
        self.assertEqual(data["user_vote"], 103)
        # Winners should be hidden while voting is still open
        self.assertEqual(data["mvp_player_ids"], [])

    def test_past_match_voting_closed(self):
        # Create an old match from 2023
        main_conn = get_connection()
        test_mid = "TEST_MVP_OLD"
        try:
            self.ensure_player(main_conn, 101, "P_101")
            self.ensure_player(main_conn, 102, "P_102")
            main_conn.execute("INSERT OR REPLACE INTO matches (match_id, date, pitch, players_a, players_b, goals_a, goals_b) VALUES (?, '2023-05-01', 'box', 1, 1, 4, 4)", (test_mid,))
            main_conn.execute("DELETE FROM match_players WHERE match_id = ?", (test_mid,))
            main_conn.execute("INSERT INTO match_players (match_id, player_id, team) VALUES (?, 101, 'a')", (test_mid,))
            main_conn.execute("INSERT INTO match_players (match_id, player_id, team) VALUES (?, 102, 'b')", (test_mid,))
            main_conn.commit()
        finally:
            main_conn.close()

        # Seed an old vote directly in accounts db
        u_seed, _ = self.create_user()
        acc_conn = get_accounts_connection()
        try:
            record_match_mvp_vote(acc_conn, test_mid, u_seed, 102)
        finally:
            acc_conn.close()

        uid_part, _ = self.create_user(role="user", linked_player_id=101)
        self.login_user(uid_part)

        # Attempt to vote on closed match -> 400
        res = self.client.post(f"/api/matches/{test_mid}/mvp-vote", json={"voted_player_id": 102})
        self.assertEqual(res.status_code, 400)
        self.assertIn("beendet", res.get_json()["error"])

        # Status endpoint shows voting is closed and reveals winner 102
        res_status = self.client.get(f"/api/matches/{test_mid}/mvp-status")
        self.assertEqual(res_status.status_code, 200)
        data = res_status.get_json()
        self.assertFalse(data["is_open"])
        self.assertFalse(data["can_vote"])
        self.assertEqual(data["mvp_player_ids"], [102])

        # Verify /matches renders golden MVP star for closed match winner
        res_matches = self.client.get("/matches")
        self.assertEqual(res_matches.status_code, 200)
        html = res_matches.get_data(as_text=True)
        self.assertTrue("match-player-gold" in html or "match-player-mvp" in html)
        self.assertIn("mvp-star", html)


    def test_anonymity_and_ui_rendering(self):
        # Create an active match
        main_conn = get_connection()
        tz = ZoneInfo("Europe/Berlin")
        today_str = datetime.now(tz).strftime("%Y-%m-%d")
        test_mid = "TEST_MVP_ANON"
        try:
            self.ensure_player(main_conn, 201, "Player Alpha")
            self.ensure_player(main_conn, 202, "Player Beta")
            main_conn.execute("INSERT OR REPLACE INTO matches (match_id, date, pitch, players_a, players_b, goals_a, goals_b) VALUES (?, ?, 'box', 1, 1, 3, 2)", (test_mid, today_str))
            main_conn.execute("DELETE FROM match_players WHERE match_id = ?", (test_mid,))
            main_conn.execute("INSERT INTO match_players (match_id, player_id, team) VALUES (?, 201, 'a')", (test_mid,))
            main_conn.execute("INSERT INTO match_players (match_id, player_id, team) VALUES (?, 202, 'b')", (test_mid,))
            main_conn.commit()
        finally:
            main_conn.close()
        invalidate_stats_cache()

        # User 1 linked to player 201 votes for player 202
        u1, _ = self.create_user(role="user", linked_player_id=201)
        self.login_user(u1)
        res = self.client.post(f"/api/matches/{test_mid}/mvp-vote", json={"voted_player_id": 202})
        self.assertEqual(res.status_code, 200)

        # User 2 linked to player 202 checks status -> sees their own vote is None, cannot see who u1 voted for
        u2, _ = self.create_user(role="user", linked_player_id=202)
        self.login_user(u2)
        res_status = self.client.get(f"/api/matches/{test_mid}/mvp-status")
        data = res_status.get_json()
        self.assertIsNone(data["user_vote"])
        # No voter user IDs in response
        self.assertNotIn("voter_user_id", json.dumps(data))
        self.assertEqual(set(data.keys()), {
            "can_vote", "deadline_formatted", "deadline_iso", "is_open",
            "match_date", "match_id", "mvp_player_ids", "gold_player_ids",
            "silver_player_ids", "bronze_player_ids", "success",
            "team_a_players", "team_b_players", "user_vote", "user_votes"
        })

        # Check match history HTML rendering
        res_matches = self.client.get("/matches")
        self.assertEqual(res_matches.status_code, 200)
        html = res_matches.get_data(as_text=True)
        # Should have MVP vote button and banner
        self.assertIn("match-mvp-btn", html)
        self.assertIn("match-mvp-banner", html)

