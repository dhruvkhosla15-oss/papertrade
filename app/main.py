import asyncio
import json
import logging
import time
from datetime import date
from pathlib import Path
from typing import Optional, List
import io
import os
from datetime import datetime, timedelta

from fastapi import FastAPI, Depends, HTTPException, WebSocket, WebSocketDisconnect, Request, Response, Query
from fastapi.responses import FileResponse, RedirectResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel as _PydBase, ConfigDict


class BaseModel(_PydBase):
    """Every request body: NaN / Infinity are never valid numbers (they slip past <, > checks)."""
    model_config = ConfigDict(allow_inf_nan=False)

from sqlalchemy.orm import Session

from . import config
from .db import init_db, SessionLocal, User, Order, Position, Trade, Ledger, Watch, get_setting, set_setting
from .auth import (make_pre_token, optional_user, get_db, current_user, current_admin, hash_password, verify_password, make_token,
                   decode_token, COOKIE)
from .auth import session_current as _session_current
from .engine import Engine, EngineError
from .feed.mock import MockFeed

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("app")
logging.getLogger("httpx").setLevel(logging.WARNING)   # its INFO lines print full request URLs

app = FastAPI(title="LimeFX")
from . import probe as _probe
_PROBE = _probe.PREFIX


from fastapi.exceptions import RequestValidationError as _RVE
from fastapi.responses import JSONResponse as _JR


@app.exception_handler(_RVE)
async def _bad_input(request, exc):
    """Plain-text reason for a malformed request (the default handler echoes the input back and
    crashes on NaN)."""
    try:
        msg = "; ".join(f"{'.'.join(str(x) for x in (e.get('loc') or [])[1:])}: {e.get('msg')}" for e in exc.errors()[:5])
    except Exception:
        msg = ""
    return _JR({"detail": msg or "Invalid input"}, status_code=422)
from fastapi.middleware.gzip import GZipMiddleware
app.add_middleware(GZipMiddleware, minimum_size=800)   # the app page is ~130 KB of text: ~75% smaller on the wire

_CSP = ("default-src 'self' blob:; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self' ws: wss:; "
        "frame-ancestors 'none'; base-uri 'self'; object-src 'none'")


def _is_https(request: Request) -> bool:
    return request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "") == "https"


def _client_ip(request: Request) -> str:
    return (request.headers.get("x-forwarded-for", "").split(",")[0].strip()
            or (request.client.host if request.client else ""))


@app.middleware("http")
async def _security_headers(request: Request, call_next):
    resp = await call_next(request)
    h = resp.headers
    h.setdefault("X-Content-Type-Options", "nosniff")
    h.setdefault("X-Frame-Options", "DENY")
    h.setdefault("Referrer-Policy", "same-origin")
    h.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
    h.setdefault("Content-Security-Policy", _CSP)
    if request.url.path.startswith("/static/") and resp.status_code == 200:
        h.setdefault("Cache-Control", "public, max-age=86400")   # fonts, icons, chart library
    if _is_https(request):
        h.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return resp


@app.middleware("http")
async def _admin_audit(request: Request, call_next):
    """Record every change a master makes (path only — never bodies)."""
    resp = await call_next(request)
    try:
        path = request.url.path
        if request.method != "GET" and path.startswith("/api/admin/") and resp.status_code < 400:
            from .auth import decode_token as _dt
            from .db import AdminLog
            data = _dt(request.cookies.get(COOKIE) or request.headers.get("authorization", "").replace("Bearer ", "") or "")
            if data:
                db = SessionLocal()
                try:
                    u = db.get(User, data["uid"])
                    db.add(AdminLog(admin_id=data["uid"], admin_name=u.username if u else "", ip=_client_ip(request),
                                    action=f"{request.method} {path}"[:160]))
                    db.commit()
                finally:
                    db.close()
    except Exception:
        log.exception("audit log failed")
    return resp


# ---- login throttling --------------------------------------------------------------------------------
_fails: dict = {}          # key -> [count, first_ts, locked_until]
LOCK_AFTER, LOCK_SECS, WINDOW = 5, 300, 900


def _throttle_check(*keys):
    now = time.time()
    for k in keys:
        f = _fails.get(k)
        if f and f[2] > now:
            raise HTTPException(429, f"Too many wrong attempts — try again in {int((f[2] - now) // 60) + 1} min")


def _throttle_fail(*keys):
    now = time.time()
    for k in keys:
        f = _fails.get(k)
        if not f or now - f[1] > WINDOW:
            f = [0, now, 0.0]
        f[0] += 1
        limit = LOCK_AFTER if not k.startswith("ip:") else LOCK_AFTER * 4    # an office shares one address
        if f[0] >= limit:
            f[2] = now + LOCK_SECS; f[0] = 0; f[1] = now
        _fails[k] = f
    if len(_fails) > 5000:
        for k in [k for k, v in _fails.items() if now - v[1] > WINDOW and v[2] < now]:
            _fails.pop(k, None)


def _throttle_ok(*keys):
    for k in keys:
        _fails.pop(k, None)


KNOWN = "pt_known"         # marks a browser / phone that has logged in to this account before


def _known_device(request: Request, uname: str) -> bool:
    d = decode_token(request.cookies.get(KNOWN) or "")
    return bool(d and d.get("kd") == uname)


def _user_key(request: Request, uname: str) -> str:
    """Wrong-password counter for an account. Devices that have logged in to it before are counted
    apart, so a stranger guessing at someone's username (five tries lock it for five minutes) cannot
    keep the real owner — a trainee or the master — out of their own account."""
    return "user:" + uname + (":known" if _known_device(request, uname) else "")


def _set_login_cookie(request: Request, response: Response, tok: str, uname: str = ""):
    response.set_cookie(COOKIE, tok, httponly=True, samesite="lax", secure=_is_https(request), max_age=30 * 86400)
    if uname:
        import jwt as _jwt
        response.set_cookie(KNOWN, _jwt.encode({"kd": uname, "exp": int(time.time()) + 400 * 86400}, config.SECRET_KEY, algorithm="HS256"),
                            httponly=True, samesite="lax", secure=_is_https(request), max_age=400 * 86400)

CANONICAL_HOST = os.environ.get("PT_CANONICAL_HOST", "")  # e.g. www.limefx.in — bare/other hosts redirect here


@app.middleware("http")
async def _canonical_host(request: Request, call_next):
    host = request.headers.get("host", "").split(":")[0]
    if CANONICAL_HOST and host and host != CANONICAL_HOST and not host.startswith(("localhost", "127.")) and not host.endswith(".railway.app"):
        return RedirectResponse(f"https://{CANONICAL_HOST}{request.url.path}" + (f"?{request.url.query}" if request.url.query else ""), status_code=308)
    return await call_next(request)

STATIC = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC), name="static")

if config.FEED == "kite":
    from .feed.kite import KiteFeed
    feed = KiteFeed(config.KITE_API_KEY, config.KITE_API_SECRET)
else:
    feed = MockFeed()
crypto = None
if config.ENABLE_CRYPTO:
    from .feed.delta import DeltaCrypto
    crypto = DeltaCrypto(feed)
forex = None
if config.ENABLE_FOREX:
    from .feed.ctrader import CTraderForex
    forex = CTraderForex(feed)
engine = Engine(feed)

# ---- websocket client registry -----------------------------------------------
class Client:
    def __init__(self, ws: WebSocket, user_id: int):
        self.ws = ws
        self.user_id = user_id
        self.tokens: set[int] = set()
        self.dirty: set[int] = set()
        self.queue: asyncio.Queue = asyncio.Queue()

clients: list[Client] = []


def _on_tick(tick):
    tok = tick["token"]
    for c in clients:
        if tok in c.tokens:
            c.dirty.add(tok)

feed.on_tick(_on_tick)


def _emit(user_id: int, event: dict):
    for c in clients:
        if c.user_id == user_id:
            c.queue.put_nowait(event)

engine.set_event_callback(_emit)


async def broadcaster():
    """Every 300ms push changed prices to each client (batching ticks)."""
    while True:
        for c in list(clients):
            if c.dirty:
                toks = list(c.dirty); c.dirty.clear()
                payload = {"type": "ticks", "ticks": [feed.prices[t] for t in toks if t in feed.prices]}
                try:
                    await c.ws.send_text(json.dumps(payload))
                except Exception:
                    pass
        await asyncio.sleep(0.3)


@app.on_event("startup")
async def startup():
    init_db()
    db = SessionLocal()
    try:
        if not db.query(User).filter_by(is_admin=True).first():
            db.add(User(username=config.ADMIN_USER, display_name="Master", is_admin=True,
                        password_hash=hash_password(config.ADMIN_PASSWORD)))
            db.commit()
            log.info("created admin user '%s'", config.ADMIN_USER)
        if config.FEED == "kite":
            tok = get_setting(db, "kite_access_token"); d = get_setting(db, "kite_token_date")
            if tok and d == date.today().isoformat():
                feed.set_access_token(tok, d)
    finally:
        db.close()
    await feed.start(asyncio.get_event_loop())
    if crypto:
        await crypto.start(asyncio.get_event_loop())
    if forex:
        await forex.start(asyncio.get_event_loop())
    engine.load_pending()
    asyncio.create_task(broadcaster())
    asyncio.create_task(engine.expiry_loop())
    asyncio.create_task(engine.liquidation_loop())
    asyncio.create_task(backup_loop())
    asyncio.create_task(_probe.loop(app, engine, feed))
    asyncio.create_task(daystart_loop())
    asyncio.create_task(feed_watch_loop())


# ---- pages -----------------------------------------------------------------------
_NOCACHE = {"Cache-Control": "no-store, must-revalidate", "Pragma": "no-cache"}


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html", headers=_NOCACHE)


@app.get("/manifest.webmanifest")
async def manifest():
    return FileResponse(STATIC / "pwa" / "manifest.webmanifest", media_type="application/manifest+json", headers=_NOCACHE)


@app.get("/sw.js")
async def service_worker():
    return FileResponse(STATIC / "pwa" / "sw.js", media_type="application/javascript", headers={**_NOCACHE, "Service-Worker-Allowed": "/"})


@app.get("/admin")
def admin_page():
    return FileResponse(STATIC / "admin.html", headers=_NOCACHE)


# ---- auth -------------------------------------------------------------------------
class LoginIn(BaseModel):
    username: str
    password: str


@app.post("/api/login")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    uname = body.username.strip().lower()
    # a device that has logged in to this account before answers only for its own wrong tries
    keys = (_user_key(request, uname),) if _known_device(request, uname) else (_user_key(request, uname), "ip:" + _client_ip(request))
    _throttle_check(*keys)
    u = db.query(User).filter_by(username=uname).first()
    if not u or not verify_password(body.password, u.password_hash):
        _throttle_fail(*keys)
        raise HTTPException(401, "Wrong username or password")
    _throttle_ok(keys[0])
    if not u.is_active and not u.is_admin:
        raise HTTPException(403, "Account frozen — contact your trainer")
    if u.totp_enabled:
        return {"ok": False, "needs_2fa": True, "pre_token": make_pre_token(u), "is_admin": u.is_admin}
    tok = make_token(u)
    _set_login_cookie(request, response, tok, u.username)
    return {"ok": True, "token": tok, "user": _user_dict(u), "is_admin": u.is_admin}


class TwoFaIn(BaseModel):
    pre_token: str
    code: str


def _totp_ok(secret: str, code: str) -> bool:
    import pyotp
    return bool(secret) and pyotp.TOTP(secret).verify((code or "").strip().replace(" ", ""), valid_window=1)


@app.post("/api/login/2fa")
def login_2fa(body: TwoFaIn, request: Request, response: Response, db: Session = Depends(get_db)):
    from .auth import decode_token
    data = decode_token(body.pre_token)
    if not data or not data.get("pre2fa"):
        raise HTTPException(401, "Login expired — enter your password again")
    u = db.get(User, data["uid"])
    key = f"2fa:{data['uid']}"
    _throttle_check(key)
    if not u or not _totp_ok(u.totp_secret, body.code):
        _throttle_fail(key)
        raise HTTPException(401, "Wrong authenticator code")
    _throttle_ok(key)
    if not u.is_active and not u.is_admin:
        raise HTTPException(403, "Account frozen — contact your trainer")
    tok = make_token(u)
    _set_login_cookie(request, response, tok, u.username)
    return {"ok": True, "token": tok, "user": _user_dict(u), "is_admin": u.is_admin}


# ---- master 2FA (TOTP: Google Authenticator / Authy / 1Password) ----------------------------------
@app.post("/api/2fa/setup")
@app.post("/api/admin/2fa/setup")
def twofa_setup(admin: User = Depends(current_user), db: Session = Depends(get_db)):
    """Create a new secret (not active until confirmed) and return the QR code to scan."""
    import pyotp, segno, io as _io
    if admin.totp_enabled:
        raise HTTPException(400, "2FA is already on. Turn it off first to set up a new device.")
    secret = pyotp.random_base32()
    admin.totp_secret = secret; db.commit()
    uri = pyotp.TOTP(secret).provisioning_uri(name=admin.username, issuer_name="limeFX Master" if admin.is_admin else "limeFX")
    buf = _io.BytesIO(); segno.make(uri, error="m").save(buf, kind="png", scale=10, border=4, dark="#000000", light="#ffffff")
    import base64
    return {"secret": secret, "uri": uri, "qr_png": "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()}


class CodeIn(BaseModel):
    code: str


@app.post("/api/2fa/confirm")
@app.post("/api/admin/2fa/confirm")
def twofa_confirm(body: CodeIn, admin: User = Depends(current_user), db: Session = Depends(get_db)):
    if not admin.totp_secret or not _totp_ok(admin.totp_secret, body.code):
        raise HTTPException(400, "That code didn't match — check the time on your phone and try again")
    admin.totp_enabled = True; db.commit()
    return {"ok": True}


@app.post("/api/2fa/disable")
@app.post("/api/admin/2fa/disable")
def twofa_disable(body: CodeIn, admin: User = Depends(current_user), db: Session = Depends(get_db)):
    if not _totp_ok(admin.totp_secret, body.code):
        raise HTTPException(400, "Wrong authenticator code")
    admin.totp_enabled = False; admin.totp_secret = ""; db.commit()
    return {"ok": True}


# ---- master accounts -----------------------------------------------------------------------------------
class AdminIn(BaseModel):
    username: str
    display_name: str = ""
    password: str


@app.get("/api/admin/admins")
def admins_list(admin: User = Depends(current_admin), db: Session = Depends(get_db)):
    return [{"id": u.id, "username": u.username, "display_name": u.display_name, "twofa": bool(u.totp_enabled),
             "is_active": u.is_active, "me": u.id == admin.id, "created_at": u.created_at.isoformat() + "Z"}
            for u in db.query(User).filter_by(is_admin=True).order_by(User.id).all()]


@app.post("/api/admin/admins")
def admins_add(body: AdminIn, admin: User = Depends(current_admin), db: Session = Depends(get_db)):
    uname = body.username.strip().lower()
    if not uname or len(body.password) < 6:
        raise HTTPException(400, "Username and a password of at least 6 characters are required")
    if db.query(User).filter_by(username=uname).first():
        raise HTTPException(400, "Username already exists")
    u = User(username=uname, display_name=body.display_name.strip() or uname, password_hash=hash_password(body.password),
             is_admin=True, is_active=True, balance=0.0)
    db.add(u); db.commit()
    return {"ok": True, "id": u.id}


@app.delete("/api/admin/admins/{uid}")
def admins_remove(uid: int, admin: User = Depends(current_admin), db: Session = Depends(get_db)):
    u = db.get(User, uid)
    if not u or not u.is_admin:
        raise HTTPException(404, "No such master account")
    if u.id == admin.id:
        raise HTTPException(400, "You can't remove your own master access — ask another master to do it")
    if db.query(User).filter_by(is_admin=True).count() <= 1:
        raise HTTPException(400, "There must be at least one master")
    db.delete(u); db.commit()
    return {"ok": True}


@app.post("/api/admin/admins/{uid}/reset-2fa")
def admins_reset_2fa(uid: int, admin: User = Depends(current_admin), db: Session = Depends(get_db)):
    """Another master can clear a colleague's 2FA if they lose their phone."""
    u = db.get(User, uid)
    if not u or not u.is_admin:
        raise HTTPException(404, "No such master account")
    u.totp_enabled = False; u.totp_secret = ""; db.commit()
    return {"ok": True}


class AdminPwIn(BaseModel):
    password: str


@app.post("/api/admin/admins/{uid}/password")
def admins_password(uid: int, body: AdminPwIn, request: Request, response: Response, admin: User = Depends(current_admin), db: Session = Depends(get_db)):
    u = db.get(User, uid)
    if not u or not u.is_admin:
        raise HTTPException(404, "No such master account")
    if len(body.password) < 6:
        raise HTTPException(400, "Password must be at least 6 characters")
    u.password_hash = hash_password(body.password)
    u.pw_changed_at = float(int(time.time()))         # logins made with the old password stop working
    db.commit()
    if u.id == admin.id:                              # a master changing their own password stays logged in on this device
        _set_login_cookie(request, response, make_token(u), u.username)
    return {"ok": True}


@app.post("/api/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE)
    return {"ok": True}


@app.get("/api/me")
def me(user: User = Depends(current_user), db: Session = Depends(get_db)):
    on, spread, stale = engine.liquidity_settings(db)
    return {"user": _user_dict(user), "funds": engine.funds(db, user), "feed": _feed_status(),
            "market_open": {ex: engine.market_open(ex) for ex in config.MARKET_HOURS}, "market_hours": config.MARKET_HOURS,
            "market_status": _market_status(), "usdinr": getattr(feed, "usdinr", lambda: None)(),
            "liquidity": {"on": on, "max_spread_pct": spread}, "alerts": _user_alerts(db, user)}


def _user_alerts(db, user) -> list:
    try:
        return json.loads(get_setting(db, f"user_alerts_{user.id}", "[]") or "[]")
    except Exception:
        return []


class AlertIn(BaseModel):
    title: str = "Notice"
    text: str


@app.post("/api/admin/users/{uid}/alert")
def admin_user_alert(uid: int, body: AlertIn, admin: User = Depends(current_admin), db: Session = Depends(get_db)):
    """Master leaves a pop-up message for one user; it shows when they next open the app, until they press OK."""
    u = db.get(User, uid)
    if not u or not body.text.strip():
        raise HTTPException(400, "Unknown user or empty message")
    engine._user_alert(db, u, (body.title.strip() or "Notice")[:60], body.text.strip()[:1200])
    return {"ok": True, "pending": len(_user_alerts(db, u))}


@app.post("/api/alerts/ack")
def ack_alerts(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """The user pressed OK on the pop-up: their pending alerts (e.g. 'Position liquidated') are cleared."""
    if _user_alerts(db, user):
        set_setting(db, f"user_alerts_{user.id}", "[]"); db.commit()
    return {"ok": True}


class PasswordIn(BaseModel):
    old_password: str
    new_password: str


@app.post("/api/password")
def change_password(body: PasswordIn, request: Request, response: Response, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not verify_password(body.old_password, user.password_hash):
        raise HTTPException(400, "Current password is wrong")
    if len(body.new_password) < 6:
        raise HTTPException(400, "Password must be at least 6 characters")
    if body.new_password == body.old_password:
        raise HTTPException(400, "Choose a new password that is different from the current one")
    user.password_hash = hash_password(body.new_password)
    user.must_change_password = False
    user.pw_changed_at = float(int(time.time()))      # every login made before this moment stops working...
    db.commit()
    tok = make_token(user)                            # ...except this device, which gets a fresh one
    _set_login_cookie(request, response, tok, user.username)
    return {"ok": True, "token": tok}


def _user_dict(u: User):
    return {"id": u.id, "username": u.username, "display_name": u.display_name, "is_admin": u.is_admin,
            "is_active": u.is_active, "balance": round(u.balance, 2), "twofa": bool(u.totp_enabled),
            "must_change_password": bool(u.must_change_password)}


# ---- market data ------------------------------------------------------------------------
# Commodities the exchange lists but nobody trades (no buyers or sellers on any contract, stale price).
# Left out of the lists users browse. Override with PT_HIDE_UNDERLYINGS=NAME,NAME (empty = hide nothing).
HIDE_UNDERLYINGS = {s.strip().upper() for s in os.environ.get("PT_HIDE_UNDERLYINGS", "KAPAS,COTTON").split(",") if s.strip()}


@app.get("/api/underlyings")
def underlyings(user: Optional[User] = Depends(optional_user)):   # visitors may browse the scrip lists
    out = []
    from .feed.base import kind_of
    has_opt = {(i.exchange, i.name) for i in feed.instruments.values() if i.instrument_type in ("CE", "PE")}
    for exch, names in feed.underlyings().items():
        for n in names:
            if n in HIDE_UNDERLYINGS:
                continue
            it = feed.index_token_for(n)
            out.append({"exchange": exch, "name": n, "spot_token": it, "kind": kind_of(exch, n), "has_options": (exch, n) in has_opt})
    order = {"NFO": 0, "BFO": 1, "MCX": 2, "CDS": 3, "CRYPTO": 4, "FOREX": 5}
    korder = {"index": 0, "mcx": 1, "currency": 2, "crypto": 3, "forex": 4, "global": 5, "stock": 6}
    out.sort(key=lambda x: (korder[x["kind"]], order.get(x["exchange"], 9), x["name"]))
    return out


@app.get("/api/expiries")
def expiries(exchange: str, name: str, user: User = Depends(current_user)):
    from .engine import ist_now
    n = ist_now(); today = n.date().isoformat()
    from .market_calendar import expiry_time_str
    close = expiry_time_str(exchange)
    out = [e for e in feed.expiries(exchange, name) if e > today or (e == today and n.strftime("%H:%M") < close)]
    return out


@app.get("/api/chain")
def chain(exchange: str, name: str, expiry: str, user: User = Depends(current_user)):
    items = feed.chain(exchange, name, expiry)
    return {"spot_token": feed.index_token_for(name), "instruments": [i.to_dict() for i in items]}


@app.get("/api/futures")
def futures(exchange: str, name: str, user: Optional[User] = Depends(optional_user)):   # visitors may see futures prices
    today = date.today().isoformat()
    items = sorted((i for i in feed.instruments.values()
                    if i.exchange == exchange and i.name == name and i.instrument_type == "FUT" and (i.expiry >= today or not i.expiry)
                    and not feed.dead_weekly(i)),
                   key=lambda x: x.expiry)
    return [i.to_dict() for i in items]


@app.get("/api/candles")
async def candles(token: int, interval: str = "5m", user: User = Depends(current_user)):
    ins = feed.instruments.get(token)
    if not ins or ins.segment == "INDICES":
        raise HTTPException(404, "charts are available for options and futures only")
    data = await asyncio.get_event_loop().run_in_executor(None, feed.candles, token, interval)
    return {"interval": interval, "candles": data}


# Showcase: what the public home page, the scrolling ticker and a new user's watchlist show.
# Indices, the most-traded F&O stocks, and the main MCX commodities. Override with PT_SHOWCASE=NIFTY,RELIANCE,GOLD,...
_SHOWCASE_DEFAULT = ["NIFTY", "BANKNIFTY", "SENSEX",
                     "RELIANCE", "HDFCBANK", "ICICIBANK", "SBIN", "INFY", "TCS", "TATAMOTORS", "BHARTIARTL", "ITC", "LT",
                     "GOLD", "SILVER", "CRUDEOIL", "NATURALGAS", "COPPER", "USDINR", "BTC", "ETH", "SOL", "EURUSD", "XAUUSD",
                     "US500", "USTEC", "US30", "XTIUSD"]
SHOWCASE = [s.strip().upper() for s in os.environ.get("PT_SHOWCASE", ",".join(_SHOWCASE_DEFAULT)).split(",") if s.strip()]
DEFAULT_WATCH = [(None, n) for n in SHOWCASE]


def _default_watch_instruments():
    out = []
    for ex, name in DEFAULT_WATCH:
        tok = feed.index_token_for(name)
        ins = feed.instruments.get(tok) if tok else None
        if ins:
            out.append(ins)
    return out


def _market_status():
    from .market_calendar import status, ist_now
    if not config.ENFORCE_MARKET_HOURS:
        out = {ex: {"open": True, "holiday": None, "opens_at": None, "closes_at": None, "label": "open"} for ex in ("NFO", "BFO", "MCX", "CDS", "CRYPTO", "FOREX")}
    else:
        out = {ex: status(ex) for ex in ("NFO", "BFO", "MCX", "CDS", "CRYPTO", "FOREX")}
    try:   # "US" chip: follows the S&P 500 contract's own timetable (the Global section)
        h = forex.hours("US500") if forex else None
        if h:
            out["US"] = {"open": h["open"], "holiday": None, "opens_at": h["opens_at"], "closes_at": h["closes_at"],
                         "label": "open" if h["open"] else "closed", "today": ist_now().date().isoformat()}
    except Exception:
        log.exception("US market status failed")
    return out


def _public_tokens():
    """Tokens a not-logged-in visitor may stream: every spot and every futures contract (no option
    chains — those, and trading, need a login). Cached per instrument load."""
    key = len(feed.instruments)
    if _public_tokens._cache[0] != key:
        toks = {i.token for i in _default_watch_instruments()}
        today = date.today().isoformat()
        for i in feed.instruments.values():
            if i.segment == "INDICES" or (i.instrument_type == "FUT" and i.expiry >= today):
                toks.add(i.token)
        _public_tokens._cache = (key, toks)
    return _public_tokens._cache[1]
_public_tokens._cache = (-1, set())

GUEST_SUB_CEILING = 2400   # leave headroom under Zerodha's 3000-instrument socket limit for users
USER_SUB_LIMIT = 1200      # contracts one account may stream at once across all its tabs (a watchlist plus the biggest option chain is a few hundred)
USER_SUB_CEILING = 2900    # users' screens never push the socket past its limit; orders and open positions keep the last 100


def _ticker():
    from .feed.base import kind_of
    out = []
    for i in _default_watch_instruments():
        ex = i.exchange if i.exchange in ("MCX", "CDS", "CRYPTO", "FOREX") else ("BFO" if i.exchange == "BSE" else "NFO")
        out.append({"exchange": ex, "name": i.name, "spot_token": i.token, "kind": kind_of(ex, i.name)})
    return out


@app.get("/api/public/home")
def public_home():
    """What a visitor sees before logging in."""
    tick = _ticker()
    return {"watchlist": [i.to_dict() for i in _default_watch_instruments()], "ticker": tick, "feed": _feed_status(),
            "market_open": {ex: engine.market_open(ex) for ex in config.MARKET_HOURS}, "market_hours": config.MARKET_HOURS,
            "market_status": _market_status(), "usdinr": getattr(feed, "usdinr", lambda: None)()}


@app.get("/api/watchlist")
def watchlist(user: User = Depends(current_user), db: Session = Depends(get_db)):
    has_global = any(getattr(i, "segment", "") == "GLOBAL-SPOT" for i in feed.instruments.values())
    if not db.query(Watch).filter_by(user_id=user.id).first() and feed.instruments:
        # empty watchlist (new user, or everything removed) -> start from the showcase list
        for n, ins in enumerate(_default_watch_instruments()):
            db.add(Watch(user_id=user.id, token=ins.token, symbol=ins.symbol, exchange=ins.exchange, position=n))
        set_setting(db, f"watch_seeded_{user.id}", "1"); set_setting(db, f"watch_showcase_{user.id}", "1"); set_setting(db, f"watch_showcase2_{user.id}", "1"); set_setting(db, f"watch_showcase3_{user.id}", "1")
        if has_global:
            set_setting(db, f"watch_showcase4_{user.id}", "1")
        db.commit()
    elif (not get_setting(db, f"watch_showcase_{user.id}") or not get_setting(db, f"watch_showcase2_{user.id}")
          or (not get_setting(db, f"watch_showcase3_{user.id}") and any(getattr(i, "exchange", "") == "FOREX" for i in feed.instruments.values()))
          or (has_global and not get_setting(db, f"watch_showcase4_{user.id}"))) and feed.instruments:
        # one-time: add the showcase scrips (top stocks, then currency + crypto) to watchlists created before they existed
        have = {w.token for w in db.query(Watch).filter_by(user_id=user.id).all()}
        last = db.query(Watch).filter_by(user_id=user.id).order_by(Watch.position.desc()).first()
        pos = (last.position + 1) if last else 0
        for ins in _default_watch_instruments():
            if ins.token not in have:
                db.add(Watch(user_id=user.id, token=ins.token, symbol=ins.symbol, exchange=ins.exchange, position=pos)); pos += 1
        set_setting(db, f"watch_showcase_{user.id}", "1"); set_setting(db, f"watch_showcase2_{user.id}", "1"); set_setting(db, f"watch_showcase3_{user.id}", "1")
        if has_global:
            set_setting(db, f"watch_showcase4_{user.id}", "1")
        db.commit()
    rows = db.query(Watch).filter_by(user_id=user.id).order_by(Watch.position, Watch.id).all()
    out = []
    for w in rows:
        ins = feed.instruments.get(w.token)
        if ins:
            out.append({**ins.to_dict(), "watch_id": w.id})
    return out


class WatchIn(BaseModel):
    token: int


@app.post("/api/watchlist")
def watchlist_add(body: WatchIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ins = feed.instruments.get(body.token)
    if not ins:
        raise HTTPException(404, "unknown contract")
    if db.query(Watch).filter_by(user_id=user.id, token=body.token).first():
        return {"ok": True}
    if db.query(Watch).filter_by(user_id=user.id).count() >= 50:
        raise HTTPException(400, "Watchlist is full (50)")
    last = db.query(Watch).filter_by(user_id=user.id).order_by(Watch.position.desc()).first()
    db.add(Watch(user_id=user.id, token=body.token, symbol=ins.symbol, exchange=ins.exchange, position=(last.position + 1) if last else 0)); db.commit()
    return {"ok": True}


class WatchOrder(BaseModel):
    tokens: List[int]


@app.put("/api/watchlist/order")
def watchlist_reorder(body: WatchOrder, user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = {w.token: w for w in db.query(Watch).filter_by(user_id=user.id).all()}
    n = 0
    for tok in body.tokens:
        if tok in rows:
            rows[tok].position = n; n += 1
    for w in sorted((w for t, w in rows.items() if t not in body.tokens), key=lambda w: w.id):
        w.position = n; n += 1
    db.commit()
    return {"ok": True}


@app.delete("/api/watchlist/{token}")
def watchlist_remove(token: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.query(Watch).filter_by(user_id=user.id, token=token).delete(); db.commit()
    return {"ok": True}


@app.get("/api/search")
def search(q: str, user: User = Depends(current_user)):
    if len(q) < 2:
        return []
    return [i.to_dict() for i in feed.search(q)]


@app.get("/api/instrument/{token}")
async def instrument(token: int, user: User = Depends(current_user)):
    i = feed.instruments.get(token)
    if not i:
        raise HTTPException(404, "unknown instrument")
    await _ensure_price(token)
    return {**i.to_dict(), "price": feed.prices.get(token)}


# ---- trading --------------------------------------------------------------------------------
class OrderIn(BaseModel):
    token: int
    side: str
    lots: int
    order_type: str = "MARKET"
    leverage: Optional[float] = None
    limit_price: Optional[float] = None
    trigger_price: Optional[float] = None
    validity: Optional[str] = "DAY"
    product: Optional[str] = None


async def _ensure_price(token: int, timeout=3.0):
    if feed.ltp(token) is None:
        feed.pin([token])
        t0 = time.time()
        while feed.ltp(token) is None and time.time() - t0 < timeout:
            await asyncio.sleep(0.1)


def _feed_up(exchange: str) -> bool:
    """True when the price feed that serves this exchange is connected."""
    if exchange == "CRYPTO":
        return bool(crypto and crypto.connected)
    if exchange == "FOREX":
        return bool(forex and forex.connected)
    return bool(feed.connected)


@app.post("/api/orders")
async def place_order(body: OrderIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ins = feed.instruments.get(body.token)
    if ins and not _feed_up(ins.exchange):
        raise HTTPException(400, "Price feed for this market is down. Orders will be rejected until the feed is back up.")
    await _ensure_price(body.token)
    # A contract nobody is streaming has a frozen price. Stream it for this order and wait for a new
    # price (some feeds publish only every few seconds); a fill or a resting order then keeps it streaming
    # on its own. The stream is kept half a minute so that a retry finds the price already live.
    held = ins is not None and not feed.live(body.token)
    if held:
        feed.subscribe([body.token])
        t0 = time.time()
        while not feed.live(body.token) and time.time() - t0 < 6.0:
            await asyncio.sleep(0.1)
    try:
        async with engine._lock:
            db.expire_all()   # objects loaded before we got the lock may be stale (concurrent orders)
            try:
                o = engine.place_order(db, user, body.token, body.side, body.lots, body.order_type,
                                       body.limit_price, body.trigger_price, body.leverage,
                                       validity=body.validity or "DAY", product=body.product)
            except EngineError as e:
                raise HTTPException(400, str(e))
    finally:
        if held:
            asyncio.get_event_loop().call_later(30, feed.unsubscribe, [body.token])
    return {"order": engine.order_dict(o), "funds": engine.funds(db, user)}


@app.get("/api/margin")
def margin(token: int, side: str, lots: int, price: Optional[float] = None, leverage: Optional[float] = None,
           user: User = Depends(current_user), db: Session = Depends(get_db)):
    ins = feed.instruments.get(token)
    if not ins:
        raise HTTPException(404, "unknown instrument")
    import math
    if price is not None and not (math.isfinite(price) and price > 0):
        price = None
    if leverage is not None and not math.isfinite(leverage):
        leverage = None
    lots = max(0, min(int(lots), 100000))
    p = price or feed.ltp(token) or 0
    qty = lots * ins.lot_size
    if leverage is not None and (not ins.leverage_options or not (1 <= leverage <= max(ins.leverage_options))):
        leverage = None
    return {"margin": engine._opening_margin(db, user, ins, side.upper(), qty, p, leverage), "qty": qty,
            "full_margin": engine.required_margin(db, ins, side.upper(), qty, p, leverage),
            "commission": engine.commission(db, ins, p, qty) if qty else 0.0, "commission_pct": engine.commission_terms(db, ins)[0],
            "commission_flat": engine.commission_terms(db, ins)[1],
            "value_factor": engine.vf(ins), "usdinr": getattr(feed, "usdinr", lambda: None)()}


@app.delete("/api/orders/{order_id}")
async def cancel_order(order_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    async with engine._lock:
        db.expire_all()   # objects loaded before we got the lock may be stale (concurrent orders)
        try:
            engine.cancel_order(db, user, order_id)
        except EngineError as e:
            raise HTTPException(400, str(e))
    return {"ok": True}


def _dated(q, col, from_, to, default_limit):
    """Optional IST date range (?from=YYYY-MM-DD&to=YYYY-MM-DD) for the user's own lists."""
    if from_ or to:
        try:
            start, end, _f, _t = _range(from_, to)
        except ValueError:
            raise HTTPException(400, "Dates must look like 2026-11-30")
        return q.filter(col >= start, col < end).limit(2000)
    return q.limit(default_limit)


@app.get("/api/orders")
def list_orders(from_: Optional[str] = Query(None, alias="from"), to: Optional[str] = None,
                user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = _dated(db.query(Order).filter_by(user_id=user.id).order_by(Order.id.desc()), Order.created_at, from_, to, 200).all()
    return [engine.order_dict(o) for o in rows]


@app.get("/api/positions")
def list_positions(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.query(Position).filter_by(user_id=user.id, is_closed=False).all()
    return [engine.position_dict(p) for p in rows]


@app.post("/api/positions/{pos_id}/close")
async def close_position(pos_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = db.query(Position).filter_by(id=pos_id, user_id=user.id, is_closed=False).first()
    if not p or not p.qty:
        raise HTTPException(404, "position not found")
    async with engine._lock:
        db.expire_all()   # objects loaded before we got the lock may be stale (concurrent orders)
        # exit first; resting stops/targets are cancelled only once the exit has gone through — if the
        # market is closed the position stays, and so must its stop-loss
        # A position bigger than the exchange freeze quantity is exited in freeze-sized slices, like a
        # broker does, instead of telling the user to split it by hand.
        from .config import FREEZE_QTY
        ins_ = feed.instruments.get(p.token)
        fz = FREEZE_QTY.get(ins_.name) if ins_ and ins_.exchange in ("NFO", "BFO") else None
        chunk = max(1, fz // p.lot_size) if fz else 10 ** 9
        side_ = "SELL" if p.qty > 0 else "BUY"
        left = abs(p.qty) // p.lot_size
        o = None
        while left > 0:
            n = min(left, chunk)
            try:
                o2 = engine.place_order(db, user, p.token, side_, n)
            except EngineError as e:
                if o is None:
                    raise HTTPException(400, str(e))
                break
            o = o2
            if o.status != "FILLED" or (o.qty // p.lot_size) < n:
                break          # book ran out of depth: stop here, the rest stays open
            left -= n
        cancelled = engine.cancel_pending_for(db, user, p.token) if left == 0 else 0
    return {"order": engine.order_dict(o), "cancelled_orders": cancelled}


@app.get("/api/trades")
def list_trades(from_: Optional[str] = Query(None, alias="from"), to: Optional[str] = None,
                user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = _dated(db.query(Trade).filter_by(user_id=user.id).order_by(Trade.id.desc()), Trade.created_at, from_, to, 300).all()
    return [{"id": t.id, "symbol": t.symbol, "exchange": t.exchange, "side": t.side, "qty": t.qty,
             "price": t.price, "realised_pnl": t.realised_pnl, "commission": t.commission or 0.0,
             "created_at": t.created_at.isoformat() + "Z"} for t in rows]


@app.get("/api/ledger")
def list_ledger(from_: Optional[str] = Query(None, alias="from"), to: Optional[str] = None,
                user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = _dated(db.query(Ledger).filter_by(user_id=user.id).order_by(Ledger.id.desc()), Ledger.created_at, from_, to, 300).all()
    return [{"id": l.id, "amount": l.amount, "balance_after": l.balance_after, "kind": l.kind, "note": l.note,
             "created_at": l.created_at.isoformat() + "Z"} for l in rows]


# ---- websocket ------------------------------------------------------------------------------
@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    tok = ws.cookies.get(COOKIE) or ws.query_params.get("token")
    data = decode_token(tok) if tok else None
    if data:
        # password typed but 2FA code not yet given, or the account is gone / frozen: a visitor, nothing more
        _db = SessionLocal()
        try:
            _u = None if data.get("pre2fa") else _db.get(User, data.get("uid"))
        finally:
            _db.close()
        if not _u or not (_u.is_active or _u.is_admin) or not _session_current(data, _u):
            data = None
    guest = not data
    await ws.accept()
    c = Client(ws, data["uid"] if data else 0)
    allowed = _public_tokens() if guest else None
    clients.append(c)

    async def pump_events():
        while True:
            ev = await c.queue.get()
            await ws.send_text(json.dumps(ev))

    pump = asyncio.create_task(pump_events())
    try:
        while True:
            msg = json.loads(await ws.receive_text())
            if msg.get("type") == "subscribe":
                toks = [int(t) for t in msg.get("tokens", [])]
                if allowed is not None:
                    allowed = _public_tokens()
                    toks = [t for t in toks if t in allowed]
                new = set(toks) - c.tokens
                if guest and len(feed._refcount) + len(new) > GUEST_SUB_CEILING:
                    # visitors never squeeze users out of the Zerodha socket
                    new = {t for t in new if t in feed._refcount}
                if not guest:
                    # one account cannot fill the socket either (it would leave no room for everyone else's contracts)
                    mine = set().union(*[x.tokens for x in clients if x.user_id == c.user_id])
                    room = USER_SUB_LIMIT - len(mine)
                    keep = set()
                    for t in toks:
                        if t in new and t not in keep and (t in mine or room > 0):
                            keep.add(t); room -= t not in mine
                    new = keep
                    if len(feed._refcount) + sum(1 for t in new if t not in feed._refcount) > USER_SUB_CEILING:
                        new = {t for t in new if t in feed._refcount}
                feed.subscribe(list(new))
                c.tokens |= new
                # immediate snapshot of what we already have
                snap = [feed.prices[t] for t in toks if t in feed.prices]
                if snap:
                    await ws.send_text(json.dumps({"type": "ticks", "ticks": snap}))
            elif msg.get("type") == "unsubscribe":
                toks = [int(t) for t in msg.get("tokens", [])]
                gone = set(toks) & c.tokens
                feed.unsubscribe(list(gone))
                c.tokens -= gone
            elif msg.get("type") == "ping":
                await ws.send_text(json.dumps({"type": "pong", "feed": _feed_status()}))
    except WebSocketDisconnect:
        pass
    except Exception as e:
        log.debug("ws error: %s", e)
    finally:
        pump.cancel()
        if c in clients:
            clients.remove(c)
        feed.unsubscribe(list(c.tokens))


# ---- admin ------------------------------------------------------------------------------------
class UserIn(BaseModel):
    username: str
    password: str
    display_name: str = ""
    initial_coins: float = 0


@app.get("/api/admin/users")
def admin_users(admin: User = Depends(current_admin), db: Session = Depends(get_db)):
    out = []
    for u in db.query(User).filter_by(is_admin=False).filter(~User.username.startswith(_PROBE)).order_by(User.id).all():
        f = engine.funds(db, u)
        out.append({**_user_dict(u), **f,
                    "open_positions": db.query(Position).filter_by(user_id=u.id, is_closed=False).count(),
                    "trades": db.query(Trade).filter_by(user_id=u.id).count(),
                    "total_credited": sum(l.amount for l in db.query(Ledger).filter_by(user_id=u.id)
                                          .filter(Ledger.kind.in_(["ADMIN_CREDIT", "ADMIN_DEBIT"]))),
                    "commission_total": round(-sum(l.amount for l in db.query(Ledger).filter_by(user_id=u.id, kind="COMMISSION")), 2)})
    return out


def _book_totals(db) -> tuple:
    """(coins allocated, users' net balance) across all real users, right now."""
    alloc = equity = 0.0
    for u in db.query(User).filter_by(is_admin=False).filter(~User.username.startswith(_PROBE)).all():
        alloc += sum(l.amount for l in db.query(Ledger).filter_by(user_id=u.id).filter(Ledger.kind.in_(["ADMIN_CREDIT", "ADMIN_DEBIT"])))
        equity += engine.funds(db, u)["equity"]
    return round(alloc, 2), round(equity, 2)


async def feed_watch_loop():
    """Telegram ping when a price feed stays down, a reminder every hour while it is still down, and a
    ping when it is back. A feed the master switched off on purpose is not reported. Short blips
    (under PT_FEED_ALERT_SECS, default 90 s) and the first minutes after a restart are ignored."""
    hold = int(os.getenv("PT_FEED_ALERT_SECS", "90"))
    await asyncio.sleep(int(os.getenv("PT_FEED_ALERT_GRACE", "180")))
    down_since: dict = {}; alerted: dict = {}
    names = {"main": "NSE / BSE / MCX / Currency", "crypto": "Crypto", "forex": "Forex / Global"}
    ist = lambda ts: (datetime.utcfromtimestamp(ts) + timedelta(hours=5, minutes=30)).strftime("%I:%M %p").lstrip("0")
    while True:
        try:
            st = _feed_status()
            feeds = {"main": st}
            if "crypto" in st: feeds["crypto"] = st["crypto"]
            if "forex" in st and st["forex"].get("configured", True): feeds["forex"] = st["forex"]
            now = time.time()
            for k, f in feeds.items():
                up = bool(f.get("connected")); off_on_purpose = bool(f.get("paused"))
                if up or off_on_purpose:
                    if k in alerted and up:
                        mins = max(1, int((now - down_since.get(k, now)) // 60))
                        await asyncio.get_event_loop().run_in_executor(None, _probe._telegram, f"✅ limefx: {names[k]} prices are back (were down {mins} min).")
                    down_since.pop(k, None); alerted.pop(k, None)
                    continue
                down_since.setdefault(k, now)
                if now - down_since[k] >= hold and (k not in alerted or now - alerted[k] >= 3600):
                    why = "It needs the daily login from the Master panel." if f.get("needs_login") else ""
                    first = k not in alerted
                    alerted[k] = now
                    msg = (f"⚠️ limefx: {names[k]} prices are DOWN since {ist(down_since[k])} IST." if first
                           else f"⚠️ limefx: {names[k]} prices are STILL down (since {ist(down_since[k])} IST).")
                    await asyncio.get_event_loop().run_in_executor(None, _probe._telegram, msg + (f" {why}" if why else "") + " Orders in that market are refused until it is back.")
        except Exception:
            log.exception("feed watch failed")
        await asyncio.sleep(20)


async def daystart_loop():
    """At the start of every IST day remember where the book stood, so 'P&L Today' can be the same
    formula as Net P&L (closed trades + open positions + commission) for today only. A snapshot taken
    late (server was down at midnight) is marked not exact and the panel falls back to closed trades."""
    while True:
        try:
            now = datetime.utcnow() + timedelta(hours=5, minutes=30)
            day = now.date().isoformat()
            db = SessionLocal()
            try:
                try:
                    snap = json.loads(get_setting(db, "daystart") or "{}")
                except Exception:
                    snap = {}
                if snap.get("day") != day:
                    alloc, equity = _book_totals(db)
                    set_setting(db, "daystart", json.dumps({"day": day, "alloc": alloc, "equity": equity,
                                                            "exact": now.hour == 0 and now.minute < 10, "at": now.strftime("%H:%M")}))
            finally:
                db.close()
        except Exception:
            log.exception("day-start snapshot failed")
        await asyncio.sleep(45)


@app.get("/api/admin/daystart")
def admin_daystart(admin: User = Depends(current_admin), db: Session = Depends(get_db)):
    try:
        return json.loads(get_setting(db, "daystart") or "{}")
    except Exception:
        return {}


@app.get("/api/admin/positions")
def admin_positions(admin: User = Depends(current_admin), db: Session = Depends(get_db)):
    """Every open position across all users, marked at the live exit price."""
    users = {u.id: u for u in db.query(User).filter_by(is_admin=False).filter(~User.username.startswith(_PROBE)).all()}
    out = []
    for p in db.query(Position).filter_by(is_closed=False).all():
        u = users.get(p.user_id)
        if not u or not p.qty:
            continue
        d = engine.position_dict(p)
        ins = feed.instruments.get(p.token)
        d.update(user_id=u.id, username=u.username, display_name=u.display_name or u.username,
                 segment=getattr(ins, "segment", ""), name=getattr(ins, "name", ""),
                 opened_at=(p.opened_at.isoformat() + "Z") if p.opened_at else None)
        out.append(d)
    return out


# ---- shadow book (dry run: no order is sent anywhere) -----------------------------------------------
# What would have happened if, for every user fill on NSE / BSE / MCX, the opposite order of the same size
# had been placed with a real broker at the same price. Pure arithmetic on trades already in the books.
SHADOW_EXCHANGES = ("NFO", "BFO", "MCX")
# Real-broker cost schedule (Zerodha's published charges, read 13 Nov 2026). % figures are of traded value
# (premium value for options). Editable only here for now.
SHADOW_RATES = {
    "eq_fut": {"brok_pct": 0.03, "brok_cap": 20.0, "tax_sell_pct": 0.05, "txn_pct": {"NFO": 0.00183, "BFO": 0.0}, "stamp_buy_pct": 0.002},
    "eq_opt": {"brok_flat": 20.0, "tax_sell_pct": 0.15, "txn_pct": {"NFO": 0.03553, "BFO": 0.0325}, "stamp_buy_pct": 0.003},
    "mcx_fut": {"brok_pct": 0.03, "brok_cap": 20.0, "tax_sell_pct": 0.01, "txn_pct": {"MCX": 0.0021}, "stamp_buy_pct": 0.002},
    "mcx_opt": {"brok_flat": 20.0, "tax_sell_pct": 0.05, "txn_pct": {"MCX": 0.0418}, "stamp_buy_pct": 0.003},
    "sebi_per_crore": 10.0, "gst_pct": 18.0,
}


def _shadow_cost(exchange: str, is_option: bool, our_side: str, value: float) -> dict:
    r = SHADOW_RATES[("mcx_" if exchange == "MCX" else "eq_") + ("opt" if is_option else "fut")]
    brok = r["brok_flat"] if "brok_flat" in r else min(r["brok_cap"], value * r["brok_pct"] / 100.0)
    tax = value * r["tax_sell_pct"] / 100.0 if our_side == "SELL" else 0.0
    txn = value * r["txn_pct"].get(exchange, 0.0) / 100.0
    sebi = value * SHADOW_RATES["sebi_per_crore"] / 1e7
    stamp = value * r["stamp_buy_pct"] / 100.0 if our_side == "BUY" else 0.0
    gst = (brok + txn + sebi) * SHADOW_RATES["gst_pct"] / 100.0
    return {"brokerage": brok, "tax": tax, "txn": txn, "sebi": sebi, "stamp": stamp, "gst": gst,
            "total": brok + tax + txn + sebi + stamp + gst}


@app.get("/api/admin/shadow")
def admin_shadow(from_: Optional[str] = Query(None, alias="from"), to: Optional[str] = None,
                 admin: User = Depends(current_admin), db: Session = Depends(get_db)):
    import re
    from .db import ShadowFill
    users = {u.id: u for u in db.query(User).filter_by(is_admin=False).filter(~User.username.startswith(_PROBE)).all()}
    try:
        d0 = datetime.strptime(from_, "%Y-%m-%d") - IST if from_ else None
        d1 = datetime.strptime(to, "%Y-%m-%d") + timedelta(days=1) - IST if to else None
    except ValueError:
        raise HTTPException(400, "Dates must look like 2026-11-13")
    live = d1 is None or d1 > datetime.utcnow()                 # running P&L only makes sense for a period that reaches now
    trades = db.query(Trade).filter(Trade.exchange.in_(SHADOW_EXCHANGES), Trade.user_id.in_(list(users) or [0])) \
               .order_by(Trade.created_at, Trade.id).all()
    ids = [t.id for t in trades]
    sf = {x.trade_id: x for x in db.query(ShadowFill).filter(ShadowFill.trade_id.in_(ids or [0])).all()}
    reasons = {o.id: (o.reason or "") for o in db.query(Order).filter(Order.id.in_([t.order_id for t in trades if t.order_id] or [0])).all()}
    keys = ("brokerage", "tax", "txn", "sebi", "stamp", "gst", "total")
    costs = dict.fromkeys(keys, 0.0)
    per, book, orders, basis_n = {}, {}, [], {}
    def row(uid):
        u = users[uid]
        return per.setdefault(uid, {"user": u.display_name or u.username, "username": u.username, "orders": 0, "turnover": 0.0,
                                    "realised": 0.0, "unrealised": 0.0, "costs": 0.0, "slippage": 0.0})
    for t in trades:
        ins = feed.instruments.get(t.token)
        vf = engine.vf(ins) if ins else 1.0
        is_opt = (ins.instrument_type in ("CE", "PE")) if ins else t.symbol.endswith(("CE", "PE"))
        ours = "SELL" if t.side == "BUY" else "BUY"
        # --- the price OUR order would have got
        x = sf.get(t.id)
        if t.order_id is None:
            px, basis = t.price, "settlement"                      # expiry / system settlement: both sides get the same price
        elif x:
            px, basis = x.price, ("live book" if x.basis == "book" else "live quote")
        else:
            m = re.search(r"bid ([0-9.]+) / ask ([0-9.]+)", reasons.get(t.order_id, ""))
            if m and float(m.group(1)) > 0 and float(m.group(2)) > 0:
                bid, ask = float(m.group(1)), float(m.group(2))    # the book printed on the user's order when it filled
                px = bid - max(0.0, t.price - ask) if ours == "SELL" else ask + max(0.0, bid - t.price)
                basis = "order record"
            else:
                px, basis = t.price, "same price"                  # nothing known about the book: no slippage assumed
        px = max(px, 0.0)
        slip = ((t.price - px) if ours == "SELL" else (px - t.price)) * t.qty * vf
        value = px * t.qty * vf
        # --- position accounting on our side (average cost)
        pos = book.setdefault((t.user_id, t.token), {"qty": 0, "avg": 0.0, "symbol": t.symbol, "exchange": t.exchange, "vf": vf})
        signed = t.qty if ours == "BUY" else -t.qty
        realised, was_long = 0.0, pos["qty"] > 0
        if pos["qty"] == 0 or (pos["qty"] > 0) == (signed > 0):
            pos["avg"] = (pos["avg"] * abs(pos["qty"]) + px * t.qty) / (abs(pos["qty"]) + t.qty); pos["qty"] += signed
        else:
            closing = min(abs(pos["qty"]), t.qty)
            realised = (px - pos["avg"]) * closing * (1 if pos["qty"] > 0 else -1) * vf
            pos["qty"] += signed
            if (pos["qty"] > 0) == (signed > 0) and pos["qty"] != 0:
                pos["avg"] = px                                    # flipped through zero
        # --- real-broker costs on our order
        if t.order_id is None:
            c = dict.fromkeys(keys, 0.0)
            if is_opt and t.exchange != "MCX" and was_long and px > 0:
                c["tax"] = c["total"] = value * 0.15 / 100.0       # STT on a bought option that expires in the money
        else:
            c = _shadow_cost(t.exchange, is_opt, ours, value)
        if (d0 is None or t.created_at >= d0) and (d1 is None or t.created_at < d1):
            for k in keys: costs[k] += c[k]
            r = row(t.user_id)
            r["orders"] += 1; r["turnover"] += value; r["realised"] += realised; r["costs"] += c["total"]; r["slippage"] += slip
            basis_n[basis] = basis_n.get(basis, 0) + 1
            orders.append({"at": t.created_at.isoformat() + "Z", "user": r["user"], "symbol": t.symbol, "exchange": t.exchange,
                           "user_side": t.side if t.order_id else "EXPIRY", "our_side": ours if t.order_id else "EXPIRY", "qty": t.qty,
                           "user_price": t.price, "price": round(px, 4), "slippage": round(slip, 2) + 0.0, "basis": basis,
                           "value": round(value, 2), "realised": round(realised, 2) + 0.0, "cost": round(c["total"], 2)})
    positions = []; margin = 0.0
    if live:
        for (uid, token), pos in book.items():
            if not pos["qty"]:
                continue
            mk = engine.mark_price(token, pos["qty"])
            if mk is None: mk = feed.ltp(token)
            u = (mk - pos["avg"]) * pos["qty"] * pos["vf"] if mk is not None else 0.0
            r = row(uid); r["unrealised"] += u
            ins = feed.instruments.get(token); lot = ins.lot_size if ins else 0
            positions.append({"user": r["user"], "symbol": pos["symbol"], "exchange": pos["exchange"], "our_side": "BUY" if pos["qty"] > 0 else "SELL",
                              "lots": abs(pos["qty"]) // lot if lot else 0, "qty": abs(pos["qty"]), "avg_price": round(pos["avg"], 4),
                              "ltp": mk, "unrealised": round(u, 2)})
        margin = sum((p.margin_blocked or 0.0) for p in db.query(Position).filter_by(is_closed=False).filter(Position.exchange.in_(SHADOW_EXCHANGES)).all()
                     if p.user_id in users and p.qty)
    realised = sum(r["realised"] for r in per.values()); unreal = sum(r["unrealised"] for r in per.values())
    for r in per.values():
        r["net"] = round(r["realised"] + r["unrealised"] - r["costs"], 2)
        for k in ("turnover", "realised", "unrealised", "costs", "slippage"): r[k] = round(r[k], 2)
    return {"live": live, "exchanges": ["NSE", "BSE", "MCX"],
            "summary": {"orders": sum(r["orders"] for r in per.values()), "turnover": round(sum(r["turnover"] for r in per.values()), 2),
                        "realised": round(realised, 2), "unrealised": round(unreal, 2), "gross": round(realised + unreal, 2),
                        "slippage": round(sum(r["slippage"] for r in per.values()), 2), "basis": basis_n,
                        "costs": {k: round(v, 2) for k, v in costs.items()}, "net": round(realised + unreal - costs["total"], 2),
                        "open_positions": len(positions), "margin_estimate": round(margin, 2)},
            "users": sorted(per.values(), key=lambda r: r["net"]), "positions": sorted(positions, key=lambda x: x["unrealised"]),
            "orders": orders[::-1][:300], "rates": SHADOW_RATES}


# ---- scheduled maintenance notice --------------------------------------------------------------------
class MaintIn(BaseModel):
    at: str                 # "HH:MM" today (IST)
    minutes: int = 10
    message: str = ""


def _maintenance(db) -> Optional[dict]:
    at = get_setting(db, "maint_at", "")
    if not at:
        return None
    try:
        start = datetime.fromisoformat(at)
    except ValueError:
        return None
    mins = int(get_setting(db, "maint_mins", "10") or 10)
    now = datetime.utcnow() + timedelta(hours=5.5)
    if now > start + timedelta(minutes=mins + 30):
        return None                      # long over
    return {"at": at, "at_ms": int((start - timedelta(hours=5.5) - datetime(1970, 1, 1)).total_seconds() * 1000),
            "minutes": mins, "message": get_setting(db, "maint_msg", "") or ""}


def _notice(db) -> Optional[dict]:
    """A message from the master that every user sees once, as a pop-up."""
    text = (get_setting(db, "notice_text", "") or "").strip()
    if not text:
        return None
    return {"id": get_setting(db, "notice_id", "") or "", "title": get_setting(db, "notice_title", "") or "Notice", "text": text}


class NoticeIn(BaseModel):
    title: str = ""
    text: str


@app.get("/api/public/maintenance")
def public_maintenance(db: Session = Depends(get_db)):
    return {"maintenance": _maintenance(db), "notice": _notice(db)}


@app.get("/api/admin/notice")
def admin_get_notice(admin: User = Depends(current_admin), db: Session = Depends(get_db)):
    return {"notice": _notice(db)}


@app.post("/api/admin/notice")
def admin_set_notice(body: NoticeIn, admin: User = Depends(current_admin), db: Session = Depends(get_db)):
    text = body.text.strip()[:800]
    if not text:
        raise HTTPException(400, "Write the notice first")
    set_setting(db, "notice_text", text); set_setting(db, "notice_title", (body.title.strip() or "Notice")[:60])
    set_setting(db, "notice_id", (datetime.utcnow() + timedelta(hours=5.5)).strftime("%Y%m%d%H%M%S")); db.commit()
    return {"notice": _notice(db)}


@app.delete("/api/admin/notice")
def admin_clear_notice(admin: User = Depends(current_admin), db: Session = Depends(get_db)):
    set_setting(db, "notice_text", ""); db.commit()
    return {"notice": None}


@app.post("/api/admin/maintenance")
def admin_set_maintenance(body: MaintIn, admin: User = Depends(current_admin), db: Session = Depends(get_db)):
    try:
        hh, mm = [int(x) for x in body.at.strip().split(":")[:2]]
    except ValueError:
        raise HTTPException(400, "Time must look like 15:45")
    now = datetime.utcnow() + timedelta(hours=5.5)
    start = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if start < now - timedelta(minutes=5):
        start += timedelta(days=1)       # a time already past means tomorrow
    set_setting(db, "maint_at", start.isoformat()); set_setting(db, "maint_mins", str(max(1, min(body.minutes, 240))))
    set_setting(db, "maint_msg", body.message.strip()[:200]); db.commit()
    return {"maintenance": _maintenance(db)}


@app.delete("/api/admin/maintenance")
def admin_clear_maintenance(admin: User = Depends(current_admin), db: Session = Depends(get_db)):
    set_setting(db, "maint_at", ""); db.commit()
    return {"ok": True}


# ---- backups & audit trail ---------------------------------------------------------------------------
def _db_file() -> Optional[Path]:
    return Path(config.DB_URL.replace("sqlite:///", "", 1)) if config.DB_URL.startswith("sqlite:///") else None


def _backup_to(dest: Path):
    """Consistent copy of the live database (SQLite online backup — safe while trading continues)."""
    import sqlite3
    src = sqlite3.connect(str(_db_file()), timeout=30)
    try:
        dst = sqlite3.connect(str(dest))
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


async def backup_loop():
    """One snapshot per day kept beside the database for 14 days — protects against a bad deploy or a
    corrupted file. (Off-server copies: use the Download backup button on the master panel.)"""
    while True:
        try:
            f = _db_file()
            if f and f.exists():
                d = config.DATA_DIR / "backups"; d.mkdir(exist_ok=True)
                today = d / f"limefx-{datetime.utcnow() + timedelta(hours=5.5):%Y-%m-%d}.db"
                if not today.exists():
                    await asyncio.get_event_loop().run_in_executor(None, _backup_to, today)
                    log.info("daily backup written: %s", today.name)
                for old in sorted(d.glob("limefx-*.db"))[:-14]:
                    old.unlink(missing_ok=True)
                if _tg_ready() and today.exists() and _tg_state().get("sent") != today.name:
                    await asyncio.get_event_loop().run_in_executor(None, _tg_send, today)
        except Exception:
            log.exception("daily backup failed")
        await asyncio.sleep(3600)


# ---- off-server copy: the daily snapshot, encrypted, sent to a private Telegram chat --------------------
# Railway variables: PT_TG_BOT_TOKEN, PT_TG_CHAT_ID, PT_BACKUP_PASSWORD (all three required; never logged).
def _tg_cfg():
    return (os.getenv("PT_TG_BOT_TOKEN", "").strip(), os.getenv("PT_TG_CHAT_ID", "").strip(), os.getenv("PT_BACKUP_PASSWORD", ""))


def _tg_ready() -> bool:
    return all(_tg_cfg())


def _tg_state_file() -> Path:
    return config.DATA_DIR / "backups" / "offsite.json"


def _tg_state() -> dict:
    try:
        return json.loads(_tg_state_file().read_text())
    except Exception:
        return {}


def _encrypt_backup(raw: bytes, password: str) -> bytes:
    """gzip, then AES-256-GCM with a key derived from the password (scrypt). Layout: LFXB1 | salt16 | nonce12 | data."""
    import gzip
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
    salt, nonce = os.urandom(16), os.urandom(12)
    key = Scrypt(salt=salt, length=32, n=2 ** 15, r=8, p=1).derive(password.encode())
    return b"LFXB1" + salt + nonce + AESGCM(key).encrypt(nonce, gzip.compress(raw), b"LFXB1")


def _tg_send(snapshot: Path, daily: bool = True) -> dict:
    """Send one encrypted snapshot. Records the outcome; never raises and never logs the token."""
    import httpx
    token, chat, password = _tg_cfg()
    st = _tg_state()
    now = f"{datetime.utcnow() + timedelta(hours=5.5):%Y-%m-%d %H:%M}"
    try:
        blob = _encrypt_backup(snapshot.read_bytes(), password)
        name = snapshot.name.replace(".db", ".db.enc")
        r = httpx.post(f"{os.getenv('PT_TG_API', 'https://api.telegram.org')}/bot{token}/sendDocument", timeout=60,
                       data={"chat_id": chat, "caption": f"limefx backup {snapshot.stem.replace('limefx-', '')} (encrypted)"},
                       files={"document": (name, blob, "application/octet-stream")})
        if r.status_code == 200 and r.json().get("ok"):
            st.update(sent_at=now, error="", ok_at=now)
            if daily:
                st["sent"] = snapshot.name
            log.info("off-server backup sent: %s (%d KB)", name, len(blob) // 1024)
        else:
            try:
                desc = str(r.json().get("description", ""))[:160]
            except Exception:
                desc = ""
            st.update(error=f"{now}: Telegram refused it ({r.status_code}) {desc}")
            log.warning("off-server backup refused: %s %s", r.status_code, desc)
    except Exception as e:   # the exception text can contain the request URL (and so the token): keep only its type
        st.update(error=f"{now}: could not send ({type(e).__name__})")
        log.warning("off-server backup failed: %s", type(e).__name__)
    try:
        _tg_state_file().parent.mkdir(exist_ok=True)
        _tg_state_file().write_text(json.dumps(st))
    except Exception:
        pass
    return st


@app.get("/api/admin/probe")
def admin_probe(admin: User = Depends(current_admin), db: Session = Depends(get_db)):
    """Last daily safety check (the site attacking itself) and the recent history."""
    try:
        last = json.loads(get_setting(db, "probe_last") or "null")
    except Exception:
        last = None
    try:
        hist = json.loads(get_setting(db, "probe_hist") or "[]")
    except Exception:
        hist = []
    return {"last": last, "history": hist, "runs_at": _probe.RUN_AT, "telegram": _tg_ready()}


@app.post("/api/admin/probe/run")
async def admin_probe_run(admin: User = Depends(current_admin)):
    res = await _probe.run_and_report(app, engine, feed)
    if res.get("busy"):
        raise HTTPException(409, "A safety check is already running")
    return res


@app.get("/api/admin/backup/offsite")
def admin_offsite(admin: User = Depends(current_admin)):
    token, chat, password = _tg_cfg()
    st = _tg_state()
    return {"configured": _tg_ready(), "missing": [n for n, v in (("PT_TG_BOT_TOKEN", token), ("PT_TG_CHAT_ID", chat), ("PT_BACKUP_PASSWORD", password)) if not v],
            "last_sent": st.get("sent_at", ""), "last_file": st.get("sent", ""), "error": st.get("error", "")}


@app.post("/api/admin/backup/offsite")
def admin_offsite_send(admin: User = Depends(current_admin)):
    """Send a fresh encrypted copy right now (also the way to test the setup)."""
    if not _tg_ready():
        raise HTTPException(400, "Off-server backup is not set up yet")
    f = _db_file()
    if not f or not f.exists():
        raise HTTPException(400, "Backups are only available for the built-in database")
    import tempfile
    tmp = Path(tempfile.gettempdir()) / f"limefx-{datetime.utcnow() + timedelta(hours=5.5):%Y-%m-%d-%H%M}.db"
    _backup_to(tmp)
    try:
        st = _tg_send(tmp, daily=False)
        ok = not st.get("error") and bool(st.get("ok_at"))
    finally:
        tmp.unlink(missing_ok=True)
    if not ok:
        raise HTTPException(502, st.get("error") or "Could not send")
    return {"ok": True, "sent_at": st.get("sent_at")}


@app.get("/api/admin/backup")
def admin_backup(admin: User = Depends(current_admin)):
    f = _db_file()
    if not f or not f.exists():
        raise HTTPException(400, "Backups are only available for the built-in database")
    import tempfile
    name = f"limefx-backup-{datetime.utcnow() + timedelta(hours=5.5):%Y-%m-%d-%H%M}.db"
    tmp = Path(tempfile.gettempdir()) / name
    _backup_to(tmp)
    return FileResponse(tmp, filename=name, media_type="application/octet-stream", headers=_NOCACHE)


@app.get("/api/admin/backups")
def admin_backups(admin: User = Depends(current_admin)):
    d = config.DATA_DIR / "backups"
    return [{"name": x.name, "kb": round(x.stat().st_size / 1024)} for x in sorted(d.glob("limefx-*.db"), reverse=True)] if d.exists() else []


@app.get("/api/admin/audit")
def admin_audit(admin: User = Depends(current_admin), db: Session = Depends(get_db)):
    from .db import AdminLog
    names = {u.id: u.username for u in db.query(User).all()}

    def nice(a: str) -> str:
        import re as _re
        m = _re.search(r"/users/(\d+)", a)
        return a + (f"  ({names.get(int(m.group(1)), '?')})" if m else "")
    return [{"at": r.created_at.isoformat() + "Z", "admin": r.admin_name, "action": nice(r.action), "ip": r.ip}
            for r in db.query(AdminLog).order_by(AdminLog.id.desc()).limit(200)]


@app.post("/api/admin/self/test-coins")
def admin_self_test_coins(admin: User = Depends(current_admin), db: Session = Depends(get_db)):
    """The master's own test balance for trying trades in the trader view. Kept out of every user
    total (all user lists and summaries filter on is_admin=False)."""
    engine._ledger(db, admin, 1000000.0, "ADMIN_CREDIT", "master test coins")
    db.commit()
    return {"ok": True, "funds": engine.funds(db, admin)}


@app.post("/api/admin/users")
def admin_create_user(body: UserIn, admin: User = Depends(current_admin), db: Session = Depends(get_db)):
    uname = body.username.strip().lower()
    if not uname or db.query(User).filter_by(username=uname).first():
        raise HTTPException(400, "Username empty or already exists")
    u = User(username=uname, display_name=body.display_name or uname, password_hash=hash_password(body.password),
             must_change_password=True)
    db.add(u); db.flush()
    if body.initial_coins:
        engine._ledger(db, u, body.initial_coins, "ADMIN_CREDIT", "initial allocation")
    db.commit()
    return _user_dict(u)


class CoinsIn(BaseModel):
    amount: float
    note: str = ""


@app.post("/api/admin/users/{uid}/coins")
def admin_coins(uid: int, body: CoinsIn, admin: User = Depends(current_admin), db: Session = Depends(get_db)):
    u = db.get(User, uid)
    if not u:
        raise HTTPException(404)
    engine._ledger(db, u, body.amount, "ADMIN_CREDIT" if body.amount >= 0 else "ADMIN_DEBIT", body.note)
    db.commit()
    _emit(u.id, {"type": "refresh", "message": f"Master {'added' if body.amount >= 0 else 'removed'} ₹{abs(body.amount):,.0f} coins"})
    return _user_dict(u)


class UserPatch(BaseModel):
    is_active: Optional[bool] = None
    password: Optional[str] = None
    display_name: Optional[str] = None
    reset_2fa: Optional[bool] = None


@app.patch("/api/admin/users/{uid}")
def admin_patch_user(uid: int, body: UserPatch, admin: User = Depends(current_admin), db: Session = Depends(get_db)):
    u = db.get(User, uid)
    if not u:
        raise HTTPException(404)
    if body.is_active is not None:
        u.is_active = body.is_active
    if body.password:
        u.password_hash = hash_password(body.password)
        u.must_change_password = True
        u.pw_changed_at = float(int(time.time()))     # logins made with the old password stop working
    if body.display_name is not None:
        u.display_name = body.display_name
    if body.reset_2fa:
        u.totp_enabled = False; u.totp_secret = ""
    db.commit()
    return _user_dict(u)


@app.delete("/api/admin/users/{uid}")
def admin_delete_user(uid: int, admin: User = Depends(current_admin), db: Session = Depends(get_db)):
    u = db.get(User, uid)
    if not u or u.is_admin:
        raise HTTPException(404)
    db.query(Trade).filter_by(user_id=uid).delete()
    db.query(Ledger).filter_by(user_id=uid).delete()
    db.query(Watch).filter_by(user_id=uid).delete()
    db.delete(u); db.commit()
    return {"ok": True}


@app.get("/api/admin/users/{uid}/detail")
def admin_user_detail(uid: int, admin: User = Depends(current_admin), db: Session = Depends(get_db)):
    u = db.get(User, uid)
    if not u:
        raise HTTPException(404)
    return {"user": _user_dict(u), "funds": engine.funds(db, u),
            "positions": [engine.position_dict(p) for p in db.query(Position).filter_by(user_id=uid, is_closed=False)],
            "orders": [engine.order_dict(o) for o in db.query(Order).filter_by(user_id=uid).order_by(Order.id.desc()).limit(100)],
            "trades": [{"id": t.id, "symbol": t.symbol, "side": t.side, "qty": t.qty, "price": t.price,
                        "realised_pnl": t.realised_pnl, "commission": t.commission or 0.0, "created_at": t.created_at.isoformat() + "Z"}
                       for t in db.query(Trade).filter_by(user_id=uid).order_by(Trade.id.desc()).limit(200)],
            "ledger": [{"amount": l.amount, "balance_after": l.balance_after, "kind": l.kind, "note": l.note,
                        "created_at": l.created_at.isoformat() + "Z"}
                       for l in db.query(Ledger).filter_by(user_id=uid).order_by(Ledger.id.desc()).limit(200)]}


@app.post("/api/admin/users/{uid}/squareoff")
async def admin_squareoff(uid: int, admin: User = Depends(current_admin), db: Session = Depends(get_db)):
    u = db.get(User, uid)
    if not u:
        raise HTTPException(404)
    done, errors = 0, []
    async with engine._lock:
        db.expire_all()   # objects loaded before we got the lock may be stale (concurrent orders)
        for p in db.query(Position).filter_by(user_id=uid, is_closed=False).all():
            try:
                engine.cancel_pending_for(db, u, p.token)
                engine.place_order(db, u, p.token, "SELL" if p.qty > 0 else "BUY", abs(p.qty) // p.lot_size)
                done += 1
            except EngineError as e:
                errors.append(f"{p.symbol}: {e}")
    return {"closed": done, "errors": errors}


@app.get("/api/admin/settings")
def admin_settings(admin: User = Depends(current_admin), db: Session = Depends(get_db)):
    on, spread, stale = engine.liquidity_settings(db)
    mp = {ex: engine.margin_pct(db, ex) for ex in ("NFO", "BFO", "MCX", "STK", "CDS", "CRYPTO")}
    for g in config.MCX_GROUP_LABELS:
        v = get_setting(db, f"margin_pct_{g}"); mp[g] = float(v) if v else config.DEFAULT_MARGIN_PCT[g]
    return {"margin_pct": mp, "mcx_groups": config.MCX_GROUP_LABELS, "mcx_option_factor": engine.mcx_option_factor(db), "market_status": _market_status(),
            "commission_pct": engine.commission_pct(db), "commission_pct_forex": engine.commission_pct(db, "FOREX"),
            "commission_pct_options": (lambda v: float(v) if v not in (None, "") else engine.commission_pct(db))(get_setting(db, "commission_pct_options")),
            "commission_flat": float(get_setting(db, "commission_flat") or 0),
            "liq_charge_flat": engine.liq_charge_terms(db)[0], "liq_charge_pct_crypto": engine.liq_charge_terms(db)[1],
            "commission_pct_crypto": (lambda v: float(v) if v not in (None, "") else engine.commission_pct(db))(get_setting(db, "commission_pct_CRYPTO")),
            "liquidity_check": on, "max_spread_pct": spread, "stale_minutes": stale,
            "feed": _feed_status(), "enforce_market_hours": config.ENFORCE_MARKET_HOURS,
            "underlyings": [u for u in config.ALLOWED_UNDERLYINGS if u != "STOCKS"], "stock_fno": config.ALLOW_STOCK_FNO}


class SettingsIn(BaseModel):
    margin_pct: dict
    commission_pct: Optional[float] = None
    commission_pct_forex: Optional[float] = None
    commission_pct_options: Optional[float] = None
    commission_flat: Optional[float] = None
    liq_charge_flat: Optional[float] = None
    liq_charge_pct_crypto: Optional[float] = None
    commission_pct_crypto: Optional[float] = None
    mcx_option_factor: Optional[float] = None
    liquidity_check: Optional[bool] = None
    max_spread_pct: Optional[float] = None
    stale_minutes: Optional[int] = None


@app.post("/api/admin/settings")
def admin_set_settings(body: SettingsIn, admin: User = Depends(current_admin), db: Session = Depends(get_db)):
    for ex, v in body.margin_pct.items():
        set_setting(db, f"margin_pct_{ex}", str(float(v)))
    if body.mcx_option_factor is not None:
        set_setting(db, "mcx_option_factor", str(min(1.0, max(0.3, float(body.mcx_option_factor)))))
    if body.commission_pct is not None:
        set_setting(db, "commission_pct", str(max(0.0, float(body.commission_pct))))
    if body.commission_pct_forex is not None:
        set_setting(db, "commission_pct_FOREX", str(max(0.0, float(body.commission_pct_forex))))
    if body.commission_pct_options is not None:
        set_setting(db, "commission_pct_options", str(max(0.0, min(5.0, float(body.commission_pct_options)))))
    if body.liq_charge_flat is not None:
        set_setting(db, "liq_charge_flat", str(max(0.0, min(10000.0, float(body.liq_charge_flat)))))
    if body.liq_charge_pct_crypto is not None:
        set_setting(db, "liq_charge_pct_CRYPTO", str(max(0.0, min(5.0, float(body.liq_charge_pct_crypto)))))
    if body.commission_flat is not None:
        set_setting(db, "commission_flat", str(max(0.0, min(1000.0, float(body.commission_flat)))))
    if body.commission_pct_crypto is not None:
        set_setting(db, "commission_pct_CRYPTO", str(max(0.0, min(5.0, float(body.commission_pct_crypto)))))
    if body.liquidity_check is not None:
        set_setting(db, "liquidity_check", "true" if body.liquidity_check else "false")
    if body.max_spread_pct is not None:
        set_setting(db, "max_spread_pct", str(float(body.max_spread_pct)))
    if body.stale_minutes is not None:
        set_setting(db, "stale_minutes", str(int(body.stale_minutes)))
    return {"ok": True}


@app.get("/api/admin/leaderboard")
def leaderboard(admin: User = Depends(current_admin), db: Session = Depends(get_db)):
    rows = []
    for u in db.query(User).filter_by(is_admin=False).filter(~User.username.startswith(_PROBE)).all():
        f = engine.funds(db, u)
        credited = sum(l.amount for l in db.query(Ledger).filter_by(user_id=u.id)
                       .filter(Ledger.kind.in_(["ADMIN_CREDIT", "ADMIN_DEBIT"])))
        rows.append({"username": u.username, "display_name": u.display_name, "credited": round(credited, 2),
                     "equity": f["equity"], "pnl": round(f["equity"] - credited, 2),
                     "pnl_pct": round((f["equity"] - credited) / credited * 100, 2) if credited else 0})
    rows.sort(key=lambda r: -r["pnl"])
    return rows


# ---- performance reports & Excel export ---------------------------------------------------------
IST = timedelta(hours=5, minutes=30)


def _range(from_: Optional[str], to: Optional[str]):
    """IST calendar range -> UTC datetimes [start, end)."""
    today = (datetime.utcnow() + IST).date()
    f = date.fromisoformat(from_) if from_ else date(2000, 1, 1)
    t = date.fromisoformat(to) if to else today
    start = datetime.combine(f, datetime.min.time()) - IST
    end = datetime.combine(t + timedelta(days=1), datetime.min.time()) - IST
    return start, end, f, t


def _ist_date(dt: datetime) -> str:
    return (dt + IST).date().isoformat()


def build_report(db: Session, users: List[User], from_: Optional[str], to: Optional[str]) -> dict:
    start, end, f, t = _range(from_, to)
    out = {"from": f.isoformat(), "to": t.isoformat(), "users": [], "daily": {}}
    all_days = {}
    for u in users:
        trades = (db.query(Trade).filter(Trade.user_id == u.id, Trade.created_at >= start, Trade.created_at < end)
                  .order_by(Trade.created_at).all())
        closing = [x for x in trades if x.realised_pnl]
        wins = [x.realised_pnl for x in closing if x.realised_pnl > 0]
        losses = [x.realised_pnl for x in closing if x.realised_pnl < 0]
        comm_total = round(sum(x.commission or 0 for x in trades), 2)
        pnl = round(sum(x.realised_pnl for x in trades) - comm_total, 2)   # net of commission
        daily = {}
        for x in trades:
            d = _ist_date(x.created_at)
            v = (x.realised_pnl or 0) - (x.commission or 0)
            daily[d] = round(daily.get(d, 0) + v, 2)
            all_days[d] = round(all_days.get(d, 0) + v, 2)
        credited = sum(l.amount for l in db.query(Ledger).filter(Ledger.user_id == u.id, Ledger.kind.in_(["ADMIN_CREDIT", "ADMIN_DEBIT"])))
        funds = engine.funds(db, u)
        out["users"].append({
            "id": u.id, "username": u.username, "display_name": u.display_name,
            "trades": len(trades), "closing_trades": len(closing), "wins": len(wins), "losses": len(losses),
            "win_rate": round(len(wins) / len(closing) * 100, 1) if closing else None,
            "gross_profit": round(sum(wins), 2), "gross_loss": round(sum(losses), 2), "commission": comm_total, "net_pnl": pnl,
            "best": round(max(wins), 2) if wins else 0, "worst": round(min(losses), 2) if losses else 0,
            "avg_win": round(sum(wins) / len(wins), 2) if wins else 0, "avg_loss": round(sum(losses) / len(losses), 2) if losses else 0,
            "profit_factor": round(sum(wins) / abs(sum(losses)), 2) if losses else None,
            "allocated": round(credited, 2), "equity": funds["equity"], "overall_pnl": round(funds["equity"] - credited, 2),
            "daily": dict(sorted(daily.items())),
        })
    out["daily"] = dict(sorted(all_days.items()))
    return out


@app.get("/api/admin/report")
def admin_report(from_: Optional[str] = Query(None, alias="from"), to: Optional[str] = None, user_id: Optional[int] = None,
                 admin: User = Depends(current_admin), db: Session = Depends(get_db)):
    q = db.query(User).filter_by(is_admin=False).filter(~User.username.startswith(_PROBE))
    if user_id:
        q = q.filter_by(id=user_id)
    return build_report(db, q.order_by(User.id).all(), from_, to)


@app.get("/api/report")
def my_report(from_: Optional[str] = Query(None, alias="from"), to: Optional[str] = None,
              user: User = Depends(current_user), db: Session = Depends(get_db)):
    return build_report(db, [user], from_, to)


def build_xlsx(db: Session, users: List[User], from_: Optional[str], to: Optional[str], only: Optional[str] = None) -> bytes:
    """only: None = everything; 'orderbook' | 'pnl' | 'ledger' = one standalone statement.
    (Legacy comma lists like 'orders,trades' are mapped onto these.)

    Every sheet uses the same words, in the same order, as the screens:
    Allocated, Available Balance, Margin Used, Unrealised, Realised, P&L, Commission, Net P&L, Net Balance."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter
    if only:
        o = only.lower()
        only = "orderbook" if "order" in o else "ledger" if "ledger" in o else "pnl"
    rep = build_report(db, users, from_, to)
    start, end, f, t = _range(from_, to)
    period = "All Time" if not from_ else (rep["from"] if rep["from"] == rep["to"] else f"{rep['from']} to {rep['to']}")
    who = users[0].display_name if len(users) == 1 else f"All Users ({len(users)})"
    gen = (datetime.utcnow() + IST).strftime("%d %b %Y, %H:%M IST")
    wb = Workbook()
    hdr_font = Font(bold=True, color="FFFFFF"); hdr_fill = PatternFill("solid", fgColor="365314")
    title_font = Font(bold=True, size=14, color="365314"); bold = Font(bold=True); grey = Font(color="6B7280")
    tot_fill = PatternFill("solid", fgColor="ECFCCB")
    MONEY = '#,##0.00;[Red]-#,##0.00'

    def sheet(title, headers, rows, money_cols=(), statement=None, totals=None, summary=None, int_cols=()):
        """One statement: title, who / period / generated, an optional one-line summary, then the table.
        Text is left-aligned, numbers right-aligned, column widths follow the content."""
        ws = wb.active if wb.active.title == "Sheet" else wb.create_sheet(title)
        ws.title = title
        ws.append([f"limefx — {statement or title}"]); ws["A1"].font = title_font
        ws.append([f"User: {who}   ·   Period: {period}   ·   Generated: {gen}"]); ws["A2"].font = grey
        ws.append([summary or ""]); ws["A3"].font = bold
        ws.append([])
        top = 5
        ws.append(headers)
        for c in ws[top]:
            c.font = hdr_font; c.fill = hdr_fill; c.alignment = Alignment(horizontal="center", vertical="center")
        for r in rows:
            ws.append(r)
        last_data = ws.max_row
        if totals:
            ws.append(totals)
            for c in ws[ws.max_row]: c.font = bold; c.fill = tot_fill
        for i, h in enumerate(headers, 1):
            L = get_column_letter(i)
            numeric = i in money_cols or i in int_cols
            width = len(str(h))
            for (cell,) in ws.iter_rows(min_row=top + 1, max_row=ws.max_row, min_col=i, max_col=i):
                v = cell.value
                if v is None:
                    continue
                if i in money_cols and isinstance(v, (int, float)):
                    cell.number_format = MONEY; width = max(width, len(f"{v:,.2f}") + 1)
                else:
                    width = max(width, len(str(v)))
                cell.alignment = Alignment(horizontal="right" if (numeric and isinstance(v, (int, float))) else "left", vertical="top")
            ws.column_dimensions[L].width = max(10, min(60, width + 3))
        ws.freeze_panes = f"A{top + 1}"
        return ws

    uid2name = {u.id: u.display_name for u in users}
    ids = [u.id for u in users]
    many = len(users) != 1
    tcol = ["User"] if many else []
    tval = (lambda uid: [uid2name.get(uid, "")]) if many else (lambda uid: [])
    sh = lambda n: n + (1 if many else 0)   # column shift when the User column is present
    sg = lambda v: f"{v:+,.2f}" if round(v, 2) else "0.00"

    # ---- Order Book -----------------------------------------------------------------------------
    if only in (None, "orderbook"):
        orders = db.query(Order).filter(Order.user_id.in_(ids), Order.created_at >= start, Order.created_at < end).order_by(Order.created_at, Order.id).all()
        cnt = lambda st: sum(1 for o in orders if o.status == st)
        sheet("Order Book", ["Date", "Time (IST)"] + tcol + ["Contract", "Side", "Type", "Lots", "Qty", "Limit Price", "Trigger Price", "Fill Price", "Status", "Note"],
              [[_ist_date(o.created_at), (o.created_at + IST).strftime("%H:%M:%S")] + tval(o.user_id) + [o.symbol, o.side, o.order_type,
                o.lots, o.qty, o.limit_price, o.trigger_price, o.fill_price, o.status, o.reason] for o in orders],
              money_cols=(sh(8), sh(9), sh(10)), int_cols=(sh(6), sh(7)), statement="Order Book",
              summary=f"Orders {len(orders)}   ·   Filled {cnt('FILLED')}   ·   Open {cnt('OPEN')}   ·   Rejected {cnt('REJECTED')}   ·   Cancelled {cnt('CANCELLED')}")
    # ---- P&L Statement --------------------------------------------------------------------------
    if only in (None, "pnl"):
        trades = db.query(Trade).filter(Trade.user_id.in_(ids), Trade.created_at >= start, Trade.created_at < end).order_by(Trade.created_at, Trade.id).all()
        cm = round(sum(x.commission or 0 for x in trades), 2)
        real = round(sum(x.realised_pnl or 0 for x in trades), 2)
        net = round(real - cm, 2)
        # trades the system made itself (auto square-off / margin call) are marked as liquidated
        liq_orders = {o.id for o in db.query(Order).filter(Order.id.in_([x.order_id for x in trades if x.order_id])).all()
                      if (o.reason or "").startswith(("Auto square-off", "Liquidated"))} if trades else set()
        sheet("P&L Statement", ["Date", "Time (IST)"] + tcol + ["Contract", "Exchange", "Side", "Qty", "Price", "Value", "Realised", "Commission", "Net P&L (Closed Trades)", "Note"],
              [[_ist_date(x.created_at), (x.created_at + IST).strftime("%H:%M:%S")] + tval(x.user_id) + [x.symbol, x.exchange,
                x.side, x.qty, x.price, round(x.price * x.qty, 2), x.realised_pnl or 0, -(x.commission or 0), round((x.realised_pnl or 0) - (x.commission or 0), 2),
                "Liquidated by system" if x.order_id in liq_orders else ""] for x in trades],
              money_cols=(sh(7), sh(8), sh(9), sh(10), sh(11)), int_cols=(sh(6),), statement="P&L Statement",
              summary=f"Trades {len(trades)}   ·   Realised {sg(real)}   ·   Commission {sg(-cm)}   ·   Net P&L (Closed Trades) {sg(net)}   (open positions not included)",
              totals=["TOTAL"] + [""] * (sh(8) - 1) + [real, -cm, net])
        # the same figures per user, in the order the screens use, then how the account stands now
        sheet("Summary", ["User", "Username", "Realised", "Commission", "Net P&L (Closed Trades)", "Trades", "Closing Trades", "Wins", "Losses", "Win Rate %",
                          "Best Trade", "Worst Trade", "Avg Win", "Avg Loss", "Profit Factor", "Allocated", "Net Balance", "Net P&L (All Time)"],
              [[u["display_name"], u["username"], round(u["gross_profit"] + u["gross_loss"], 2), -u["commission"], u["net_pnl"], u["trades"], u["closing_trades"],
                u["wins"], u["losses"], u["win_rate"], u["best"], u["worst"], u["avg_win"], u["avg_loss"], u["profit_factor"],
                u["allocated"], u["equity"], u["overall_pnl"]] for u in rep["users"]],
              money_cols=(3, 4, 5, 11, 12, 13, 14, 16, 17, 18), int_cols=(6, 7, 8, 9, 10, 15), statement="Summary",
              summary="Realised, Commission, Net P&L (Closed Trades) and Trades are for the period and count closed trades only — open positions are not included. Allocated, Net Balance and Net P&L (All Time) are as of now and do include open positions.",
              totals=(["TOTAL", "", real, -cm, net, len(trades)] + [""] * 9 + [round(sum(u["allocated"] for u in rep["users"]), 2),
                      round(sum(u["equity"] for u in rep["users"]), 2), round(sum(u["overall_pnl"] for u in rep["users"]), 2)]) if many else None)
        days = sorted({d for u in rep["users"] for d in u["daily"]})
        cum = 0; rows = []
        for d in days:
            v = rep["daily"].get(d, 0); cum = round(cum + v, 2)
            rows.append([d] + ([u["daily"].get(d, 0) for u in rep["users"]] if many else []) + [v, cum])
        ncol = (len(rep["users"]) if many else 0) + 3
        sheet("Daily Net P&L", ["Date"] + ([u["display_name"] for u in rep["users"]] if many else []) + ["Net P&L (Closed Trades)", "Cumulative Net P&L (Closed Trades)"], rows,
              money_cols=tuple(range(2, ncol + 1)), statement="Daily Net P&L",
              summary="Net P&L per day = Realised − Commission on that day's closed trades. Open positions are not included — they land here on the day they close.")
    # ---- Ledger Statement -----------------------------------------------------------------------
    if only in (None, "ledger"):
        kinds = {"ADMIN_CREDIT": "Coins Added", "ADMIN_DEBIT": "Coins Removed", "REALISED_PNL": "Realised",
                 "EXPIRY_SETTLEMENT": "Expiry Settlement", "LOT_SIZE_CORRECTION": "Lot Size Correction", "COMMISSION": "Commission",
                 "LIQUIDATION": "Margin Call"}
        led = db.query(Ledger).filter(Ledger.user_id.in_(ids), Ledger.created_at >= start, Ledger.created_at < end).order_by(Ledger.created_at, Ledger.id).all()
        rows = []; opening = None
        if not many:
            prev = db.query(Ledger).filter(Ledger.user_id == ids[0], Ledger.created_at < start).order_by(Ledger.created_at.desc(), Ledger.id.desc()).first()
            opening = prev.balance_after if prev else 0
            rows.append([rep["from"] if from_ else "", "", "Opening Balance", "", opening, ""])
        rows += [[_ist_date(l.created_at), (l.created_at + IST).strftime("%H:%M:%S")] + tval(l.user_id) + [
                  "Auto Square-off Charge" if (l.note or "").startswith("Auto square-off charge") else "Auto Square-off" if (l.note or "").startswith("Auto square-off") else kinds.get(l.kind, l.kind),
                  l.amount, l.balance_after, l.note] for l in led]
        cr = round(sum(l.amount for l in led if l.kind == "ADMIN_CREDIT"), 2); dr = round(sum(l.amount for l in led if l.kind == "ADMIN_DEBIT"), 2)
        pnl = round(sum(l.amount for l in led if l.kind not in ("ADMIN_CREDIT", "ADMIN_DEBIT", "COMMISSION")), 2)
        cmm = round(sum(l.amount for l in led if l.kind == "COMMISSION"), 2)
        closing = (led[-1].balance_after if led else opening) if not many else None
        summ = f"Entries {len(led)}   ·   Coins Added {sg(cr)}   ·   Coins Removed {sg(dr)}   ·   Realised {sg(pnl)}   ·   Commission {sg(cmm)}   ·   Net P&L {sg(round(pnl + cmm, 2))}"
        sheet("Ledger Statement", ["Date", "Time (IST)"] + tcol + ["Type", "Amount", "Balance After", "Note"], rows, money_cols=(sh(4), sh(5)),
              statement="Ledger Statement", summary=summ,
              totals=(["", "", "Closing Balance", "", closing, ""] if not many else None))
    buf = io.BytesIO(); wb.save(buf); return buf.getvalue()


def _stmt_tag(sheets: Optional[str]) -> str:
    if not sheets:
        return "AllStatements"
    s = sheets.lower()
    return "OrderBook" if "order" in s else "Ledger" if "ledger" in s else "PnL"


def _xlsx_response(data: bytes, name: str):
    return StreamingResponse(io.BytesIO(data), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": f'attachment; filename="{name}"'})


def _admin_rows(db):
    """One row per user with the reconciliation columns the master table shows."""
    rows = []
    for u in db.query(User).filter_by(is_admin=False).filter(~User.username.startswith(_PROBE)).order_by(User.id).all():
        f = engine.funds(db, u)
        led = db.query(Ledger).filter_by(user_id=u.id).all()
        alloc = sum(l.amount for l in led if l.kind in ("ADMIN_CREDIT", "ADMIN_DEBIT"))
        comm = -sum(l.amount for l in led if l.kind == "COMMISSION")
        realised = f["balance"] - alloc + comm
        rows.append({"name": u.display_name, "username": u.username, "status": "active" if u.is_active else "frozen",
                     "allocated": alloc, "exposure": f["used_margin"], "available": f["available"], "unrealised": f["unrealised"],
                     "realised": realised, "commission": comm, "net_balance": f["equity"], "net_pnl": f["equity"] - alloc,
                     "open_positions": db.query(Position).filter_by(user_id=u.id, is_closed=False).count(),
                     "trades": db.query(Trade).filter_by(user_id=u.id).count()})
    return rows


@app.get("/api/admin/summary.xlsx")
def admin_summary_xlsx(admin: User = Depends(current_admin), db: Session = Depends(get_db)):
    """The Master panel as a sheet: the Dashboard row (our side) on top, the user table under it, the
    same columns in the same order as the screen."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter
    rows = _admin_rows(db)
    now = (datetime.utcnow() + timedelta(hours=5, minutes=30))
    wb = Workbook(); ws = wb.active; ws.title = "Master Summary"
    cols = ["User", "Username", "Status", "Allocated", "Available Balance", "Margin Used", "Unrealised", "Realised", "P&L",
            "Commission", "Net P&L", "Net Balance", "Open Pos", "Trades"]
    hfont = Font(bold=True, color="FFFFFF"); hfill = PatternFill("solid", fgColor="365314"); bold = Font(bold=True)
    tfill = PatternFill("solid", fgColor="ECFCCB")
    money = '"₹"#,##0.00;[Red]-"₹"#,##0.00'

    def header(r):
        for i, h in enumerate(cols, 1):
            c = ws.cell(r, i, h); c.font = hfont; c.fill = hfill; c.alignment = Alignment(horizontal="center", vertical="center")
        ws.row_dimensions[r].height = 22

    ws["A1"] = "limefx — Master Summary"; ws["A1"].font = Font(bold=True, size=14, color="365314")
    ws["A2"] = f"Generated: {now.strftime('%d %b %Y, %I:%M %p')} IST   ·   All Time   ·   {len(rows)} Users"; ws["A2"].font = Font(color="6B7280")
    DASH_H, DASH_V, USERS_T, USERS_H = 4, 5, 7, 8
    first = USERS_H + 1; n = len(rows); last = first + n - 1; tot = last + 1
    # ---- users (their side) ----
    ws.cell(USERS_T, 1, "Users (Their Side)").font = bold
    header(USERS_H)
    for k, r in enumerate(rows):
        i = first + k
        for c, v in enumerate([r["name"], r["username"], r["status"], r["allocated"], r["available"], r["exposure"], r["unrealised"], r["realised"],
                               f"=G{i}+H{i}", -r["commission"], f"=I{i}+J{i}", r["net_balance"], r["open_positions"], r["trades"]], 1):
            ws.cell(i, c, v)
    ws.cell(tot, 1, "TOTAL")
    for col in range(4, 15):
        L = get_column_letter(col)
        ws.cell(tot, col, f"=SUM({L}{first}:{L}{last})" if n else 0)
    for c in ws[tot]:
        c.font = bold; c.fill = tfill
    # ---- dashboard (our side): the totals with the P&L signs turned round ----
    ws.cell(DASH_H - 1, 1, "Dashboard (Our Side)").font = bold
    header(DASH_H)
    for i in (1, 2, 3):
        ws.cell(DASH_H, i, "").fill = hfill
    ws.cell(DASH_V, 1, "Dashboard").font = bold
    for col in range(4, 15):
        L = get_column_letter(col)
        flip = col in (7, 8, 9, 10, 11)          # Unrealised, Realised, P&L, Commission, Net P&L are the opposite for us
        ws.cell(DASH_V, col, f"={'-' if flip else ''}{L}{tot}").font = bold
    for c in ws[DASH_V]:
        c.fill = tfill
    # ---- check column ----
    ws.cell(USERS_H, 16, "Check (Should Be 0)").font = bold
    for i in range(first, last + 1):
        ws.cell(i, 16, f"=ROUND(D{i}+K{i}-L{i},2)").number_format = money
    # ---- formats and alignment ----
    for r in [DASH_V] + list(range(first, tot + 1)):
        for col in range(4, 13):
            c = ws.cell(r, col); c.number_format = money; c.alignment = Alignment(horizontal="right")
        for col in (13, 14):
            ws.cell(r, col).alignment = Alignment(horizontal="right")
        for col in (1, 2, 3):
            ws.cell(r, col).alignment = Alignment(horizontal="left")
    for i, w in enumerate([24, 14, 10, 17, 19, 17, 16, 16, 16, 15, 16, 18, 10, 9, 2, 20], 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = f"B{USERS_H + 1}"
    # ---- how to read it ----
    w2 = wb.create_sheet("How It Adds Up")
    lines = [["limefx — How It Adds Up", ""], ["", ""],
             ["Allocated", "Coins given to the user (added minus removed)."],
             ["Available Balance", "What the user can still trade with."],
             ["Margin Used", "Margin blocked by open positions and pending orders."],
             ["Unrealised", "Open positions valued at the price they could exit at right now."],
             ["Realised", "Profit or loss booked on closed trades, before commission."],
             ["P&L", "Unrealised + Realised."],
             ["Commission", "Charged on every buy and sell: a percentage of the traded value (of the premium for options), plus the flat fee per order where one is set. Negative for the user, positive for us."],
             ["Net P&L", "P&L + Commission (commission is negative for the user)."],
             ["Net Balance", "Allocated + Net P&L. What the account is worth now."],
             ["", ""],
             ["Dashboard (Our Side)", "The TOTAL row with Unrealised, Realised, P&L, Commission and Net P&L turned round: what users lose, we gain."],
             ["Check (Should Be 0)", "Allocated + Net P&L − Net Balance for each user."]]
    for l in lines:
        w2.append(l)
    w2["A1"].font = Font(bold=True, size=13)
    for i in range(3, 15):
        w2.cell(i, 1).font = Font(bold=True)
    w2.column_dimensions["A"].width = 24; w2.column_dimensions["B"].width = 110
    buf = io.BytesIO(); wb.save(buf)
    return _xlsx_response(buf.getvalue(), f"limefx_master_summary_{now.strftime('%Y-%m-%d')}.xlsx")


@app.get("/api/admin/export.xlsx")
def admin_export(from_: Optional[str] = Query(None, alias="from"), to: Optional[str] = None, user_id: Optional[int] = None,
                 sheets: Optional[str] = None, admin: User = Depends(current_admin), db: Session = Depends(get_db)):
    q = db.query(User).filter_by(is_admin=False).filter(~User.username.startswith(_PROBE))
    if user_id:
        q = q.filter_by(id=user_id)
    users = q.order_by(User.id).all()
    rep_name = f"limefx_{(users[0].username if user_id and users else 'all')}_{_stmt_tag(sheets)}_{from_ or 'start'}_to_{to or 'today'}.xlsx"
    return _xlsx_response(build_xlsx(db, users, from_, to, sheets), rep_name)


@app.get("/api/export.xlsx")
def my_export(from_: Optional[str] = Query(None, alias="from"), to: Optional[str] = None, sheets: Optional[str] = None,
              user: User = Depends(current_user), db: Session = Depends(get_db)):
    return _xlsx_response(build_xlsx(db, [user], from_, to, sheets), f"limefx_{user.username}_{_stmt_tag(sheets)}_{from_ or 'start'}_to_{to or 'today'}.xlsx")


# ---- Pulse (public): gainers / losers / most traded ---------------------------------------------
from .pulse import Pulse
pulse = Pulse(feed)


@app.get("/api/public/pulse")
def public_pulse(period: str = "today", kind: str = "all"):
    if period not in ("today", "week", "month"):
        period = "today"
    if kind not in ("all", "index", "stock", "mcx", "currency", "crypto", "forex", "global"):
        kind = "all"
    return pulse.snapshot(period, kind)


# ---- feed control (master) ----------------------------------------------------------------------
@app.post("/api/admin/feed/disconnect")
def feed_disconnect(admin: User = Depends(current_admin)):
    if not hasattr(feed, "disconnect"):
        raise HTTPException(400, "Not available for this feed")
    feed.disconnect()
    log.info("live feed disconnected by master %s", admin.username)
    return feed.status()


@app.post("/api/admin/feed/crypto/disconnect")
def crypto_disconnect(admin: User = Depends(current_admin)):
    if not crypto:
        raise HTTPException(400, "Crypto feed is not enabled")
    crypto.disconnect()
    log.info("crypto feed disconnected by master %s", admin.username)
    return crypto.status()


@app.post("/api/admin/feed/crypto/reconnect")
def crypto_reconnect(admin: User = Depends(current_admin)):
    if not crypto:
        raise HTTPException(400, "Crypto feed is not enabled")
    crypto.reconnect()
    log.info("crypto feed reconnect by master %s", admin.username)
    return crypto.status()


class ForexTokenIn(BaseModel):
    token: str
    refresh_token: Optional[str] = None


@app.post("/api/admin/feed/forex/token")
def forex_token(body: ForexTokenIn, admin: User = Depends(current_admin)):
    """Master pastes the cTrader access token (from openapi.ctrader.com → Sandbox → Get token, or the OAuth flow)."""
    if not forex:
        raise HTTPException(400, "Forex feed is not configured (set PT_CTRADER_CLIENT_ID/SECRET)")
    t = body.token.strip()
    if t.startswith("http"):
        from urllib.parse import urlparse, parse_qs
        q = parse_qs(urlparse(t).query)
        t = (q.get("code") or q.get("access_token") or [""])[0]
    if not t:
        raise HTTPException(400, "No token found")
    forex.save_token(t, (body.refresh_token or "").strip() or None)
    forex.reconnect()
    log.info("forex token set by master %s", admin.username)
    return forex.status()


@app.get("/api/admin/feed/forex/symbols")
def admin_forex_symbols(admin: User = Depends(current_admin)):
    """Everything the connected forex account lists (not just what limefx offers) — for deciding what to add."""
    return getattr(forex, "all_symbols", []) if forex else []


@app.get("/api/admin/feed/forex/probe")
async def admin_forex_probe(names: str, admin: User = Depends(current_admin)):
    if not forex or not forex.connected:
        raise HTTPException(400, "Forex feed is not connected")
    return await forex.probe([n.strip() for n in names.split(",") if n.strip()][:25])


@app.get("/api/admin/feed/forex/global-check")
def admin_global_check(admin: User = Depends(current_admin)):
    """Every Global contract with the currency it is priced in, the rupee rate used and what one lot is worth — for checking conversions."""
    if not forex:
        return []
    out = []
    for tok, ins in forex.items.items():
        if ins.segment != "GLOBAL-SPOT":
            continue
        m = forex.meta.get(tok, {}); px = feed.ltp(tok); vf = forex.value_factor(ins); is_open, opens = forex.market_open(tok)
        out.append({"symbol": ins.symbol, "title": m.get("title"), "quote": m.get("quote"), "inr_per_quote": round(forex.quote_to_inr(m.get("quote", "USD")) or 0, 4),
                    "price": px, "lot": ins.lot_size, "one_lot_inr": round((px or 0) * ins.lot_size * vf, 2), "max_leverage": m.get("leverage"),
                    "open": is_open, "reopens": opens, "tick_age": feed.tick_age(tok)})
    return sorted(out, key=lambda x: x["symbol"])


@app.post("/api/admin/feed/forex/disconnect")
def forex_disconnect(admin: User = Depends(current_admin)):
    if not forex:
        raise HTTPException(400, "Forex feed is not configured")
    forex.disconnect(); return forex.status()


@app.post("/api/admin/feed/forex/reconnect")
def forex_reconnect(admin: User = Depends(current_admin)):
    if not forex:
        raise HTTPException(400, "Forex feed is not configured")
    forex.reconnect(); return forex.status()


@app.post("/api/admin/feed/reconnect")
def feed_reconnect(admin: User = Depends(current_admin)):
    if not hasattr(feed, "reconnect"):
        raise HTTPException(400, "Not available for this feed")
    ok = feed.reconnect()
    log.info("live feed reconnect by master %s -> %s", admin.username, ok)
    if not ok:
        raise HTTPException(400, "Today's Zerodha login is needed first — use Connect Zerodha")
    return feed.status()


# ---- Zerodha connect -----------------------------------------------------------------------
@app.get("/auth/kite/login")
def kite_login(admin: User = Depends(current_admin)):
    if config.FEED != "kite":
        raise HTTPException(400, "Feed is not kite")
    return RedirectResponse(feed.login_url())


@app.get("/auth/kite/callback")
async def kite_callback(request: Request, request_token: str = "", status: str = "", db: Session = Depends(get_db)):
    if config.FEED != "kite":
        raise HTTPException(400, "Feed is not kite")
    if not request_token:
        return RedirectResponse("/admin?kite=failed")
    try:
        tok = await asyncio.get_event_loop().run_in_executor(None, feed.exchange_request_token, request_token)
    except Exception as e:
        log.exception("kite login failed")
        return RedirectResponse(f"/admin?kite=failed&msg={e}")
    set_setting(db, "kite_access_token", tok)
    set_setting(db, "kite_token_date", date.today().isoformat())
    await asyncio.get_event_loop().run_in_executor(None, feed.connect)
    engine.load_pending()
    return RedirectResponse("/admin?kite=ok")


@app.get("/api/feed/status")
def feed_status(user: User = Depends(current_user)):
    return _feed_status()


def _feed_status():
    s = feed.status()
    if crypto:
        s["crypto"] = crypto.status()
    if forex:
        s["forex"] = forex.status()
    return s
