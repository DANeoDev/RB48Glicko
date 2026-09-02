import unittest

from web.app import app


class MatchCenterFrontendTests(unittest.TestCase):
    def test_match_center_uses_one_frontend_implementation(self):
        with app.test_client() as client:
            response = client.get("/match-center")

            self.assertEqual(response.status_code, 200)
            self.assertIn(b"window.matchCenterPlayers", response.data)
            self.assertIn(b"match_center.css", response.data)
            self.assertIn(b"match_center.js", response.data)
            self.assertNotIn(b"add_player_modal.js", response.data)
            self.assertNotIn(b"match_save_feedback.js", response.data)
            self.assertNotIn(b"match_center_navigation.js", response.data)
            self.assertNotIn(b'id="use-imported"', response.data)
            self.assertNotIn(b'id="fairer-imported"', response.data)

            css_response = client.get("/static/match_center.css")
            js_response = client.get("/static/match_center.js")
            self.assertEqual(css_response.status_code, 200)
            self.assertEqual(js_response.status_code, 200)
            self.assertNotIn(b"var(--green)", css_response.data)
            self.assertNotIn(b"var(--green-dark)", css_response.data)
            css_response.close()
            js_response.close()
