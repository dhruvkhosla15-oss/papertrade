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
    return jwt.encode({"uid": user.id, "adm": user.is_admin, "exp": int(time.time()) + 30 * 86400},
                      SECRET_KEY, algorithm="HS256")


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
    if not data or data.get("pre2fa"):
        raise HTTPException(401, "Not logged in")
    u = db.get(User, data["uid"])
    if not u or not u.is_active and not u.is_admin:
        raise HTTPException(401, "Account inactive")
    return u


def optional_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    """Like current_user but returns None for visitors instead of raising."""
    try:
        return current_user(request, db)
    except HTTPException:
        return None


def current_admin(user: User = Depends(current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(403, "Admin only")
    return user
