"""CLI utility to promote, verify, approve, or manage account roles and tiers."""

import argparse
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from scripts.accounts.database import (
    approve_user,
    get_accounts_connection,
    get_user_by_login,
    mark_email_verified,
    set_psychology_test_status,
    update_user_role,
)


def promote_user(login, role="webmaster", verify=True, pass_test=True, approve=True):
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

        if approve:
            approve_user(connection, user_id, approved=True)

        if pass_test:
            from datetime import datetime, timezone
            test_date = datetime.now(timezone.utc).isoformat(timespec="seconds")
            set_psychology_test_status(connection, user_id, True, test_date)

        updated = get_user_by_login(connection, login)
        print(f"\n✓ Successfully updated user '{updated['username']}':")
        print(f"  • Role: {updated['role']}")
        print(f"  • Email Verified: {'Yes' if updated['email_verified'] else 'No'}")
        print(f"  • Webmaster Approved: {'Yes' if updated['is_approved'] else 'No'}")
        print(f"  • Glicko Test Passed: {'Yes' if updated['psychology_test_passed'] else 'No'}\n")
        return True
    finally:
        connection.close()


def set_user_approval(login, approved=True):
    """Manually approve or revoke a user account."""
    connection = get_accounts_connection()
    try:
        user = get_user_by_login(connection, login)
        if not user:
            print(f"Error: User '{login}' not found.")
            return False

        approve_user(connection, user["id"], approved=approved)
        status = "Approved" if approved else "Revoked"
        print(f"\n✓ Account '{user['username']}' membership approval set to: {status}\n")
        return True
    finally:
        connection.close()


def list_users():
    """Print all registered users and their current tiers."""
    connection = get_accounts_connection()
    try:
        rows = connection.execute(
            """
            SELECT id, username, email, role, email_verified, is_approved, psychology_test_passed, created_at
            FROM users ORDER BY id
            """
        ).fetchall()

        print("\nRB48 Registered Accounts:")
        print(f"{'ID':<4} {'Username':<22} {'Email':<28} {'Role':<10} {'Verified':<10} {'Approved':<10} {'Glicko':<8}")
        print("-" * 98)
        for r in rows:
            print(
                f"{r['id']:<4} {r['username']:<22} {r['email']:<28} {r['role']:<10} "
                f"{'Yes' if r['email_verified'] else 'No':<10} "
                f"{'Yes' if r['is_approved'] else 'No':<10} "
                f"{'Yes' if r['psychology_test_passed'] else 'No':<8}"
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

    # Approve command
    approve_cmd = subparsers.add_parser("approve", help="Approve user membership")
    approve_cmd.add_argument("login", help="Username or email")

    # Revoke command
    revoke_cmd = subparsers.add_parser("revoke", help="Revoke user membership")
    revoke_cmd.add_argument("login", help="Username or email")

    args = parser.parse_args()

    if args.command == "list" or not args.command:
        list_users()
    elif args.command == "promote":
        promote_user(args.login, role=args.role)
    elif args.command == "approve":
        set_user_approval(args.login, approved=True)
    elif args.command == "revoke":
        set_user_approval(args.login, approved=False)


if __name__ == "__main__":
    main()
