import unittest
from web.app import create_app


class TestQOLRoutes(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.client = self.app.test_client()

    def test_ics_export(self):
        with self.client.session_transaction() as sess:
            sess["user_id"] = 1
            sess["user_role"] = "user"
            sess["user_tier"] = "user"
            sess["user_is_approved"] = 1
        resp = self.client.get("/planner/export.ics")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"BEGIN:VCALENDAR", resp.data)
        self.assertIn(b"END:VCALENDAR", resp.data)

    def test_api_players_list(self):
        with self.client.session_transaction() as sess:
            sess["user_id"] = 1
            sess["user_role"] = "user"
            sess["user_tier"] = "user"
            sess["user_is_approved"] = 1
        resp = self.client.get("/api/players-list")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIsInstance(data, list)
        if len(data) > 0:
            self.assertIn("id", data[0])
            self.assertIn("name", data[0])

    def test_api_community_synergies(self):
        with self.client.session_transaction() as sess:
            sess["user_id"] = 1
            sess["user_role"] = "user"
            sess["user_tier"] = "user"
            sess["user_is_approved"] = 1
        resp = self.client.get("/api/community-synergies?min_games=1")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("best_duos", data)

    def test_achievements_guest_redirects_to_login(self):
        resp = self.client.get("/achievements")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login", resp.headers["Location"])

    def test_achievements_player_view_personalized(self):
        with self.client.session_transaction() as sess:
            sess["user_id"] = 1
            sess["user_role"] = "user"
            sess["user_tier"] = "user"
            sess["user_is_approved"] = 1
        resp = self.client.get("/achievements/1")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Auszeichnungen", resp.data)
        self.assertIn(b"Freigeschaltet", resp.data)

    def test_stats_streaks_modal_rendered(self):
        with self.client.session_transaction() as sess:
            sess["user_id"] = 1
            sess["user_role"] = "user"
            sess["user_tier"] = "user"
            sess["user_is_approved"] = 1
        resp = self.client.get("/stats")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'id="synergies-modal"', resp.data)
        self.assertIn(b'id="streaks-modal"', resp.data)
        self.assertIn(b'id="open-streaks-modal-btn"', resp.data)
        self.assertIn(b'id="open-synergies-modal-btn"', resp.data)


if __name__ == "__main__":
    unittest.main()
