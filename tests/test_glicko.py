import math
import unittest

from scripts.glicko.glicko2 import (
    Glicko2,
    Rating,
    DEFAULT_RATING,
    DEFAULT_RD,
    DEFAULT_SIGMA,
    WIN,
    LOSS,
    DRAW,
    TOTAL,
    expected_score,
)
from scripts.glicko.glicko2_calculator import (
    calculate_team_rating,
    create_virtual_rating,
)


class GlickoEngineTests(unittest.TestCase):
    def setUp(self):
        self.engine = Glicko2()

    def test_default_rating_instantiation(self):
        r = Rating()
        self.assertEqual(r.rating, DEFAULT_RATING)
        self.assertEqual(r.rd, DEFAULT_RD)
        self.assertEqual(r.sigma, DEFAULT_SIGMA)

    def test_scale_conversions(self):
        rating = Rating(rating=1500.0, rd=200.0, sigma=0.06)
        scaled = self.engine._scale_down(rating)
        self.assertAlmostEqual(scaled.mu, 0.0)
        self.assertAlmostEqual(scaled.phi, 200.0 / 173.7178)
        self.assertEqual(scaled.sigma, 0.06)

        restored = self.engine._scale_up(scaled)
        self.assertAlmostEqual(restored.rating, 1500.0)
        self.assertAlmostEqual(restored.rd, 200.0)
        self.assertEqual(restored.sigma, 0.06)

    def test_expected_score_symmetry(self):
        r1 = 1600.0
        r2 = 1400.0
        rd = 100.0
        p1 = expected_score(r1, r2, rd)
        p2 = expected_score(r2, r1, rd)
        self.assertGreater(p1, 0.5)
        self.assertLess(p2, 0.5)
        self.assertAlmostEqual(p1 + p2, 1.0, places=5)

    def test_win_increases_rating_and_decreases_rd(self):
        player = Rating(rating=1500.0, rd=200.0, sigma=0.06)
        opponent = Rating(rating=1500.0, rd=200.0, sigma=0.06)

        updated = self.engine.update_rating(player, [(WIN, opponent)])
        self.assertGreater(updated.rating, 1500.0)
        self.assertLess(updated.rd, 200.0)

    def test_loss_decreases_rating_and_decreases_rd(self):
        player = Rating(rating=1500.0, rd=200.0, sigma=0.06)
        opponent = Rating(rating=1500.0, rd=200.0, sigma=0.06)

        updated = self.engine.update_rating(player, [(LOSS, opponent)])
        self.assertLess(updated.rating, 1500.0)
        self.assertLess(updated.rd, 200.0)

    def test_draw_maintains_rating_for_equal_opponents(self):
        player = Rating(rating=1500.0, rd=200.0, sigma=0.06)
        opponent = Rating(rating=1500.0, rd=200.0, sigma=0.06)

        updated = self.engine.update_rating(player, [(DRAW, opponent)])
        self.assertAlmostEqual(updated.rating, 1500.0, places=2)
        self.assertLess(updated.rd, 200.0)


class TeamRatingCalculatorTests(unittest.TestCase):
    def test_calculate_team_rating(self):
        ratings = {
            1: {TOTAL: Rating(1600.0, 100.0, 0.05)},
            2: {TOTAL: Rating(1400.0, 100.0, 0.05)},
        }
        team_rating = calculate_team_rating([1, 2], 2, ratings, TOTAL)
        self.assertIsNotNone(team_rating)
        self.assertAlmostEqual(team_rating.rating, 1500.0)
        self.assertAlmostEqual(team_rating.rd, 100.0)

    def test_create_virtual_rating(self):
        ratings = {
            1: {TOTAL: Rating(1600.0, 120.0, 0.05)},
        }
        team_rating = Rating(1500.0, 100.0, 0.05)
        virtual = create_virtual_rating(1, team_rating, ratings, TOTAL)
        self.assertAlmostEqual(virtual.rating, 1500.0)
        expected_rd = math.sqrt((120.0 ** 2 + 100.0 ** 2) / 2)
        self.assertAlmostEqual(virtual.rd, expected_rd)
        self.assertEqual(virtual.sigma, 0.05)


if __name__ == "__main__":
    unittest.main()
