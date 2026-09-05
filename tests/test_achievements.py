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
from scripts.analysis.achievements import get_player_achievements
from web.services.translations import t


class TestAchievements(unittest.TestCase):
    def setUp(self):
        self.conn = get_connection()

    def tearDown(self):
        self.conn.close()

    def test_get_player_achievements_structure(self):
        # Test for player 1
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
        # Non-glicko user should see locked or hidden highest rank
        ach_non_glicko = get_player_achievements(self.conn, 1, user_has_glicko_tier=False)
        rank_ach = [a for a in ach_non_glicko if a["id"] == "highest_rank"]
        self.assertTrue(len(rank_ach) == 0 or not rank_ach[0]["unlocked"])

    def test_nonexistent_player(self):
        ach = get_player_achievements(self.conn, 999999, user_has_glicko_tier=True)
        self.assertEqual(ach, [])

    def test_translations_keys_resolve(self):
        # Ensure new achievement keys exist in de and en catalogs
        for key in [
            "achievements.perfect_month_title",
            "achievements.perfect_month_desc",
            "achievements.cursebreaker_title",
            "achievements.cursebreaker_desc",
            "achievements.cursebreaker_partner_title",
            "achievements.cursebreaker_partner_detail",
            "achievements.comeback_king_title",
            "achievements.comeback_king_desc",
            "achievements.tier_platin"
        ]:
            res_de = t(key, lang="de", partner="Max", streak=4)
            res_en = t(key, lang="en", partner="Max", streak=4)
            self.assertNotEqual(str(res_de), key)
            self.assertNotEqual(str(res_en), key)


class TestAchievementsLogicSynthetic(unittest.TestCase):
    """In-memory tests verifying specific achievement edge cases and calculations."""

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

        # Create players 1 to 10
        for pid in range(1, 11):
            self.conn.execute("INSERT INTO players (player_id) VALUES (?)", (pid,))
            self.conn.execute("INSERT INTO aliases (alias, player_id) VALUES (?, ?)", (f"Player_{pid}", pid))
        self.conn.commit()
        self.match_id_counter = 1

    def tearDown(self):
        self.conn.close()

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

    def test_first_game_ignored(self):
        # Add 1 match for player 1 (won 10-0) -> this is their debut match
        self.add_match("2026-05-01", [1, 2], [3, 4], 10, 0, {1: 1600, 2: 1600, 3: 1400, 4: 1400})

        ach = get_player_achievements(self.conn, 1)
        # Clean sheet should NOT be unlocked because first match is ignored
        clean_sheet = [a for a in ach if a["id"] == "weisse_wand"][0]
        self.assertFalse(clean_sheet["unlocked"])
        century = [a for a in ach if a["id"] == "century_club"][0]
        self.assertFalse(century["unlocked"])
        self.assertIn("0 / 25 Spiele", century["progress_text"])

        # Add second match (won 10-0) -> active_matches now has 1 match
        self.add_match("2026-05-02", [1, 2], [3, 4], 10, 0, {1: 1600, 2: 1600, 3: 1400, 4: 1400})
        ach2 = get_player_achievements(self.conn, 1)
        clean_sheet2 = [a for a in ach2 if a["id"] == "weisse_wand"][0]
        self.assertTrue(clean_sheet2["unlocked"])
        self.assertEqual(clean_sheet2["tier"], "bronze")

    def test_perfect_month(self):
        # Debut match on 2026-04-01 (ignored)
        self.add_match("2026-04-01", [1, 2], [3, 4], 5, 2)

        # Month 1 (2026-05): 2 matches, 2 wins
        self.add_match("2026-05-10", [1, 2], [3, 4], 5, 2)
        self.add_match("2026-05-15", [1, 2], [3, 4], 4, 1)

        ach = get_player_achievements(self.conn, 1)
        pm = [a for a in ach if a["id"] == "perfect_month"][0]
        self.assertTrue(pm["unlocked"])
        self.assertEqual(pm["tier"], "bronze")

        # Month 2 (2026-06): 2 matches, 2 wins
        self.add_match("2026-06-05", [1, 2], [3, 4], 5, 2)
        self.add_match("2026-06-12", [1, 2], [3, 4], 6, 3)

        ach = get_player_achievements(self.conn, 1)
        pm = [a for a in ach if a["id"] == "perfect_month"][0]
        self.assertTrue(pm["unlocked"])
        self.assertEqual(pm["tier"], "silver")

        # Month 3 (2026-07): 2 matches, 2 wins
        self.add_match("2026-07-02", [1, 2], [3, 4], 5, 2)
        self.add_match("2026-07-09", [1, 2], [3, 4], 4, 0)

        ach = get_player_achievements(self.conn, 1)
        pm = [a for a in ach if a["id"] == "perfect_month"][0]
        self.assertTrue(pm["unlocked"])
        self.assertEqual(pm["tier"], "gold")

    def test_cursebreaker_placeholder_when_no_curses_broken(self):
        # Player plays matches without forming or breaking curses
        self.add_match("2026-01-01", [1, 2], [3, 4], 5, 2)
        self.add_match("2026-01-05", [1, 2], [3, 4], 5, 3)

        ach = get_player_achievements(self.conn, 1)
        cb = [a for a in ach if a["id"] == "cursebreaker_placeholder"][0]
        self.assertFalse(cb["unlocked"])
        self.assertEqual(cb["tier"], "locked")

    def test_cursebreaker_partner_streaks_and_tiers(self):
        # Debut match for player 1 (ignored)
        self.add_match("2026-01-01", [1, 10], [8, 9], 5, 3)

        # 1. Partner 2: 4 consecutive losses together, then win -> Bronze
        for d in range(1, 5):
            self.add_match(f"2026-02-0{d}", [1, 2], [8, 9], 2, 5, {1: 1500, 2: 1500, 8: 1500, 9: 1500})
        # Win together on Feb 5
        self.add_match("2026-02-05", [1, 2], [8, 9], 6, 2, {1: 1500, 2: 1500, 8: 1500, 9: 1500})

        # 2. Partner 3: 5 consecutive losses together, then win -> Silver
        for d in range(1, 6):
            self.add_match(f"2026-03-0{d}", [1, 3], [8, 9], 1, 4, {1: 1500, 3: 1500, 8: 1500, 9: 1500})
        # Win together on March 6
        self.add_match("2026-03-06", [1, 3], [8, 9], 5, 3, {1: 1500, 3: 1500, 8: 1500, 9: 1500})

        # 3. Partner 4: 6 consecutive losses together, then win as favorite (rating higher) -> Gold
        for d in range(1, 7):
            self.add_match(f"2026-04-0{d}", [1, 4], [8, 9], 0, 3, {1: 1600, 4: 1600, 8: 1400, 9: 1400})
        # Win together on April 7 (expected win prob ~ 0.76 > 0.50)
        self.add_match("2026-04-07", [1, 4], [8, 9], 5, 2, {1: 1600, 4: 1600, 8: 1400, 9: 1400})

        # 4. Partner 5: 6 consecutive losses together, then win as underdog (rating lower) -> Platin
        for d in range(1, 7):
            self.add_match(f"2026-05-0{d}", [1, 5], [8, 9], 1, 5, {1: 1300, 5: 1300, 8: 1600, 9: 1600})
        # Win together on May 7 (underdog, avg team 1300 vs 1600, expected prob < 0.20 <= 0.50)
        self.add_match("2026-05-07", [1, 5], [8, 9], 5, 4, {1: 1300, 5: 1300, 8: 1600, 9: 1600})

        ach = get_player_achievements(self.conn, 1)

        # Check badges
        cb_p2 = [a for a in ach if a["id"] == "cursebreaker_2"]
        self.assertEqual(len(cb_p2), 1)
        self.assertEqual(cb_p2[0]["tier"], "bronze")
        self.assertIn("Player_2", cb_p2[0]["title"])
        self.assertIn("4", cb_p2[0]["progress_text"])

        cb_p3 = [a for a in ach if a["id"] == "cursebreaker_3"]
        self.assertEqual(len(cb_p3), 1)
        self.assertEqual(cb_p3[0]["tier"], "silver")
        self.assertIn("Player_3", cb_p3[0]["title"])
        self.assertIn("5", cb_p3[0]["progress_text"])

        cb_p4 = [a for a in ach if a["id"] == "cursebreaker_4"]
        self.assertEqual(len(cb_p4), 1)
        self.assertEqual(cb_p4[0]["tier"], "gold")
        self.assertIn("Player_4", cb_p4[0]["title"])
        self.assertIn("6", cb_p4[0]["progress_text"])

        cb_p5 = [a for a in ach if a["id"] == "cursebreaker_5"]
        self.assertEqual(len(cb_p5), 1)
        self.assertEqual(cb_p5[0]["tier"], "platin")
        self.assertIn("Player_5", cb_p5[0]["title"])
        self.assertIn("6", cb_p5[0]["progress_text"])

    def test_comeback_king_tiers(self):
        # Debut match (ignored)
        self.add_match("2026-01-01", [1, 2], [3, 4], 5, 5, {1: 1500})

        # Bronze: drop 120, gain 135 within 30 days
        self.add_match("2026-01-10", [1, 2], [3, 4], 5, 3, {1: 1600})
        self.add_match("2026-01-20", [1, 2], [3, 4], 1, 4, {1: 1480})
        self.add_match("2026-02-05", [1, 2], [3, 4], 5, 2, {1: 1615})

        ach = get_player_achievements(self.conn, 1)
        cb = [a for a in ach if a["id"] == "comeback_king"][0]
        self.assertTrue(cb["unlocked"])
        self.assertEqual(cb["tier"], "bronze")
        self.assertIn("-120 / +135 Rating (1 Monat)", cb["progress_text"])

        # Silver: drop 220, gain 240
        self.add_match("2026-02-20", [1, 2], [3, 4], 0, 5, {1: 1395}) # drop of 220 from 1615 in 15 days
        self.add_match("2026-03-05", [1, 2], [3, 4], 5, 1, {1: 1635}) # gain of 240 from 1395 in 13 days

        ach_silver = get_player_achievements(self.conn, 1)
        cb_silver = [a for a in ach_silver if a["id"] == "comeback_king"][0]
        self.assertEqual(cb_silver["tier"], "silver")

        # Gold: drop 310, gain 330
        self.add_match("2026-03-20", [1, 2], [3, 4], 0, 5, {1: 1325}) # drop of 310 from 1635 in 15 days
        self.add_match("2026-04-05", [1, 2], [3, 4], 5, 0, {1: 1655}) # gain of 330 from 1325 in 16 days

        ach_gold = get_player_achievements(self.conn, 1)
        cb_gold = [a for a in ach_gold if a["id"] == "comeback_king"][0]
        self.assertEqual(cb_gold["tier"], "gold")


if __name__ == "__main__":
    unittest.main()
