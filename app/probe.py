"""Daily safety check: the site attacks itself.

Two hidden test accounts (never shown in any user list or total) go through the real API — the same
doors a user's phone uses — and try to cheat: nonsense numbers, cheap-margin orders, many orders at
the same instant, instant round trips for free money, touching each other's orders, trading a closed
market. Every attempt must be refused or must not make money. Then every real account's books are
checked. The result is stored for the Master panel and sent to Telegram.

Nothing here can touch a real account: the attacker only ever holds the two test accounts' sessions.
"""
import asyncio
import json
import logging
import math
import os
import secrets
import time
from datetime import datetime, timedelta

import httpx

from .auth import COOKIE, make_token
from .db import SessionLocal, User, Order, Position, Trade, Ledger, get_setting, set_setting

log = logging.getLogger("probe")
PREFIX = "zz-probe-"
RUN_AT = os.getenv("PT_PROBE_AT", "10:05,21:35")    # IST times, comma-separated: a live check at each slot
_SLOTS = [s.strip() for s in RUN_AT.split(",") if s.strip()] or ["10:05"]   # 10:05 catches Indian markets
# while they are open; 21:35 catches the US / Global ETF session, which is closed during the morning slot.
_running = asyncio.Lock()


def is_probe(username: str) -> bool:
    return (username or "").startswith(PREFIX)


def _ist() -> datetime:
    return datetime.utcnow() + timedelta(hours=5, minutes=30)


class Probe:
    def __init__(self, app, engine, feed):
        self.app, self.engine, self.feed = app, engine, feed
        self.rows = []          # {"area", "check", "ok", "info"}
        self.area = ""

    # ---- bookkeeping ---------------------------------------------------------------------
    def ok(self, check: str, passed: bool, info=""):
        self.rows.append({"area": self.area, "check": check, "ok": bool(passed), "info": str(info)[:220]})

    def note(self, check: str, info=""):
        self.rows.append({"area": self.area, "check": check, "ok": None, "info": str(info)[:220]})

    def _users(self, db):
        out = []
        for n in ("a", "b"):
            u = db.query(User).filter_by(username=PREFIX + n).first()
            if not u:
                # a password hash nothing can match: these accounts cannot be logged into from outside
                u = User(username=PREFIX + n, display_name="Safety check " + n.upper(), is_admin=False, is_active=True,
                         password_hash="!" + secrets.token_hex(24), balance=0.0)
                db.add(u); db.commit()
            out.append(u)
        return out

    async def _wipe(self, balances=(1_000_000.0, 1_000_000.0)):
        """Start (and finish) from a clean slate: no orders, positions, trades or ledger on the test accounts."""
        async with self.engine._lock:
            db = SessionLocal()
            try:
                for u, bal in zip(self._users(db), balances):
                    for M in (Trade, Ledger, Order, Position):
                        db.query(M).filter_by(user_id=u.id).delete()
                    u.balance = bal; u.is_active = True; u.must_change_password = False; u.pw_changed_at = 0.0
                    set_setting(db, f"access_{u.id}", "")        # a segment the check switched off on its own account
                db.commit()
            finally:
                db.close()

    async def _set_balance(self, uid: int, bal: float):
        async with self.engine._lock:
            db = SessionLocal()
            try:
                db.get(User, uid).balance = round(bal, 2); db.commit()
            finally:
                db.close()

    async def _set_active(self, uid: int, active: bool):
        async with self.engine._lock:
            db = SessionLocal()
            try:
                db.get(User, uid).is_active = bool(active); db.commit()
            finally:
                db.close()

    async def _set_access(self, uid: int, off_key: str = ""):
        """Switch one trading-access segment off on a TEST account (or all back on). Real accounts are set
        by the Master only; this writes nothing but the test account's own switch."""
        async with self.engine._lock:
            db = SessionLocal()
            try:
                set_setting(db, f"access_{uid}", json.dumps({off_key: False}) if off_key else ""); db.commit()
            finally:
                db.close()

    def _client(self, user=None):
        cookies = {COOKIE: make_token(user)} if user else None
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://localhost",
                                 cookies=cookies, timeout=30)

    # ---- small helpers over the real API ---------------------------------------------------
    async def _order(self, c, **body):
        r = await c.post("/api/orders", json=body)
        try:
            j = r.json()
        except Exception:
            j = {}
        return r.status_code, (j.get("order") or {}), str(j.get("detail", ""))[:140]

    async def _raw(self, c, body: str):
        r = await c.post("/api/orders", content=body, headers={"content-type": "application/json"})
        return r.status_code

    async def _funds(self, c):
        r = await c.get("/api/me")
        return r.json()["funds"] if r.status_code == 200 else None

    async def _orders(self, c):
        r = await c.get("/api/orders")
        return r.json() if r.status_code == 200 else None

    async def _positions(self, c):
        r = await c.get("/api/positions")
        return [p for p in r.json() if p["qty"]] if r.status_code == 200 else None

    async def _flatten(self, c):
        for o in (await self._orders(c)) or []:
            if o["status"] == "OPEN":
                await c.delete(f"/api/orders/{o['id']}")
        for p in (await self._positions(c)) or []:
            await c.post(f"/api/positions/{p['id']}/close")

    async def _wait_order(self, c, oid, secs=7.0):
        t0 = time.time()
        while time.time() - t0 < secs:
            o = next((x for x in (await self._orders(c)) or [] if x["id"] == oid), None)
            if o and o["status"] != "OPEN":
                return o
            await asyncio.sleep(0.5)
        return next((x for x in (await self._orders(c)) or [] if x["id"] == oid), None)

    def _quote(self, token):
        t = self.feed.prices.get(token) or {}
        return t.get("bid"), t.get("ask"), t.get("ltp")

    # ---- which contracts to attack ---------------------------------------------------------
    def _targets(self):
        ins_all = list(self.feed.instruments.values())
        today = _ist().date().isoformat()

        def nearest(exchange, names):
            """Candidates, best first: the nearest three expiries of each name. The run takes the first one
            that actually has a live two-sided price, so a dead weekly contract (seen on USDINR) cannot
            leave a whole market unattacked."""
            out = []
            for nm in names:
                c = [i for i in ins_all if i.exchange == exchange and i.instrument_type == "FUT" and i.name == nm
                     and (not i.expiry or i.expiry >= today)]
                out += sorted(c, key=lambda i: i.expiry or "")[:3]
            return out

        def sym(exchange, symbol):
            return next((i for i in ins_all if i.exchange == exchange and i.symbol == symbol), None)

        cry = next((i for i in ins_all if i.exchange == "CRYPTO" and i.instrument_type == "FUT" and i.symbol.startswith("BTC")), None)
        # one full attack run per market we offer, so no market is left unchecked
        return [("NSE", nearest("NFO", ["NIFTY", "BANKNIFTY"])), ("BSE", nearest("BFO", ["SENSEX", "BANKEX"])),
                ("MCX", nearest("MCX", ["CRUDEOILM", "GOLDM", "SILVERM", "NATGASMINI"])),
                ("Currency", nearest("CDS", ["USDINR", "EURINR", "GBPINR"])),
                ("Crypto", cry), ("Forex", sym("FOREX", "EURUSD")), ("Global", sym("FOREX", "US500"))]

    async def _pick(self, cands):
        """First candidate with a live two-sided price; the first one if the market is shut or none has."""
        cands = [c for c in (cands or []) if c]
        if not cands:
            return None
        first = cands[0]
        if len(cands) == 1 or not self._feed_up(first) or not self.engine.tradable_now(first):
            return first
        self.feed.pin([c.token for c in cands])
        for _ in range(32):
            for c in cands:
                bid, ask, ltp = self._quote(c.token)
                if bid and ask and ltp:
                    return c
            await asyncio.sleep(0.25)
        return first

    def _feed_up(self, ins) -> bool:
        if ins.exchange == "CRYPTO":
            c = getattr(self.feed, "crypto", None); return bool(c and c.connected)
        if ins.exchange == "FOREX":
            f = getattr(self.feed, "forex", None); return bool(f and f.connected)
        return bool(self.feed.connected)

    # ---- the attacks -----------------------------------------------------------------------
    async def _bought_option(self, ua):
        """A bought option's premium is fully paid up front, so a dip in its price must NOT get it squared
        off. Buy one with almost every coin the account has, and expect it to be left alone."""
        self.area = "Bought option"
        today = _ist().strftime("%Y-%m-%d")
        pick = None
        for exchange, name in (("NFO", "NIFTY"), ("BFO", "SENSEX"), ("CRYPTO", "BTC")):
            opts = [i for i in self.feed.instruments.values() if i.exchange == exchange and i.name == name
                    and i.instrument_type == "CE" and i.expiry and i.expiry >= today]
            st = self.feed.index_token_for(name)
            spot = (self.feed.prices.get(st) or {}).get("ltp") if st else None
            if not opts or not spot or not self._feed_up(opts[0]) or not self.engine.tradable_now(opts[0]):
                continue
            exps = sorted({i.expiry for i in opts})
            exp = exps[1] if len(exps) > 1 and exps[0] == today else exps[0]
            cand = sorted([i for i in opts if i.expiry == exp], key=lambda i: abs(i.strike - spot))[:6]
            self.feed.subscribe([i.token for i in cand])
            for _ in range(16):
                await asyncio.sleep(0.25)
                live = [i for i in cand if all(self._quote(i.token))]
                if live:
                    pick = live[0]; break
            if pick:
                break
        if not pick:
            self.note("not tested", "no option with a live two-sided price in an open market"); return
        ca = self._client(ua)
        try:
            await self._flatten(ca); await self._set_balance(ua.id, 1_000_000.0)
            st, o, d = await self._order(ca, token=pick.token, side="BUY", lots=1)
            o = await self._wait_order(ca, o["id"]) if st == 200 else None
            pos = [p for p in (await self._positions(ca)) or [] if p["token"] == pick.token]
            if not (o and o.get("status") == "FILLED" and pos):
                self.note("not tested", f"could not buy {pick.symbol} ({d or (o or {}).get('reason', '')})"[:150]); return
            f = await self._funds(ca)
            await self._set_balance(ua.id, round(f["used_margin"] + 1.0, 2))      # every coin is in the option
            low, short = 0.0, False
            for _ in range(16):                                                  # 8 s > two square-off passes
                await asyncio.sleep(0.5)
                f2 = await self._funds(ca)
                low = min(low, f2["unrealised"]); short = short or bool(f2.get("margin_short")) or f2["available"] < 0
            pos = [p for p in (await self._positions(ca)) or [] if p["token"] == pick.token]
            self.ok("a bought option is not squared off when its price dips (the premium is already paid)",
                    bool(pos) and not short,
                    f"{pick.symbol}: lowest running P&L ₹{low:,.0f}{'' if low < 0 else ' (no dip during the test)'}, "
                    f"Available Balance ₹{f2['available']:,.2f}, position {'kept' if pos else 'CLOSED'}")
        finally:
            try:
                await self._flatten(ca)
            except Exception:
                pass
            await self._set_balance(ua.id, 1_000_000.0)
            await ca.aclose()

    async def _shortfall(self, label, ins, ua):
        """Nobody may carry more than their coins cover. Open a position on the test account, then take its
        coins away so that its Available Balance is below zero, and expect the system to square it off."""
        self.area = label
        if not self._feed_up(ins) or not self.engine.tradable_now(ins):
            return
        bid, ask, ltp = self._quote(ins.token)
        if not (bid and ask and ltp):
            return
        db = SessionLocal()
        try:
            strict = datetime.utcnow() >= self.engine.strict_from(db)
        finally:
            db.close()
        if not strict:
            self.note("margin shortfall not tested", "the auto square-off rule is still in its one-time warning period"); return
        ca = self._client(ua)
        try:
            await self._flatten(ca); await self._set_balance(ua.id, 1_000_000.0)
            st, o, d = await self._order(ca, token=ins.token, side="BUY", lots=2)
            if st != 200:
                st, o, d = await self._order(ca, token=ins.token, side="BUY", lots=1)
            o = await self._wait_order(ca, o["id"]) if st == 200 else None
            pos = [p for p in (await self._positions(ca)) or [] if p["token"] == ins.token]
            if not (o and o.get("status") == "FILLED" and pos):
                self.note("margin shortfall not tested", f"could not open a test position ({d or (o or {}).get('reason', '')})"[:150]); return
            lots0 = abs(pos[0]["qty"]) // ins.lot_size
            f = await self._funds(ca)
            await self._set_balance(ua.id, round(f["used_margin"] * 0.97, 2))        # coins no longer cover the margin
            f1 = await self._funds(ca)
            st, _, d = await self._order(ca, token=ins.token, side="BUY", lots=1)
            self.ok("short of margin: a new order is refused", st == 400, d)
            lots1, f2 = lots0, f1
            for _ in range(30):
                await asyncio.sleep(0.5)
                pos = [p for p in (await self._positions(ca)) or [] if p["token"] == ins.token]
                lots1 = abs(pos[0]["qty"]) // ins.lot_size if pos else 0
                f2 = await self._funds(ca)
                if lots1 < lots0 and f2["available"] >= 0:
                    break
            self.ok("carrying more than your coins cover is squared off automatically (Available Balance back above zero)",
                    lots1 < lots0 and f2["available"] >= 0,
                    f"Available Balance ₹{f1['available']:,.0f} → ₹{f2['available']:,.0f}; {lots0} lot(s) → {lots1}")
            if lots0 >= 2:
                self.ok("only as many lots as needed are squared off", lots1 == lots0 - 1, f"{lots0} lots → {lots1}")
        finally:
            try:
                await self._flatten(ca)
            except Exception:
                pass
            await self._set_balance(ua.id, 1_000_000.0)
            await ca.aclose()

    async def _frozen(self, label, ins, ua):
        """A contract nobody is looking at stops receiving prices; its last one stays in memory, frozen.
        An order must never be filled at such a price (look, stop looking, wait for the market to move,
        then trade at the old price — the loophole of 13 Nov 2026). Take a contract nobody is streaming,
        look at it once, plant a recognisable price in its frozen book and send an order: it must be
        refused or filled at a newly streamed price, never at the planted one."""
        self.area = label
        if not self._feed_up(ins) or not self.engine.tradable_now(ins):
            return
        feed = self.feed
        today = _ist().date().isoformat()
        if ins.exchange == "CRYPTO":
            cand = [i for i in feed.instruments.values() if i.exchange == "CRYPTO" and i.instrument_type in ("CE", "PE")
                    and i.expiry and i.expiry >= today]
            spot = feed.ltp(feed.index_token_for(ins.name) or -1) or 0
            cand.sort(key=lambda i: (i.name != ins.name, i.expiry, abs(i.strike - spot)))
        else:
            cand = [i for i in feed.instruments.values() if i.exchange == ins.exchange and i.segment == ins.segment
                    and i.instrument_type == "FUT" and (not i.expiry or i.expiry >= today)]
            cand.sort(key=lambda i: (i.expiry or "", i.symbol))
        cand = [i for i in cand if i.token != ins.token and i.token not in feed._refcount and self.engine.tradable_now(i)][:4]
        if not cand:
            self.note("frozen-price order not tested", "every contract of this market is being streamed all the time"); return
        ca = self._client(ua)
        try:
            await self._flatten(ca); await self._set_balance(ua.id, 1_000_000.0)
            why = "no contract with a two-sided price that nobody else is streaming"
            for c in cand:
                T = c.token
                feed.subscribe([T])                              # look at it once ...
                try:
                    for _ in range(20):
                        t = feed.prices.get(T) or {}
                        if feed.live(T) and t.get("asks") and t.get("bid") and t.get("ask"):
                            break
                        await asyncio.sleep(0.25)
                finally:
                    feed.unsubscribe([T])                        # ... and stop looking: the price is now frozen
                real = feed.prices.get(T)
                if T in feed._refcount or not real or not (real.get("asks") and real.get("bid") and real.get("ask")):
                    continue
                trap = round(real["ask"] * 1.0137, 6)            # worse for the buyer, so nobody could ever gain from it
                planted = dict(real)
                planted.update({"ask": trap, "asks": [(trap,) + tuple(real["asks"][0][1:])]})
                feed.prices[T] = planted
                try:
                    st, o, d = await self._order(ca, token=T, side="BUY", lots=1)
                finally:
                    if feed.prices.get(T) is planted:
                        feed.prices[T] = real
                if st == 200 and o.get("status") == "FILLED":
                    hit = abs((o.get("fill_price") or 0) - trap) < 1e-9
                    self.ok("an order on a contract nobody is streaming waits for a live price (never fills at the frozen one)", not hit,
                            f"{c.symbol}: frozen book said {trap}, filled {o.get('fill_price')}")
                    return
                if st == 400 and "live price" in d:
                    self.ok("an order on a contract nobody is streaming waits for a live price (never fills at the frozen one)", True,
                            f"{c.symbol}: refused until a new price arrives")
                    return
                why = f"{c.symbol}: {d or o.get('reason') or 'no fill'}"
            self.note("frozen-price order not tested", why[:160])
        finally:
            try:
                await self._flatten(ca)
            except Exception:
                pass
            await ca.aclose()

    async def _resting_rules(self, label, ins, ub):
        """The rules an order is checked against when it is placed must still hold when it fills later
        (loopholes of 15 Nov 2026). Two cases, on the test account only:
        1. Trading access. In a segment that is switched off a position may only be reduced. A resting exit
           is accepted because it is no bigger than the position; when the position is then reduced, the
           exit is bigger than what is left. It must close the rest and no more, never open a position the
           other way round (holding 3 lots, exits of 2 and 3 lots used to leave the account 2 lots short).
        2. Frozen account. A resting order of an account that was frozen in the meantime must open nothing."""
        self.area = label
        if not self._feed_up(ins) or not self.engine.tradable_now(ins):
            return
        T = ins.token
        bid, ask, ltp = self._quote(T)
        if not (bid and ask and ltp):
            return
        from . import access as _access
        key = _access.key_for(ins)
        band = float(ins.price_band_pct or 0)
        cb = self._client(ub)
        try:
            await self._flatten(cb); await self._set_balance(ub.id, 5_000_000.0)
            # 1. an exit that has become bigger than the position, in a switched-off segment
            st, o, d = await self._order(cb, token=T, side="BUY", lots=2)
            if not key or not (st == 200 and o.get("status") == "FILLED" and o.get("lots") == 2):
                self.note("switched-off segment not tested", f"could not open a 2-lot test position ({d or o.get('reason', '')})"[:150])
            else:
                await self._set_access(ub.id, key)
                st, _, d = await self._order(cb, token=T, side="BUY", lots=1)
                self.ok("segment switched off: adding to a position is refused", st == 400, d)
                bid = self._quote(T)[0] or bid
                lo = bid * (0.01 if not band else 1 - band / 100 * 0.9)
                # the exit of 2 lots rests until the next price; one lot is sold at market before that
                s1, o1, d1 = await self._order(cb, token=T, side="SELL", lots=2, order_type="LIMIT", limit_price=round(lo, 6))
                s2, o2, d2 = await self._order(cb, token=T, side="SELL", lots=1)
                done = await self._wait_order(cb, o1["id"]) if s1 == 200 else None
                pos = [p for p in (await self._positions(cb)) or [] if p["token"] == T]
                short = [p for p in pos if p["qty"] < 0]
                fair = (s1 == 200 and s2 == 200 and o2.get("status") == "FILLED" and done and done["status"] in ("FILLED", "CANCELLED", "REJECTED")
                        and done["updated_at"] >= o2["updated_at"])
                if fair:
                    self.ok("segment switched off: an exit that has become bigger than the position only closes it, never opens one the other way",
                            not short, f"now holding {short[0]['qty']}" if short else f"exit order ended {done['status']} for {done['lots']} lot(s)")
                else:
                    self.note("oversized exit inconclusive", "the exit filled before the position could be reduced, or no price tick arrived within 7 s")
                await self._set_access(ub.id)
            await self._flatten(cb)
            # 2. a frozen account's resting order
            ask = self._quote(T)[1] or ask
            hi = ask * (3 if not band else 1 + band / 100 * 0.9)
            st, o, d = await self._order(cb, token=T, side="BUY", lots=1, order_type="LIMIT", limit_price=round(hi, 6))
            if st == 200 and o.get("status") == "OPEN":
                await self._set_active(ub.id, False)
                frozen_at = datetime.utcnow()
                status, held, when = "OPEN", 0, None
                for _ in range(14):
                    db = SessionLocal()
                    try:
                        row = db.get(Order, o["id"])
                        status, when = row.status, row.updated_at
                        held = sum(p.qty for p in db.query(Position).filter_by(user_id=ub.id, token=T, is_closed=False).all())
                    finally:
                        db.close()
                    if status != "OPEN":
                        break
                    await asyncio.sleep(0.5)
                await self._set_active(ub.id, True)
                if status == "OPEN" or (status == "FILLED" and when and when <= frozen_at):
                    self.note("frozen-account order inconclusive", "the order filled before the account was frozen, or no price tick arrived within 7 s")
                else:
                    self.ok("a frozen account's resting order opens nothing", status == "CANCELLED" and not held,
                            f"order {status}" + (f", now holding {held}" if held else ""))
            else:
                self.note("frozen-account order not tested", (d or o.get("reason", "") or "the order did not rest")[:150])
        finally:
            await self._set_access(ub.id); await self._set_active(ub.id, True)
            try:
                await self._flatten(cb)
            except Exception:
                pass
            await self._set_balance(ub.id, 1_000_000.0)
            await cb.aclose()

    async def _stream_flood(self, ub):
        """Orders on many contracts nobody is watching. Every such order makes the site stream the contract
        (it needs a live price), even when the order is nonsense and is refused. Without a limit one account
        could fill the price socket in seconds, and it stayed full: nobody else's contracts got prices."""
        self.area = "Price socket"
        try:
            from .main import ORDER_STREAM_LIMIT as limit
        except Exception:
            limit = 25
        if not self.feed.connected:
            self.note("skipped", "main price feed is not connected"); return
        today = _ist().date().isoformat()
        quiet = [i for i in self.feed.instruments.values()
                 if i.exchange in ("NFO", "BFO", "MCX", "CDS") and i.instrument_type in ("CE", "PE") and (i.expiry or "") > today
                 and i.token not in self.feed._refcount and i.token < 5_000_000_000]
        quiet.sort(key=lambda i: (i.expiry, i.symbol), reverse=True)        # far months first: nobody is there
        n = limit + 15
        if len(quiet) < n:
            self.note("skipped", "not enough unwatched contracts to try it"); return
        toks = [i.token for i in quiet[:n]]
        clients = [self._client(ub) for _ in range(n)]
        try:
            res = await asyncio.gather(*[c.post("/api/orders", json={"token": t, "side": "BUY", "lots": 0}) for c, t in zip(clients, toks)],
                                       return_exceptions=True)
        finally:
            for c in clients:
                await c.aclose()
        codes = [r.status_code for r in res if not isinstance(r, Exception)]
        streamed = sum(1 for t in toks if t in self.feed._refcount)
        self.ok(f"{n} junk orders on {n} unwatched contracts: at most {limit} of them start streaming", streamed <= limit + 2 and 200 not in codes,
                f"{streamed} streaming, {codes.count(429)} orders told to slow down")
        await asyncio.sleep(33)
        still = sum(1 for t in toks if t in self.feed._refcount)
        self.ok("those streams are dropped again after half a minute (the socket does not fill up for good)", still <= 2, f"{still} still streaming")

    async def _old_login(self, ub):
        """A new password must end every older login (found 13 Nov 2026: a login kept working for a month
        after the Master reset the password). The test account's own session is used: mark its password as
        changed just now and the session opened before that must be turned away."""
        self.area = "Logins"
        c = self._client(ub)
        try:
            r1 = await c.get("/api/me")
            async with self.engine._lock:
                db = SessionLocal()
                try:
                    db.get(User, ub.id).pw_changed_at = time.time() + 60; db.commit()
                finally:
                    db.close()
            r2 = await c.get("/api/me")
            r3 = await c.post("/api/orders", json={"token": 1, "side": "BUY", "lots": 1})
            self.ok("a login made before the password was changed stops working", r1.status_code == 200 and r2.status_code == 401 and r3.status_code == 401,
                    f"before {r1.status_code}, after {r2.status_code}/{r3.status_code}")
        finally:
            async with self.engine._lock:
                db = SessionLocal()
                try:
                    db.get(User, ub.id).pw_changed_at = 0.0; db.commit()
                finally:
                    db.close()
            await c.aclose()

    async def _attack(self, label, ins, ua, ub):
        self.area = label
        T = ins.token
        ca, cb, anon = self._client(ua), self._client(ub), self._client()
        try:
            if not self._feed_up(ins):
                self.note("skipped", "price feed for this market is not connected"); return
            if not self.engine.tradable_now(ins):
                st, _, d = await self._order(ca, token=T, side="BUY", lots=1)
                self.ok("market is closed: order refused", st == 400, d)
                st, _, d = await self._order(ca, token=T, side="BUY", lots=1, order_type="LIMIT", limit_price=1)
                self.ok("market is closed: limit order refused", st == 400, d)
                return
            # make sure there is a live price
            self.feed.pin([T])
            for _ in range(40):
                bid, ask, ltp = self._quote(T)
                if bid and ask and ltp:
                    break
                await asyncio.sleep(0.25)
            if not (bid and ask and ltp):
                self.note("skipped", f"no live two-sided price for {ins.symbol}"); return
            self.note("contract", f"{ins.symbol} bid {bid} ask {ask}")
            age = self.feed.tick_age(T) or 0
            self.ok("price is fresh (last update under 5 minutes old)", age < 300, f"{int(age)} s old")
            self.ok("price is sane: bid below ask, last price near them", 0 < bid <= ask and bid * 0.97 <= ltp <= ask * 1.03, f"bid {bid} ask {ask} last {ltp}")
            await self._set_balance(ua.id, 1_000_000.0)

            # 1. nonsense numbers ------------------------------------------------------------
            before = len((await self._orders(ca)) or [])
            bad = 0
            for lots in (0, -1, 10 ** 9):
                st, _, _ = await self._order(ca, token=T, side="BUY", lots=lots); bad += st not in (400, 422)
            for body in ('{"token":%d,"side":"BUY","lots":1.5}', '{"token":%d,"side":"BUY","lots":NaN}',
                         '{"token":%d,"side":"BUY","lots":1,"order_type":"LIMIT","limit_price":NaN}',
                         '{"token":%d,"side":"BUY","lots":1,"order_type":"LIMIT","limit_price":Infinity}',
                         '{"token":%d,"side":"BUY","lots":1,"order_type":"LIMIT","limit_price":-5}',
                         '{"token":%d,"side":"SELL","lots":1,"order_type":"SL","trigger_price":NaN}',
                         '{"token":%d,"side":"BUY","lots":1,"leverage":NaN}',
                         '{"token":%d,"side":"HOLD","lots":1}', '{"token":%d,"side":"BUY","lots":1,"order_type":"FOK"}'):
                st = await self._raw(ca, body % T); bad += st not in (400, 422)
            f = await self._funds(ca)
            after = [o for o in (await self._orders(ca)) or [] if o["status"] in ("OPEN", "FILLED")]
            self.ok("12 nonsense orders (zero, negative, fraction, not-a-number, infinite) all refused", bad == 0 and f is not None and len(after) <= before,
                    f"{bad} got through" if bad else "")
            if ins.leverage_options:
                mx = max(ins.leverage_options); n = 0
                for lv in (0, -5, 0.5, mx * 2 + 1, 1e9):
                    st, _, _ = await self._order(ca, token=T, side="BUY", lots=1, leverage=lv); n += st != 400
                self.ok(f"leverage outside 1–{mx:g}x refused", n == 0)
            if ins.exchange in ("CRYPTO", "FOREX"):
                st, _, _ = await self._order(ca, token=T, side="BUY", lots=1, product="MIS")
                self.ok("intraday product on a 24-hour market refused", st == 400)
            st, _, _ = await self._order(ca, token=T, side="SELL", lots=1, order_type="SL", trigger_price=round(ask * 1.02, 6))
            st2, _, _ = await self._order(ca, token=T, side="BUY", lots=1, order_type="SL", trigger_price=round(bid * 0.98, 6))
            self.ok("stop-loss on the wrong side of the market refused", st == 400 and st2 == 400)
            await self._flatten(ca)

            # 2. doors that must be shut -----------------------------------------------------
            r = await anon.post("/api/orders", json={"token": T, "side": "BUY", "lots": 1})
            self.ok("order without login refused", r.status_code in (401, 403))
            r1 = await ca.get("/api/admin/backup/offsite"); r2 = await ca.post("/api/admin/probe/run")
            self.ok("user cannot open Master functions", r1.status_code in (401, 403) and r2.status_code in (401, 403))

            m = (await ca.get("/api/margin", params={"token": T, "side": "BUY", "lots": 1})).json()
            m1 = float(m.get("full_margin") or 0); comm1 = float(m.get("commission") or 0)
            if m1 <= 0 or not math.isfinite(m1):
                self.ok("margin for one lot is a real number", False, m1); return
            if m1 + comm1 > 900_000:
                self.note("skipped trading attacks", f"one lot needs ₹{m1:,.0f}, more than the test account holds"); return

            # 3. free money? instant round trips ---------------------------------------------
            f0 = await self._funds(ca); fills = 0
            db = SessionLocal()
            try:
                tmax = max([t.id for t in db.query(Trade).filter_by(user_id=ua.id).all()] or [0])
            finally:
                db.close()
            for _ in range(3):
                s1, o1, _ = await self._order(ca, token=T, side="BUY", lots=1)
                s2, o2, _ = await self._order(ca, token=T, side="SELL", lots=1)
                fills += (s1 == 200 and o1.get("status") == "FILLED") + (s2 == 200 and o2.get("status") == "FILLED")
            await self._flatten(ca)
            f1 = await self._funds(ca)
            if fills:
                gain = f1["balance"] - f0["balance"]
                notional = ltp * ins.lot_size * (self.engine.vf(ins) or 1.0)
                self.ok("3 instant round trips do not make money", gain <= notional * 0.0015, f"result ₹{gain:,.2f}")
                db = SessionLocal()
                try:
                    tr = db.query(Trade).filter(Trade.user_id == ua.id, Trade.id > tmax).all()
                    books = sum((t.realised_pnl or 0) - (t.commission or 0) for t in tr)
                    led = db.query(Ledger).filter_by(user_id=ua.id).order_by(Ledger.id.desc()).first()
                    self.ok("trades (P&L − commission) equal the balance change", abs(books - gain) < 0.5,
                            f"trades ₹{books:,.2f} vs balance ₹{gain:,.2f}")
                    self.ok("last ledger line equals the balance", (led is None) or abs(led.balance_after - f1["balance"]) < 0.011)
                finally:
                    db.close()
            else:
                self.note("round trips skipped", "no fill (book empty right now)")

            # 4. price tricks -----------------------------------------------------------------
            band = float(ins.price_band_pct or 0)
            hi = ask * (3 if not band else 1 + band / 100 * 0.9)
            st, o, d = await self._order(ca, token=T, side="BUY", lots=1, order_type="LIMIT", limit_price=round(hi, 6))
            if st == 200:
                o = await self._wait_order(ca, o["id"])
                if o and o["status"] == "FILLED":
                    self.ok("buy limit far above the market fills at the market, not at my price", o["fill_price"] <= ask * 1.004, f"asked {hi:g}, filled {o['fill_price']}")
                    lo = bid * (0.01 if not band else 1 - band / 100 * 0.9)
                    st, o, d = await self._order(ca, token=T, side="SELL", lots=1, order_type="LIMIT", limit_price=round(lo, 6))
                    if st == 200:
                        o = await self._wait_order(ca, o["id"])
                        if o and o["status"] == "FILLED":
                            self.ok("sell limit far below the market fills at the market bid", o["fill_price"] >= bid * 0.996, f"asked {lo:g}, filled {o['fill_price']}")
                else:
                    self.note("limit-price trick inconclusive", "no price tick arrived within 7 s")
            await self._flatten(ca)

            # 5. cheap margin: tiny limit price, position far bigger than the account ----------
            max_lots = max(500, ins.pos_limit // max(ins.lot_size, 1)) if ins.pos_limit else 500
            if ins.pos_limit:
                max_lots = min(max_lots, ins.pos_limit // max(ins.lot_size, 1))
            lots = max(2, min(max_lots, 4))
            await self._set_balance(ub.id, round(m1 * 1.2 + comm1 * 2, 2))          # can afford one lot, never `lots`
            st, o, d = await self._order(cb, token=T, side="SELL", lots=lots)
            self.ok("market order bigger than the account can carry refused", st == 400, d)
            lo = bid * (0.01 if not band else 1 - band / 100 * 0.9)
            st, o, d = await self._order(cb, token=T, side="SELL", lots=lots, order_type="LIMIT", limit_price=round(lo, 6))
            if st == 200:
                o = await self._wait_order(cb, o["id"])
            pos = await self._positions(cb)
            self.ok("cheap-margin trick (tiny limit price, oversized position) opens nothing", not pos, (o or {}).get("reason") or d)
            await self._flatten(cb)

            # 6. many orders at the same instant ----------------------------------------------
            await self._set_balance(ub.id, round((m1 + comm1) * 3.5, 2))            # room for 3 lots
            clients = [self._client(ub) for _ in range(12)]
            try:
                res = await asyncio.gather(*[c.post("/api/orders", json={"token": T, "side": "BUY", "lots": 1}) for c in clients], return_exceptions=True)
            finally:
                for c in clients:
                    await c.aclose()
            filled = sum(1 for r in res if not isinstance(r, Exception) and r.status_code == 200 and r.json()["order"]["status"] == "FILLED")
            pos = await self._positions(cb); held = sum(abs(p["qty"]) // max(p["lot_size"], 1) for p in pos or [])
            fb = await self._funds(cb)
            self.ok("12 orders at the same instant: never more than the account can carry", held <= 3 and filled <= 3 and fb["used_margin"] <= fb["balance"] + m1 * 0.05,
                    f"{filled} filled, {12 - filled} refused")
            # 7. other people's things --------------------------------------------------------
            if pos:
                r = await ca.post(f"/api/positions/{pos[0]['id']}/close")
                self.ok("another account cannot close my position", r.status_code == 404)
            # 8. duplicates: the same tap sent many times ----------------------------------------
            if pos:
                clients = [self._client(ub) for _ in range(6)]
                try:
                    res = await asyncio.gather(*[c.post(f"/api/positions/{pos[0]['id']}/close") for c in clients], return_exceptions=True)
                finally:
                    for c in clients:
                        await c.aclose()
                okc = sum(1 for r in res if not isinstance(r, Exception) and r.status_code == 200)
                after = await self._positions(cb)
                was_long = pos[0]["qty"] > 0
                flipped = [p for p in after or [] if (p["qty"] > 0) != was_long]
                self.ok("Exit tapped 6 times at once closes the position once — never flips it the other way", okc <= 1 and not flipped,
                        f"{okc} exit went through" + (f", now holding {flipped[0]['qty']}" if flipped else ""))
            far = bid * (0.5 if not band else 1 - band / 100 * 0.6)
            await self._set_balance(ub.id, 1_000_000.0)
            st, o, d = await self._order(cb, token=T, side="BUY", lots=1, order_type="LIMIT", limit_price=round(far, 6))
            if st == 200 and o.get("status") == "OPEN":
                r = await ca.delete(f"/api/orders/{o['id']}")
                self.ok("another account cannot cancel my order", r.status_code == 400)
                clients = [self._client(ub) for _ in range(5)]
                try:
                    res = await asyncio.gather(*[c.delete(f"/api/orders/{o['id']}") for c in clients], return_exceptions=True)
                finally:
                    for c in clients:
                        await c.aclose()
                okc = sum(1 for r in res if not isinstance(r, Exception) and r.status_code == 200)
                fb = await self._funds(cb)
                self.ok("Cancel sent 5 times at once cancels once and frees the margin once", okc == 1 and abs(fb["used_margin"]) < 0.01 and abs(fb["balance"] - 1_000_000.0) < 0.01,
                        f"{okc} cancels accepted, margin held ₹{fb['used_margin']:,.2f}")
            await self._flatten(cb); await self._flatten(ca)
            # 9. the same exit resting twice (stop-loss and target, or a double tap on a limit exit) --------
            # Both become fillable on the same price tick. The first closes the position and cancels the
            # other; the cancelled one must not fill as well and open a position the other way round.
            st, o, d = await self._order(cb, token=T, side="BUY", lots=1)
            if st == 200 and o.get("status") == "FILLED":
                lo = bid * (0.01 if not band else 1 - band / 100 * 0.9)
                clients = [self._client(ub) for _ in range(2)]
                try:
                    res = await asyncio.gather(*[c.post("/api/orders", json={"token": T, "side": "SELL", "lots": 1, "order_type": "LIMIT",
                                                                             "limit_price": round(lo, 6)}) for c in clients], return_exceptions=True)
                finally:
                    for c in clients:
                        await c.aclose()
                ids = [r.json()["order"]["id"] for r in res if not isinstance(r, Exception) and r.status_code == 200]
                done = [await self._wait_order(cb, i) for i in ids]
                after = await self._positions(cb)
                short = [p for p in after or [] if p["token"] == T and p["qty"] < 0]
                # Only a fair test if both exits were resting together. If the first had already filled before
                # the second was even accepted (a price tick came in between), the second is simply a new
                # sell order on a flat account, which is allowed like any other new order.
                together = len(ids) == 2 and all(done) and all(
                    x["updated_at"] >= max(y["created_at"] for y in done) for x in done if x["status"] == "FILLED")
                if together and any(x["status"] == "FILLED" for x in done):
                    self.ok("the same limit exit resting twice closes the position once — never flips it the other way", not short,
                            f"now holding {short[0]['qty']}" if short else f"{sum(1 for x in done if x and x['status'] == 'FILLED')} filled")
                else:
                    self.note("double limit exit inconclusive", "the exits were not both resting at the same moment, or no price tick arrived within 7 s")
                await self._flatten(cb)
            left = ((await self._positions(ca)) or []) + ((await self._positions(cb)) or [])
            if left:
                self.note("test position could not be closed (no depth)", ", ".join(p["symbol"] for p in left))
        finally:
            for c in (ca, cb, anon):
                await c.aclose()

    # ---- thin (illiquid) contracts ---------------------------------------------------------------
    async def _illiquid(self, label, exchange, names, ua):
        """Buy more than the whole visible book of a thin far-out option, try to take the same sellers
        twice, then dump it. Must never fill beyond what is really offered, and must lose money."""
        self.area = label + " thin contract"
        today = _ist().date().isoformat()
        name, opts = names[0], []
        for nm in names:
            opts = [i for i in self.feed.instruments.values() if i.exchange == exchange and i.name == nm
                    and i.instrument_type in ("CE", "PE") and i.expiry and i.expiry >= today]
            if opts:
                name = nm; break
        ut = self.feed.index_token_for(name)
        if ut and opts and self.feed.ltp(ut) is None:
            self.feed.pin([ut])
            for _ in range(12):
                if self.feed.ltp(ut) is not None:
                    break
                await asyncio.sleep(0.25)
        spot = self.feed.ltp(ut) if ut else None
        if not opts or not spot:
            self.note("skipped", "no options or no underlying price"); return
        if not self.engine.tradable_now(opts[0]) or not self._feed_up(opts[0]):
            self.note("skipped", "market closed or feed off"); return
        exp = min(i.expiry for i in opts)
        cand = sorted([i for i in opts if i.expiry == exp and ((i.instrument_type == "CE" and i.strike >= spot * 1.025) or
                                                               (i.instrument_type == "PE" and i.strike <= spot * 0.975))],
                      key=lambda i: -abs(i.strike - spot))[:10]          # farthest first = thinnest
        watched = [i.token for i in cand]
        self.feed.subscribe(watched)
        await asyncio.sleep(4)
        pick = None
        for i in cand:
            t = self.feed.prices.get(i.token) or {}
            asks, bids = t.get("asks") or [], t.get("bids") or []
            if asks and bids and 0 < sum(a[0] * a[1] for a in asks) * (self.engine.vf(i) or 1) < 350_000:
                pick = (i, asks, bids); break
        if not pick:
            # Nothing two-sided among the far strikes of the nearest expiry (on Currency the weekly
            # contracts do not trade at all): widen to every out-of-the-money strike of the nearest
            # three expiries, still thinnest first.
            exps = sorted({i.expiry for i in opts})[:3]
            seen = set(watched)
            more = []
            for e in exps:                # per expiry: the 24 strikes nearest the money, where any trading is
                more += sorted([i for i in opts if i.expiry == e and i.token not in seen and
                                ((i.instrument_type == "CE" and i.strike > spot) or (i.instrument_type == "PE" and i.strike < spot))],
                               key=lambda i: abs(i.strike - spot))[:24]
            if more:
                self.feed.subscribe([i.token for i in more]); watched += [i.token for i in more]
                await asyncio.sleep(4)
                for i in sorted(more, key=lambda i: -abs(i.strike - spot)):
                    t = self.feed.prices.get(i.token) or {}
                    asks, bids = t.get("asks") or [], t.get("bids") or []
                    if asks and bids and 0 < sum(a[0] * a[1] for a in asks) * (self.engine.vf(i) or 1) < 350_000:
                        pick = (i, asks, bids); break
        ca = self._client(ua)
        try:
            nobid = next((i for i in cand if (self.feed.prices.get(i.token) or {}).get("ltp") and not ((self.feed.prices.get(i.token) or {}).get("bids"))), None)
            if nobid:
                st, o, d = await self._order(ca, token=nobid.token, side="SELL", lots=1)
                self.ok("selling into a contract with no buyers is refused", st == 400, d)
            if not pick:
                self.note("skipped depth attack", "no thin option with a two-sided book that the test account can buy out"); return
            ins, asks, bids = pick
            await self._set_balance(ua.id, 1_000_000.0)
            depth = sum(a[1] for a in asks); depth_lots = int(depth // ins.lot_size)
            from .config import FREEZE_QTY
            cap = 500
            fz = FREEZE_QTY.get(ins.name) if ins.exchange in ("NFO", "BFO") else None
            if fz:
                cap = min(cap, fz // ins.lot_size)
            want = max(1, min(depth_lots + 3, cap))
            self.note("contract", f"{ins.symbol}: {depth_lots} lots offered, best ask {asks[0][0]}, best bid {bids[0][0]}; trying to buy {want}")
            f0 = await self._funds(ca)
            # the book can tick between choosing the contract and the order: judge the fill against the
            # offers seen right before and right after it, not against the older snapshot
            asks = (self.feed.prices.get(ins.token) or {}).get("asks") or asks
            depth = sum(a[1] for a in asks); depth_lots = int(depth // ins.lot_size)
            st, o1, d = await self._order(ca, token=ins.token, side="BUY", lots=want)
            q1 = o1.get("qty", 0) if (st == 200 and o1.get("status") == "FILLED") else 0
            asks2 = (self.feed.prices.get(ins.token) or {}).get("asks") or []
            if q1:
                seen = [a[0] for a in asks] + [a[0] for a in asks2]
                self.ok("never fills more than the sellers really offered", q1 <= max(depth, sum(a[1] for a in asks2)) + 1e-6, f"filled {q1 // ins.lot_size} of {depth_lots} lots offered")
                self.ok("fills at the sellers' prices (not at the last traded price)", min(seen) - 1e-6 <= o1["fill_price"] <= max(seen) + 1e-6,
                        f"filled {o1['fill_price']}, asks {min(seen)}–{max(seen)}")
            st, o2, d2 = await self._order(ca, token=ins.token, side="BUY", lots=want)
            q2 = o2.get("qty", 0) if (st == 200 and o2.get("status") == "FILLED") else 0
            if want > depth_lots and q1 and [tuple(a[:2]) for a in asks2] == [tuple(a[:2]) for a in asks]:
                self.ok("the same sellers cannot be taken twice (repeat order gets nothing)", q2 == 0, f"second order filled {q2 // ins.lot_size} lots" if q2 else d2)
            elif q1:
                self.ok("two back-to-back orders together stay within what was offered", q1 + q2 <= depth + sum(a[1] for a in asks2) + 1e-6,
                        f"{(q1 + q2) // ins.lot_size} lots filled")
            for _ in range(3):
                await self._flatten(ca)
                if not [p for p in (await self._positions(ca)) or [] if p["token"] == ins.token]:
                    break
                await asyncio.sleep(1.5)
            left = [p for p in (await self._positions(ca)) or [] if p["token"] == ins.token]
            f1 = await self._funds(ca)
            if q1 and not left:
                self.ok("buying out a thin book and dumping it loses money", f1["balance"] <= f0["balance"] + 0.01, f"result ₹{f1['balance'] - f0['balance']:,.2f}")
            elif q1:
                self.ok("bought-out position is not valued above what buyers would pay", f1["equity"] <= f0["equity"] + 0.01,
                        f"stuck with {left[0]['qty']} (no buyers); equity change ₹{f1['equity'] - f0['equity']:,.2f}")
            else:
                self.note("depth attack inconclusive", d or "no fill")
        finally:
            await ca.aclose()
            try:
                self.feed.unsubscribe(watched)
            except Exception:
                pass
            await self._wipe()          # a position stuck without buyers must not colour the next test

    def _price_sanity(self):
        self.area = "Prices"
        bad, crossed, far, n = [], [], [], 0
        for tok, t in list(self.feed.prices.items()):
            ins = self.feed.instruments.get(tok)
            if not ins or not isinstance(t, dict) or t.get("ltp") is None:
                continue
            n += 1
            vals = [t.get(k) for k in ("ltp", "bid", "ask") if t.get(k) is not None]
            # Any negative or non-finite price is always a broken feed. A price of exactly zero is only
            # broken where zero is impossible — an index level or a future/spot last trade. A deep
            # out-of-the-money option (e.g. an 82 USDINR put when the rate is ~94) legitimately has a
            # premium and a one-sided book that round to zero; that is a worthless contract, not a feed
            # bug, and the thin-contract buy-out test already proves it cannot be used to make money.
            neg = any((not isinstance(v, (int, float))) or (not math.isfinite(v)) or v < 0 for v in vals)
            zero_bad = ins.segment != "INDICES" and ins.instrument_type not in ("CE", "PE") and any(v == 0 for v in vals)
            if neg or zero_bad:
                bad.append(ins.symbol); continue
            b, a = t.get("bid"), t.get("ask")
            if b and a and b > a * 1.0000001:
                crossed.append(f"{ins.symbol} {b}>{a}")
            if b and a and ins.instrument_type == "FUT" and not (b * 0.9 <= t["ltp"] <= a * 1.1):
                far.append(f"{ins.symbol} last {t['ltp']} vs {b}/{a}")
        self.ok(f"no zero, negative or broken price among {n} live contracts", not bad, ", ".join(bad[:8]))
        self.ok("no contract shows a bid above its ask", not crossed, "; ".join(crossed[:6]))
        self.ok("no future's last price is more than 10% away from its bid/ask", not far, "; ".join(far[:6]))
        # every open position of a real account must have a usable exit price
        db = SessionLocal()
        try:
            nomark = []
            for p in db.query(Position).filter_by(is_closed=False).all():
                ins = self.feed.instruments.get(p.token)
                if not p.qty or not ins or not self.engine.tradable_now(ins) or not self._feed_up(ins):
                    continue
                mk = self.engine.mark_price(p.token, p.qty)
                if mk is None or not math.isfinite(mk) or mk <= 0:
                    nomark.append(p.symbol)
            self.ok("every open position in an open market has a live price to value it", not nomark, ", ".join(sorted(set(nomark))[:8]))
        finally:
            db.close()

    # ---- the books of every real account -------------------------------------------------------
    def _books(self):
        self.area = "All accounts"
        db = SessionLocal()
        try:
            users = [u for u in db.query(User).all() if not is_probe(u.username)]
            bad_led, bad_funds = [], []
            for u in users:
                led = db.query(Ledger).filter_by(user_id=u.id).order_by(Ledger.id.desc()).first()
                if led and abs((led.balance_after or 0) - (u.balance or 0)) > 0.011:
                    bad_led.append(f"{u.username} ₹{(u.balance or 0) - (led.balance_after or 0):+,.2f}")
                try:
                    f = self.engine.funds(db, u)
                    if not all(math.isfinite(float(v)) for v in f.values()):
                        bad_funds.append(u.username)
                except Exception as e:
                    bad_funds.append(f"{u.username} ({type(e).__name__})")
            self.ok(f"balance equals the last ledger line on all {len(users)} accounts", not bad_led, "; ".join(bad_led[:6]))
            self.ok("every account's funds can be computed", not bad_funds, "; ".join(bad_funds[:6]))
            # Weekly settlement: the finished weeks, the ledger and the carried positions must tell one story.
            from . import weekly as _wk
            from .db import WeekSettlement
            wk_led, wk_sum, wk_pos = [], [], []
            for u in users:
                rows = db.query(WeekSettlement).filter_by(user_id=u.id).all()
                if abs(sum(r.result for r in rows) - _wk.settled_total(db, u)) > 0.05:
                    wk_led.append(u.username)
                wk_sum += [f"{u.username} {r.week_end} ({r.other:+,.2f})" for r in rows if abs(r.other or 0) >= 0.05]
            for p in db.query(Position).filter_by(is_closed=False).all():
                if not p.qty or not p.carried_week:
                    continue
                d = self.engine.position_dict(p)
                if not (p.entry_avg and p.entry_avg > 0) or (d.get("unrealised") is not None and d.get("total_since_entry") is not None
                                                             and abs(d["settled_earlier"] + d["unrealised"] - d["total_since_entry"]) > 0.02):
                    wk_pos.append(p.symbol)
            self.ok("finished weeks in the weekly report match the ledger on every account", not wk_led, ", ".join(wk_led[:6]))
            self.ok("every finished week adds up (closed trades + open positions at week close − commission)", not wk_sum, "; ".join(wk_sum[:6]))
            self.ok("every carried position keeps its original average (settled earlier + this week = total since entry)", not wk_pos, ", ".join(sorted(set(wk_pos))[:8]))
            nopx = sorted({p.symbol for p in db.query(Position).filter_by(is_closed=False).all() if p.qty and _wk.close_price(self.engine, p) is None})
            self.ok("every open position has a price the weekly cut-off can value it at", not nopx, ", ".join(nopx[:8]))
            over = []
            for p in db.query(Position).filter_by(is_closed=False).all():
                v = _wk.close_price(self.engine, p) if p.qty else None
                t = self.feed.prices.get(p.token) or {}
                other = t.get("ask") if p.qty > 0 else t.get("bid")
                if v is not None and other and ((p.qty > 0 and v > other * 1.0001) or (p.qty < 0 and v < other * 0.9999)):
                    over.append(f"{p.symbol} valued {v:g}, book {other:g}")
            self.ok("no open position is valued for the weekly cut-off above the best offer (long) or below the best bid (short)", not over, "; ".join(over[:6]))
            now_i = _ist()
            due = _wk.last_finished_week_end(now_i).isoformat()
            closed = get_setting(db, "week_closed") or due
            just = now_i.weekday() == 0 and now_i.hour == 0 and now_i.minute < 15
            self.ok("the weekly cut-off has run for every finished week", closed >= due or just, f"last closed {closed}, due {due}")
            # ---- what the Master and the users are shown: the same figures everywhere, open or shut, holiday or not ----
            try:
                import sys
                M = sys.modules.get("app.main") or sys.modules.get("main")
                from . import market_calendar as _cal
                moved, zero, differ, rep_bad = [], [], [], []
                per_user = {}
                for p in db.query(Position).filter_by(is_closed=False).all():
                    if not p.qty:
                        continue
                    d = self.engine.position_dict(p)
                    per_user[p.user_id] = per_user.get(p.user_id, 0.0) + (d["unrealised"] or 0.0)
                    shut = self.engine.at_close_price(p)
                    if shut and p.last_mark is not None and d["mark"] != p.last_mark:
                        moved.append(p.symbol)                      # shut market: must sit on the closing price
                    if d["mark"] is None:
                        zero.append(p.symbol)                       # would be shown at 0 P&L
                self.ok("positions in a shut market (night, weekend, holiday) are valued at their closing price", not moved, ", ".join(sorted(set(moved))[:8]))
                self.ok("no open position is shown without a price (it would read as zero P&L)", not zero, ", ".join(sorted(set(zero))[:8]))
                rows = {r["username"]: r for r in (M._admin_rows(db) if M else [])}
                tol = lambda a, b: abs((a or 0) - (b or 0)) <= max(1.0, 0.002 * abs(b or 0))      # prices tick between two reads
                for u in users:
                    f = self.engine.funds(db, u); r = rows.get(u.username); w = _wk.running_row(self.engine, db, u)
                    want = per_user.get(u.id, 0.0)
                    if not tol(f["unrealised"], want) or (r and not tol(r["unrealised"], want)) or not tol(w["valuation"], want):
                        differ.append(f"{u.username} (positions {want:,.0f}, balance {f['unrealised']:,.0f}, Master {r['unrealised'] if r else '-'}, weekly {w['valuation']:,.0f})")
                    if r and (abs(r["allocated"] + r["net_pnl"] - r["net_balance"]) > 0.05 or abs(r["unrealised"] + r["realised"] - r["commission"] - r["net_pnl"]) > 0.05):
                        rep_bad.append(f"{u.username}: row does not add up")
                    if r and not tol(r["net_pnl"], w["result"]):
                        rep_bad.append(f"{u.username}: Master {r['net_pnl']:,.0f} vs weekly report {w['result']:,.0f}")
                    if M:
                        a = M.build_report(db, [u], None, None)["users"][0]
                        done_w = sum(x.result for x in db.query(WeekSettlement).filter_by(user_id=u.id).all())
                        if not tol(a["week_pnl"], w["result"]) or not tol(a["overall_pnl"], done_w + w["result"]):
                            rep_bad.append(f"{u.username}: user P&L week {a['week_pnl']:,.0f} / all time {a['overall_pnl']:,.0f} vs weekly report {w['result']:,.0f} + finished weeks {done_w:,.0f}")
                self.ok("open-position P&L is the same on the user screen, the Master table and the weekly report", not differ, "; ".join(differ[:4]))
                self.ok("Master table, user P&L and weekly report agree, and every row adds up", not rep_bad, "; ".join(rep_bad[:4]))
                wd = now_i.weekday()
                st = {k: _cal.status(k) for k in ("NFO", "BFO", "MCX", "CDS")}
                from .config import ENFORCE_MARKET_HOURS as _enf
                wrong = [k for k, v in st.items() if _enf and bool(v.get("open")) != bool(self.engine.market_open(k))]      # trading follows the calendar shown
                self.ok("market open/closed status matches the calendar (weekend, holiday)", not wrong, ", ".join(wrong))
                self.note("markets right now", ", ".join(f"{k} {'open' if v.get('open') else 'closed' + (' (' + str(v.get('holiday')) + ')' if v.get('holiday') else '')}" for k, v in st.items()))
            except Exception as e:
                self.ok("screen and report figures could be cross-checked", False, f"{type(e).__name__}: {e}")
            o_bad = [o.id for o in db.query(Order).filter_by(status="OPEN").all()
                     if o.margin_blocked is None or o.margin_blocked < 0 or (o.order_type == "LIMIT" and not (o.limit_price and o.limit_price > 0))
                     or (o.order_type == "SL" and not (o.trigger_price and o.trigger_price > 0)) or o.qty <= 0]
            self.ok("no resting order without a valid price, size or margin", not o_bad, f"orders {o_bad[:8]}")
            p_bad = [p.id for p in db.query(Position).filter_by(is_closed=False).all()
                     if p.margin_blocked is None or p.margin_blocked < -0.01 or not math.isfinite(p.avg_price or 0) or (p.qty and (p.avg_price or 0) <= 0)]
            self.ok("no open position with a broken price or margin", not p_bad, f"positions {p_bad[:8]}")
            # A position on a contract the site has stopped listing is valued with the wrong rupee factor
            # (seen with crypto options after their expiry), and one still open after its expiry day was
            # never settled. Only judged while that market's feed is up and has its contract list.
            today = _ist().date().isoformat()
            listed = {i.exchange for i in self.feed.instruments.values()}
            lost, overdue, unsure = [], [], 0
            for p in db.query(Position).filter_by(is_closed=False).all():
                if not p.qty:
                    continue
                ins = self.feed.instruments.get(p.token)
                up = p.exchange in listed and self._feed_up(ins or type("X", (), {"exchange": p.exchange})())
                if not up:
                    unsure += 1; continue
                if ins is None:
                    lost.append(p.symbol)
                if p.expiry and p.expiry < today:
                    overdue.append(f"{p.symbol} ({p.expiry})")
            self.ok("every open position is on a contract the site still lists (so it is valued correctly)", not lost, ", ".join(sorted(set(lost))[:8]))
            self.ok("no open position left unsettled on a contract that expired before today", not overdue, ", ".join(sorted(set(overdue))[:8]))
            if unsure:
                self.note("positions not judged", f"{unsure} in a market whose feed is off right now")
            # An option is settled against its underlying. If nobody streams the underlying its price in
            # memory is frozen, and the settlement pays the wrong amount (found 13 Nov 2026).
            cold = []
            for p in db.query(Position).filter_by(is_closed=False).all():
                ins = self.feed.instruments.get(p.token)
                if not p.qty or not ins or ins.instrument_type not in ("CE", "PE") or not self._feed_up(ins):
                    continue
                if p.opened_at and (datetime.utcnow() - p.opened_at).total_seconds() < 180:
                    continue
                ut = self.feed.index_token_for(ins.name)
                if ut and ut in self.feed.instruments and ut not in self.feed._refcount:
                    cold.append(f"{p.symbol} ({ins.name})")
            self.ok("the underlying of every open option position is being streamed (so it settles at a live price)", not cold, ", ".join(sorted(set(cold))[:8]))
            # Nobody may carry more than their coins cover: an Available Balance below zero must be squared
            # off within seconds. Judged only for accounts with a position in a market that is open now.
            strict = datetime.utcnow() >= self.engine.strict_from(db)
            over = []
            for u in users:
                ps = [p for p in db.query(Position).filter_by(user_id=u.id, is_closed=False).all() if p.qty]
                if not ps:
                    continue
                f = self.engine.funds(db, u)
                since = self.engine._neg_since.get(u.id)
                can = any(self.feed.instruments.get(p.token) and self.engine.tradable_now(self.feed.instruments[p.token]) for p in ps)
                if f["available"] < -1 and can and since and time.time() - since > 90 and not self.engine.week_grace(db, u.id):
                    over.append(f"{u.username} ₹{f['available']:,.0f}")
            if strict:
                self.ok("no account is carrying more than its coins cover (Available Balance not below zero)", not over, "; ".join(over[:6]))
            elif over:
                self.note("accounts below zero Available Balance", "; ".join(over[:6]) + " — warned; auto square-off starts after the one-time warning period")
            # Closing price of an expired future (15 Nov 2026). A future that settles at its order book is
            # settled at the closing price kept for the position. That price must have been looked at in the
            # last seconds before the contract stopped trading: one from a minute earlier can be traded
            # against (see the market move in the last seconds, add at the new price, be settled at the old).
            try:
                from .market_calendar import expiry_time_str
                today = _ist().date()
                names = {u.id: u.username for u in users}
                old_marks, n, seen, gaps = [], 0, set(), set()
                rows = (db.query(Position).filter(Position.is_closed == True, Position.expiry >= (today - timedelta(days=3)).isoformat(),  # noqa: E712
                                                  Position.expiry <= today.isoformat()).order_by(Position.id.desc()).all())
                for p in rows:
                    k = (p.user_id, p.token)
                    if k in seen:
                        continue
                    seen.add(k)
                    if (p.user_id not in names or p.exchange not in ("NFO", "BFO", "MCX", "CDS") or not (p.symbol or "").endswith("FUT")
                            or p.last_mark is None or not p.last_mark_at or not p.updated_at
                            or p.expiry < "2026-11-15"):          # the every-second closing price exists since 15 Nov 2026
                        continue
                    d = datetime.fromisoformat(p.expiry)
                    hh, mm = expiry_time_str(p.exchange, d.date()).split(":")[:2]
                    stop = d.replace(hour=int(hh), minute=int(mm)) - timedelta(hours=5, minutes=30)      # UTC
                    if not (stop <= p.updated_at <= stop + timedelta(seconds=150)):
                        continue          # closed by the user before the expiry, or settled late (site was down)
                    n += 1
                    age = (stop - p.last_mark_at).total_seconds()
                    if age > 45:
                        old_marks.append(f"{names[p.user_id]} {p.symbol} ({int(age)} s before the stop)")
                    # for the owner's eyes only: index, stock and currency futures settle at the underlying. If
                    # that is far from where the contract itself last traded, the last seconds were free money.
                    t = (db.query(Trade).filter(Trade.user_id == p.user_id, Trade.token == p.token, Trade.order_id == None,  # noqa: E711
                                                Trade.created_at >= stop).order_by(Trade.id.desc()).first())
                    if t and t.price and p.last_mark > 0 and abs(t.price - p.last_mark) / p.last_mark > 0.001:
                        gaps.add(f"{p.symbol} settled {t.price:g}, own closing price {p.last_mark:g} ({(t.price / p.last_mark - 1) * 100:+.2f}%)")
                self.ok(f"futures that expired in the last three days: the closing price was taken in the contract's last seconds ({n} positions)",
                        not old_marks, "; ".join(old_marks[:5]))
                if gaps:
                    self.note("expired futures settled more than 0.1% away from their own closing price", "; ".join(sorted(gaps)[:4]))
            except Exception as e:
                self.ok("closing price of expired futures readable", False, type(e).__name__)
            neg = [u.username for u in users if (u.balance or 0) < -0.01]
            if neg:
                self.note("accounts with a negative balance", ", ".join(neg[:8]))
        finally:
            db.close()
        self.area = "Prices"
        fx = getattr(self.feed, "forex", None); cry = getattr(self.feed, "crypto", None)
        try:
            if fx and fx.connected:
                r = fx.quote_to_inr("USD")
                self.ok("dollar–rupee rate is sensible", bool(r) and 60 < r < 150, r)
                for q, (a, b) in {"EUR": (70, 170), "GBP": (80, 200), "JPY": (0.3, 1.2), "AUD": (35, 110)}.items():
                    v = fx.quote_to_inr(q)
                    if v:
                        self.ok(f"{q}–rupee rate is sensible", a < v < b, round(v, 4))
                cu = getattr(self.feed, "usdinr", lambda: None)()
                if r and cu:
                    self.ok("the two dollar–rupee sources agree within 10%", abs(cu / r - 1) < 0.10, f"{cu} vs {round(r, 3)}")
        except Exception as e:
            self.ok("conversion rates readable", False, type(e).__name__)
        # Expiry moment. Crypto options: the exchange's own moment (5:30 pm IST) — settling later hands out
        # hours of free option time (the loophole of 12 Nov 2026). Currency: the last trading day ends at
        # 12:30 pm although the segment stays open until 5 pm (closed 13 Nov 2026).
        try:
            bad, n = [], 0
            if cry and cry.connected:
                from .market_calendar import close_time_str
                opts = [i for i in cry.items.values() if i.instrument_type in ("CE", "PE") and getattr(i, "expiry_at", 0)]
                for i in opts:
                    t = datetime.utcfromtimestamp(i.expiry_at) + timedelta(hours=5, minutes=30)
                    if (self.engine.expired(i, now=t - timedelta(minutes=1)) or not self.engine.expired(i, now=t + timedelta(minutes=1))
                            or i.expiry != t.date().isoformat() or close_time_str("CRYPTO") != t.strftime("%H:%M")):
                        bad.append(f"{i.symbol} ({t:%d %b %H:%M})")
                n += len(opts)
            cds = [i for i in self.feed.instruments.values() if i.exchange == "CDS" and i.instrument_type == "FUT" and i.expiry][:60]
            for i in cds:
                d = datetime.fromisoformat(i.expiry)
                if self.engine.expired(i, now=d.replace(hour=12, minute=29)) or not self.engine.expired(i, now=d.replace(hour=12, minute=31)):
                    bad.append(f"{i.symbol} (12:30 pm on {d:%d %b})")
            n += len(cds)
            if n:
                self.ok(f"crypto options and currency contracts stop trading and settle at the exchange's own expiry time ({n} contracts)", not bad, ", ".join(bad[:5]))
            else:
                self.note("expiry time not checked", "no crypto options or currency contracts listed right now")
        except Exception as e:
            self.ok("expiry time readable", False, type(e).__name__)
        self.note("feeds", f"NSE/MCX {'on' if self.feed.connected else 'OFF'} · crypto {'on' if cry and cry.connected else 'OFF'} · forex/global {'on' if fx and fx.connected else 'OFF'}")

    # ---- run -----------------------------------------------------------------------------------
    async def run(self) -> dict:
        t0 = time.time()
        await self._wipe()
        db = SessionLocal()
        try:
            ua, ub = self._users(db)
            db.expunge_all()
        finally:
            db.close()
        # preflight: the attacker must actually be reaching the API as its test account, otherwise
        # every "refused" below would be meaningless
        c = self._client(ua)
        try:
            r = await c.get("/api/me")
            reach = r.status_code == 200 and r.json().get("user", {}).get("username") == ua.username
        except Exception:
            reach = False
        finally:
            await c.aclose()
        if not reach:
            self.area = "Self-check"
            self.ok("the check could reach the site as its test account", False, f"got HTTP {getattr(r, 'status_code', '?')} — nothing was tested, this is a fault in the check, not a loophole")
            await self._wipe(balances=(0.0, 0.0))
            return {"at": f"{_ist():%Y-%m-%d %H:%M}", "secs": round(time.time() - t0, 1), "passed": 0, "failed": 1, "ok": False, "rows": self.rows}
        try:
            for label, ins in self._targets():
                if isinstance(ins, list):
                    ins = await self._pick(ins)
                if not ins:
                    self.area = label; self.note("skipped", "no contract listed"); continue
                try:
                    await self._attack(label, ins, ua, ub)
                    await self._shortfall(label, ins, ua)
                    await self._frozen(label, ins, ua)
                    await self._resting_rules(label, ins, ub)
                except Exception as e:
                    log.exception("probe attack on %s crashed", label)
                    self.area = label; self.ok("the check itself ran to the end", False, f"{type(e).__name__}: {e}")
                    for u in (ua, ub):
                        c = self._client(u)
                        try:
                            await self._flatten(c)
                        except Exception:
                            pass
                        await c.aclose()
            try:
                await self._bought_option(ua)
            except Exception as e:
                log.exception("probe bought-option check crashed")
                self.area = "Bought option"; self.ok("the check itself ran to the end", False, f"{type(e).__name__}: {e}")
            for label, exchange, names in (("NSE", "NFO", ["NIFTY", "BANKNIFTY"]), ("BSE", "BFO", ["SENSEX", "BANKEX"]),
                                          ("MCX", "MCX", ["CRUDEOILM", "CRUDEOIL", "NATURALGAS", "NATGASMINI", "GOLDM", "GOLD", "SILVERM"]),
                                          ("Currency", "CDS", ["USDINR", "EURINR", "GBPINR"]), ("Crypto", "CRYPTO", ["BTC", "ETH"])):
                try:
                    await self._illiquid(label, exchange, names, ua)
                except Exception as e:
                    log.exception("probe thin-contract attack on %s crashed", label)
                    self.ok("the check itself ran to the end", False, f"{type(e).__name__}: {e}")
            try:
                await self._old_login(ub)
            except Exception as e:
                log.exception("probe login check crashed")
                self.ok("the login check ran to the end", False, f"{type(e).__name__}: {e}")
            try:
                await self._stream_flood(ub)
            except Exception as e:
                log.exception("probe price-socket check crashed")
                self.ok("the price-socket check ran to the end", False, f"{type(e).__name__}: {e}")
            try:
                self._price_sanity()
            except Exception as e:
                log.exception("probe price check crashed")
                self.ok("the price check ran to the end", False, f"{type(e).__name__}: {e}")
            try:
                self._books()
            except Exception as e:
                log.exception("probe books check crashed")
                self.ok("the books check ran to the end", False, f"{type(e).__name__}: {e}")
        finally:
            await self._wipe(balances=(0.0, 0.0))
        failed = [r for r in self.rows if r["ok"] is False]
        passed = [r for r in self.rows if r["ok"] is True]
        return {"at": f"{_ist():%Y-%m-%d %H:%M}", "secs": round(time.time() - t0, 1), "passed": len(passed), "failed": len(failed),
                "ok": not failed, "rows": self.rows}


def _telegram(text: str) -> str:
    """Plain message on the same private Telegram chat as the backups. Never raises, never logs the token."""
    token, chat = os.getenv("PT_TG_BOT_TOKEN", "").strip(), os.getenv("PT_TG_CHAT_ID", "").strip()
    if not (token and chat):
        return "Telegram is not set up"
    try:
        r = httpx.post(f"{os.getenv('PT_TG_API', 'https://api.telegram.org')}/bot{token}/sendMessage", timeout=30,
                       data={"chat_id": chat, "text": text[:3900]})
        return "" if (r.status_code == 200 and r.json().get("ok")) else f"Telegram refused it ({r.status_code})"
    except Exception as e:
        return f"could not send ({type(e).__name__})"


def _message(res: dict) -> str:
    head = f"limefx daily safety check · {res['at']}\n"
    if res["ok"]:
        body = f"✅ All {res['passed']} checks passed. No way found to cheat the system today."
    else:
        bad = [r for r in res["rows"] if r["ok"] is False]
        body = f"⚠️ {res['failed']} of {res['passed'] + res['failed']} checks FAILED:\n" + "\n".join(
            f"• {r['area']}: {r['check']}" + (f" — {r['info']}" if r["info"] else "") for r in bad[:12])
        body += "\n\nSend this to Claude to get it closed."
    skipped = sorted({r["area"] for r in res["rows"] if r["ok"] is None and r["check"].startswith("skipped")})
    closed = sorted({r["area"] for r in res["rows"] if r["check"].startswith("market is closed")})
    tail = ""
    if closed:
        tail += f"\nClosed right now (only the closed-market check ran): {', '.join(closed)}."
    if skipped:
        tail += f"\nNot attacked (no live feed/contract): {', '.join(skipped)}."
    return head + body + tail


async def run_and_report(app, engine, feed, scheduled: bool = False, slot: str = "") -> dict:
    if _running.locked():
        return {"busy": True}
    async with _running:
        res = await Probe(app, engine, feed).run()
        err = await asyncio.get_event_loop().run_in_executor(None, _telegram, _message(res))
        res["telegram"] = err or "sent"
        db = SessionLocal()
        try:
            set_setting(db, "probe_last", json.dumps(res))
            try:
                hist = json.loads(get_setting(db, "probe_hist") or "[]")
            except Exception:
                hist = []
            hist = ([{"at": res["at"], "passed": res["passed"], "failed": res["failed"], "ok": res["ok"]}] + hist)[:30]
            set_setting(db, "probe_hist", json.dumps(hist))
            if scheduled:
                set_setting(db, "probe_slot", f"{_ist().date().isoformat()}|{slot}")
        finally:
            db.close()
        log.warning("daily safety check: %d passed, %d failed (%ss)", res["passed"], res["failed"], res["secs"])
        return res


def _forward_nightly_report():
    """The nightly review (a separate session that hunts for new loopholes) leaves its plain-language
    report in app/nightly_report.txt. Each new report is sent once to Telegram when the server starts."""
    import hashlib
    from pathlib import Path
    f = Path(__file__).with_name("nightly_report.txt")
    if not f.exists():
        return
    text = f.read_text(encoding="utf-8", errors="replace").strip()
    if not text:
        return
    h = hashlib.sha256(text.encode()).hexdigest()
    db = SessionLocal()
    try:
        if get_setting(db, "nightly_report_hash") == h:
            return
        err = _telegram("limefx nightly loophole hunt\n\n" + text)
        if not err:
            set_setting(db, "nightly_report_hash", h)
        else:
            log.warning("nightly report not sent: %s", err)
    finally:
        db.close()


async def loop(app, engine, feed):
    """A live check at each time in RUN_AT (IST). Two slots a day so every market gets checked while it is
    open: the morning slot covers the Indian markets, the evening slot the US / Global session that is shut
    in the morning. If the server was down at a slot's minute, that slot runs when it is back."""
    await asyncio.sleep(150)          # let the price feeds connect after a restart
    try:
        await asyncio.get_event_loop().run_in_executor(None, _forward_nightly_report)
    except Exception:
        log.exception("nightly report forward failed")
    while True:
        try:
            now = _ist()
            today = now.date().isoformat()
            hm = now.strftime("%H:%M")
            due = [s for s in _SLOTS if hm >= s]        # slots whose time has passed today
            if due:
                slot = max(due)                          # the latest one that is due
                marker = f"{today}|{slot}"
                db = SessionLocal()
                try:
                    done = get_setting(db, "probe_slot")
                finally:
                    db.close()
                if done != marker:
                    await run_and_report(app, engine, feed, scheduled=True, slot=slot)
        except Exception:
            log.exception("daily safety check failed to run")
        await asyncio.sleep(60)
