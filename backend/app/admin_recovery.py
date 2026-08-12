"""Local, interactive recovery for database-backed administrator accounts.

Run only inside the backend container:
    python -m app.admin_recovery --username ADMIN --reset-password

This module is deliberately separate from normal HTTP login. It requires local
container access and never prints or stores a plaintext password in a command
line, log message, or .env file.
"""
from __future__ import annotations

import argparse
import getpass
import sys
from typing import Optional

from app.admin_accounts import bootstrap_admin_account, local_recover_admin, lookup_admin_by_username


def _prompt_new_password() -> str:
    password = getpass.getpass("New administrator password: ")
    confirm = getpass.getpass("Repeat new administrator password: ")
    if password != confirm:
        raise ValueError("Passwords do not match.")
    return password


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Local recovery for the PostgreSQL-backed administrator account."
    )
    parser.add_argument("--username", default="ADMIN", help="Administrator username (default: ADMIN)")
    parser.add_argument(
        "--status",
        action="store_true",
        help="Show whether the database account exists and is active; never shows a password.",
    )
    parser.add_argument(
        "--ensure-active",
        action="store_true",
        help="Re-enable the named administrator account without changing its password.",
    )
    parser.add_argument(
        "--reset-password",
        action="store_true",
        help="Prompt for a new password, store its PBKDF2 hash in PostgreSQL, and enable the account.",
    )
    parser.add_argument(
        "--confirm-local-recovery",
        action="store_true",
        help="Required acknowledgement for password changes or account reactivation.",
    )
    args = parser.parse_args(argv)

    # Guarantees the table/account bootstrap path is available on an empty DB.
    bootstrap_admin_account()

    changing = args.ensure_active or args.reset_password
    if changing and not args.confirm_local_recovery:
        parser.error("Pass --confirm-local-recovery for local account recovery.")

    if args.reset_password:
        try:
            new_password = _prompt_new_password()
            account = local_recover_admin(
                username=args.username,
                new_password=new_password,
                ensure_active=True,
            )
        except ValueError as exc:
            print(f"Recovery failed: {exc}", file=sys.stderr)
            return 2
        print(
            f"Administrator '{account['username']}' is active and its PostgreSQL password was updated."
        )
        return 0

    if args.ensure_active:
        try:
            account = local_recover_admin(
                username=args.username,
                new_password=None,
                ensure_active=True,
            )
        except ValueError as exc:
            print(f"Recovery failed: {exc}", file=sys.stderr)
            return 2
        print(f"Administrator '{account['username']}' is active. Password was not changed.")
        return 0

    account = lookup_admin_by_username(args.username)
    if not account:
        print("No administrator account exists yet. Restart the backend after setting ADMIN_BOOTSTRAP_* in .env.")
        return 1
    print(
        f"Administrator '{account['username']}' exists in PostgreSQL; active={str(bool(account['is_active'])).lower()}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
