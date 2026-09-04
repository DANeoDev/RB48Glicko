import unittest
from scripts.database.database import get_connection
from scripts.analysis.achievements import get_player_achievements


class TestAchievements(unittest.TestCase):
    def setUp(self):
        self.conn = get_connection()

    def tearDown(self):
        self.conn.close()

    def test_get_player_achievements_structure(self):
        # Test for player 1 (Konsti or Kevin or active player)
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


if __name__ == "__main__":
    unittest.main()
