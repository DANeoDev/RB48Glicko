import unittest

from scripts.accounts.auth import validate_registration
from web.services.markdown_service import render_markdown, MarkdownError


class MarkdownServiceTests(unittest.TestCase):
    def test_headings_rendered(self):
        text = "# Big Title\n## Sub Title"
        html = render_markdown(text)
        self.assertIn("<h1>Big Title</h1>", html)
        self.assertIn("<h2>Sub Title</h2>", html)

    def test_formatting_rendered(self):
        text = "This is **bold** and *italic* text."
        html = render_markdown(text)
        self.assertIn("<strong>bold</strong>", html)
        self.assertIn("<em>italic</em>", html)

    def test_lists_rendered(self):
        unordered = "- First\n- Second"
        html_u = render_markdown(unordered)
        self.assertIn("<ul>", html_u)
        self.assertIn("<li>First</li>", html_u)
        self.assertIn("<li>Second</li>", html_u)
        self.assertIn("</ul>", html_u)

        ordered = "1. First item\n2. Second item"
        html_o = render_markdown(ordered)
        self.assertIn("<ol>", html_o)
        self.assertIn("<li>First item</li>", html_o)
        self.assertIn("<li>Second item</li>", html_o)
        self.assertIn("</ol>", html_o)

    def test_links_rendered_safely(self):
        text = "Visit [RB48](https://example.com) for details."
        html = render_markdown(text)
        self.assertIn('<a href="https://example.com" target="_blank" rel="noopener noreferrer">RB48</a>', html)

    def test_html_injection_is_escaped(self):
        malicious = "<script>alert('pwned')</script>"
        html = render_markdown(malicious)
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_non_string_raises_error(self):
        with self.assertRaises(MarkdownError):
            render_markdown(None)


class AuthValidationTests(unittest.TestCase):
    def test_valid_registration(self):
        error = validate_registration("valid_user", "user@example.com", "securepassword123")
        self.assertIsNone(error)

    def test_short_username(self):
        error = validate_registration("ab", "user@example.com", "securepassword123")
        self.assertEqual(error, "Username must be between 3 and 30 characters.")

    def test_invalid_email(self):
        error = validate_registration("valid_user", "invalid_email", "securepassword123")
        self.assertEqual(error, "Please enter a valid email address.")

    def test_short_password(self):
        error = validate_registration("valid_user", "user@example.com", "short")
        self.assertEqual(error, "Password must be at least 8 characters long.")


if __name__ == "__main__":
    unittest.main()
