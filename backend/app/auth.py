"""Accounts, sessions and role checks.

- Passwords: scrypt (stdlib), per-user salt, constant-time compare.
- Sessions: random token in an HttpOnly cookie; only its SHA-256 is stored, so a database leak
  does not leak live sessions. Sessions expire and logout revokes them.
- Roles: viewer < reviewer < admin. Routers require viewer; routes that change things require
  reviewer or admin (see require()).
- CSRF: cookie-authenticated requests that change data must send X-Requested-With (a custom
  header a cross-site form cannot send), on top of SameSite=Lax cookies.
- auth_mode="off" (tests, local scripts) acts as a built-in admin and is logged loudly.
"""

import hashlib
import hmac
import logging
import secrets
import threading
import time
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta

from fastapi import Depends, Request
from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.db import Base, get_db
from app.models import now

log = logging.getLogger("streamsense.auth")

ROLES = ("viewer", "reviewer", "admin")
COOKIE = "ss_session"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(default="viewer")
    password_hash: Mapped[str]
    active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(default=now)
    last_login_at: Mapped[datetime | None] = mapped_column(default=None)


class UserSession(Base):
    __tablename__ = "sessions"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(default=now)
    expires_at: Mapped[datetime]
    last_seen_at: Mapped[datetime] = mapped_column(default=now)


# ---- passwords ---------------------------------------------------------------------------

_N, _R, _P = 2**14, 8, 1


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return f"scrypt${_N}${_R}${_P}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, dk = stored.split("$")
        got = hashlib.scrypt(
            password.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p), dklen=32
        )
        return hmac.compare_digest(got.hex(), dk)
    except (ValueError, TypeError):
        return False


def check_password_policy(password: str) -> None:
    if len(password) < 10:
        raise ValueError("Password must be at least 10 characters")


# ---- sessions ----------------------------------------------------------------------------


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _aware(t: datetime) -> datetime:
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def create_session(db: Session, user: User, ttl_hours: int) -> str:
    token = secrets.token_urlsafe(32)
    db.add(
        UserSession(
            token_hash=_hash(token),
            user_id=user.id,
            expires_at=datetime.now(UTC) + timedelta(hours=ttl_hours),
        )
    )
    user.last_login_at = datetime.now(UTC)
    db.commit()
    return token


def revoke_session(db: Session, token: str | None) -> None:
    if token:
        s = db.get(UserSession, _hash(token))
        if s is not None:
            db.delete(s)
            db.commit()


def revoke_user_sessions(db: Session, user_id: int) -> None:
    for s in db.query(UserSession).filter(UserSession.user_id == user_id):
        db.delete(s)
    db.commit()


# ---- login throttling (per email + per client) -------------------------------------------


class Throttle:
    """At most `limit` failures per key in `window` seconds (in-process; fine for one API)."""

    def __init__(self, limit: int = 5, window: float = 300) -> None:
        self.limit, self.window = limit, window
        self.fails: dict[str, deque] = defaultdict(deque)
        self.lock = threading.Lock()

    def blocked(self, *keys: str) -> bool:
        now = time.monotonic()
        with self.lock:
            for k in keys:
                q = self.fails[k]
                while q and now - q[0] > self.window:
                    q.popleft()
                if len(q) >= self.limit:
                    return True
        return False

    def fail(self, *keys: str) -> None:
        with self.lock:
            for k in keys:
                self.fails[k].append(time.monotonic())

    def reset(self, *keys: str) -> None:
        with self.lock:
            for k in keys:
                self.fails.pop(k, None)


throttle = Throttle()


# ---- dependencies ------------------------------------------------------------------------

_DEV_ADMIN = User(id=0, email="dev@local", name="dev", role="admin", password_hash="", active=True)


def authenticate(request: Request, db: Session = Depends(get_db)) -> User:
    """The signed-in user, or 401. Enforces the CSRF header on state-changing requests."""
    from app.routers.common import error

    s = request.app.state.settings
    if s.auth_mode == "off":
        return _DEV_ADMIN
    token = request.cookies.get(COOKIE)
    if not token:
        raise error(401, "not_signed_in", "Sign in to continue")
    sess = db.get(UserSession, _hash(token))
    if sess is None or _aware(sess.expires_at) < datetime.now(UTC):
        raise error(401, "session_expired", "Your session has expired; sign in again")
    user = db.get(User, sess.user_id)
    if user is None or not user.active:
        raise error(401, "account_disabled", "This account is disabled")
    if request.method not in SAFE_METHODS and not request.headers.get("x-requested-with"):
        raise error(403, "csrf", "Missing X-Requested-With header")
    if datetime.now(UTC) - _aware(sess.last_seen_at) > timedelta(minutes=5):
        sess.last_seen_at = datetime.now(UTC)
        db.commit()
    return user


def require(role: str):  # noqa: ANN201
    """Dependency: the signed-in user, if their role is at least `role`; else 403."""
    need = ROLES.index(role)

    def check(user: User = Depends(authenticate)) -> User:
        from app.routers.common import error

        if ROLES.index(user.role) < need:
            raise error(403, "forbidden", f"This needs the {role} role")
        return user

    check.__name__ = f"require_{role}"
    return check


viewer = require("viewer")
reviewer = require("reviewer")
admin = require("admin")
