import os
from pathlib import Path
import re
import shutil
import tempfile
import time
import unittest

from scripts.accounts.auth import pass_psychology_test, register_user
from scripts.accounts.database import approve_user, get_accounts_connection, mark_email_verified, update_user_role
from web.app import app


class RouteTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_accounts_db = Path(self.temp_dir.name) / "test_accounts.db"
        self.test_rb48_db = Path(self.temp_dir.name) / "test_rb48.db"
        prod_rb48 = Path(__file__).resolve().parents[1] / "data" / "rb48.db"
        if prod_rb48.exists():
            shutil.copy2(prod_rb48, self.test_rb48_db)
        os.environ["RB48_ACCOUNTS_DATABASE_FILE"] = str(self.test_accounts_db)
        os.environ["RB48_DATABASE_FILE"] = str(self.test_rb48_db)
        self.client = app.test_client()

    def tearDown(self):
        os.environ.pop("RB48_ACCOUNTS_DATABASE_FILE", None)
        os.environ.pop("RB48_DATABASE_FILE", None)
        self.temp_dir.cleanup()

    def create_user_session(self, role="user", verified=True, approved=True, psychology_passed=True):
        unique_name = f"rt_user_{int(time.time() * 1000000)}"
        email = f"{unique_name}@example.com"
        user_id, _ = register_user(unique_name, email, "password123", role=role)

        connection = get_accounts_connection()
        try:
            if verified:
                mark_email_verified(connection, user_id)
            if approved or role in ("admin", "webmaster"):
                approve_user(connection, user_id, approved=True)
            if role != "user":
                update_user_role(connection, user_id, role)
        finally:
            connection.close()

        if psychology_passed:
            pass_psychology_test(user_id)

        return user_id

    def test_public_routes_render(self):
        public_routes = [
            "/",
            "/dashboard",
            "/matches",
            "/glickofaq",
            "/about",
            "/model-documentation",
            "/model-documentation/raw",
            "/login",
            "/register",
            "/resend-verification",
        ]
        for route in public_routes:
            with self.subTest(route=route):
                response = self.client.get(route)
                self.assertEqual(response.status_code, 200)

    def test_model_documentation_formula_rendering(self):
        # Glicko docs
        resp_glicko = self.client.get("/model-documentation")
        self.assertEqual(resp_glicko.status_code, 200)
        html_glicko = resp_glicko.get_data(as_text=True)
        no_script_glicko = re.sub(r"<script.*?</script>", "", html_glicko, flags=re.DOTALL)
        no_boxes_glicko = re.sub(r'<div class="doc-formula-box">\$\$.*?\$\$</div>', '', no_script_glicko, flags=re.DOTALL)
        self.assertNotIn("$$", no_boxes_glicko)

    def test_protected_routes_redirect_unauthenticated(self):
        # Visitor trying to access stats, model analysis, or match center
        resp_stats = self.client.get("/stats")
        self.assertEqual(resp_stats.status_code, 302)

        resp_model = self.client.get("/model-analysis")
        self.assertEqual(resp_model.status_code, 302)

        resp_mc = self.client.get("/match-center")
        self.assertEqual(resp_mc.status_code, 302)

    def test_authenticated_approved_user_can_access_stats(self):
        user_id = self.create_user_session(role="user", verified=True, approved=True, psychology_passed=False)
        with self.client.session_transaction() as sess:
            sess["user_id"] = user_id

        resp_stats = self.client.get("/stats")
        self.assertEqual(resp_stats.status_code, 200)
        stats_html = resp_stats.get_data(as_text=True)
        self.assertIn("time-rail-title-badge", stats_html)
        self.assertIn("Statistik<br>Historie", stats_html)

        # Check matches timeline top scroll button
        resp_matches = self.client.get("/matches")
        self.assertEqual(resp_matches.status_code, 200)
        self.assertIn("Nach oben scrollen", resp_matches.get_data(as_text=True))

        # User can access Match Center (Matchmaker view only)
        resp_mc = self.client.get("/match-center")
        self.assertEqual(resp_mc.status_code, 200)
        mc_html = resp_mc.get_data(as_text=True)
        self.assertIn("matchmaker-details", mc_html)
        self.assertNotIn("parser-details", mc_html)
        self.assertNotIn('id="match-form"', mc_html)

        # But cannot access model analysis yet (requires psychology test)
        resp_model = self.client.get("/model-analysis")
        self.assertEqual(resp_model.status_code, 302)

    def test_authenticated_glicko_user_access(self):
        user_id = self.create_user_session(role="user", verified=True, approved=True, psychology_passed=True)
        with self.client.session_transaction() as sess:
            sess["user_id"] = user_id

        # Glicko user can access stats, model analysis, and Match Center (Matchmaker view)
        resp_stats = self.client.get("/stats")
        self.assertEqual(resp_stats.status_code, 200)

        resp = self.client.get("/model-analysis")
        self.assertEqual(resp.status_code, 200)

        resp_mc = self.client.get("/match-center")
        self.assertEqual(resp_mc.status_code, 200)
        mc_html = resp_mc.get_data(as_text=True)
        self.assertIn("matchmaker-details", mc_html)
        self.assertNotIn("parser-details", mc_html)
        self.assertNotIn('id="match-form"', mc_html)

    def test_admin_access(self):
        admin_id = self.create_user_session(role="admin", verified=True, approved=True, psychology_passed=True)
        with self.client.session_transaction() as sess:
            sess["user_id"] = admin_id

        resp = self.client.get("/match-center")
        self.assertEqual(resp.status_code, 200)
        admin_html = resp.get_data(as_text=True)
        self.assertIn("matchmaker-details", admin_html)
        self.assertIn("parser-details", admin_html)
        self.assertIn('id="match-form"', admin_html)

    def test_news_pagination_api(self):
        response = self.client.get("/news/items?offset=0&limit=2")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIn("news", data)
        self.assertIn("has_more", data)

    def test_stats_page_renders_delta_selector_and_data_attributes(self):
        user_id = self.create_user_session(role="user", verified=True, approved=True, psychology_passed=True)
        with self.client.session_transaction() as sess:
            sess["user_id"] = user_id

        response = self.client.get("/stats")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("delta-mode-select", html)
        self.assertIn("delta-toggle-btn", html)
        self.assertTrue("Letztes Spiel" in html or "Last Game" in html)
        self.assertTrue("Letzter Monat" in html or "Last Month" in html)

        # Also verify player profile timeline
        resp_player = self.client.get("/player/1")
        self.assertEqual(resp_player.status_code, 200)
        self.assertIn("Nach oben scrollen", resp_player.get_data(as_text=True))
        self.assertTrue("Letztes Quartal" in html or "Last Quarter" in html)
        self.assertTrue("Letztes Jahr" in html or "Last Year" in html)
        self.assertTrue("Δ C-Rating" in html or "Δ C Rating" in html)
        self.assertTrue("Δ E-Rating" in html or "Δ E Rating" in html)
        self.assertIn("Δ RD", html)
        self.assertTrue("Δ S" in html or "Δ G" in html)
        self.assertTrue("Δ Sg" in html or "Δ W" in html)
        self.assertTrue("Δ Nd" in html or "Δ L" in html)
        self.assertTrue("Δ S%" in html or "Δ W%" in html)
        self.assertIn("data-total-delta-game-conservative", html)
        self.assertIn("data-total-delta-game-rating", html)
        self.assertIn("data-total-delta-game-rd", html)
        self.assertIn("data-total-delta-month-games", html)
        self.assertIn('const isGlickoUser = true;', html)
        self.assertIn('let currentSortColumn = isGlickoUser ? "conservative" : "games";', html)

    def test_stats_sorting_for_regular_user_defaults_to_games(self):
        user_id = self.create_user_session(role="user", verified=True, approved=True, psychology_passed=False)
        with self.client.session_transaction() as sess:
            sess["user_id"] = user_id

        response = self.client.get("/stats")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('const isGlickoUser = false;', html)
        self.assertIn('let currentSortColumn = isGlickoUser ? "conservative" : "games";', html)

    def test_match_center_create_player_ajax(self):
        admin_id = self.create_user_session(role="admin", verified=True, approved=True, psychology_passed=True)
        with self.client.session_transaction() as sess:
            sess["user_id"] = admin_id

        # First verify match center renders + Add new player button and modal
        get_res = self.client.get("/match-center")
        self.assertEqual(get_res.status_code, 200)
        self.assertTrue("+ Neuen Spieler" in get_res.get_data(as_text=True) or "+ Add new player" in get_res.get_data(as_text=True))
        self.assertIn("add-modal", get_res.get_data(as_text=True))

        # Test AJAX player creation
        import time
        unique_name = f"AjaxPlayer_{int(time.time() * 1000)}"
        post_res = self.client.post(
            "/match-center",
            data={
                "action": "create_player",
                "new_alias": unique_name,
                "new_positions": ["MID", "ATT"],
                "main_position": "ATT",
                "calibration": "average",
                "certainty": "uncertain",
                "target_team": "a",
            },
            headers={"X-Requested-With": "XMLHttpRequest"}
        )
        self.assertEqual(post_res.status_code, 200)
        data = post_res.get_json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data.get("alias"), unique_name)
        self.assertEqual(data.get("target_team"), "a")
        self.assertIn("player_id", data)

    def test_glickofaq_contains_model_documentation_link(self):
        resp = self.client.get("/glickofaq")
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn("/model-documentation", html)
        self.assertIn("webmaster-project", html)
        self.assertIn("Hier findest du eine detaillierte Dokumentation der RB48Glicko Implementation", html)

    def test_model_documentation_renders_dynamically_from_markdown(self):
        resp = self.client.get("/model-documentation")
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn("perceived strength", html)
        self.assertIn("doc-container", html)
        self.assertIn("1. Introduction: Why Glicko-2 for Recreational Football?", html)
        self.assertIn("katex.min.css", html)
        self.assertIn("katex.min.js", html)
        self.assertIn("auto-render.min.js", html)

        # Verify static KaTeX assets are successfully served locally
        resp_css = self.client.get("/static/vendor/katex/katex.min.css")
        self.assertEqual(resp_css.status_code, 200)
        resp_css.close()
        resp_js = self.client.get("/static/vendor/katex/katex.min.js")
        self.assertEqual(resp_js.status_code, 200)
        resp_js.close()

        raw_resp = self.client.get("/model-documentation/raw")
        self.assertEqual(raw_resp.status_code, 200)
        self.assertIn("text/markdown", raw_resp.content_type)
        raw_text = raw_resp.get_data(as_text=True)
        self.assertIn("perceived strength", raw_text)

    def test_delete_match_endpoint_requires_admin_and_works(self):
        import json
        from scripts.database.database import get_connection
        from scripts.database.db_players import get_players
        from scripts.matches.match_entry import add_match

        conn = get_connection()
        try:
            players = get_players(conn)
            pids = list(players.keys())[:2]
            # Add a temporary test match
            match_id = add_match(
                conn,
                "2026-12-01",
                "box",
                [pids[0]],
                [pids[1]],
                10,
                8,
            )
        finally:
            conn.close()

        # 1. Unauthenticated or regular user cannot delete
        user_id = self.create_user_session(role="user")
        with self.client.session_transaction() as sess:
            sess["user_id"] = user_id

        res_forbidden = self.client.post(
            "/matches/delete",
            data=json.dumps({"match_id": match_id}),
            content_type="application/json",
            headers={"X-Requested-With": "XMLHttpRequest"}
        )
        self.assertEqual(res_forbidden.status_code, 302)

        # 2. Admin can delete
        admin_id = self.create_user_session(role="admin")
        with self.client.session_transaction() as sess:
            sess["user_id"] = admin_id

        res_ok = self.client.post(
            "/matches/delete",
            data=json.dumps({"match_id": match_id}),
            content_type="application/json",
            headers={"X-Requested-With": "XMLHttpRequest"}
        )
        self.assertEqual(res_ok.status_code, 200)
        data = res_ok.get_json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data.get("deleted_match_id"), match_id)

        # Verify match no longer exists in DB
        conn = get_connection()
        try:
            row = conn.execute("SELECT 1 FROM matches WHERE match_id = ?", (match_id,)).fetchone()
            self.assertIsNone(row)
        finally:
            conn.close()

    def test_model_switcher_visibility_and_toggle(self):
        """Test that model switcher is only visible for Glicko-tier users and toggles correctly."""
        # 1. Visitor cannot see model switcher
        resp_visitor = self.client.get("/dashboard")
        self.assertEqual(resp_visitor.status_code, 200)
        self.assertNotIn("model-toggle-group", resp_visitor.get_data(as_text=True))

        # 2. Regular user (Tier.USER) cannot see model switcher
        user_id = self.create_user_session(role="user", verified=True, approved=True, psychology_passed=False)
        with self.client.session_transaction() as sess:
            sess["user_id"] = user_id

        resp_user = self.client.get("/dashboard")
        self.assertEqual(resp_user.status_code, 200)
        self.assertNotIn("model-toggle-group", resp_user.get_data(as_text=True))

    def test_achievements_search_filter_and_webmaster_view(self):
        # 1. Unauthenticated visitor redirects to login
        resp = self.client.get("/achievements")
        self.assertEqual(resp.status_code, 302)

        # 2. Webmaster user accesses achievements
        wm_id = self.create_user_session(role="webmaster", verified=True, approved=True, psychology_passed=True)
        with self.client.session_transaction() as sess:
            sess["user_id"] = wm_id
        resp = self.client.get("/achievements")
        self.assertEqual(resp.status_code, 302)
        target_url = resp.headers.get("Location", "")
        self.assertIn("/achievements/", target_url)

        resp_page = self.client.get(target_url)
        self.assertEqual(resp_page.status_code, 200)
        html = resp_page.get_data(as_text=True)

        # Verify search filter elements are present in Webmaster view:
        self.assertIn('id="player-search-input"', html)
        self.assertIn('id="players-datalist"', html)
        self.assertIn('id="achievements-search-input"', html)
        self.assertIn('class="achievements-filter-bar"', html)
        self.assertIn('data-filter="all"', html)
        self.assertIn('data-filter="unlocked"', html)
        self.assertIn('data-filter="locked"', html)
        self.assertIn('id="achievements-counter"', html)
        self.assertIn('id="no-achievements-found"', html)

    def test_mobile_navigation_markup_and_css(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn('id="nav-mobile-toggle"', html)
        self.assertIn('class="nav-actions"', html)
        self.assertIn('id="nav-links"', html)

        # Ensure CSS does not have the rogue !important hiding the mobile toggle globally
        css_path = Path(__file__).resolve().parents[1] / "web" / "static" / "style.css"
        css_text = css_path.read_text(encoding="utf-8")
        self.assertNotIn(".nav-mobile-toggle {\n    display: none !important;", css_text)
        self.assertIn("display: inline-flex !important;", css_text)

    def test_update_match_pitch_endpoint_and_recalculation(self):
        import csv
        import json
        from scripts.database.database import get_connection
        from scripts.database.db_players import get_players
        from scripts.glicko.glicko2_calculator import recalculate_glicko2_ratings
        from scripts.matches.match_entry import add_match

        test_matches_dir = Path(self.temp_dir.name) / "matches"
        test_backup_dir = Path(self.temp_dir.name) / "match_backups"
        old_matches_dir = os.environ.get("RB48_MATCHES_DIR")
        old_backup_dir = os.environ.get("RB48_MATCH_BACKUP_DIR")
        os.environ["RB48_MATCHES_DIR"] = str(test_matches_dir)
        os.environ["RB48_MATCH_BACKUP_DIR"] = str(test_backup_dir)

        try:
            conn = get_connection()
            try:
                players = get_players(conn)
                pids = list(players.keys())[:2]
                match_id = add_match(
                    conn,
                    "2026-12-05",
                    "box",
                    [pids[0]],
                    [pids[1]],
                    5,
                    3,
                )
                recalculate_glicko2_ratings(connection=conn, create_backup=False)

                ratings_before = {
                    r["rating_type"]: r["rating"]
                    for r in conn.execute(
                        "SELECT rating_type, rating FROM ratings WHERE player_id = ?",
                        (pids[0],),
                    ).fetchall()
                }
                self.assertEqual(set(ratings_before.keys()), {"box", "hf", "total"})
            finally:
                conn.close()

            # 1. Regular user does not see pitch edit UI and cannot POST /matches/update-pitch
            user_id = self.create_user_session(role="user")
            with self.client.session_transaction() as sess:
                sess["user_id"] = user_id

            resp_user_page = self.client.get("/matches")
            html_user = resp_user_page.get_data(as_text=True)
            self.assertNotIn('class="match-pitch-btn"', html_user)
            self.assertNotIn('id="change-pitch-modal"', html_user)

            res_forbidden = self.client.post(
                "/matches/update-pitch",
                data=json.dumps({"match_id": match_id, "pitch": "hf"}),
                content_type="application/json",
                headers={"X-Requested-With": "XMLHttpRequest"},
            )
            self.assertIn(res_forbidden.status_code, (302, 403))

            # 2. Admin sees pitch edit button/modal and can switch box -> hf
            admin_id = self.create_user_session(role="admin")
            with self.client.session_transaction() as sess:
                sess["user_id"] = admin_id

            resp_admin_page = self.client.get("/matches")
            html_admin = resp_admin_page.get_data(as_text=True)
            self.assertIn('class="match-pitch-btn"', html_admin)
            self.assertIn('id="change-pitch-modal"', html_admin)

            res_admin = self.client.post(
                "/matches/update-pitch",
                data=json.dumps({"match_id": match_id, "pitch": "hf"}),
                content_type="application/json",
                headers={"X-Requested-With": "XMLHttpRequest"},
            )
            self.assertEqual(res_admin.status_code, 200)
            data_admin = res_admin.get_json()
            self.assertTrue(data_admin.get("success"))
            self.assertTrue(data_admin.get("changed"))
            self.assertEqual(data_admin.get("old_pitch"), "box")
            self.assertEqual(data_admin.get("new_pitch"), "hf")
            self.assertIsNotNone(data_admin.get("backup_file"))
            self.assertTrue((test_backup_dir / data_admin["backup_file"]).exists())

            # Verify DB pitch and recalculated rating tracks (box decreases, hf increases, total unchanged)
            conn = get_connection()
            try:
                m_row = conn.execute(
                    "SELECT pitch FROM matches WHERE match_id = ?",
                    (match_id,),
                ).fetchone()
                self.assertEqual(m_row["pitch"], "hf")

                ratings_after = {
                    r["rating_type"]: r["rating"]
                    for r in conn.execute(
                        "SELECT rating_type, rating FROM ratings WHERE player_id = ?",
                        (pids[0],),
                    ).fetchall()
                }
                self.assertLess(ratings_after["box"], ratings_before["box"])
                self.assertGreater(ratings_after["hf"], ratings_before["hf"])
                self.assertAlmostEqual(ratings_after["total"], ratings_before["total"], places=6)
            finally:
                conn.close()

            # Verify CSV source file was updated to 'hf'
            csv_path = test_matches_dir / "2026-12-05.csv"
            with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
                csv_rows = list(csv.reader(f))
            matched_rows = [r for r in csv_rows if r and r[0] == match_id]
            self.assertEqual(len(matched_rows), 1)
            self.assertEqual(matched_rows[0][1], "hf")

            # 3. Webmaster can switch hf -> box and tracks return to original values
            wm_id = self.create_user_session(role="webmaster")
            with self.client.session_transaction() as sess:
                sess["user_id"] = wm_id

            res_wm = self.client.post(
                "/matches/update-pitch",
                data=json.dumps({"match_id": match_id, "pitch": "box"}),
                content_type="application/json",
                headers={"X-Requested-With": "XMLHttpRequest"},
            )
            self.assertEqual(res_wm.status_code, 200)
            data_wm = res_wm.get_json()
            self.assertTrue(data_wm.get("success"))
            self.assertEqual(data_wm.get("new_pitch"), "box")

            conn = get_connection()
            try:
                ratings_back = {
                    r["rating_type"]: r["rating"]
                    for r in conn.execute(
                        "SELECT rating_type, rating FROM ratings WHERE player_id = ?",
                        (pids[0],),
                    ).fetchall()
                }
                self.assertAlmostEqual(ratings_back["box"], ratings_before["box"], places=6)
                self.assertAlmostEqual(ratings_back["hf"], ratings_before["hf"], places=6)
                self.assertAlmostEqual(ratings_back["total"], ratings_before["total"], places=6)
            finally:
                conn.close()
        finally:
            if old_matches_dir is None:
                os.environ.pop("RB48_MATCHES_DIR", None)
            else:
                os.environ["RB48_MATCHES_DIR"] = old_matches_dir
            if old_backup_dir is None:
                os.environ.pop("RB48_MATCH_BACKUP_DIR", None)
            else:
                os.environ["RB48_MATCH_BACKUP_DIR"] = old_backup_dir


if __name__ == "__main__":
    unittest.main()

