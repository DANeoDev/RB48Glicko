import os
from pathlib import Path
import tempfile
import time
import unittest

from scripts.accounts.auth import (
    generate_verification_token,
    verify_email_token,
    verify_user_email,
    register_user,
    get_user,
)


class AuthTokensTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_accounts_db = Path(self.temp_dir.name) / "test_accounts.db"
        os.environ["RB48_ACCOUNTS_DATABASE_FILE"] = str(self.test_accounts_db)

    def tearDown(self):
        os.environ.pop("RB48_ACCOUNTS_DATABASE_FILE", None)
        self.temp_dir.cleanup()

    def test_generate_and_verify_token(self):
        token = generate_verification_token(user_id=42, email="tester@example.com")
        self.assertIsInstance(token, str)

        payload, error = verify_email_token(token)
        self.assertIsNone(error)
        self.assertIsNotNone(payload)
        self.assertEqual(payload.get("user_id"), 42)
        self.assertEqual(payload.get("email"), "tester@example.com")

    def test_expired_token(self):
        token = generate_verification_token(user_id=99, email="fast@example.com")
        # Validate with max_age_seconds = -1 to simulate expiration
        payload, error = verify_email_token(token, max_age_seconds=-1)
        self.assertIsNone(payload)
        self.assertIn("expired", error.lower())

    def test_tampered_token(self):
        token = generate_verification_token(user_id=1, email="real@example.com")
        tampered = token + "xyz"
        payload, error = verify_email_token(tampered)
        self.assertIsNone(payload)
        self.assertIn("invalid", error.lower())

    def test_verify_user_email_integration(self):
        unique_login = f"user_tok_{int(time.time() * 1000)}"
        email = f"{unique_login}@example.com"
        user_id, error = register_user(unique_login, email, "password123")
        self.assertIsNone(error)

        user = get_user(user_id)
        self.assertEqual(user["email_verified"], 0)

        token = generate_verification_token(user_id, email)
        success, msg = verify_user_email(token)
        self.assertTrue(success)

        updated = get_user(user_id)
        self.assertEqual(updated["email_verified"], 1)


if __name__ == "__main__":
    unittest.main()
