"""Sign-in, sessions, roles, CSRF, throttling and admin user management (auth_mode=session)."""

import pytest
from fastapi.testclient import TestClient

from app import db as dbm
from app.auth import User, hash_password, throttle
from app.main import create_app

from .conftest import analyze, jpeg, make_settings

PW = "correct horse battery"
H = {"X-Requested-With": "streamsense"}  # what the UI sends on every change


@pytest.fixture
def app_client(tmp_path):
    throttle.fails.clear()
    app = create_app(make_settings(tmp_path, auth_mode="session"))
    with TestClient(app) as c:
        with dbm.session() as db:
            for email, role in [
                ("admin@x.io", "admin"),
                ("rev@x.io", "reviewer"),
                ("view@x.io", "viewer"),
            ]:
                db.add(
                    User(
                        email=email,
                        name=email.split("@")[0],
                        role=role,
                        password_hash=hash_password(PW),
                    )
                )
            db.commit()
        yield c


def login(c, email, pw=PW):
    c.cookies.clear()
    return c.post("/auth/login", json={"email": email, "password": pw})


def test_public_and_protected(app_client):
    c = app_client
    assert c.get("/health").status_code == 200
    for path in ("/games", "/alerts", "/runs", "/model", "/media/frames/1", "/users"):
        r = c.get(path)
        assert r.status_code == 401 and r.json()["error"]["code"] == "not_signed_in", path


def test_login_cookie_and_logout(app_client):
    c = app_client
    r = login(c, "Rev@X.io")  # emails are case-insensitive
    assert r.status_code == 200 and r.json()["role"] == "reviewer"
    set_cookie = r.headers["set-cookie"].lower()
    assert "ss_session=" in set_cookie and "httponly" in set_cookie and "samesite=lax" in set_cookie
    assert c.get("/auth/me").json()["email"] == "rev@x.io"
    assert c.post("/auth/logout").status_code == 204
    assert c.get("/auth/me").status_code == 401
    assert login(c, "rev@x.io", "wrong password!").status_code == 401


def test_roles(app_client):
    c = app_client
    login(c, "view@x.io")
    assert c.get("/games").status_code == 200
    r = analyze(c, jpeg(), name="a.jpg", ctype="image/jpeg")  # viewer cannot upload
    assert r.status_code in (403, 401)
    assert c.post("/games", json={"home": "A", "away": "B", "sport": "S", "date": "2026-11-15"},
                  headers=H).status_code == 403  # fmt: skip
    login(c, "rev@x.io")
    r = c.post("/analyses", headers=H, data={"home": "A", "away": "B", "sport": "Soccer"},
               files={"file": ("a.jpg", jpeg(), "image/jpeg")})  # fmt: skip
    assert r.status_code == 202
    g = c.post(
        "/games", headers=H, json={"home": "A", "away": "B", "sport": "S", "date": "2026-11-15"}
    )
    assert g.status_code == 201  # reviewers can create games ...
    gid = g.json()["id"]
    assert c.post("/thresholds", json={"alertThreshold": 3}, headers=H).status_code == 403
    assert c.delete(f"/games/{gid}", headers=H).status_code == 403  # ... but not delete them
    assert c.get("/users").status_code == 403
    login(c, "admin@x.io")
    assert c.post("/thresholds", json={"alertThreshold": 3}, headers=H).status_code == 201
    assert c.delete(f"/games/{gid}", headers=H).status_code == 204


def test_actions_are_attributed_to_the_signed_in_user(app_client):
    c = app_client
    login(c, "rev@x.io")
    r = c.post("/analyses", headers={**H, "X-StreamSense-User": "someone-else"},
               data={"home": "A", "away": "B", "sport": "Soccer"},
               files={"file": ("a.jpg", jpeg(), "image/jpeg")})  # fmt: skip
    gid = r.json()["game"]["id"]
    fb = c.post("/feedback", headers=H, json={"gameId": gid, "frameIndex": 0, "kind": "correct"})
    assert fb.json()["reviewer"] == "rev"  # the session, not a header


def test_csrf_header_required_for_changes(app_client):
    c = app_client
    login(c, "admin@x.io")
    r = c.post("/thresholds", json={"alertThreshold": 3})  # no X-Requested-With
    assert r.status_code == 403 and r.json()["error"]["code"] == "csrf"


def test_login_throttle(app_client):
    c = app_client
    for _ in range(5):
        assert login(c, "rev@x.io", "nope nope nope").status_code == 401
    r = login(c, "rev@x.io")  # even the right password is refused while throttled
    assert r.status_code == 429 and r.json()["error"]["code"] == "too_many_attempts"


def test_admin_user_management(app_client):
    c = app_client
    login(c, "admin@x.io")
    r = c.post("/users", headers=H, json={"email": "New@X.io", "name": "New", "role": "reviewer",
                                          "password": "short"})  # fmt: skip
    assert r.status_code == 422 and r.json()["error"]["code"] == "weak_password"
    r = c.post(
        "/users",
        headers=H,
        json={"email": "new@x.io", "name": "New", "role": "reviewer", "password": PW},
    )
    assert r.status_code == 201
    uid = r.json()["id"]
    assert (
        c.post(
            "/users", headers=H, json={"email": "new@x.io", "name": "N", "password": PW}
        ).status_code
        == 409
    )
    # the new user signs in, then is demoted: their session is revoked immediately
    other = TestClient(c.app)
    assert login(other, "new@x.io").status_code == 200
    assert c.patch(f"/users/{uid}", headers=H, json={"role": "viewer"}).json()["role"] == "viewer"
    assert other.get("/auth/me").status_code == 401
    assert c.patch(f"/users/{uid}", headers=H, json={"active": False}).json()["active"] is False
    assert login(other, "new@x.io").status_code == 401
    # reset password, then the user can sign in with it once re-activated
    c.patch(f"/users/{uid}", headers=H, json={"active": True})
    assert (
        c.post(
            f"/users/{uid}/password", headers=H, json={"password": "another long pass"}
        ).status_code
        == 204
    )
    assert login(other, "new@x.io", "another long pass").status_code == 200


def test_admin_cannot_lock_themselves_out(app_client):
    c = app_client
    me = login(c, "admin@x.io").json()
    r = c.patch(f"/users/{me['id']}", headers=H, json={"role": "viewer"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "self_lockout"
    r = c.patch(f"/users/{me['id']}", headers=H, json={"active": False})
    assert r.status_code == 409


def test_change_own_password(app_client):
    c = app_client
    login(c, "view@x.io")
    body = {"currentPassword": "wrong one!!", "newPassword": "a brand new password"}
    assert c.post("/auth/password", headers=H, json=body).status_code == 401
    body["currentPassword"] = PW
    assert c.post("/auth/password", headers=H, json=body).status_code == 204
    assert c.get("/auth/me").status_code == 401  # all sessions revoked
    assert login(c, "view@x.io", "a brand new password").status_code == 200


def test_passwords_are_hashed():
    h = hash_password(PW)
    assert PW not in h and h.startswith("scrypt$") and h != hash_password(PW)  # salted
