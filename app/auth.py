import calendar
import json
import os
import secrets
import time
import jwt
from fastapi import Request, HTTPException, Depends
import bcrypt
from sqlalchemy.orm import Session
from .db import SessionLocal, User
from .config import SECRET_KEY

COOKIE = "pt_session"


def hash_password(p: str) -> str:
    return bcrypt.hashpw(p.encode()[:72], bcrypt.gensalt()).decode()


def verify_password(p: str, h: str) -> bool:
    try:
        return bcrypt.checkpw(p.encode()[:72], h.encode())
    except Exception:
        return False


def make_token(user: User) -> str:
    now = int(time.time())
    # "sid" tells one login from another made in the same second (so that logging out ends this login only)
    # and "at" is the exact moment (see session_current: a login must be younger than its account)
    return jwt.encode({"uid": user.id, "adm": user.is_admin, "iat": now, "exp": now + SESSION_SECS, "sid": secrets.token_hex(6),
                       "at": round(time.time(), 6)}, SECRET_KEY, algorithm="HS256")


SESSION_SECS = 30 * 86400


def _started(data: dict) -> float:
    """When a login was made. Logins from before 13 Nov 2026 carry no start time; theirs is worked out from the expiry."""
    return float(data.get("iat") or (int(data.get("exp") or 0) - SESSION_SECS))


def _login_id(data: dict) -> str:
    return str(data.get("sid") or f"t{int(_started(data))}")


_ended: dict = {}        # account number -> logins of it that were logged out (kept in settings "logout_<number>")
ENDED_KEPT = 40          # per account; a login lasts 30 days, nobody logs out this often


def ended_logins(uid: int) -> list:
    got = _ended.get(uid)
    if got is None:
        from .db import get_setting
        db = SessionLocal()
        try:
            got = json.loads(get_setting(db, f"logout_{uid}") or "[]")
        except Exception:
            got = []
        finally:
            db.close()
        _ended[uid] = got = [str(x) for x in got][-ENDED_KEPT:]
    return got


def end_login(db: Session, data: dict):
    """Log out: this login stops working on the server, not only in the browser that asked. Before
    19 Nov 2026 "Log out" only removed the login from that browser; a copy of it kept working for up to
    30 days."""
    from .db import set_setting
    uid = int(data["uid"])
    got = [x for x in ended_logins(uid) if x != _login_id(data)] + [_login_id(data)]
    _ended[uid] = got = got[-ENDED_KEPT:]
    set_setting(db, f"logout_{uid}", json.dumps(got))


def session_current(data: dict, user: User) -> bool:
    """False for a login that no longer counts for this account:
    - made before the account's password was last changed or reset. A new password must end every older
      login: otherwise someone who once got into an account (a shared phone, a borrowed password) keeps
      trading on it for a month, whatever the owner or the Master does;
    - made before the account itself was created. The database hands the number of a deleted account out
      again, and a login is only a signed account number: until 19 Nov 2026 the login of a deleted account
      was accepted as the next account created, a new Master login included;
    - logged out (see end_login)."""
    try:
        started = _started(data)
    except (TypeError, ValueError):
        return False
    created = getattr(user, "created_at", None)
    if created is not None:
        try:
            born = calendar.timegm(created.timetuple())
            exact = data.get("at")
            if isinstance(exact, (int, float)) and not isinstance(exact, bool):
                if exact < born + created.microsecond / 1e6:
                    return False
            elif started < born:        # logins from before 19 Nov 2026 know their start to the second only
                return False
        except Exception:
            pass
    try:
        if _login_id(data) in ended_logins(user.id):
            return False
    except Exception:
        pass
    changed = getattr(user, "pw_changed_at", None) or 0
    if not changed:
        return True
    try:
        return float(started) >= float(changed)
    except (TypeError, ValueError):
        return False


def make_pre_token(user: User) -> str:
    """Short-lived token issued after password check, before the 2FA code (5 minutes)."""
    return jwt.encode({"uid": user.id, "pre2fa": True, "exp": int(time.time()) + 300}, SECRET_KEY, algorithm="HS256")


def decode_token(tok: str) -> dict | None:
    try:
        return jwt.decode(tok, SECRET_KEY, algorithms=["HS256"])
    except Exception:
        return None


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    tok = request.cookies.get(COOKIE) or request.headers.get("authorization", "").replace("Bearer ", "")
    data = decode_token(tok) if tok else None
    if not data or data.get("pre2fa") or "uid" not in data:      # only a full login token is a session
        raise HTTPException(401, "Not logged in")
    u = db.get(User, data["uid"])
    if not u or not u.is_active and not u.is_admin:
        raise HTTPException(401, "Account inactive")
    if not session_current(data, u):
        raise HTTPException(401, "Password was changed — please log in again")
    # first login: nothing but the password change (and the few calls the change screen needs) until it's done
    if getattr(u, "must_change_password", False) and request.url.path not in PASSWORD_CHANGE_ALLOWED:
        raise HTTPException(403, "Password change required before you can use the platform")
    return u


PASSWORD_CHANGE_ALLOWED = {"/api/password", "/api/me", "/api/logout", "/api/feed/status"}


def optional_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    """Like current_user but returns None for visitors instead of raising."""
    try:
        return current_user(request, db)
    except HTTPException:
        return None


ADMIN_NO_2FA_ALLOWED = {"/api/admin/2fa/setup", "/api/admin/2fa/confirm"}


def current_admin(request: Request, user: User = Depends(current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(403, "Admin only")
    # the master panel controls every user's coins: a password alone is not enough
    if not user.totp_enabled and request.url.path not in ADMIN_NO_2FA_ALLOWED and os.getenv("PT_FEED", "mock") != "mock":   # local simulator is exempt
        raise HTTPException(403, "2FA_REQUIRED")
    return user
