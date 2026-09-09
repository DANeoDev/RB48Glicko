import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest

from scripts.accounts.auth import register_user
from scripts.accounts.database import get_accounts_connection, mark_email_verified, update_user_role
from scripts.glicko.glicko2 import TOTAL
from scripts.matches.match_entry import create_new_player
from scripts.matchmaking.match_parser import normalize_player_name, resolve_player_names
from scripts.matchmaking.matchmaker import generate_match
from web.app import app


class MatchCenterFrontendTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_accounts_db = Path(self.temp_dir.name) / "test_accounts.db"
        self.test_rb48_db = Path(self.temp_dir.name) / "test_rb48.db"
        self.test_planner_db = Path(self.temp_dir.name) / "test_planner.db"
        prod_rb48 = Path(__file__).resolve().parents[1] / "data" / "rb48.db"
        if prod_rb48.exists():
            shutil.copy2(prod_rb48, self.test_rb48_db)
        os.environ["RB48_ACCOUNTS_DATABASE_FILE"] = str(self.test_accounts_db)
        os.environ["RB48_DATABASE_FILE"] = str(self.test_rb48_db)
        os.environ["RB48_PLANNER_DATABASE_FILE"] = str(self.test_planner_db)

        self.app = app
        unique_name = f"mc_admin_{int(time.time() * 1000000)}"
        self.admin_id, _ = register_user(unique_name, f"{unique_name}@example.com", "adminpass123", role="admin")
        conn = get_accounts_connection()
        try:
            mark_email_verified(conn, self.admin_id)
            update_user_role(conn, self.admin_id, "admin")
        finally:
            conn.close()

    def tearDown(self):
        os.environ.pop("RB48_ACCOUNTS_DATABASE_FILE", None)
        os.environ.pop("RB48_DATABASE_FILE", None)
        os.environ.pop("RB48_PLANNER_DATABASE_FILE", None)
        self.temp_dir.cleanup()

    def test_match_center_uses_one_frontend_implementation(self):
        with self.app.test_client() as client:
            with client.session_transaction() as sess:
                sess["user_id"] = self.admin_id

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

    def test_match_center_post_generate_action(self):
        with self.app.test_client() as client:
            with client.session_transaction() as sess:
                sess["user_id"] = self.admin_id

            response = client.post("/match-center", data={
                "action": "generate",
                "mode": "total",
                "pitch": "box",
                "players": ["1", "2"],
            })
            self.assertEqual(response.status_code, 200)
            self.assertIn(b"window.matchCenterPlayers", response.data)

    def test_match_center_js_syntax_is_valid(self):
        node_path = shutil.which("node")
        if node_path:
            js_file = os.path.join(self.app.root_path, "static", "match_center.js")
            result = subprocess.run(
                [node_path, "-c", js_file],
                capture_output=True,
                text=True
            )
            self.assertEqual(
                result.returncode,
                0,
                f"JavaScript syntax error in match_center.js:\n{result.stderr}"
            )

    def test_normalize_player_name(self):
        self.assertEqual(normalize_player_name("[M] Daniel"), "Daniel")
        self.assertEqual(normalize_player_name("Daniel [M]"), "Daniel")
        self.assertEqual(normalize_player_name("  [m]  Konsti   Müller  "), "Konsti Müller")
        self.assertEqual(normalize_player_name("Dennis"), "Dennis")

    def test_resolve_player_names(self):
        players = {
            1: {"aliases": ["Daniel", "Dani"], "positions": ["MID"]},
            2: {"aliases": ["Konsti"], "positions": ["ATT"]},
            3: {"aliases": ["Konsti Müller"], "positions": ["DEF"]},
        }
        verified, conflicts, unmatched = resolve_player_names(["[M] Daniel", "Konsti", "Unknown Guy"], players)
        self.assertIn(1, verified)
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["name"], "Konsti")
        self.assertEqual(len(unmatched), 1)
        self.assertEqual(unmatched[0]["name"], "Unknown Guy")

    def test_matchmaker_generation(self):
        players = {
            1: {"aliases": ["Player 1"], "positions": ["GK"]},
            2: {"aliases": ["Player 2"], "positions": ["DEF"]},
            3: {"aliases": ["Player 3"], "positions": ["MID"]},
            4: {"aliases": ["Player 4"], "positions": ["ATT"]},
        }
        ratings = {
            1: {TOTAL: {"rating": 1500.0, "rd": 200.0, "sigma": 0.06}},
            2: {TOTAL: {"rating": 1520.0, "rd": 180.0, "sigma": 0.06}},
            3: {TOTAL: {"rating": 1480.0, "rd": 190.0, "sigma": 0.06}},
            4: {TOTAL: {"rating": 1500.0, "rd": 200.0, "sigma": 0.06}},
        }
        result = generate_match([1, 2, 3, 4], players, ratings, TOTAL, seed=42)
        self.assertIsNotNone(result)
        self.assertEqual(len(result["team_a"]) + len(result["team_b"]), 4)
        self.assertIn("rating_difference", result)
        self.assertIn("position_penalty", result)

    def test_create_player_with_main_position(self):
        from scripts.database.database import get_connection
        from scripts.database.db_players import get_players

        conn = get_connection()
        try:
            unique_name = f"Striker_{int(time.time() * 1000000)}"
            pid, _ = create_new_player(conn, unique_name, ["MID", "ATT"], calibration_level="average", main_position="ATT")
            players = get_players(conn)
            self.assertIn(pid, players)
            # In players data, main position is tagged with *
            self.assertIn("ATT*", players[pid]["positions"])
            self.assertIn("MID", players[pid]["positions"])
        finally:
            conn.close()

    def test_create_player_with_certainty_level(self):
        from scripts.database.database import get_connection
        from scripts.database.db_ratings import get_calibrations
        from scripts.matches.match_entry import CERTAINTY_LEVELS

        conn = get_connection()
        try:
            unique_name = f"Veteran_{int(time.time() * 1000000)}"
            pid, values = create_new_player(
                conn,
                unique_name,
                ["DEF"],
                calibration_level="strong",
                certainty_level="extremely_certain",
            )
            calibrations = get_calibrations(conn)
            self.assertIn(pid, calibrations)
            self.assertEqual(calibrations[pid]["rd"], 80.0)
            self.assertEqual(values["rd"], 80.0)

            # Test default uncertain
            unique_name2 = f"Rookie_{int(time.time() * 1000000)}"
            pid2, values2 = create_new_player(
                conn,
                unique_name2,
                ["ATT"],
                calibration_level="average",
            )
            calibrations = get_calibrations(conn)
            self.assertEqual(calibrations[pid2]["rd"], CERTAINTY_LEVELS["uncertain"][0])
            self.assertEqual(values2["rd"], CERTAINTY_LEVELS["uncertain"][0])
        finally:
            conn.close()

    def test_calculate_match_details_asymmetric_deltas(self):
        from scripts.frontend.view_models import calculate_match_details

        match = {
            "goals_a": 5,
            "goals_b": 3,
            "players_a": 1,
            "players_b": 1,
        }
        team_a = [1]
        team_b = [2]
        match_ratings = {
            1: {TOTAL: {"rating": 1500.0, "rd": 200.0, "sigma": 0.06}},
            2: {TOTAL: {"rating": 1700.0, "rd": 80.0, "sigma": 0.06}},
        }
        details = calculate_match_details(match, team_a, team_b, match_ratings, TOTAL)
        self.assertIsNotNone(details["delta_a"])
        self.assertIsNotNone(details["delta_b"])
        # Team A won against a stronger opponent (1700 vs 1500) with high RD (200)
        self.assertGreater(details["delta_a"], 0)
        # Team B lost with lower RD (80)
        self.assertLess(details["delta_b"], 0)
        # Because RDs and ratings differ, absolute gains/losses are not strictly identical
        self.assertNotEqual(round(details["delta_a"], 4), round(-details["delta_b"], 4))

    def test_calculate_match_details_player_specific_delta(self):
        from scripts.frontend.view_models import calculate_match_details

        match = {
            "goals_a": 4,
            "goals_b": 2,
            "players_a": 2,
            "players_b": 2,
        }
        team_a = [1, 2]
        team_b = [3, 4]
        match_ratings = {
            1: {TOTAL: {"rating": 1500.0, "rd": 250.0, "sigma": 0.06}}, # high RD
            2: {TOTAL: {"rating": 1500.0, "rd": 60.0, "sigma": 0.06}},  # low RD
            3: {TOTAL: {"rating": 1500.0, "rd": 100.0, "sigma": 0.06}},
            4: {TOTAL: {"rating": 1500.0, "rd": 100.0, "sigma": 0.06}},
        }
        details_p1 = calculate_match_details(match, team_a, team_b, match_ratings, TOTAL, player_id=1)
        details_p2 = calculate_match_details(match, team_a, team_b, match_ratings, TOTAL, player_id=2)

        self.assertIsNotNone(details_p1["player_delta"])
        self.assertIsNotNone(details_p2["player_delta"])
        # High RD player 1 should gain more rating than low RD player 2 on the same winning team
        self.assertGreater(details_p1["player_delta"], details_p2["player_delta"])

    def test_match_center_get_with_players_and_date_and_pitch(self):
        with self.app.test_client() as client:
            with client.session_transaction() as sess:
                sess["user_id"] = self.admin_id

            response = client.get("/match-center?players=1,2,3&pitch=hf&date=2026-10-15")
            self.assertEqual(response.status_code, 200)
            # Check that date is prefilled
            self.assertIn(b'value="2026-10-15"', response.data)
            # Check that selected players checkboxes are checked
            self.assertIn(b'value="1"\n                                checked', response.data)
            self.assertIn(b'value="2"\n                                checked', response.data)
            self.assertIn(b'value="3"\n                                checked', response.data)

    def test_match_center_import_planner_action(self):
        from scripts.planner.database import get_planner_connection, create_event, set_user_rsvp, add_guest_rsvp

        p_conn = get_planner_connection()
        try:
            event_id = create_event(p_conn, "2026-10-21 20:00", "box", title="Wednesday Box Match")
            # Add user RSVP
            set_user_rsvp(p_conn, event_id, self.admin_id, "AdminUser", "attending")
            # Add guest RSVP with a known player name (e.g., Daniel)
            add_guest_rsvp(p_conn, event_id, "Daniel", self.admin_id, 1)
        finally:
            p_conn.close()

        with self.app.test_client() as client:
            with client.session_transaction() as sess:
                sess["user_id"] = self.admin_id

            # Post action import_planner
            response = client.post("/match-center", data={
                "action": "import_planner",
                "planner_event_id": str(event_id),
            })
            self.assertEqual(response.status_code, 200)
            self.assertIn(b"Kader erfolgreich importiert", response.data)
            self.assertIn(b'value="2026-10-21"', response.data)

    def test_match_center_parse_source_match_renders_prefilled_teams(self):
        from unittest.mock import patch
        with patch("web.routes.match_center.parse_match_text") as mock_parse:
            mock_parse.return_value = {
                "kind": "match",
                "match_date": "2026-10-21",
                "players": ["Daniel", "Dennis"],
                "team_a": ["Daniel"],
                "team_b": ["Dennis"],
                "goals_a": 10,
                "goals_b": 5,
            }
            with self.app.test_client() as client:
                with client.session_transaction() as sess:
                    sess["user_id"] = self.admin_id

                response = client.post("/match-center", data={
                    "action": "parse_source",
                    "match_text": "Team A vs Team B",
                })
                self.assertEqual(response.status_code, 200)
                self.assertIn(b"Daniel", response.data)
                self.assertIn(b"Dennis", response.data)

    def test_match_center_ignore_parser_player_action(self):
        from scripts.database.database import get_connection
        from scripts.database.db_players import get_ignored_aliases

        with self.app.test_client() as client:
            with client.session_transaction() as sess:
                sess["user_id"] = self.admin_id

            response = client.post("/match-center", data={
                "action": "ignore_parser_player",
                "target_alias": "UnknownGuestX",
                "parsed_kind": "match",
                "parsed_player": ["Daniel", "UnknownGuestX"],
                "parsed_team_a": "Daniel",
                "parsed_team_b": "UnknownGuestX",
                "parsed_goals_a": "5",
                "parsed_goals_b": "3",
            })
            self.assertEqual(response.status_code, 200)
            self.assertIn(b"Ignored", response.data)

        conn = get_connection()
        try:
            ignored = get_ignored_aliases(conn)
            self.assertIn("unknownguestx", {a.casefold() for a in ignored})
        finally:
            conn.close()

    def test_match_center_parse_match_with_ignored_player_counts_external(self):
        from unittest.mock import patch
        from scripts.database.database import get_connection
        from scripts.database.db_players import add_ignored_alias

        conn = get_connection()
        try:
            add_ignored_alias(conn, "GuestExternal")
            conn.commit()
        finally:
            conn.close()

        with patch("web.routes.match_center.parse_match_text") as mock_parse:
            mock_parse.return_value = {
                "kind": "match",
                "match_date": "2026-10-22",
                "players": ["Daniel", "GuestExternal", "Dennis"],
                "team_a": ["Daniel", "GuestExternal"],
                "team_b": ["Dennis"],
                "goals_a": 7,
                "goals_b": 6,
            }
            with self.app.test_client() as client:
                with client.session_transaction() as sess:
                    sess["user_id"] = self.admin_id

                response = client.post("/match-center", data={
                    "action": "parse_source",
                    "match_text": "Team A vs Team B match",
                })
                self.assertEqual(response.status_code, 200)
                # GuestExternal should not be unmatched because it is ignored
                self.assertNotIn(b"GuestExternal", response.data.split(b"New / Unrecognized Players")[-1] if b"New / Unrecognized Players" in response.data else b"")
                # Hidden external input should have value 1
                self.assertIn(b'id="external-a"\n                value="1"', response.data)

    def test_match_center_save_match_with_external_players(self):
        from scripts.database.database import get_connection
        from scripts.database.db_players import get_ignored_aliases, get_players

        conn = get_connection()
        try:
            players = get_players(conn)
            pids = list(players.keys())[:2]
        finally:
            conn.close()

        with self.app.test_client() as client:
            with client.session_transaction() as sess:
                sess["user_id"] = self.admin_id

            response = client.post("/match-center", data={
                "action": "save",
                "date": "2026-10-23",
                "pitch": "box",
                "team_a": [str(pids[0])],
                "team_b": [str(pids[1])],
                "external_a": "1",
                "external_b": "0",
                "goals_a": "10",
                "goals_b": "8",
            })
            self.assertEqual(response.status_code, 200)
            self.assertIn(b"Saved", response.data)

        conn = get_connection()
        try:
            ignored = get_ignored_aliases(conn)
            self.assertIn("externer spieler 1", {a.casefold() for a in ignored})
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()



