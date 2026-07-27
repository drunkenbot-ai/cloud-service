"""Create the first superadmin account.

Run this once, directly against the database, before anyone can log into
the admin web UI at all -- there's no other way to create the very first
admin, since every admin-creation path in the UI itself requires already
being a superadmin.

Usage:
    python scripts/create_first_admin.py you@drunkenbot.ai
    (you'll be prompted for a password)
"""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import crud  # noqa: E402
from app.db import SessionLocal, init_db  # noqa: E402
from app.security import validate_password_strength  # noqa: E402


def main() -> None:
    """Parse arguments and create the first superadmin."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("email", help="Email address for the first superadmin")
    args = parser.parse_args()

    init_db()
    db = SessionLocal()
    try:
        existing = crud.get_admin_user_by_email(db, args.email)
        if existing is not None:
            print(f"An admin user with email {args.email} already exists.")
            return

        password = getpass.getpass("Password: ")
        confirm = getpass.getpass("Confirm password: ")
        if password != confirm:
            print("Passwords did not match.")
            return
        weakness = validate_password_strength(password)
        if weakness:
            print(weakness)
            return

        admin = crud.create_admin_user(db, args.email, password, "superadmin", created_by_admin_id=None)
        print(f"Created superadmin: {admin.email} (id={admin.id})")
        print("You can now log in at /admin-ui/login")
    finally:
        db.close()


if __name__ == "__main__":
    main()
