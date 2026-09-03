import math
import unittest
from unittest.mock import patch

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
    BOX,
    expected_score,
)
from scripts.glicko.glicko2_calculator import (
    calculate_team_rating,
    calculate_teammates_rd,
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
        # Decoupled virtual player preserves personal RD
        self.assertAlmostEqual(virtual.rd, 120.0)
        self.assertEqual(virtual.sigma, 0.05)

    def test_teammate_impact(self):
        engine = Glicko2()
        self.assertEqual(engine.teammate_impact(None), 1.0)
        # Calibrated teammates (RD 60) -> high clarity (~0.98)
        self.assertGreater(engine.teammate_impact(60.0), 0.95)
        # Uncalibrated teammates (RD 348) -> dampened (~0.67)
        self.assertAlmostEqual(engine.teammate_impact(348.0), 0.672, places=2)

    def test_calculate_teammates_rd(self):
        ratings = {
            1: {TOTAL: Rating(1600.0, 60.0, 0.03)},
            2: {TOTAL: Rating(1400.0, 120.0, 0.03)},
            3: {TOTAL: Rating(1500.0, 180.0, 0.03)},
        }
        # Player 1's teammates are Player 2 (RD 120) and Player 3 (RD 180)
        teammates_rd = calculate_teammates_rd(1, [1, 2, 3], 3, ratings, TOTAL)
        expected = math.sqrt((120.0 ** 2 + 180.0 ** 2) / 2)
        self.assertAlmostEqual(teammates_rd, expected)

        # 1v1 match (total_players == 1) should return None
        single_rd = calculate_teammates_rd(1, [1], 1, ratings, TOTAL)
        self.assertIsNone(single_rd)

    def test_update_player_rd_veteran_stability(self):
        engine = Glicko2()
        veteran = Rating(rating=1600.0, rd=60.0, sigma=0.03)
        opp_team = Rating(rating=1500.0, rd=100.0, sigma=0.03)
        my_team = Rating(rating=1550.0, rd=100.0, sigma=0.03)

        # Veteran with rookie teammates (RD 348)
        rd_with_rookies = engine.update_player_rd(
            player=veteran,
            opponent_team=opp_team,
            team_rating=my_team,
            teammates_rd=348.0,
        )
        # Veteran RD should remain stable, not collapse!
        self.assertGreater(rd_with_rookies, 58.0)
        self.assertLess(rd_with_rookies, 60.0)

        # Veteran with veteran teammates (RD 60)
        rd_with_vets = engine.update_player_rd(
            player=veteran,
            opponent_team=opp_team,
            team_rating=my_team,
            teammates_rd=60.0,
        )
        # Stable teammates provide slightly more information (smaller RD) than chaotic teammates
        self.assertLess(rd_with_vets, rd_with_rookies)

    def test_update_player_rd_rookie_convergence(self):
        engine = Glicko2()
        rookie = Rating(rating=1500.0, rd=348.0, sigma=0.03)
        opp_team = Rating(rating=1500.0, rd=200.0, sigma=0.03)
        my_team = Rating(rating=1500.0, rd=200.0, sigma=0.03)

        # Rookie playing with rookie teammates (RD 348)
        new_rd = engine.update_player_rd(
            player=rookie,
            opponent_team=opp_team,
            team_rating=my_team,
            teammates_rd=348.0,
        )
        # Must make significant progress (no stalling: drops by ~62 RD points)
        self.assertLess(new_rd, 290.0)

        # Rookie playing with veteran teammates (RD 60) converges even faster
        new_rd_with_vets = engine.update_player_rd(
            player=rookie,
            opponent_team=opp_team,
            team_rating=my_team,
            teammates_rd=60.0,
        )
        self.assertLess(new_rd_with_vets, new_rd)

    @patch("scripts.glicko.glicko2_calculator.get_match_teams")
    def test_update_match_end_to_end(self, mock_get_teams):
        from scripts.glicko.glicko2_calculator import update_match
        from scripts.glicko.glicko2 import BOX

        mock_get_teams.return_value = ([1, 2], [3, 4])
        ratings = {
            1: {TOTAL: Rating(1500.0, 348.0, 0.03), BOX: Rating(1500.0, 348.0, 0.03)},
            2: {TOTAL: Rating(1500.0, 348.0, 0.03), BOX: Rating(1500.0, 348.0, 0.03)},
            3: {TOTAL: Rating(1500.0, 348.0, 0.03), BOX: Rating(1500.0, 348.0, 0.03)},
            4: {TOTAL: Rating(1500.0, 348.0, 0.03), BOX: Rating(1500.0, 348.0, 0.03)},
        }
        match = {
            "match_id": "2026-09-01-1",
            "pitch": "box",
            "players_a": 2,
            "players_b": 2,
            "goals_a": 3,
            "goals_b": 1,
        }
        engine = Glicko2()
        update_match(None, match, ratings, engine)

        # Team 1 won, ratings should increase and RDs should decrease
        self.assertGreater(ratings[1][TOTAL].rating, 1500.0)
        self.assertLess(ratings[1][TOTAL].rd, 348.0)
        self.assertGreater(ratings[1][BOX].rating, 1500.0)
        self.assertLess(ratings[1][BOX].rd, 348.0)

        # Team 2 lost, ratings should decrease and RDs should decrease
        self.assertLess(ratings[3][TOTAL].rating, 1500.0)
        self.assertLess(ratings[3][TOTAL].rd, 348.0)

    @patch("scripts.glicko.glicko2_calculator.get_match_teams")
    def test_bayesian_rating_update_dampening(self, mock_get_teams):
        from scripts.glicko.glicko2_calculator import update_match

        engine = Glicko2()
        match = {
            "match_id": "2026-09-01-1",
            "pitch": "box",
            "players_a": 2,
            "players_b": 2,
            "goals_a": 0,
            "goals_b": 2,
        }

        # Setup A: Veteran (Player 1) with Veteran teammate (Player 2)
        mock_get_teams.return_value = ([1, 2], [3, 4])
        ratings_a = {
            1: {TOTAL: Rating(1600.0, 60.0, 0.03), BOX: Rating(1600.0, 60.0, 0.03)},
            2: {TOTAL: Rating(1600.0, 60.0, 0.03), BOX: Rating(1600.0, 60.0, 0.03)},
            3: {TOTAL: Rating(1600.0, 60.0, 0.03), BOX: Rating(1600.0, 60.0, 0.03)},
            4: {TOTAL: Rating(1600.0, 60.0, 0.03), BOX: Rating(1600.0, 60.0, 0.03)},
        }
        update_match(None, match, ratings_a, engine)
        loss_with_vets = 1600.0 - ratings_a[1][TOTAL].rating

        # Setup B: Veteran (Player 1) with Rookie teammate (Player 2, RD 348)
        ratings_b = {
            1: {TOTAL: Rating(1600.0, 60.0, 0.03), BOX: Rating(1600.0, 60.0, 0.03)},
            2: {TOTAL: Rating(1600.0, 348.0, 0.03), BOX: Rating(1600.0, 348.0, 0.03)},
            3: {TOTAL: Rating(1600.0, 60.0, 0.03), BOX: Rating(1600.0, 60.0, 0.03)},
            4: {TOTAL: Rating(1600.0, 60.0, 0.03), BOX: Rating(1600.0, 60.0, 0.03)},
        }
        update_match(None, match, ratings_b, engine)
        loss_with_rookie = 1600.0 - ratings_b[1][TOTAL].rating

        # Veteran should NOT suffer an inflated loss (loss is small, < 15 pts)
        self.assertLess(loss_with_rookie, 15.0)
        # Teammate noise dampens rating change: loss with rookie teammates is smaller than with stable teammates
        self.assertLess(loss_with_rookie, loss_with_vets)

    def test_update_player_session_order_independence(self):
        """Verify that game order within a session has ZERO effect on rating, RD, and sigma."""
        engine = Glicko2()
        player = Rating(1500.0, 200.0, 0.03)

        team_a = Rating(1500.0, 100.0, 0.03)
        opp_a = Rating(1600.0, 100.0, 0.03)

        team_b = Rating(1550.0, 80.0, 0.03)
        opp_b = Rating(1480.0, 90.0, 0.03)

        # Order 1: Match A (Win) then Match B (Loss)
        games_order_1 = [
            (team_a, opp_a, WIN, 100.0),
            (team_b, opp_b, LOSS, 80.0),
        ]
        res_1 = engine.update_player_session(player, games_order_1)

        # Order 2: Match B (Loss) then Match A (Win)
        games_order_2 = [
            (team_b, opp_b, LOSS, 80.0),
            (team_a, opp_a, WIN, 100.0),
        ]
        res_2 = engine.update_player_session(player, games_order_2)

        self.assertAlmostEqual(res_1.rating, res_2.rating, places=9)
        self.assertAlmostEqual(res_1.rd, res_2.rd, places=9)
        self.assertAlmostEqual(res_1.sigma, res_2.sigma, places=9)

    def test_group_matches_by_date(self):
        from scripts.glicko.glicko2_calculator import group_matches_by_date

        matches = [
            {"match_id": "2026-07-15-2", "date": "2026-07-15"},
            {"match_id": "2026-07-08-1", "date": "2026-07-08"},
            {"match_id": "2026-07-15-1", "date": "2026-07-15"},
        ]
        sessions = group_matches_by_date(matches)
        dates = list(sessions.keys())
        self.assertEqual(dates, ["2026-07-08", "2026-07-15"])
        self.assertEqual(len(sessions["2026-07-08"]), 1)
        self.assertEqual(len(sessions["2026-07-15"]), 2)
        # Should be sorted by match_id
        self.assertEqual(sessions["2026-07-15"][0]["match_id"], "2026-07-15-1")
        self.assertEqual(sessions["2026-07-15"][1]["match_id"], "2026-07-15-2")

    @patch("scripts.glicko.glicko2_calculator.get_match_teams")
    def test_update_session_multi_match(self, mock_get_teams):
        from scripts.glicko.glicko2_calculator import update_session

        def side_effect(conn, match_id):
            if match_id == "2026-09-01-1":
                return ([1, 2], [3, 4])
            else:
                # Players 1 & 3 now team up against 2 & 4 in Game 2
                return ([1, 3], [2, 4])

        mock_get_teams.side_effect = side_effect
        engine = Glicko2()

        ratings = {
            1: {TOTAL: Rating(1500.0, 348.0, 0.03), BOX: Rating(1500.0, 348.0, 0.03)},
            2: {TOTAL: Rating(1500.0, 348.0, 0.03), BOX: Rating(1500.0, 348.0, 0.03)},
            3: {TOTAL: Rating(1500.0, 348.0, 0.03), BOX: Rating(1500.0, 348.0, 0.03)},
            4: {TOTAL: Rating(1500.0, 348.0, 0.03), BOX: Rating(1500.0, 348.0, 0.03)},
            5: {TOTAL: Rating(1500.0, 200.0, 0.03), BOX: Rating(1500.0, 200.0, 0.03)},  # Inactive player
        }

        session_matches = [
            {"match_id": "2026-09-01-1", "date": "2026-09-01", "pitch": "box", "players_a": 2, "players_b": 2, "goals_a": 2, "goals_b": 0},
            {"match_id": "2026-09-01-2", "date": "2026-09-01", "pitch": "box", "players_a": 2, "players_b": 2, "goals_a": 1, "goals_b": 3},
        ]

        update_session(None, session_matches, ratings, engine)

        # Player 1 won Game 1 and lost Game 2 against roughly equal teams -> rating stays close to 1500
        self.assertAlmostEqual(ratings[1][TOTAL].rating, 1500.0, delta=20.0)
        # But RD dropped significantly from 2 games!
        self.assertLess(ratings[1][TOTAL].rd, 280.0)

        # Inactive Player 5 gained inactivity RD tick exactly ONCE (not twice)
        from scripts.glicko.glicko2 import INACTIVITY_RD_TICK
        self.assertAlmostEqual(ratings[5][TOTAL].rd, 200.0 + INACTIVITY_RD_TICK, places=5)

    @patch("scripts.frontend.view_models.get_match_ratings")
    @patch("scripts.frontend.view_models.get_match_teams")
    @patch("scripts.frontend.view_models.get_matches")
    def test_build_match_history_session_indicators(self, mock_get_matches, mock_get_teams, mock_get_ratings):
        from scripts.frontend.view_models import build_match_history

        mock_get_matches.return_value = {
            "2026-09-01-1": {"match_id": "2026-09-01-1", "date": "2026-09-01", "pitch": "box", "players_a": 2, "players_b": 2, "goals_a": 2, "goals_b": 0},
            "2026-09-01-2": {"match_id": "2026-09-01-2", "date": "2026-09-01", "pitch": "box", "players_a": 2, "players_b": 2, "goals_a": 1, "goals_b": 1},
            "2026-09-08-1": {"match_id": "2026-09-08-1", "date": "2026-09-08", "pitch": "box", "players_a": 2, "players_b": 2, "goals_a": 3, "goals_b": 1},
        }
        mock_get_teams.return_value = ([1, 2], [3, 4])
        mock_get_ratings.return_value = {
            1: {TOTAL: {"rating": 1500.0, "rd": 200.0, "sigma": 0.03}, BOX: {"rating": 1500.0, "rd": 200.0, "sigma": 0.03}},
            2: {TOTAL: {"rating": 1500.0, "rd": 200.0, "sigma": 0.03}, BOX: {"rating": 1500.0, "rd": 200.0, "sigma": 0.03}},
            3: {TOTAL: {"rating": 1500.0, "rd": 200.0, "sigma": 0.03}, BOX: {"rating": 1500.0, "rd": 200.0, "sigma": 0.03}},
            4: {TOTAL: {"rating": 1500.0, "rd": 200.0, "sigma": 0.03}, BOX: {"rating": 1500.0, "rd": 200.0, "sigma": 0.03}},
        }
        players = {
            1: {"aliases": ["Player 1"]},
            2: {"aliases": ["Player 2"]},
            3: {"aliases": ["Player 3"]},
            4: {"aliases": ["Player 4"]},
        }

        # Global match history
        global_history = build_match_history(None, players, player_id=None, rating_type=TOTAL)
        self.assertEqual(len(global_history), 3)

        # Game 1 on 2026-09-01: pending indicator
        self.assertTrue(global_history[0]["is_session_pending"])
        self.assertFalse(global_history[0]["is_session_final"])
        self.assertEqual(global_history[0]["session_match_num"], 1)
        self.assertEqual(global_history[0]["session_matches_total"], 2)
        self.assertIn("second game of the day", global_history[0]["session_tooltip"])

        # Game 2 on 2026-09-01: session final
        self.assertFalse(global_history[1]["is_session_pending"])
        self.assertTrue(global_history[1]["is_session_final"])
        self.assertIn("Session result", global_history[1]["session_tooltip"])

        # Game 3 on 2026-09-08: single match of the day
        self.assertFalse(global_history[2]["is_session_pending"])
        self.assertFalse(global_history[2]["is_session_final"])
        self.assertEqual(global_history[2]["session_matches_total"], 1)

        # Personal match history for Player 1
        personal_history = build_match_history(None, players, player_id=1, rating_type=TOTAL)
        self.assertEqual(len(personal_history), 3)
        self.assertTrue(personal_history[0]["is_session_pending"])
        self.assertFalse(personal_history[1]["is_session_pending"])
        self.assertTrue(personal_history[1]["is_session_final"])
        # Player won Game 1 and drew Game 2 -> net session delta is positive
        self.assertGreater(personal_history[1]["player_delta"], 0.0)

    def test_calibration_values_certainty_levels(self):
        from scripts.matches.match_entry import calibration_values, CERTAINTY_LEVELS

        # Default uncertain
        vals_default = calibration_values(None, "average", "uncertain")
        self.assertEqual(vals_default["rd"], CERTAINTY_LEVELS["uncertain"][0])

        # Extremely certain
        vals_certain = calibration_values(None, "average", "extremely_certain")
        self.assertEqual(vals_certain["rd"], 80.0)

        # High certainty
        vals_high = calibration_values(None, "average", "high")
        self.assertEqual(vals_high["rd"], 120.0)

        # Moderate certainty
        vals_mod = calibration_values(None, "average", "moderate")
        self.assertEqual(vals_mod["rd"], 180.0)

        # Somewhat uncertain
        vals_some = calibration_values(None, "average", "somewhat_uncertain")
        self.assertEqual(vals_some["rd"], 250.0)

        # Invalid certainty
        with self.assertRaises(ValueError):
            calibration_values(None, "average", "invalid_certainty")


if __name__ == "__main__":
    unittest.main()
