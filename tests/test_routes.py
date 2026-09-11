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
            "/whr-documentation",
            "/whr-documentation/raw",
            "/login",
            "/register",
            "/resend-verification",
        ]
        for route in public_routes:
            with self.subTest(route=route):
                response = self.client.get(route)
                self.assertEqual(response.status_code, 200)

    def test_model_documentation_formula_rendering(self):
        # WHR docs
        resp_whr = self.client.get("/whr-documentation")
        self.assertEqual(resp_whr.status_code, 200)
        html_whr = resp_whr.get_data(as_text=True)
        # Check that matrix formulas rendered into doc-formula-box
        self.assertIn('<div class="doc-formula-box">$$H_{\\text{prior}} = \\begin{pmatrix}', html_whr)
        self.assertIn('<div class="doc-formula-box">$$H_i = \\begin{pmatrix}', html_whr)
        # Verify no raw unparsed $$ outside formula boxes in documentation body
        no_script_whr = re.sub(r"<script.*?</script>", "", html_whr, flags=re.DOTALL)
        no_boxes_whr = re.sub(r'<div class="doc-formula-box">\$\$.*?\$\$</div>', '', no_script_whr, flags=re.DOTALL)
        self.assertNotIn("$$", no_boxes_whr)
        # Check inline math
        self.assertIn(r"\(1/\sqrt{N}\)", html_whr)

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

        # But cannot access model analysis yet (requires psychology test)
        resp_model = self.client.get("/model-analysis")
        self.assertEqual(resp_model.status_code, 302)

    def test_authenticated_glicko_user_access(self):
        user_id = self.create_user_session(role="user", verified=True, approved=True, psychology_passed=True)
        with self.client.session_transaction() as sess:
            sess["user_id"] = user_id

        # Glicko user can access stats and model analysis
        resp_stats = self.client.get("/stats")
        self.assertEqual(resp_stats.status_code, 200)

        resp = self.client.get("/model-analysis")
        self.assertEqual(resp.status_code, 200)

        # Glicko user can also access WHR analysis mode
        resp_whr = self.client.get("/model-analysis?mode=whr")
        self.assertEqual(resp_whr.status_code, 200)
        whr_html = resp_whr.get_data(as_text=True)
        self.assertIn("Whole-History Rating", whr_html)
        self.assertIn("Log-Loss", whr_html)
        self.assertIn("btn-graph-toggle", whr_html)
        self.assertIn("comparison-series", whr_html)

        # But Glicko user cannot access Match Center (Admin only)
        resp_mc = self.client.get("/match-center")
        self.assertEqual(resp_mc.status_code, 302)

    def test_admin_access(self):
        admin_id = self.create_user_session(role="admin", verified=True, approved=True, psychology_passed=True)
        with self.client.session_transaction() as sess:
            sess["user_id"] = admin_id

        resp = self.client.get("/match-center")
        self.assertEqual(resp.status_code, 200)

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

        # Attempting /set-model as regular user does not activate WHR
        resp_set = self.client.get("/set-model?model=whr&next=/dashboard")
        self.assertEqual(resp_set.status_code, 302)
        with self.client.session_transaction() as sess:
            self.assertNotIn("active_model", sess)

        # 3. Glicko user (Tier.GLICKO_USER) CAN see model switcher
        glicko_id = self.create_user_session(role="user", verified=True, approved=True, psychology_passed=True)
        with self.client.session_transaction() as sess:
            sess["user_id"] = glicko_id

        resp_glicko = self.client.get("/dashboard")
        self.assertEqual(resp_glicko.status_code, 200)
        html_glicko = resp_glicko.get_data(as_text=True)
        self.assertIn("model-toggle-group", html_glicko)
        self.assertIn("Glicko-2", html_glicko)
        self.assertIn("WHR", html_glicko)

        # Toggle to WHR
        resp_switch_whr = self.client.get("/set-model?model=whr&next=/dashboard")
        self.assertEqual(resp_switch_whr.status_code, 302)
        with self.client.session_transaction() as sess:
            self.assertEqual(sess.get("active_model"), "whr")

        resp_after_whr = self.client.get("/dashboard")
        html_after_whr = resp_after_whr.get_data(as_text=True)
        self.assertIn('data-model="whr"', html_after_whr)

        # Toggle back to Glicko
        resp_switch_glicko = self.client.get("/set-model?model=glicko&next=/dashboard")
        self.assertEqual(resp_switch_glicko.status_code, 302)
        with self.client.session_transaction() as sess:
            self.assertEqual(sess.get("active_model"), "glicko")

    def test_stats_leaderboard_whr_switch(self):
        """Test that /stats renders WHR leaderboard and banner when active_model == whr."""
        glicko_id = self.create_user_session(role="user", verified=True, approved=True, psychology_passed=True)

        # 1. Default Glicko mode on /stats
        with self.client.session_transaction() as sess:
            sess["user_id"] = glicko_id
            sess["active_model"] = "glicko"

        resp_glicko = self.client.get("/stats")
        self.assertEqual(resp_glicko.status_code, 200)
        html_g = resp_glicko.get_data(as_text=True)
        self.assertNotIn("whr-mode-banner", html_g)

        # 2. WHR mode on /stats
        with self.client.session_transaction() as sess:
            sess["user_id"] = glicko_id
            sess["active_model"] = "whr"

        resp_whr = self.client.get("/stats")
        self.assertEqual(resp_whr.status_code, 200)
        html_w = resp_whr.get_data(as_text=True)
        self.assertIn("whr-mode-banner", html_w)
        self.assertIn("Whole-History Rating (WHR) aktiv", html_w)
        self.assertIn('window.activeModel = "whr"', html_w)
        self.assertIn('id="historical-snapshots-data"', html_w)
        self.assertIn("time-rail-wrapper", html_w)

    def test_model_analysis_whr_default(self):
        """Test that /model-analysis defaults to mode=whr when active_model == whr."""
        glicko_id = self.create_user_session(role="user", verified=True, approved=True, psychology_passed=True)

        with self.client.session_transaction() as sess:
            sess["user_id"] = glicko_id
            sess["active_model"] = "whr"

        resp = self.client.get("/model-analysis")
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn("Whole-History Rating", html)
        self.assertIn("Kalibrierungsfehler", html)
        self.assertIn("Log-Loss", html)

    def test_matches_whr_switch(self):
        """Test that /matches renders WHR banner and data when active_model == whr."""
        glicko_id = self.create_user_session(role="user", verified=True, approved=True, psychology_passed=True)

        # 1. Glicko mode
        with self.client.session_transaction() as sess:
            sess["user_id"] = glicko_id
            sess["active_model"] = "glicko"

        resp_g = self.client.get("/matches")
        self.assertEqual(resp_g.status_code, 200)
        html_g = resp_g.get_data(as_text=True)
        self.assertNotIn("WHR Hindsight-Modus aktiv", html_g)

        # 2. WHR mode
        with self.client.session_transaction() as sess:
            sess["user_id"] = glicko_id
            sess["active_model"] = "whr"

        resp_w = self.client.get("/matches")
        self.assertEqual(resp_w.status_code, 200)
        html_w = resp_w.get_data(as_text=True)
        self.assertIn("WHR Hindsight-Modus aktiv", html_w)
        self.assertIn("WHR Retrospektiv", html_w)

    def test_faq_whr_tab_gating(self):
        """Test that WHR tab in FAQ is gated to Glicko-tier users."""
        # 1. Non-glicko user
        user_id = self.create_user_session(role="user", verified=True, approved=True, psychology_passed=False)
        with self.client.session_transaction() as sess:
            sess["user_id"] = user_id

        resp = self.client.get("/glickofaq")
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertNotIn("🔮 WHR: Whole-History Rating", html)
        self.assertNotIn("id=\"faq-whr\"", html)

        # 2. Glicko user
        glicko_id = self.create_user_session(role="user", verified=True, approved=True, psychology_passed=True)
        with self.client.session_transaction() as sess:
            sess["user_id"] = glicko_id

        resp = self.client.get("/glickofaq")
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn("🔮 WHR: Whole-History Rating", html)
        self.assertIn("id=\"faq-whr\"", html)
        self.assertIn("/whr-documentation", html)

    def test_whr_documentation_page(self):
        """Test /whr-documentation and /whr-documentation/raw endpoints."""
        resp = self.client.get("/whr-documentation")
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn("Whole-History Rating", html)
        self.assertIn("Thomas", html)

        resp_raw = self.client.get("/whr-documentation/raw")
        self.assertEqual(resp_raw.status_code, 200)
        self.assertEqual(resp_raw.mimetype, "text/markdown")
        md_text = resp_raw.get_data(as_text=True)
        self.assertIn("# The RB48 Team-Based Whole-History Rating (WHR) Engine", md_text)

    def test_rating_comparison_routes(self):
        # 1. Unauthenticated visitor redirects
        resp = self.client.get("/rating-comparison")
        self.assertEqual(resp.status_code, 302)

        resp_alias = self.client.get("/model-comparison")
        self.assertEqual(resp_alias.status_code, 302)

        # 2. Non-Glicko user redirects
        non_glicko_id = self.create_user_session(role="user", verified=True, approved=True, psychology_passed=False)
        with self.client.session_transaction() as sess:
            sess["user_id"] = non_glicko_id
        resp = self.client.get("/rating-comparison")
        self.assertEqual(resp.status_code, 302)

        # 3. Glicko user gets 200 and sees comparison table
        glicko_id = self.create_user_session(role="user", verified=True, approved=True, psychology_passed=True)
        with self.client.session_transaction() as sess:
            sess["user_id"] = glicko_id
        resp = self.client.get("/rating-comparison")
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn("Modellvergleich: Glicko-2 vs. WHR", html)
        self.assertIn("comparison-table", html)
        self.assertIn("WHR (±RD)", html)

        # Pitch switcher
        for pitch in ("total", "box", "hf"):
            resp = self.client.get(f"/rating-comparison?pitch={pitch}")
            self.assertEqual(resp.status_code, 200)

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


if __name__ == "__main__":
    unittest.main()

