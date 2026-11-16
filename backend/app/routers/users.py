"""Sign-in, the current user, and admin user management."""

from fastapi import APIRouter, Depends, Request, Response
from pydantic import Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import (
    COOKIE,
    ROLES,
    User,
    admin,
    authenticate,
    check_password_policy,
    create_session,
    hash_password,
    revoke_session,
    revoke_user_sessions,
    throttle,
    verify_password,
)
from app.config import Settings
from app.db import get_db
from app.schemas import Api, UTCDatetime

from .common import error, settings_dep

router = APIRouter(tags=["auth"])


class UserOut(Api):
    id: int
    email: str
    name: str
    role: str
    active: bool
    created_at: UTCDatetime
    last_login_at: UTCDatetime | None = None


class Login(Api):
    email: str = Field(max_length=254)
    password: str = Field(max_length=200)


class PasswordChange(Api):
    current_password: str = Field(max_length=200)
    new_password: str = Field(max_length=200)


class UserCreate(Api):
    email: str = Field(min_length=3, max_length=254)
    name: str = Field(min_length=1, max_length=120)
    role: str = "viewer"
    password: str = Field(max_length=200)


class UserUpdate(Api):
    name: str | None = Field(None, min_length=1, max_length=120)
    role: str | None = None
    active: bool | None = None


class PasswordReset(Api):
    password: str = Field(max_length=200)


def _role(role: str) -> str:
    if role not in ROLES:
        raise error(422, "invalid_role", f"Role must be one of {', '.join(ROLES)}")
    return role


def _password(pw: str) -> str:
    try:
        check_password_policy(pw)
    except ValueError as e:
        raise error(422, "weak_password", str(e)) from None
    return pw


# ---- session -----------------------------------------------------------------------------


@router.post("/auth/login", response_model=UserOut)
def login(body: Login, request: Request, response: Response, db: Session = Depends(get_db),
          s: Settings = Depends(settings_dep)):  # fmt: skip
    email = body.email.strip().lower()
    client = f"ip:{request.client.host if request.client else '?'}"
    if throttle.blocked(email, client):
        raise error(
            429, "too_many_attempts", "Too many failed sign-ins; try again in a few minutes"
        )
    user = db.scalar(select(User).where(User.email == email))
    if user is None or not user.active or not verify_password(body.password, user.password_hash):
        throttle.fail(email, client)
        raise error(401, "bad_credentials", "Wrong email or password")
    throttle.reset(email)
    token = create_session(db, user, s.session_ttl_hours)
    response.set_cookie(
        COOKIE, token, max_age=s.session_ttl_hours * 3600, httponly=True, samesite="lax",
        secure=s.cookie_secure, path="/",
    )  # fmt: skip
    return user


@router.post("/auth/logout", status_code=204)
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    revoke_session(db, request.cookies.get(COOKIE))
    response.delete_cookie(COOKIE, path="/")
    response.status_code = 204
    return response


@router.get("/auth/me", response_model=UserOut)
def me(user: User = Depends(authenticate)):
    return user


@router.post("/auth/password", status_code=204)
def change_password(body: PasswordChange, request: Request, db: Session = Depends(get_db),
                    user: User = Depends(authenticate)):  # fmt: skip
    u = db.get(User, user.id)
    if u is None or not verify_password(body.current_password, u.password_hash):
        raise error(401, "bad_credentials", "Current password is wrong")
    u.password_hash = hash_password(_password(body.new_password))
    revoke_user_sessions(db, u.id)  # sign out everywhere else too
    return Response(status_code=204)


# ---- admin: users ------------------------------------------------------------------------


@router.get("/users", response_model=list[UserOut], dependencies=[Depends(admin)])
def list_users(db: Session = Depends(get_db)):
    return list(db.scalars(select(User).order_by(User.created_at)))


@router.post("/users", response_model=UserOut, status_code=201, dependencies=[Depends(admin)])
def create_user(body: UserCreate, db: Session = Depends(get_db)):
    email = body.email.strip().lower()
    if "@" not in email:
        raise error(422, "invalid_email", "Enter a valid email")
    if db.scalar(select(User).where(User.email == email)):
        raise error(409, "user_exists", "A user with that email already exists")
    u = User(email=email, name=body.name.strip(), role=_role(body.role),
             password_hash=hash_password(_password(body.password)))  # fmt: skip
    db.add(u)
    db.commit()
    return u


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(user_id: int, body: UserUpdate, db: Session = Depends(get_db),
                me_: User = Depends(admin)):  # fmt: skip
    u = db.get(User, user_id)
    if u is None:
        raise error(404, "user_not_found", "No such user")
    if u.id == me_.id and (body.role not in (None, "admin") or body.active is False):
        raise error(409, "self_lockout", "You cannot demote or deactivate yourself")
    if body.role is not None and body.role != "admin" and u.role == "admin" and _admins(db) <= 1:
        raise error(409, "last_admin", "Keep at least one active admin")
    changed_access = False
    if body.name is not None:
        u.name = body.name.strip()
    if body.role is not None and body.role != u.role:
        u.role, changed_access = _role(body.role), True
    if body.active is not None and body.active != u.active:
        u.active, changed_access = body.active, True
    db.commit()
    if changed_access:
        revoke_user_sessions(db, u.id)  # new access applies immediately
    return u


@router.post("/users/{user_id}/password", status_code=204, dependencies=[Depends(admin)])
def reset_password(user_id: int, body: PasswordReset, db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if u is None:
        raise error(404, "user_not_found", "No such user")
    u.password_hash = hash_password(_password(body.password))
    db.commit()
    revoke_user_sessions(db, u.id)
    return Response(status_code=204)


def _admins(db: Session) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(User)
            .where(User.role == "admin", User.active.is_(True))
        )
        or 0
    )
