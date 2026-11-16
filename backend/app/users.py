"""User admin from the shell (bootstrap the first admin, recover access).

  python -m app.users create --email you@example.com --name "You" --role admin
  python -m app.users list
  python -m app.users set-role --email someone@example.com --role reviewer
  python -m app.users deactivate --email someone@example.com
  python -m app.users reset-password --email someone@example.com

Passwords are prompted (never passed on the command line, where they would land in shell
history and process listings). Uses the same STREAMSENSE_API_* settings as the API.
"""

import argparse
import getpass
import sys

from sqlalchemy import select

from app import db as dbm
from app.auth import ROLES, User, check_password_policy, hash_password, revoke_user_sessions
from app.config import get_settings


def _prompt_password() -> str:
    pw = getpass.getpass("Password (min 10 chars): ")
    if pw != getpass.getpass("Repeat password: "):
        sys.exit("Passwords do not match")
    try:
        check_password_policy(pw)
    except ValueError as e:
        sys.exit(str(e))
    return pw


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m app.users")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create")
    c.add_argument("--email", required=True)
    c.add_argument("--name", required=True)
    c.add_argument("--role", choices=ROLES, default="viewer")
    sub.add_parser("list")
    r = sub.add_parser("set-role")
    r.add_argument("--email", required=True)
    r.add_argument("--role", choices=ROLES, required=True)
    for name in ("deactivate", "activate", "reset-password"):
        sub.add_parser(name).add_argument("--email", required=True)
    a = p.parse_args()

    s = get_settings()
    dbm.init_engine(s.database_url)
    with dbm.session() as db:
        if a.cmd == "list":
            for u in db.scalars(select(User).order_by(User.created_at)):
                print(
                    f"{u.id:4d}  {u.email:32s} {u.role:9s} {'active' if u.active else 'disabled'}  {u.name}"
                )
            return
        email = a.email.strip().lower()
        u = db.scalar(select(User).where(User.email == email))
        if a.cmd == "create":
            if u is not None:
                sys.exit(f"{email} already exists")
            db.add(
                User(
                    email=email,
                    name=a.name,
                    role=a.role,
                    password_hash=hash_password(_prompt_password()),
                )
            )
            db.commit()
            print(f"created {email} ({a.role})")
            return
        if u is None:
            sys.exit(f"no user {email}")
        if a.cmd == "set-role":
            u.role = a.role
        elif a.cmd == "deactivate":
            u.active = False
        elif a.cmd == "activate":
            u.active = True
        elif a.cmd == "reset-password":
            u.password_hash = hash_password(_prompt_password())
        db.commit()
        revoke_user_sessions(db, u.id)
        print(f"{a.cmd}: {email}")


if __name__ == "__main__":
    main()
