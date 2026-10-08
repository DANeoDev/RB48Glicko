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
            "team_a_players", "team_b_players", "user_vote", "user_votes",
            "is_box_session", "box_matches", "canonical_match_id", "box_players",
            "restriction_reason",
        })

        # Check match history HTML rendering
        res_matches = self.client.get("/matches")
        self.assertEqual(res_matches.status_code, 200)
        html = res_matches.get_data(as_text=True)
        # Should have MVP vote button and banner
        self.assertIn("match-mvp-btn", html)
        self.assertIn("match-mvp-banner", html)

    def test_self_voting_disallowed_api_and_db(self):
        """Users must strictly never be allowed to vote for themselves as MVP (neither slot 1, 2, nor 3)."""
        main_conn = get_connection()
        tz = ZoneInfo("Europe/Berlin")
        today_str = datetime.now(tz).strftime("%Y-%m-%d")
        test_mid = "TEST_SELF_VOTE"
        try:
            self.ensure_player(main_conn, 301, "Self Voter")
            self.ensure_player(main_conn, 302, "Teammate One")
            self.ensure_player(main_conn, 303, "Opponent One")
            main_conn.execute("INSERT OR REPLACE INTO matches (match_id, date, pitch, players_a, players_b, goals_a, goals_b) VALUES (?, ?, 'hf', 2, 1, 3, 1)", (test_mid, today_str))
            main_conn.execute("DELETE FROM match_players WHERE match_id = ?", (test_mid,))
            main_conn.execute("INSERT INTO match_players (match_id, player_id, team) VALUES (?, 301, 'a')", (test_mid,))
            main_conn.execute("INSERT INTO match_players (match_id, player_id, team) VALUES (?, 302, 'a')", (test_mid,))
            main_conn.execute("INSERT INTO match_players (match_id, player_id, team) VALUES (?, 303, 'b')", (test_mid,))
            main_conn.commit()
        finally:
            main_conn.close()

        u_self, _ = self.create_user(role="user", linked_player_id=301)
        self.login_user(u_self)

        # 1. Self-voting in slot 1 is rejected with 400
        res1 = self.client.post(f"/api/matches/{test_mid}/mvp-vote", json={"voted_player_id": 301})
        self.assertEqual(res1.status_code, 400)
        self.assertIn("selbst", res1.get_json()["error"])

        # 2. Self-voting in slot 2 is rejected with 400
        res2 = self.client.post(f"/api/matches/{test_mid}/mvp-vote", json={"voted_player_ids": [302, 301]})
        self.assertEqual(res2.status_code, 400)
        self.assertIn("selbst", res2.get_json()["error"])

        # 3. Self-voting directly in database function raises ValueError
        acc_conn = get_accounts_connection()
        try:
            with self.assertRaises(ValueError) as ctx:
                record_match_mvp_vote(acc_conn, test_mid, u_self, 301)
            self.assertIn("selbst", str(ctx.exception))
        finally:
            acc_conn.close()

        # 4. Status endpoint excludes the current user from selectable candidates
        res_status = self.client.get(f"/api/matches/{test_mid}/mvp-status")
        data = res_status.get_json()
        cand_ids = [p["id"] for p in data["team_a_players"]] + [p["id"] for p in data["team_b_players"]]
        self.assertNotIn(301, cand_ids)
        self.assertIn(302, cand_ids)
        self.assertIn(303, cand_ids)

        # 5. Legitimate vote for teammate succeeds
        res_ok = self.client.post(f"/api/matches/{test_mid}/mvp-vote", json={"voted_player_id": 302})
        self.assertEqual(res_ok.status_code, 200)

    def test_box_evening_unified_mvp_voting(self):
        """Box appointments on the same date share a single unified MVP election for the entire evening."""
        main_conn = get_connection()
        tz = ZoneInfo("Europe/Berlin")
        today_str = datetime.now(tz).strftime("%Y-%m-%d")
        mid1 = f"{today_str}-1"
        mid2 = f"{today_str}-2"

        try:
            for pid in (401, 402, 403, 404, 405):
                self.ensure_player(main_conn, pid, f"Player {pid}")

            # Game 1: 401 & 402 vs 403
            main_conn.execute("INSERT OR REPLACE INTO matches (match_id, date, pitch, players_a, players_b, goals_a, goals_b) VALUES (?, ?, 'box', 2, 1, 5, 4)", (mid1, today_str))
            main_conn.execute("DELETE FROM match_players WHERE match_id = ?", (mid1,))
            main_conn.execute("INSERT INTO match_players (match_id, player_id, team) VALUES (?, 401, 'a')", (mid1,))
            main_conn.execute("INSERT INTO match_players (match_id, player_id, team) VALUES (?, 402, 'a')", (mid1,))
            main_conn.execute("INSERT INTO match_players (match_id, player_id, team) VALUES (?, 403, 'b')", (mid1,))

            # Game 2: 401 & 404 vs 405 (Player 404 and 405 only played game 2, Player 402 only played game 1)
            main_conn.execute("INSERT OR REPLACE INTO matches (match_id, date, pitch, players_a, players_b, goals_a, goals_b) VALUES (?, ?, 'box', 2, 1, 3, 3)", (mid2, today_str))
            main_conn.execute("DELETE FROM match_players WHERE match_id = ?", (mid2,))
            main_conn.execute("INSERT INTO match_players (match_id, player_id, team) VALUES (?, 401, 'a')", (mid2,))
            main_conn.execute("INSERT INTO match_players (match_id, player_id, team) VALUES (?, 404, 'a')", (mid2,))
            main_conn.execute("INSERT INTO match_players (match_id, player_id, team) VALUES (?, 405, 'b')", (mid2,))
            main_conn.commit()
        finally:
            main_conn.close()

        invalidate_stats_cache()

        # User linked to Player 402 (who only played in game 1)
        u402, _ = self.create_user(role="user", linked_player_id=402)
        self.login_user(u402)

        # Check status for game 2: 402 can vote because they participated in the Box evening!
        res_s2 = self.client.get(f"/api/matches/{mid2}/mvp-status")
        self.assertEqual(res_s2.status_code, 200)
        d2 = res_s2.get_json()
        self.assertTrue(d2["is_box_session"])
        self.assertEqual(d2["canonical_match_id"], mid2)
        self.assertTrue(d2["can_vote"])
        # Candidates include players from both games (401, 403, 404, 405), excluding self (402)
        all_cands = [p["id"] for p in d2["box_players"]]
        self.assertNotIn(402, all_cands)
        self.assertIn(401, all_cands)
        self.assertIn(404, all_cands)
        self.assertIn(405, all_cands)

        # Before voting: match history shows voting UI ONLY on the last game of the day (mid2)
        res_pre_hist = self.client.get("/matches")
        self.assertEqual(res_pre_hist.status_code, 200)
        pre_html = res_pre_hist.get_data(as_text=True)
        self.assertIn(f'data-match-id="{mid2}" data-can-vote="true"', pre_html)
        self.assertIn(f'data-match-id="{mid1}" data-can-vote="false"', pre_html)

        # Player 402 votes for Player 404 (who only played in game 2) via game 2's endpoint
        vote_res = self.client.post(f"/api/matches/{mid2}/mvp-vote", json={"voted_player_ids": [404, 401]})
        self.assertEqual(vote_res.status_code, 200)
        v_data = vote_res.get_json()
        self.assertTrue(v_data["success"])
        self.assertTrue(v_data["is_box_session"])
        self.assertEqual(v_data["canonical_match_id"], mid2)
        self.assertEqual(v_data["box_matches"], [mid1, mid2])

        # Status for game 1 now also reflects the recorded vote via evening pooling
        res_s1 = self.client.get(f"/api/matches/{mid1}/mvp-status")
        d1 = res_s1.get_json()
        self.assertEqual(d1["user_votes"], [404, 401])
        self.assertEqual(d1["user_vote"], 404)

        # Match history renders both cards, but voting button & banner are ONLY on the last match of the day (mid2)
        res_hist = self.client.get("/matches")
        self.assertEqual(res_hist.status_code, 200)
        hist_html = res_hist.get_data(as_text=True)
        self.assertIn(f'data-match-id="{mid1}"', hist_html)
        self.assertIn(f'data-match-id="{mid2}"', hist_html)

        # Split html per match card to verify exact presence/absence of MVP voting UI
        # In reverse chronological history, mid2 (last game of day) comes before mid1 (earlier game)
        start2 = hist_html.find(f'data-match-id="{mid2}"')
        start1 = hist_html.find(f'data-match-id="{mid1}"')
        self.assertTrue(start2 != -1 and start1 != -1 and start2 < start1)
        m2_section = hist_html[start2:start1]
        m1_section = hist_html[start1:start1 + 2500]

        # mid2 (last match of the day) has the MVP button and banner
        self.assertIn("match-mvp-btn", m2_section)
        self.assertIn("match-mvp-banner", m2_section)
        self.assertIn("Box-MVP gewählt", m2_section)

        # mid1 (earlier match) does NOT have the MVP button or banner ("nur eine Karte und ein Symbol über dem letzten Spiel")
        self.assertNotIn("match-mvp-btn", m1_section)
        self.assertNotIn("match-mvp-banner", m1_section)

    def test_mvp_voting_ui_and_restriction_for_unlinked_and_guest_users(self):
        """MVP voting UI must be visible for guest & unlinked users with restriction guidance modal."""
        main_conn = get_connection()
        tz = ZoneInfo("Europe/Berlin")
        today = datetime.now(tz).date().strftime("%Y-%m-%d")
        mid = "TEST_RESTRICT_MATCH"
        try:
            self.ensure_player(main_conn, 501, "Player 501")
            self.ensure_player(main_conn, 502, "Player 502")
            self.ensure_player(main_conn, 503, "Player 503")
            self.ensure_player(main_conn, 504, "Player 504")
            main_conn.execute("INSERT OR REPLACE INTO matches (match_id, date, pitch, players_a, players_b, goals_a, goals_b) VALUES (?, ?, 'box', 2, 2, 3, 2)", (mid, today))
            main_conn.execute("DELETE FROM match_players WHERE match_id = ?", (mid,))
            main_conn.execute("INSERT INTO match_players (match_id, player_id, team) VALUES (?, 501, 'a')", (mid,))
            main_conn.execute("INSERT INTO match_players (match_id, player_id, team) VALUES (?, 502, 'a')", (mid,))
            main_conn.execute("INSERT INTO match_players (match_id, player_id, team) VALUES (?, 503, 'b')", (mid,))
            main_conn.execute("INSERT INTO match_players (match_id, player_id, team) VALUES (?, 504, 'b')", (mid,))
            main_conn.commit()
        finally:
            main_conn.close()
        invalidate_stats_cache()

        # 1. Guest user (not logged in)
        with self.client.session_transaction() as sess:
            sess.clear()
        res_matches = self.client.get("/matches")
        self.assertEqual(res_matches.status_code, 200)
        html = res_matches.get_data(as_text=True)
        self.assertIn('data-show-voting-ui="true"', html)
        self.assertIn('data-can-vote="false"', html)
        self.assertIn('class="match-mvp-btn restricted"', html)
        self.assertIn('mvp-restriction-modal', html)

        res_api_guest = self.client.get(f"/api/matches/{mid}/mvp-status")
        self.assertEqual(res_api_guest.status_code, 200)
        d_guest = res_api_guest.get_json()
        self.assertFalse(d_guest["can_vote"])
        self.assertEqual(d_guest["restriction_reason"], "not_logged_in")

        # 2. Logged-in user without linked player profile
        u_unlinked, _ = self.create_user(role="user", linked_player_id=None)
        self.login_user(u_unlinked)
        res_api_unlinked = self.client.get(f"/api/matches/{mid}/mvp-status")
        d_unlinked = res_api_unlinked.get_json()
        self.assertFalse(d_unlinked["can_vote"])
        self.assertEqual(d_unlinked["restriction_reason"], "not_linked")

        # 3. Logged-in user with linked player profile who did NOT participate
        u_nonpart, _ = self.create_user(role="user", linked_player_id=999)
        self.login_user(u_nonpart)
        res_api_nonpart = self.client.get(f"/api/matches/{mid}/mvp-status")
        d_nonpart = res_api_nonpart.get_json()
        self.assertFalse(d_nonpart["can_vote"])
        self.assertEqual(d_nonpart["restriction_reason"], "not_participant")

        # 4. Logged-in participant
        u_part, _ = self.create_user(role="user", linked_player_id=501)
        self.login_user(u_part)
        res_api_part = self.client.get(f"/api/matches/{mid}/mvp-status")
        d_part = res_api_part.get_json()
        self.assertTrue(d_part["can_vote"])
        self.assertIsNone(d_part["restriction_reason"])


