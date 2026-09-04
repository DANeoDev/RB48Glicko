import unittest
from scripts.database.database import get_connection
from scripts.analysis.synergies import get_community_synergies
from scripts.analysis.streaks import get_dashboard_streaks


class TestSynergiesAndStreaks(unittest.TestCase):
    def setUp(self):
        self.conn = get_connection()

    def tearDown(self):
        self.conn.close()

    def test_community_synergies(self):
        synergies = get_community_synergies(self.conn, min_games=2)
        self.assertIn("best_duos", synergies)
        self.assertIn("worst_duos", synergies)
        self.assertIn("kryptonite_rivals", synergies)
        self.assertIn("balanced_matchups", synergies)

        if synergies["best_duos"]:
            top_duo = synergies["best_duos"][0]
            self.assertIn("player1_name", top_duo)
            self.assertIn("player2_name", top_duo)
            self.assertIn("win_rate", top_duo)
            self.assertGreaterEqual(top_duo["win_rate"], 0)

    def test_dashboard_streaks(self):
        streaks = get_dashboard_streaks(self.conn)
        self.assertIn("active_win_streaks", streaks)
        self.assertIn("all_time_win_streaks", streaks)
        self.assertIn("most_improved", streaks)

        for s in streaks["active_win_streaks"]:
            self.assertGreaterEqual(s["count"], 2)


if __name__ == "__main__":
    unittest.main()
