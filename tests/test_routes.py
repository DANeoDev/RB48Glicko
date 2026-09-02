import unittest
from web.app import app


class RouteTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_main_routes_render(self):
        routes = [
            "/",
            "/dashboard",
            "/stats",
            "/matches",
            "/model-analysis",
            "/glickofaq",
            "/login",
            "/register",
            "/match-center",
        ]
        for route in routes:
            with self.subTest(route=route):
                response = self.client.get(route)
                self.assertEqual(response.status_code, 200)

    def test_news_pagination_api(self):
        response = self.client.get("/news/items?offset=0&limit=2")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIn("news", data)
        self.assertIn("has_more", data)


if __name__ == "__main__":
    unittest.main()
