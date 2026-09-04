import unittest
from datetime import datetime
from web.app import app
from web.services.translations import (
    t,
    get_current_lang,
    set_current_lang,
    format_date_localized,
    format_month_localized,
    TRANSLATIONS,
)


class I18nTests(unittest.TestCase):
    def setUp(self):
        self.app = app
        self.app.config["TESTING"] = True
        self.app.config["SECRET_KEY"] = "test-i18n-secret"
        self.client = self.app.test_client()

    def test_default_language_is_german(self):
        """Without any session or query param, the active language must be 'de'."""
        with self.app.test_request_context("/"):
            self.assertEqual(get_current_lang(), "de")

        # Renders German content by default
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        # HTML tag lang attribute
        self.assertIn('<html lang="de">', html)
        # German navigation and dashboard elements
        self.assertIn("Spielhistorie", html)
        self.assertIn("Planer", html)

    def test_switch_language_to_english_and_back(self):
        """User can switch between English and German via /set-language/<lang>."""
        # 1. Switch to English
        resp = self.client.get("/set-language/en?next=/about", follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn('<html lang="en">', html)
        self.assertIn("About RB 48", html)
        self.assertIn("Match History", html)
        self.assertIn("Planner", html)

        # 2. Switch back to German
        resp2 = self.client.get("/set-language/de?next=/about", follow_redirects=True)
        self.assertEqual(resp2.status_code, 200)
        html2 = resp2.get_data(as_text=True)
        self.assertIn('<html lang="de">', html2)
        self.assertIn("Über RB 48", html2)
        self.assertIn("Spielhistorie", html2)
        self.assertIn("Planer", html2)

    def test_switch_language_open_redirect_protection(self):
        """Ensure external malicious redirect URLs in 'next' parameter are sanitized."""
        resp = self.client.get("/set-language/de?next=https://evil.com/phish")
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.headers["Location"], "/")

        resp2 = self.client.get("/set-language/de?next=//evil.com")
        self.assertEqual(resp2.status_code, 302)
        self.assertEqual(resp2.headers["Location"], "/")

    def test_switch_language_invalid_locale_ignored(self):
        """Passing an unsupported locale like 'fr' defaults safely back to 'de'."""
        resp = self.client.get("/set-language/fr?next=/about", follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn('<html lang="de">', html)

    def test_date_formatting_localized(self):
        """Test formatting dates into German and English with Wednesday matchdays."""
        # Wednesday test
        wed = "2026-09-09 20:00"
        de_str = format_date_localized(wed, lang="de")
        en_str = format_date_localized(wed, lang="en")
        self.assertIn("Mittwoch", de_str)
        self.assertIn("09.09.2026", de_str)
        self.assertIn("Wednesday", en_str)
        self.assertIn("09.09.2026", en_str)

        # Sunday test
        sun = "2026-09-13 18:00"
        de_sun = format_date_localized(sun, lang="de")
        en_sun = format_date_localized(sun, lang="en")
        self.assertIn("Sonntag", de_sun)
        self.assertIn("Sunday", en_sun)

    def test_month_formatting_localized(self):
        """Test month formatting in German and English."""
        self.assertEqual(format_month_localized("2026-03-01", lang="de"), "März 2026")
        self.assertEqual(format_month_localized("2026-03-01", lang="en"), "March 2026")
        self.assertEqual(format_month_localized("2026-05-15", lang="de"), "Mai 2026")
        self.assertEqual(format_month_localized("2026-05-15", lang="en"), "May 2026")
        self.assertEqual(format_month_localized("2026-10-01", lang="de"), "Oktober 2026")
        self.assertEqual(format_month_localized("2026-10-01", lang="en"), "October 2026")
        self.assertEqual(format_month_localized("2026-12-01", lang="de"), "Dezember 2026")
        self.assertEqual(format_month_localized("2026-12-01", lang="en"), "December 2026")

    def test_translation_helper_fallback_and_formatting(self):
        """Test t() helper with kwargs, fallbacks, and HTML safety."""
        # Known key in German
        self.assertEqual(str(t("common.save", lang="de")), "Speichern")
        self.assertEqual(str(t("common.save", lang="en")), "Save")

        # Kwarg formatting
        self.assertEqual(str(t("planner.attending_count", lang="de", count=7)), "7 zugesagt")
        self.assertEqual(str(t("planner.attending_count", lang="en", count=7)), "7 attending")

        # Missing key returns default or key itself
        self.assertEqual(str(t("nonexistent.key", default="Default Value")), "Default Value")
        self.assertEqual(str(t("nonexistent.key")), "nonexistent.key")

    def test_no_legacy_tuesday_references_in_catalogs(self):
        """Standard matchdays are Wednesdays. Verify no Tuesday/Dienstag remnants in catalogs."""
        for lang in ("de", "en"):
            catalog = TRANSLATIONS.get(lang, {})
            for key, text in catalog.items():
                if isinstance(text, str):
                    self.assertNotIn(
                        "tuesday",
                        text.lower(),
                        f"Legacy 'tuesday' found in {lang} key '{key}': {text}",
                    )
                    self.assertNotIn(
                        "dienstag",
                        text.lower(),
                        f"Legacy 'dienstag' found in {lang} key '{key}': {text}",
                    )


if __name__ == "__main__":
    unittest.main()
