import sqlite3
import unittest
from datetime import datetime
from scripts.database.database import (
    create_players_table,
    create_aliases_table,
    create_positions_table,
    create_ignored_aliases_table,
    create_matches_table,
    create_match_players_table,
    create_calibrations_table,
    create_match_ratings_table,
    create_ratings_table,
    get_connection,
)
from scripts.accounts.database import (
    create_account_tables,
    mark_user_achievements_seen,
)
from scripts.analysis.achievements import (
    get_player_achievements,
    get_user_unseen_achievements_count,
)
from web.services.translations import t


class TestAchievements(unittest.TestCase):
    def setUp(self):
        self.conn = get_connection()

    def tearDown(self):
        self.conn.close()

    def test_get_player_achievements_structure(self):
        achievements = get_player_achievements(self.conn, 1, user_has_glicko_tier=True)
        self.assertIsInstance(achievements, list)
        self.assertGreater(len(achievements), 0)

        for ach in achievements:
            self.assertIn("id", ach)
            self.assertIn("icon", ach)
            self.assertIn("title_key", ach)
            self.assertIn("unlocked", ach)
            self.assertIn("progress_text", ach)
            self.assertIn("tier", ach)

    def test_highest_rank_tier_gating(self):
        ach_non_glicko = get_player_achievements(self.conn, 1, user_has_glicko_tier=False)
        rank_ach = [a for a in ach_non_glicko if a["id"] == "highest_rank"]
        self.assertTrue(len(rank_ach) == 0 or not rank_ach[0]["unlocked"])

    def test_nonexistent_player(self):
        ach = get_player_achievements(self.conn, 999999, user_has_glicko_tier=True)
        self.assertEqual(ach, [])

    def test_translations_keys_resolve(self):
        keys = [
            "achievements.perfect_month_title",
            "achievements.perfect_month_desc",
            "achievements.buddies_title",
            "achievements.buddies_partner_title",
            "achievements.golden_duo_title",
            "achievements.golden_duo_partner_title",
            "achievements.thick_and_thin_title",
            "achievements.thick_and_thin_partner_title",
            "achievements.underdog_duo_title",
            "achievements.underdog_duo_partner_title",
            "achievements.teamplayer_title",
            "achievements.teamplayer_desc",
            "achievements.closed_society_title",
            "achievements.closed_society_desc",
            "achievements.cursebreaker_title",
            "achievements.cursebreaker_desc",
            "achievements.comeback_king_title",
            "achievements.comeback_king_desc",
            "achievements.tier_platin",
            "achievements.tier_neutral",
            "achievements.badge_new",
            "achievements.new_notification",
        ]
        for key in keys:
            res_de = t(key, lang="de", partner="Max", count=10, streak=4)
            res_en = t(key, lang="en", partner="Max", count=10, streak=4)
            self.assertNotEqual(str(res_de), key)
            self.assertNotEqual(str(res_en), key)


class TestAchievementsLogicSynthetic(unittest.TestCase):
    """In-memory tests verifying revised achievement rules and calculations."""

    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        create_players_table(self.conn)
        create_aliases_table(self.conn)
        create_positions_table(self.conn)
        create_ignored_aliases_table(self.conn)
        create_matches_table(self.conn)
        create_match_players_table(self.conn)
        create_calibrations_table(self.conn)
        create_match_ratings_table(self.conn)
        create_ratings_table(self.conn)

        # Accounts in-memory DB for testing linked players and notifications
        self.acc_conn = sqlite3.connect(":memory:")
        self.acc_conn.row_factory = sqlite3.Row
        create_account_tables(self.acc_conn)

        # Create players 1 to 25
        for pid in range(1, 26):
            self.conn.execute("INSERT INTO players (player_id) VALUES (?)", (pid,))
            self.conn.execute("INSERT INTO aliases (alias, player_id) VALUES (?, ?)", (f"Player_{pid}", pid))
        self.conn.commit()
        self.match_id_counter = 1

    def tearDown(self):
        self.conn.close()
        self.acc_conn.close()

    def add_match(self, date_str, team_a, team_b, goals_a, goals_b, ratings_map=None):
        mid = f"m_{self.match_id_counter}"
        self.match_id_counter += 1
        self.conn.execute(
            "INSERT INTO matches (match_id, date, pitch, players_a, players_b, goals_a, goals_b) VALUES (?, ?, 'box', ?, ?, ?, ?)",
            (mid, date_str, len(team_a), len(team_b), goals_a, goals_b)
        )
        for pid in team_a:
            self.conn.execute("INSERT INTO match_players (match_id, player_id, team) VALUES (?, ?, 'a')", (mid, pid))
        for pid in team_b:
            self.conn.execute("INSERT INTO match_players (match_id, player_id, team) VALUES (?, ?, 'b')", (mid, pid))
        
        if ratings_map:
            for pid, r in ratings_map.items():
                self.conn.execute(
                    "INSERT INTO match_ratings (match_id, player_id, rating_type, rating, rd, sigma) VALUES (?, ?, 'total', ?, 50.0, 0.06)",
                    (mid, pid, float(r))
                )
        self.conn.commit()
        return mid

    def add_warmup_5_matches(self):
        """Add first 5 global matches that must be ignored by achievement calculations."""
        for i in range(1, 6):
            self.add_match(f"2026-01-0{i}", [1, 2], [3, 4], 10, 0, {1: 1500, 2: 1500, 3: 1500, 4: 1500})

    def test_first_5_global_matches_ignored(self):
        # 1. Add 5 matches where player 1 wins with clean sheet
        self.add_warmup_5_matches()

        ach = get_player_achievements(self.conn, 1, accounts_connection=self.acc_conn)
        clean_sheet = [a for a in ach if a["id"] == "weisse_wand"][0]
        self.assertFalse(clean_sheet["unlocked"])
        century = [a for a in ach if a["id"] == "century_club"][0]
        self.assertFalse(century["unlocked"])
        self.assertIn("0 / 25 Spiele", century["progress_text"])

        # 2. Add match 6 (won with clean sheet) -> now active_matches has 1 match
        self.add_match("2026-02-01", [1, 2], [3, 4], 5, 0, {1: 1500, 2: 1500, 3: 1500, 4: 1500})
        ach2 = get_player_achievements(self.conn, 1, accounts_connection=self.acc_conn)
        clean_sheet2 = [a for a in ach2 if a["id"] == "weisse_wand"][0]
        self.assertTrue(clean_sheet2["unlocked"])
        self.assertEqual(clean_sheet2["tier"], "bronze")

    def test_ironman_thresholds(self):
        self.add_warmup_5_matches()

        # 5 consecutive matchdays: bronze
        for d in range(1, 6):
            self.add_match(f"2026-03-{d:02d}", [1, 2], [3, 4], 3, 1)

        ach = get_player_achievements(self.conn, 1, accounts_connection=self.acc_conn)
        iron = [a for a in ach if a["id"] == "iron_man"][0]
        self.assertTrue(iron["unlocked"])
        self.assertEqual(iron["tier"], "bronze")
        self.assertIn("5 / 5 Spieltage", iron["progress_text"])

        # Up to 10: silver
        for d in range(6, 11):
            self.add_match(f"2026-03-{d:02d}", [1, 2], [3, 4], 3, 1)

        ach10 = get_player_achievements(self.conn, 1, accounts_connection=self.acc_conn)
        iron10 = [a for a in ach10 if a["id"] == "iron_man"][0]
        self.assertEqual(iron10["tier"], "silver")

    def test_underdog_threshold_32_percent(self):
        self.add_warmup_5_matches()

        # Win with 35% win probability (team A: 1400 vs team B: 1510 -> expected ~0.347)
        # Should NOT count for underdog hero (requires < 32%)
        self.add_match("2026-03-01", [1, 2], [3, 4], 4, 2, {1: 1400, 2: 1400, 3: 1510, 4: 1510})
        ach = get_player_achievements(self.conn, 1, accounts_connection=self.acc_conn)
        ud = [a for a in ach if a["id"] == "underdog_hero"][0]
        self.assertFalse(ud["unlocked"])

        # Win with 25% win probability (team A: 1300 vs team B: 1550 -> expected ~0.19 < 0.32)
        # Should count as underdog victory!
        self.add_match("2026-03-05", [1, 2], [3, 4], 4, 3, {1: 1300, 2: 1300, 3: 1550, 4: 1550})
        ach2 = get_player_achievements(self.conn, 1, accounts_connection=self.acc_conn)
        ud2 = [a for a in ach2 if a["id"] == "underdog_hero"][0]
        self.assertTrue(ud2["unlocked"])
        self.assertEqual(ud2["tier"], "bronze")

    def test_makelloser_monat_all_matches_participated_and_won(self):
        self.add_warmup_5_matches()

        # Month 2026-04 has 3 global matches.
        # Player 1 participates in only 2 of them (and wins both)
        self.add_match("2026-04-05", [1, 2], [3, 4], 5, 2)
        self.add_match("2026-04-12", [1, 2], [3, 4], 4, 1)
        self.add_match("2026-04-19", [5, 2], [3, 4], 4, 1) # player 1 did NOT play in this match

        ach = get_player_achievements(self.conn, 1, accounts_connection=self.acc_conn)
        pm = [a for a in ach if a["id"] == "perfect_month"][0]
        self.assertFalse(pm["unlocked"])

        # Month 2026-05 has 2 global matches. Player 1 plays and wins ALL of them!
        self.add_match("2026-05-05", [1, 2], [3, 4], 6, 2)
        self.add_match("2026-05-12", [1, 2], [3, 4], 5, 3)

        ach2 = get_player_achievements(self.conn, 1, accounts_connection=self.acc_conn)
        pm2 = [a for a in ach2 if a["id"] == "perfect_month"][0]
        self.assertTrue(pm2["unlocked"])
        self.assertEqual(pm2["tier"], "bronze")
        self.assertIn("Mai 2026", pm2["detail_text"])

        # Month 2026-06: plays and wins all global matches -> Silver (2 perfect months)
        self.add_match("2026-06-05", [1, 2], [3, 4], 6, 2)
        ach3 = get_player_achievements(self.conn, 1, accounts_connection=self.acc_conn)
        pm3 = [a for a in ach3 if a["id"] == "perfect_month"][0]
        self.assertEqual(pm3["tier"], "silver")
        self.assertIn("Mai 2026", pm3["detail_text"])
        self.assertIn("Juni 2026", pm3["detail_text"])

        # Test ongoing uncompleted month: 2027-01 with reference_date 2027-01-15
        from datetime import datetime
        self.add_match("2027-01-05", [1, 2], [3, 4], 5, 1)
        ach_ongoing = get_player_achievements(self.conn, 1, accounts_connection=self.acc_conn, reference_date=datetime(2027, 1, 15))
        pm_ongoing = [a for a in ach_ongoing if a["id"] == "perfect_month"][0]
        self.assertEqual(pm_ongoing["tier"], "silver")
        self.assertNotIn("Januar 2027", pm_ongoing["detail_text"])

    def test_makelloser_monat_first_month_ineligible(self):
        # 5 warmup matches in 2026-01
        self.add_warmup_5_matches()
        # Add 6th match in 2026-01 where player 1 wins
        self.add_match("2026-01-20", [1, 2], [3, 4], 5, 1)

        # In 2026-01, player 1 played all active matches and won.
        # But 2026-01 is the FIRST month of match history -> NOT eligible!
        ach = get_player_achievements(self.conn, 1, accounts_connection=self.acc_conn)
        pm = [a for a in ach if a["id"] == "perfect_month"][0]
        self.assertFalse(pm["unlocked"])
        self.assertEqual(pm["tier"], "locked")

        # In 2026-02 (the SECOND month of match history), player 1 plays and wins all matches
        self.add_match("2026-02-05", [1, 2], [3, 4], 5, 2)
        ach2 = get_player_achievements(self.conn, 1, accounts_connection=self.acc_conn)
        pm2 = [a for a in ach2 if a["id"] == "perfect_month"][0]
        self.assertTrue(pm2["unlocked"])
        self.assertEqual(pm2["tier"], "bronze")
        self.assertIn("Februar 2026", pm2["detail_text"])

    def test_winning_streak(self):
        self.add_warmup_5_matches()

        # 3 wins in a row -> not unlocked
        for i in range(1, 4):
            self.add_match(f"2026-02-{i:02d}", [1, 2], [3, 4], 5, 2)
        ach = get_player_achievements(self.conn, 1, accounts_connection=self.acc_conn)
        ws = [a for a in ach if a["id"] == "winning_streak"][0]
        self.assertFalse(ws["unlocked"])

        # 4th win in a row -> Bronze
        self.add_match("2026-02-04", [1, 2], [3, 4], 5, 2)
        ach4 = get_player_achievements(self.conn, 1, accounts_connection=self.acc_conn)
        ws4 = [a for a in ach4 if a["id"] == "winning_streak"][0]
        self.assertTrue(ws4["unlocked"])
        self.assertEqual(ws4["tier"], "bronze")

        # 4 more wins (total 8) -> Silver
        for i in range(5, 9):
            self.add_match(f"2026-02-{i:02d}", [1, 2], [3, 4], 5, 2)
        ach8 = get_player_achievements(self.conn, 1, accounts_connection=self.acc_conn)
        ws8 = [a for a in ach8 if a["id"] == "winning_streak"][0]
        self.assertEqual(ws8["tier"], "silver")

        # A loss resets active streak, but record streak stays at 8 (Silver)
        self.add_match("2026-02-09", [1, 2], [3, 4], 1, 4)
        ach_loss = get_player_achievements(self.conn, 1, accounts_connection=self.acc_conn)
        ws_loss = [a for a in ach_loss if a["id"] == "winning_streak"][0]
        self.assertEqual(ws_loss["tier"], "silver")
        self.assertTrue(ws_loss["unlocked"])
        self.assertIn("aktuell: 0", ws_loss["detail_text"])

    def test_teammate_achievements_buddies_duos(self):
        self.add_warmup_5_matches()

        # Player 1 plays 10 matches with Player 2: 7 wins (2 underdog <32%), 3 losses
        for i in range(1, 8):
            # 2 underdog wins
            if i <= 2:
                ratings = {1: 1300, 2: 1300, 3: 1600, 4: 1600}
            else:
                ratings = {1: 1500, 2: 1500, 3: 1500, 4: 1500}
            self.add_match(f"2026-07-{i:02d}", [1, 2], [3, 4], 5, 2, ratings)

        for i in range(8, 11):
            self.add_match(f"2026-07-{i:02d}", [1, 2], [3, 4], 1, 4, {1: 1500, 2: 1500, 3: 1500, 4: 1500})

        ach = get_player_achievements(self.conn, 1, accounts_connection=self.acc_conn)

        # Buddies 2: 10 games -> bronze
        buddies = [a for a in ach if a["id"] == "buddies_2"]
        self.assertEqual(len(buddies), 1)
        self.assertEqual(buddies[0]["tier"], "bronze")
        self.assertIn("Player_2", buddies[0]["title"])

        # Golden duo: only 7 wins, needs 10 for bronze -> not unlocked
        gd = [a for a in ach if a["id"] == "golden_duo_2"]
        self.assertEqual(len(gd), 0)

        # Add 3 more wins with Player 2 (total 10 wins, 1 underdog) -> Golden Duo Bronze, Underdog Duo 3 -> Bronze!
        self.add_match("2026-07-15", [1, 2], [3, 4], 4, 1, {1: 1500, 2: 1500, 3: 1500, 4: 1500})
        self.add_match("2026-07-16", [1, 2], [3, 4], 4, 1, {1: 1500, 2: 1500, 3: 1500, 4: 1500})
        self.add_match("2026-07-17", [1, 2], [3, 4], 4, 1, {1: 1300, 2: 1300, 3: 1600, 4: 1600})  # underdog

        ach2 = get_player_achievements(self.conn, 1, accounts_connection=self.acc_conn)
        gd2 = [a for a in ach2 if a["id"] == "golden_duo_2"]
        self.assertEqual(len(gd2), 1)
        self.assertEqual(gd2[0]["tier"], "bronze")

        ud_duo = [a for a in ach2 if a["id"] == "underdog_duo_2"]
        self.assertEqual(len(ud_duo), 1)
        self.assertEqual(ud_duo[0]["tier"], "bronze")

        # Durch Dick und Dünn: 3 losses, needs 10 -> not unlocked
        ddd = [a for a in ach2 if a["id"] == "thick_and_thin_2"]
        self.assertEqual(len(ddd), 0)

        # Add 7 more losses with Player 2 -> total 10 losses -> bronze
        for i in range(16, 23):
            self.add_match(f"2026-07-{i:02d}", [1, 2], [3, 4], 1, 4, {1: 1500, 2: 1500, 3: 1500, 4: 1500})
        ach3 = get_player_achievements(self.conn, 1, accounts_connection=self.acc_conn)
        ddd2 = [a for a in ach3 if a["id"] == "thick_and_thin_2"]
        self.assertEqual(len(ddd2), 1)
        self.assertEqual(ddd2[0]["tier"], "bronze")

    def test_geschlossene_gesellschaft(self):
        self.add_warmup_5_matches()

        # Same exact team [1, 2, 3] on 2 distinct dates
        self.add_match("2026-08-01", [1, 2, 3], [4, 5, 6], 5, 3)
        self.add_match("2026-08-08", [1, 2, 3], [4, 5, 6], 4, 2)

        ach = get_player_achievements(self.conn, 1, accounts_connection=self.acc_conn)
        cs = [a for a in ach if a["id"] == "closed_society"][0]
        self.assertTrue(cs["unlocked"])
        self.assertEqual(cs["tier"], "bronze")

    def test_teamplayer_achievement(self):
        self.add_warmup_5_matches()

        # Create 15 linked users for pids 2..16
        for pid in range(2, 17):
            self.acc_conn.execute(
                "INSERT INTO users (username, email, password_hash, role, email_verified, is_approved, player_id, created_at) VALUES (?, ?, 'pw', 'user', 1, 1, ?, '2026-01-01')",
                (f"user_{pid}", f"user_{pid}@example.com", pid)
            )
        self.acc_conn.commit()

        # Before playing with all of them -> Teamplayer is below bronze (neutral) and NOT unlocked for regular users
        ach = get_player_achievements(self.conn, 1, accounts_connection=self.acc_conn)
        tp = [a for a in ach if a["id"] == "teamplayer"][0]
        self.assertFalse(tp["unlocked"])
        self.assertEqual(tp["tier"], "neutral")

        # Now play at least 1 match with each linked player (pids 2 to 16)
        for pid in range(2, 17):
            self.add_match("2026-07-01", [1, pid], [18, 19], 5, 2)

        ach_bronze = get_player_achievements(self.conn, 1, accounts_connection=self.acc_conn)
        tp_bronze = [a for a in ach_bronze if a["id"] == "teamplayer"][0]
        self.assertTrue(tp_bronze["unlocked"])
        self.assertEqual(tp_bronze["tier"], "bronze")

        # Now a 17th player links an account! Player 1 has not played with Player 17 yet.
        self.acc_conn.execute(
            "INSERT INTO users (username, email, password_hash, role, email_verified, is_approved, player_id, created_at) VALUES ('user_17', 'u17@example.com', 'pw', 'user', 1, 1, 17, '2026-01-01')"
        )
        self.acc_conn.commit()

        # Because Bronze was reached previously, the "below bronze" neutral card remains UNLOCKED!
        ach_after_new_user = get_player_achievements(self.conn, 1, accounts_connection=self.acc_conn)
        tp_neutral = [a for a in ach_after_new_user if a["id"] == "teamplayer"][0]
        self.assertTrue(tp_neutral["unlocked"])
        self.assertEqual(tp_neutral["tier"], "neutral")
        self.assertIn("Player_17", tp_neutral["detail_text"])

    def test_unseen_achievements_count_and_mark_seen(self):
        self.add_warmup_5_matches()

        # Create user for player 1 in acc_conn
        self.acc_conn.execute(
            "INSERT INTO users (id, username, email, password_hash, role, email_verified, is_approved, player_id, created_at) VALUES (101, 'testuser', 'tu@example.com', 'pw', 'user', 1, 1, 1, '2026-01-01')"
        )
        self.acc_conn.commit()

        # Player 1 wins match with clean sheet -> unlocks weisse_wand:bronze
        self.add_match("2026-02-01", [1, 2], [3, 4], 5, 0, {1: 1500, 2: 1500, 3: 1500, 4: 1500})

        unseen = get_user_unseen_achievements_count(101, 1, accounts_connection=self.acc_conn, primary_connection=self.conn)
        self.assertGreater(unseen, 0)

        # Verify weisse_wand:bronze was unlocked
        achievements = get_player_achievements(self.conn, 1, accounts_connection=self.acc_conn)
        unlocked_keys = [f"{a['id']}:{a.get('tier', '')}" for a in achievements if a.get("unlocked") and a.get("tier") != "neutral"]
        self.assertIn("weisse_wand:bronze", unlocked_keys)

        # Mark all unlocked as seen
        mark_user_achievements_seen(self.acc_conn, 101, unlocked_keys)
        unseen_after = get_user_unseen_achievements_count(101, 1, accounts_connection=self.acc_conn, primary_connection=self.conn)
        self.assertEqual(unseen_after, 0)


import os
import tempfile
from pathlib import Path
from web.app import create_app
from scripts.accounts.auth import register_user
from scripts.accounts.database import mark_email_verified, approve_user, link_user_to_player, get_accounts_connection


class TestAchievementsRoute(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_accounts_db = Path(self.temp_dir.name) / "test_accounts.db"
        os.environ["RB48_ACCOUNTS_DATABASE_FILE"] = str(self.test_accounts_db)

        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def tearDown(self):
        os.environ.pop("RB48_ACCOUNTS_DATABASE_FILE", None)
        self.temp_dir.cleanup()

    def test_player_achievements_route_as_linked_user(self):
        user_id, _ = register_user("achuser", "ach@example.com", "password123")
        conn = get_accounts_connection()
        try:
            mark_email_verified(conn, user_id)
            approve_user(conn, user_id, approved=True)
            link_user_to_player(conn, user_id, 1)
        finally:
            conn.close()

        with self.client.session_transaction() as sess:
            sess["user_id"] = user_id

        # Visit own achievements
        resp = self.client.get("/achievements/1")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Auszeichnungen & Meilensteine", resp.get_data(as_text=True))

    def test_player_profile_graphs_rendered_for_glicko_user(self):
        from scripts.accounts.auth import pass_psychology_test
        user_id, _ = register_user("chartuser", "chart@example.com", "password123")
        conn = get_accounts_connection()
        try:
            mark_email_verified(conn, user_id)
            approve_user(conn, user_id, approved=True)
            link_user_to_player(conn, user_id, 1)
        finally:
            conn.close()
        pass_psychology_test(user_id)

        with self.client.session_transaction() as sess:
            sess["user_id"] = user_id

        resp = self.client.get("/player/1")
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn("chart.js", html.lower())
        self.assertIn('class="graphs"', html)
        self.assertIn("new Chart", html)
        self.assertIn("totalChart", html)


if __name__ == "__main__":
    unittest.main()
