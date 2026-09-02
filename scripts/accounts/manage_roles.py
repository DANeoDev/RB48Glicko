"""CLI utility to promote, verify, or manage account roles and tiers."""

import argparse
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from scripts.accounts.database import (
    get_accounts_connection,
    get_user_by_login,
    mark_email_verified,
    set_psychology_test_status,
    update_user_role,
)


def promote_user(login, role="webmaster", verify=True, pass_test=True):
    """Promote an account by username or email."""
    connection = get_accounts_connection()
    try:
        user = get_user_by_login(connection, login)
        if not user:
            print(f"Error: User '{login}' not found in data/accounts.db.")
            return False

        user_id = user["id"]
        update_user_role(connection, user_id, role)

        if verify:
            mark_email_verified(connection, user_id)

        if pass_test:
            from datetime import datetime, timezone
            test_date = datetime.now(timezone.utc).isoformat(timespec="seconds")
            set_psychology_test_status(connection, user_id, True, test_date)

        updated = get_user_by_login(connection, login)
        print(f"\n✓ Successfully updated user '{updated['username']}':")
        print(f"  • Role: {updated['role']}")
        print(f"  • Email Verified: {'Yes' if updated['email_verified'] else 'No'}")
        print(f"  • Glicko Test Passed: {'Yes' if updated['psychology_test_passed'] else 'No'}\n")
        return True
    finally:
        connection.close()


def list_users():
    """Print all registered users and their current tiers."""
    connection = get_accounts_connection()
    try:
        rows = connection.execute(
            "SELECT id, username, email, role, email_verified, psychology_test_passed, created_at FROM users ORDER BY id"
        ).fetchall()

        print("\nRB48 Registered Accounts:")
        print(f"{'ID':<4} {'Username':<22} {'Email':<30} {'Role':<12} {'Verified':<10} {'Glicko':<8}")
        print("-" * 90)
        for r in rows:
            print(
                f"{r['id']:<4} {r['username']:<22} {r['email']:<30} {r['role']:<12} "
                f"{'Yes' if r['email_verified'] else 'No':<10} {'Yes' if r['psychology_test_passed'] else 'No':<8}"
            )
        print()
    finally:
        connection.close()


def main():
    parser = argparse.ArgumentParser(description="RB48 Account & Role Manager")
    subparsers = parser.add_subparsers(dest="command")

    # List command
    subparsers.add_parser("list", help="List all accounts")

    # Promote command
    promote_cmd = subparsers.add_parser("promote", help="Promote a user account")
    promote_cmd.add_argument("login", help="Username or email of the account")
    promote_cmd.add_argument(
        "--role",
        choices=["user", "admin", "webmaster"],
        default="webmaster",
        help="Target role (default: webmaster)",
    )

    args = parser.parse_args()

    if args.command == "list" or not args.command:
        list_users()
    elif args.command == "promote":
        promote_user(args.login, role=args.role)


if __name__ == "__main__":
    main()
