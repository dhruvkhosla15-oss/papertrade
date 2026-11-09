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
from pydantic import BaseModel
from sqlalchemy.orm import Session

from . import config
from .db import init_db, SessionLocal, User, Order, Position, Trade, Ledger, Watch, get_setting, set_setting
from .auth import (make_pre_token, optional_user, get_db, current_user, current_admin, hash_password, verify_password, make_token,
                   decode_token, COOKIE)
from .engine import Engine, EngineError
from .feed.mock import MockFeed

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("app")

app = FastAPI(title="LimeFX")

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
    engine.load_pending()
    asyncio.create_task(broadcaster())
    asyncio.create_task(engine.expiry_loop())


# ---- pages -----------------------------------------------------------------------
_NOCACHE = {"Cache-Control": "no-store, must-revalidate", "Pragma": "no-cache"}


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html", headers=_NOCACHE)


@app.get("/admin")
def admin_page():
    return FileResponse(STATIC / "admin.html", headers=_NOCACHE)


# ---- auth -------------------------------------------------------------------------
class LoginIn(BaseModel):
    username: str
    password: str


@app.post("/api/login")
def login(body: LoginIn, response: Response, db: Session = Depends(get_db)):
    u = db.query(User).filter_by(username=body.username.strip().lower()).first()
    if not u or not verify_password(body.password, u.password_hash):
        raise HTTPException(401, "Wrong username or password")
    if not u.is_active and not u.is_admin:
        raise HTTPException(403, "Account frozen — contact your trainer")
    if u.is_admin and u.totp_enabled:
        return {"ok": False, "needs_2fa": True, "pre_token": make_pre_token(u), "is_admin": True}
    tok = make_token(u)
    response.set_cookie(COOKIE, tok, httponly=True, samesite="lax", max_age=30 * 86400)
    return {"ok": True, "token": tok, "user": _user_dict(u), "is_admin": u.is_admin}


class TwoFaIn(BaseModel):
    pre_token: str
    code: str


def _totp_ok(secret: str, code: str) -> bool:
    import pyotp
    return bool(secret) and pyotp.TOTP(secret).verify((code or "").strip().replace(" ", ""), valid_window=1)


@app.post("/api/login/2fa")
def login_2fa(body: TwoFaIn, response: Response, db: Session = Depends(get_db)):
    from .auth import decode_token
    data = decode_token(body.pre_token)
    if not data or not data.get("pre2fa"):
        raise HTTPException(401, "Login expired — enter your password again")
    u = db.get(User, data["uid"])
    if not u or not u.is_admin or not _totp_ok(u.totp_secret, body.code):
        raise HTTPException(401, "Wrong authenticator code")
    tok = make_token(u)
    response.set_cookie(COOKIE, tok, httponly=True, samesite="lax", max_age=30 * 86400)
    return {"ok": True, "token": tok, "user": _user_dict(u), "is_admin": True}


# ---- master 2FA (TOTP: Google Authenticator / Authy / 1Password) ----------------------------------
@app.post("/api/admin/2fa/setup")
def twofa_setup(admin: User = Depends(current_admin), db: Session = Depends(get_db)):
    """Create a new secret (not active until confirmed) and return the QR code to scan."""
    import pyotp, segno, io as _io
    if admin.totp_enabled:
        raise HTTPException(400, "2FA is already on. Turn it off first to set up a new device.")
    secret = pyotp.random_base32()
    admin.totp_secret = secret; db.commit()
    uri = pyotp.TOTP(secret).provisioning_uri(name=admin.username, issuer_name="limeFX Master")
    buf = _io.BytesIO(); segno.make(uri).save(buf, kind="svg", scale=5, dark="#111827", light=None)
    return {"secret": secret, "uri": uri, "qr_svg": buf.getvalue().decode()}


class CodeIn(BaseModel):
    code: str


@app.post("/api/admin/2fa/confirm")
def twofa_confirm(body: CodeIn, admin: User = Depends(current_admin), db: Session = Depends(get_db)):
    if not admin.totp_secret or not _totp_ok(admin.totp_secret, body.code):
        raise HTTPException(400, "That code didn't match — check the time on your phone and try again")
    admin.totp_enabled = True; db.commit()
    return {"ok": True}


@app.post("/api/admin/2fa/disable")
def twofa_disable(body: CodeIn, admin: User = Depends(current_admin), db: Session = Depends(get_db)):
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
def admins_password(uid: int, body: AdminPwIn, admin: User = Depends(current_admin), db: Session = Depends(get_db)):
    u = db.get(User, uid)
    if not u or not u.is_admin:
        raise HTTPException(404, "No such master account")
    if len(body.password) < 6:
        raise HTTPException(400, "Password must be at least 6 characters")
    u.password_hash = hash_password(body.password); db.commit()
    return {"ok": True}


@app.post("/api/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE)
    return {"ok": True}


@app.get("/api/me")
def me(user: User = Depends(current_user), db: Session = Depends(get_db)):
    on, spread, stale = engine.liquidity_settings(db)
    return {"user": _user_dict(user), "funds": engine.funds(db, user), "feed": feed.status(),
            "market_open": {ex: engine.market_open(ex) for ex in config.MARKET_HOURS},
            "liquidity": {"on": on, "max_spread_pct": spread}}


class PasswordIn(BaseModel):
    old_password: str
    new_password: str


@app.post("/api/password")
def change_password(body: PasswordIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not verify_password(body.old_password, user.password_hash):
        raise HTTPException(400, "Current password is wrong")
    if len(body.new_password) < 4:
        raise HTTPException(400, "Password too short")
    user.password_hash = hash_password(body.new_password)
    db.commit()
    return {"ok": True}


def _user_dict(u: User):
    return {"id": u.id, "username": u.username, "display_name": u.display_name, "is_admin": u.is_admin,
            "is_active": u.is_active, "balance": round(u.balance, 2), "twofa": bool(u.totp_enabled)}


# ---- market data ------------------------------------------------------------------------
@app.get("/api/underlyings")
def underlyings(user: Optional[User] = Depends(optional_user)):   # visitors may browse the scrip lists
    out = []
    from .feed.base import kind_of
    for exch, names in feed.underlyings().items():
        for n in names:
            it = feed.index_token_for(n)
            out.append({"exchange": exch, "name": n, "spot_token": it, "kind": kind_of(exch, n)})
    order = {"NFO": 0, "BFO": 1, "MCX": 2}
    korder = {"index": 0, "mcx": 1, "stock": 2}
    out.sort(key=lambda x: (korder[x["kind"]], order.get(x["exchange"], 9), x["name"]))
    return out


@app.get("/api/expiries")
def expiries(exchange: str, name: str, user: User = Depends(current_user)):
    from .engine import ist_now
    n = ist_now(); today = n.date().isoformat()
    close = config.MARKET_HOURS.get(exchange, ("09:15", "15:30"))[1]
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
                    if i.exchange == exchange and i.name == name and i.instrument_type == "FUT" and i.expiry >= today),
                   key=lambda x: x.expiry)
    return [i.to_dict() for i in items]


@app.get("/api/candles")
async def candles(token: int, interval: str = "5m", user: User = Depends(current_user)):
    ins = feed.instruments.get(token)
    if not ins or ins.segment == "INDICES":
        raise HTTPException(404, "charts are available for options and futures only")
    data = await asyncio.get_event_loop().run_in_executor(None, feed.candles, token, interval)
    return {"interval": interval, "candles": data}


# Showcase: what the public home page, the scrolling ticker and a new trainee's watchlist show.
# Indices, the most-traded F&O stocks, and the main MCX commodities. Override with PT_SHOWCASE=NIFTY,RELIANCE,GOLD,...
_SHOWCASE_DEFAULT = ["NIFTY", "BANKNIFTY", "SENSEX",
                     "RELIANCE", "HDFCBANK", "ICICIBANK", "SBIN", "INFY", "TCS", "TATAMOTORS", "BHARTIARTL", "ITC", "LT",
                     "GOLD", "SILVER", "CRUDEOIL", "NATURALGAS", "COPPER"]
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

GUEST_SUB_CEILING = 2400   # leave headroom under Zerodha's 3000-instrument socket limit for trainees


def _ticker():
    from .feed.base import kind_of
    out = []
    for i in _default_watch_instruments():
        ex = i.exchange if i.exchange == "MCX" else ("BFO" if i.exchange == "BSE" else "NFO")
        out.append({"exchange": ex, "name": i.name, "spot_token": i.token, "kind": kind_of(ex, i.name)})
    return out


@app.get("/api/public/home")
def public_home():
    """What a visitor sees before logging in."""
    tick = _ticker()
    return {"watchlist": [i.to_dict() for i in _default_watch_instruments()], "ticker": tick, "feed": feed.status()}


@app.get("/api/watchlist")
def watchlist(user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not db.query(Watch).filter_by(user_id=user.id).first() and not get_setting(db, f"watch_seeded_{user.id}"):
        for n, ins in enumerate(_default_watch_instruments()):
            db.add(Watch(user_id=user.id, token=ins.token, symbol=ins.symbol, exchange=ins.exchange, position=n))
        set_setting(db, f"watch_seeded_{user.id}", "1")
        db.commit()
    elif not get_setting(db, f"watch_showcase_{user.id}") and feed.instruments:
        # one-time: add the showcase scrips (top stocks etc.) to watchlists created before they existed
        have = {w.token for w in db.query(Watch).filter_by(user_id=user.id).all()}
        last = db.query(Watch).filter_by(user_id=user.id).order_by(Watch.position.desc()).first()
        pos = (last.position + 1) if last else 0
        for ins in _default_watch_instruments():
            if ins.token not in have:
                db.add(Watch(user_id=user.id, token=ins.token, symbol=ins.symbol, exchange=ins.exchange, position=pos)); pos += 1
        set_setting(db, f"watch_showcase_{user.id}", "1")
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
    limit_price: Optional[float] = None
    trigger_price: Optional[float] = None


async def _ensure_price(token: int, timeout=3.0):
    if feed.ltp(token) is None:
        feed.pin([token])
        t0 = time.time()
        while feed.ltp(token) is None and time.time() - t0 < timeout:
            await asyncio.sleep(0.1)


@app.post("/api/orders")
async def place_order(body: OrderIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    await _ensure_price(body.token)
    async with engine._lock:
        try:
            o = engine.place_order(db, user, body.token, body.side, body.lots, body.order_type,
                                   body.limit_price, body.trigger_price)
        except EngineError as e:
            raise HTTPException(400, str(e))
    return {"order": engine.order_dict(o), "funds": engine.funds(db, user)}


@app.get("/api/margin")
def margin(token: int, side: str, lots: int, price: Optional[float] = None,
           user: User = Depends(current_user), db: Session = Depends(get_db)):
    ins = feed.instruments.get(token)
    if not ins:
        raise HTTPException(404, "unknown instrument")
    p = price or feed.ltp(token) or 0
    qty = lots * ins.lot_size
    return {"margin": engine._opening_margin(db, user, ins, side.upper(), qty, p), "qty": qty,
            "full_margin": engine.required_margin(db, ins, side.upper(), qty, p),
            "commission": round(p * qty * engine.commission_pct(db) / 100.0, 2), "commission_pct": engine.commission_pct(db)}


@app.delete("/api/orders/{order_id}")
async def cancel_order(order_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    async with engine._lock:
        try:
            engine.cancel_order(db, user, order_id)
        except EngineError as e:
            raise HTTPException(400, str(e))
    return {"ok": True}


@app.get("/api/orders")
def list_orders(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.query(Order).filter_by(user_id=user.id).order_by(Order.id.desc()).limit(200).all()
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
        try:
            o = engine.place_order(db, user, p.token, "SELL" if p.qty > 0 else "BUY", abs(p.qty) // p.lot_size)
        except EngineError as e:
            raise HTTPException(400, str(e))
    return {"order": engine.order_dict(o)}


@app.get("/api/trades")
def list_trades(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.query(Trade).filter_by(user_id=user.id).order_by(Trade.id.desc()).limit(300).all()
    return [{"id": t.id, "symbol": t.symbol, "exchange": t.exchange, "side": t.side, "qty": t.qty,
             "price": t.price, "realised_pnl": t.realised_pnl, "commission": t.commission or 0.0,
             "created_at": t.created_at.isoformat() + "Z"} for t in rows]


@app.get("/api/ledger")
def list_ledger(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.query(Ledger).filter_by(user_id=user.id).order_by(Ledger.id.desc()).limit(300).all()
    return [{"id": l.id, "amount": l.amount, "balance_after": l.balance_after, "kind": l.kind, "note": l.note,
             "created_at": l.created_at.isoformat() + "Z"} for l in rows]


# ---- websocket ------------------------------------------------------------------------------
@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    tok = ws.cookies.get(COOKIE) or ws.query_params.get("token")
    data = decode_token(tok) if tok else None
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
                    # visitors never squeeze trainees out of the Zerodha socket
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
                await ws.send_text(json.dumps({"type": "pong", "feed": feed.status()}))
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
    for u in db.query(User).filter_by(is_admin=False).order_by(User.id).all():
        f = engine.funds(db, u)
        out.append({**_user_dict(u), **f,
                    "open_positions": db.query(Position).filter_by(user_id=u.id, is_closed=False).count(),
                    "trades": db.query(Trade).filter_by(user_id=u.id).count(),
                    "total_credited": sum(l.amount for l in db.query(Ledger).filter_by(user_id=u.id)
                                          .filter(Ledger.kind.in_(["ADMIN_CREDIT", "ADMIN_DEBIT"])))})
    return out


@app.post("/api/admin/users")
def admin_create_user(body: UserIn, admin: User = Depends(current_admin), db: Session = Depends(get_db)):
    uname = body.username.strip().lower()
    if not uname or db.query(User).filter_by(username=uname).first():
        raise HTTPException(400, "Username empty or already exists")
    u = User(username=uname, display_name=body.display_name or uname, password_hash=hash_password(body.password))
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


@app.patch("/api/admin/users/{uid}")
def admin_patch_user(uid: int, body: UserPatch, admin: User = Depends(current_admin), db: Session = Depends(get_db)):
    u = db.get(User, uid)
    if not u:
        raise HTTPException(404)
    if body.is_active is not None:
        u.is_active = body.is_active
    if body.password:
        u.password_hash = hash_password(body.password)
    if body.display_name is not None:
        u.display_name = body.display_name
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
        for p in db.query(Position).filter_by(user_id=uid, is_closed=False).all():
            try:
                engine.place_order(db, u, p.token, "SELL" if p.qty > 0 else "BUY", abs(p.qty) // p.lot_size)
                done += 1
            except EngineError as e:
                errors.append(f"{p.symbol}: {e}")
    return {"closed": done, "errors": errors}


@app.get("/api/admin/settings")
def admin_settings(admin: User = Depends(current_admin), db: Session = Depends(get_db)):
    on, spread, stale = engine.liquidity_settings(db)
    return {"margin_pct": {ex: engine.margin_pct(db, ex) for ex in ("NFO", "BFO", "MCX", "STK")},
            "commission_pct": engine.commission_pct(db),
            "liquidity_check": on, "max_spread_pct": spread, "stale_minutes": stale,
            "feed": feed.status(), "enforce_market_hours": config.ENFORCE_MARKET_HOURS,
            "underlyings": [u for u in config.ALLOWED_UNDERLYINGS if u != "STOCKS"], "stock_fno": config.ALLOW_STOCK_FNO}


class SettingsIn(BaseModel):
    margin_pct: dict
    commission_pct: Optional[float] = None
    liquidity_check: Optional[bool] = None
    max_spread_pct: Optional[float] = None
    stale_minutes: Optional[int] = None


@app.post("/api/admin/settings")
def admin_set_settings(body: SettingsIn, admin: User = Depends(current_admin), db: Session = Depends(get_db)):
    for ex, v in body.margin_pct.items():
        set_setting(db, f"margin_pct_{ex}", str(float(v)))
    if body.commission_pct is not None:
        set_setting(db, "commission_pct", str(max(0.0, float(body.commission_pct))))
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
    for u in db.query(User).filter_by(is_admin=False).all():
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
    q = db.query(User).filter_by(is_admin=False)
    if user_id:
        q = q.filter_by(id=user_id)
    return build_report(db, q.order_by(User.id).all(), from_, to)


@app.get("/api/report")
def my_report(from_: Optional[str] = Query(None, alias="from"), to: Optional[str] = None,
              user: User = Depends(current_user), db: Session = Depends(get_db)):
    return build_report(db, [user], from_, to)


def build_xlsx(db: Session, users: List[User], from_: Optional[str], to: Optional[str], only: Optional[str] = None) -> bytes:
    """only: None = everything; 'orderbook' | 'pnl' | 'ledger' = one standalone statement.
    (Legacy comma lists like 'orders,trades' are mapped onto these.)"""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter
    if only:
        o = only.lower()
        only = "orderbook" if "order" in o else "ledger" if "ledger" in o else "pnl"
    rep = build_report(db, users, from_, to)
    start, end, f, t = _range(from_, to)
    period = "All history" if not from_ else (rep["from"] if rep["from"] == rep["to"] else f"{rep['from']} to {rep['to']}")
    who = users[0].display_name if len(users) == 1 else f"All trainees ({len(users)})"
    gen = (datetime.utcnow() + IST).strftime("%d %b %Y, %H:%M IST")
    wb = Workbook()
    hdr_font = Font(bold=True, color="FFFFFF"); hdr_fill = PatternFill("solid", fgColor="365314")
    title_font = Font(bold=True, size=14, color="365314"); bold = Font(bold=True)
    tot_fill = PatternFill("solid", fgColor="ECFCCB")

    def sheet(title, headers, rows, money_cols=(), statement=None, totals=None):
        ws = wb.active if wb.active.title == "Sheet" else wb.create_sheet(title)
        ws.title = title
        top = 1
        if statement:
            ws.append([f"limeFX — {statement}"]); ws["A1"].font = title_font
            ws.append([f"Trainee: {who}", "", f"Period: {period}", "", f"Generated: {gen}"])
            for c in ws[2]: c.font = Font(color="6B7280")
            ws.append([]); top = 4
        ws.append(headers)
        for c in ws[top]:
            c.font = hdr_font; c.fill = hdr_fill; c.alignment = Alignment(horizontal="center")
        for r in rows:
            ws.append(r)
        if totals:
            ws.append(totals)
            for c in ws[ws.max_row]: c.font = bold; c.fill = tot_fill
        for i, h in enumerate(headers, 1):
            ws.column_dimensions[get_column_letter(i)].width = max(12, min(44, len(str(h)) + 6))
            if i in money_cols:
                for cell in ws.iter_rows(min_row=top + 1, min_col=i, max_col=i):
                    cell[0].number_format = '#,##0.00'
        ws.freeze_panes = f"A{top + 1}"
        return ws

    uid2name = {u.id: u.display_name for u in users}
    ids = [u.id for u in users]
    many = len(users) != 1
    tcol = ["Trainee"] if many else []
    tval = (lambda uid: [uid2name.get(uid, "")]) if many else (lambda uid: [])
    sh = lambda n: n + (1 if many else 0)   # column shift when the Trainee column is present

    # ---- Order book statement -------------------------------------------------------------
    if only in (None, "orderbook"):
        orders = db.query(Order).filter(Order.user_id.in_(ids), Order.created_at >= start, Order.created_at < end).order_by(Order.created_at).all()
        filled = sum(1 for o in orders if o.status == "FILLED"); rej = sum(1 for o in orders if o.status == "REJECTED")
        sheet("Order Book", ["Date", "Time (IST)"] + tcol + ["Contract", "Side", "Type", "Lots", "Qty", "Limit price", "Trigger", "Status", "Fill price", "Note"],
              [[_ist_date(o.created_at), (o.created_at + IST).strftime("%H:%M:%S")] + tval(o.user_id) + [o.symbol, o.side, o.order_type,
                o.lots, o.qty, o.limit_price, o.trigger_price, o.status, o.fill_price, o.reason] for o in orders],
              money_cols=(sh(8), sh(9), sh(11)), statement="Order Book Statement",
              totals=[f"{len(orders)} orders", f"{filled} filled, {rej} rejected"] + [""] * (sh(11) - 1))
    # ---- P&L statement -----------------------------------------------------------------------
    if only in (None, "pnl"):
        trades = db.query(Trade).filter(Trade.user_id.in_(ids), Trade.created_at >= start, Trade.created_at < end).order_by(Trade.created_at).all()
        cm = round(sum(x.commission or 0 for x in trades), 2)
        net = round(sum(x.realised_pnl or 0 for x in trades) - cm, 2)
        gp = round(sum(x.realised_pnl for x in trades if (x.realised_pnl or 0) > 0), 2)
        gl = round(sum(x.realised_pnl for x in trades if (x.realised_pnl or 0) < 0), 2)
        sheet("P&L Statement", ["Date", "Time (IST)"] + tcol + ["Contract", "Exchange", "Side", "Qty", "Price", "Value", "Commission", "Realised P&L", "Net"],
              [[_ist_date(x.created_at), (x.created_at + IST).strftime("%H:%M:%S")] + tval(x.user_id) + [x.symbol, x.exchange,
                x.side, x.qty, x.price, round(x.price * x.qty, 2), -(x.commission or 0), x.realised_pnl, round((x.realised_pnl or 0) - (x.commission or 0), 2)] for x in trades],
              money_cols=(sh(7), sh(8), sh(9), sh(10), sh(11)), statement="Profit & Loss Statement",
              totals=[f"{len(trades)} trades", f"Gross profit {gp:,.2f} / Gross loss {gl:,.2f}"] + [""] * (sh(6)) + [-cm, round(gp + gl, 2), net])
        days = sorted({d for u in rep["users"] for d in u["daily"]})
        cum = 0; rows = []
        for d in days:
            v = rep["daily"].get(d, 0); cum = round(cum + v, 2)
            rows.append([d] + ([u["daily"].get(d, 0) for u in rep["users"]] if many else []) + [v, cum])
        sheet("Daily P&L", ["Date"] + ([u["display_name"] for u in rep["users"]] if many else []) + ["Net P&L", "Cumulative"], rows,
              money_cols=tuple(range(2, (len(rep["users"]) if many else 0) + 4)), statement="Day-wise Profit & Loss")
        sheet("Summary", ["Trainee", "Username", "Trades", "Closing trades", "Wins", "Losses", "Win rate %", "Gross profit", "Gross loss",
                          "Commission paid", "Net P&L (period)", "Best trade", "Worst trade", "Avg win", "Avg loss", "Profit factor", "Coins allocated", "Equity now", "Overall P&L"],
              [[u["display_name"], u["username"], u["trades"], u["closing_trades"], u["wins"], u["losses"], u["win_rate"], u["gross_profit"], u["gross_loss"],
                -u["commission"], u["net_pnl"], u["best"], u["worst"], u["avg_win"], u["avg_loss"], u["profit_factor"], u["allocated"], u["equity"], u["overall_pnl"]] for u in rep["users"]],
              money_cols=(8, 9, 10, 11, 12, 13, 14, 15, 17, 18, 19), statement="Performance Summary")
    # ---- Ledger statement ------------------------------------------------------------------------
    if only in (None, "ledger"):
        kinds = {"ADMIN_CREDIT": "Coins added by master", "ADMIN_DEBIT": "Coins removed by master", "REALISED_PNL": "Realised P&L",
                 "EXPIRY_SETTLEMENT": "Expiry settlement", "LOT_SIZE_CORRECTION": "Lot size correction", "COMMISSION": "Commission"}
        led = db.query(Ledger).filter(Ledger.user_id.in_(ids), Ledger.created_at >= start, Ledger.created_at < end).order_by(Ledger.created_at).all()
        rows = []
        if not many:
            prev = db.query(Ledger).filter(Ledger.user_id == ids[0], Ledger.created_at < start).order_by(Ledger.created_at.desc()).first()
            rows.append([rep["from"] if from_ else "", "", "Opening balance", "", prev.balance_after if prev else 0, ""])
        rows += [[_ist_date(l.created_at), (l.created_at + IST).strftime("%H:%M:%S")] + tval(l.user_id) + [kinds.get(l.kind, l.kind),
                  l.amount, l.balance_after, l.note] for l in led]
        cr = round(sum(l.amount for l in led if l.kind == "ADMIN_CREDIT"), 2); dr = round(sum(l.amount for l in led if l.kind == "ADMIN_DEBIT"), 2)
        pnl = round(sum(l.amount for l in led if l.kind not in ("ADMIN_CREDIT", "ADMIN_DEBIT", "COMMISSION")), 2)
        cmm = round(sum(l.amount for l in led if l.kind == "COMMISSION"), 2)
        closing = led[-1].balance_after if (led and not many) else (rows[0][4] if rows and not many else None)
        sheet("Ledger", ["Date", "Time (IST)"] + tcol + ["Type", "Amount", "Balance after", "Note"], rows, money_cols=(sh(4), sh(5)),
              statement="Coin Ledger Statement",
              totals=[f"{len(led)} entries", f"Added {cr:,.0f} / Removed {dr:,.0f} / P&L {pnl:,.2f} / Commission {cmm:,.2f}"] + [""] * (sh(1)) + ["Closing balance" if not many else "", closing if not many else "", ""])
    buf = io.BytesIO(); wb.save(buf); return buf.getvalue()


def _stmt_tag(sheets: Optional[str]) -> str:
    if not sheets:
        return "AllStatements"
    s = sheets.lower()
    return "OrderBook" if "order" in s else "Ledger" if "ledger" in s else "PnL"


def _xlsx_response(data: bytes, name: str):
    return StreamingResponse(io.BytesIO(data), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.get("/api/admin/export.xlsx")
def admin_export(from_: Optional[str] = Query(None, alias="from"), to: Optional[str] = None, user_id: Optional[int] = None,
                 sheets: Optional[str] = None, admin: User = Depends(current_admin), db: Session = Depends(get_db)):
    q = db.query(User).filter_by(is_admin=False)
    if user_id:
        q = q.filter_by(id=user_id)
    users = q.order_by(User.id).all()
    rep_name = f"limefx_{(users[0].username if user_id and users else 'all')}_{_stmt_tag(sheets)}_{from_ or 'start'}_to_{to or 'today'}.xlsx"
    return _xlsx_response(build_xlsx(db, users, from_, to, sheets), rep_name)


@app.get("/api/export.xlsx")
def my_export(from_: Optional[str] = Query(None, alias="from"), to: Optional[str] = None, sheets: Optional[str] = None,
              user: User = Depends(current_user), db: Session = Depends(get_db)):
    return _xlsx_response(build_xlsx(db, [user], from_, to, sheets), f"limefx_{user.username}_{_stmt_tag(sheets)}_{from_ or 'start'}_to_{to or 'today'}.xlsx")


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
    return feed.status()
