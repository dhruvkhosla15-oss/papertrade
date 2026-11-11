"""
Crypto derivatives from Delta Exchange India (public market data — no API key needed).

Attached on top of the primary feed (Zerodha or mock): products become Instruments on exchange
"CRYPTO" (perpetual futures as FUT with no expiry, options as CE/PE), ticks are published through the
same `feed._publish`, and subscriptions / candles for crypto tokens are routed here.

Contracts are USD-quoted. `lot_size` is 1 contract; `multiplier` carries the contract size in the
underlying (BTCUSD: 0.001 BTC), so one contract's rupee value = price x multiplier x USDINR. The
engine applies `feed.value_factor(ins)` = multiplier x USDINR to every P&L / margin / commission
calculation for these instruments.

Depth: full L2 book for perpetuals, best bid/ask (with size) for options via the ticker channel.
Sizes from Delta are in contracts, which is exactly our qty unit (lot_size=1).
"""
import asyncio
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone

import httpx

from .base import Instrument

log = logging.getLogger("app.feed.delta")

REST = os.getenv("PT_DELTA_REST", "https://api.india.delta.exchange")
WS = os.getenv("PT_DELTA_WS", "wss://socket.india.delta.exchange")
TOKEN_BASE = 5_000_000_000           # Delta product ids are small ints; keep them clear of Zerodha tokens
PERPS = [s.strip().upper() for s in os.getenv("PT_CRYPTO_PERPS", "BTCUSD,ETHUSD,SOLUSD,XRPUSD,BNBUSD,XAUTUSD").split(",") if s.strip()]
OPTION_UNDERLYINGS = [s.strip().upper() for s in os.getenv("PT_CRYPTO_OPTIONS", "BTC,ETH").split(",") if s.strip()]
OPTION_DAYS = int(os.getenv("PT_CRYPTO_OPTION_DAYS", "10"))   # list option expiries this far ahead
IST = timedelta(hours=5, minutes=30)


class DeltaCrypto:
    def __init__(self, feed):
        self.feed = feed
        self.items: dict = {}            # token -> Instrument
        self.symbols: dict = {}          # symbol -> token
        self._subs: set = set()          # tokens wanted
        self._ws = None
        self._loop = None
        self.connected = False
        self.paused = False
        self.message = "not started"
        self._refresh_task = None
        # --- wire into the primary feed ---
        self._orig_load = feed.load_instruments
        self._orig_sub, self._orig_unsub = feed._subscribe, feed._unsubscribe
        self._orig_candles, self._orig_index = feed.candles, feed.index_token_for
        feed.load_instruments = self._load_instruments
        feed._subscribe = self._subscribe
        feed._unsubscribe = self._unsubscribe
        feed.candles = self._candles
        feed.index_token_for = self._index_token_for
        feed.value_factor = self.value_factor
        feed.usdinr = self.usdinr
        feed.crypto = self

    # ---- instruments ---------------------------------------------------------------------------
    def _load_instruments(self, items):
        self._orig_load(list(items) + list(self.items.values()))

    def _merge(self):
        # re-run the primary loader with its own items so ours are merged in
        base = [i for i in self.feed.instruments.values() if i.exchange != "CRYPTO"]
        self._orig_load(base + list(self.items.values()))

    def refresh_products(self):
        out = {}
        with httpx.Client(timeout=20) as c:
            r = c.get(f"{REST}/v2/products", params={"states": "live", "contract_types": "perpetual_futures", "page_size": 500})
            r.raise_for_status()
            for p in r.json()["result"]:
                if p["symbol"] not in PERPS:
                    continue
                tok = TOKEN_BASE + int(p["id"])
                und = (p.get("underlying_asset") or {}).get("symbol") or p["symbol"].replace("USD", "")
                if p.get("trading_status") not in (None, "operational"):
                    continue
                out[tok] = Instrument(tok, p["symbol"], und, "CRYPTO", "CRYPTO-PERP", "FUT", "", 0, 1,
                                      float(p["tick_size"]), f"{p['contract_value']} {und} (price in USD)",
                                      multiplier=float(p["contract_value"]), **self._risk(p))
            horizon = datetime.now(timezone.utc) + timedelta(days=OPTION_DAYS)
            for ctype in ("call_options", "put_options"):
                after = None
                for _ in range(20):
                    params = {"states": "live", "contract_types": ctype, "page_size": 500}
                    if after:
                        params["after"] = after
                    r = c.get(f"{REST}/v2/products", params=params); r.raise_for_status()
                    j = r.json()
                    for p in j["result"]:
                        und = (p.get("underlying_asset") or {}).get("symbol")
                        if und not in OPTION_UNDERLYINGS or not p.get("settlement_time"):
                            continue
                        st = datetime.fromisoformat(p["settlement_time"].replace("Z", "+00:00"))
                        if st > horizon:
                            continue
                        tok = TOKEN_BASE + int(p["id"])
                        exp = (st + IST).date().isoformat()          # the exchange's own expiry moment (12:00 UTC = 5:30 pm IST)
                        if p.get("trading_status") not in (None, "operational"):
                            continue
                        out[tok] = Instrument(tok, p["symbol"], und, "CRYPTO", "CRYPTO-OPT",
                                              "CE" if ctype == "call_options" else "PE", exp,
                                              float(p["strike_price"]), 1, float(p["tick_size"]),
                                              f"{p['contract_value']} {und} (price in USD)",
                                              multiplier=float(p["contract_value"]), expiry_at=st.timestamp(), **self._risk(p))
                    after = (j.get("meta") or {}).get("after")
                    if not after:
                        break
        # The exchange stops listing a contract the moment it expires (or is suspended). Anything a user
        # here still holds must stay known until it is settled: without the contract a position has no
        # strike and no rupee value per point, and would be valued and settled at ten times its worth.
        held = self._held()
        today = (datetime.now(timezone.utc) + IST).date().isoformat()
        for tok, old in self.items.items():
            if tok not in out and (tok in held or (old.instrument_type != "FUT" and old.expiry >= today)):
                out[tok] = old
        for tok, sym in held.items():
            if tok not in out:
                g = self._rebuild(tok, sym, out)      # e.g. after a restart: rebuilt from the position's own symbol
                if g:
                    out[tok] = g
        self.items = out
        self.symbols = {i.symbol: i.token for i in out.values()}
        self._merge()
        log.info("delta: %d crypto instruments (%d perpetuals, %d options)", len(out),
                 sum(1 for i in out.values() if i.instrument_type == "FUT"), sum(1 for i in out.values() if i.instrument_type != "FUT"))

    @staticmethod
    def _held() -> dict:
        """{token: symbol} of crypto contracts with an open position or a resting order."""
        try:
            from ..db import SessionLocal, Position, Order
            db = SessionLocal()
            try:
                out = {p.token: p.symbol for p in db.query(Position).filter_by(is_closed=False, exchange="CRYPTO") if p.qty}
                for o in db.query(Order).filter_by(status="OPEN", exchange="CRYPTO"):
                    out.setdefault(o.token, o.symbol)
                return out
            finally:
                db.close()
        except Exception:
            log.exception("delta: could not read held contracts")
            return {}

    @staticmethod
    def _rebuild(tok: int, sym: str, listed: dict):
        """An option the exchange no longer lists, rebuilt from its symbol (C-BTC-75000-121126) so a
        position in it can still be valued and settled. The contract size is the perpetual's."""
        try:
            kind, und, strike, ddmmyy = sym.split("-")
            perp = next(i for i in listed.values() if i.instrument_type == "FUT" and i.name == und)
            exp = f"20{ddmmyy[4:6]}-{ddmmyy[2:4]}-{ddmmyy[0:2]}"
            datetime.fromisoformat(exp)
            return Instrument(tok, sym, und, "CRYPTO", "CRYPTO-OPT", {"C": "CE", "P": "PE"}[kind], exp, float(strike), 1,
                              perp.tick_size, f"{perp.multiplier:g} {und} (price in USD)", multiplier=perp.multiplier)
        except Exception:
            log.error("delta: held contract %s is no longer listed and could not be rebuilt", sym)
            return None

    @staticmethod
    def _risk(p):
        f = lambda k: float(p[k]) if p.get(k) not in (None, "") else 0.0
        steps = tuple(int(x) for x in ((p.get("ui_config") or {}).get("leverage_slider_values") or [1, 2, 5, 10, 25, 50, 100, 200]))
        mx = int(round(100 / f("initial_margin"))) if f("initial_margin") else 200
        return {"init_margin_pct": f("initial_margin"), "maint_margin_pct": f("maintenance_margin"),
                "pos_limit": int(f("position_size_limit")), "price_band_pct": f("price_band"),
                "leverage_options": tuple(s for s in steps if s <= mx)}

    # ---- helpers used by engine / pulse ---------------------------------------------------------
    INR_INDEX = ".DEUSDTINR"      # Delta's own USD(T)/INR index: what its app uses for rupee display

    def usdinr(self):
        """Delta's USDT/INR index — the only rate used for rupee figures, so ours always match
        Delta's and there is no arbitrage against the NSE USDINR. The last value is remembered across
        restarts; until a value is known crypto trading is blocked (fx_ready() is False)."""
        d = getattr(self, "_inr", None)
        if d is None:
            d = self._load_inr()
        return d[0] if d else None

    def fx_ready(self) -> bool:
        return self.usdinr() is not None

    def fx_source(self) -> str:
        d = getattr(self, "_inr", None)
        if not d:
            return "waiting for Delta USDT/INR index"
        age = time.time() - d[1]
        return "Delta USDT/INR index" + ("" if age < 120 else f" (last update {int(age // 60)} min ago)")

    def _load_inr(self):
        try:
            from ..db import SessionLocal, get_setting
            db = SessionLocal()
            try:
                v = get_setting(db, "delta_usdt_inr"); t = get_setting(db, "delta_usdt_inr_ts")
            finally:
                db.close()
            if v:
                self._inr = (float(v), float(t or 0)); return self._inr
        except Exception:
            pass
        return None

    def _save_inr(self):
        now = time.time()
        if now - getattr(self, "_inr_saved", 0) < 60:
            return
        self._inr_saved = now
        try:
            from ..db import SessionLocal, set_setting
            db = SessionLocal()
            try:
                set_setting(db, "delta_usdt_inr", str(self._inr[0])); set_setting(db, "delta_usdt_inr_ts", str(self._inr[1])); db.commit()
            finally:
                db.close()
        except Exception:
            log.exception("delta: could not persist INR rate")

    def value_factor(self, ins) -> float:
        """Rupee value of a 1.0 price move on 1 unit of qty."""
        if ins is None or ins.exchange != "CRYPTO":
            return 1.0
        return (ins.multiplier or 1.0) * (self.usdinr() or 0.0)

    def _index_token_for(self, name):
        for i in self.items.values():
            if i.name == name and i.instrument_type == "FUT":
                return i.token          # perpetual acts as the underlying for options & Pulse
        return self._orig_index(name)

    # ---- subscriptions ----------------------------------------------------------------------------
    def _split(self, tokens):
        mine = [t for t in tokens if t in self.items]
        other = [t for t in tokens if t not in self.items]
        return mine, other

    def _subscribe(self, tokens):
        mine, other = self._split(tokens)
        if other:
            self._orig_sub(other)
        if mine:
            self._subs |= set(mine)
            self._send_subs(mine)

    def _unsubscribe(self, tokens):
        mine, other = self._split(tokens)
        if other:
            self._orig_unsub(other)
        if mine:
            self._subs -= set(mine)
            self._send_unsubs(mine)

    def _channels(self, tokens):
        perps = [self.items[t].symbol for t in tokens if self.items[t].instrument_type == "FUT"]
        syms = [self.items[t].symbol for t in tokens]
        ch = [{"name": "v2/ticker", "symbols": syms}]
        if perps:
            ch.append({"name": "l2_orderbook", "symbols": perps})
        return ch

    def _send(self, msg):
        if self._ws and self._loop:
            asyncio.run_coroutine_threadsafe(self._ws.send(json.dumps(msg)), self._loop)

    def _send_subs(self, tokens):
        self._send({"type": "subscribe", "payload": {"channels": self._channels(tokens)}})

    def _send_unsubs(self, tokens):
        self._send({"type": "unsubscribe", "payload": {"channels": self._channels(tokens)}})

    # ---- websocket ---------------------------------------------------------------------------------
    async def start(self, loop):
        self._loop = loop
        try:
            await loop.run_in_executor(None, self.refresh_products)
        except Exception as e:
            log.warning("delta: product list failed: %s", e)
            self.message = f"product list failed: {e}"
        # perpetuals are the underlying reference for every option's margin/maintenance: always stream them
        self.feed.pin([t for t, i in self.items.items() if i.instrument_type == "FUT"])
        loop.create_task(self._run())
        loop.create_task(self._refresh_loop())

    async def _refresh_loop(self):
        while True:
            await asyncio.sleep(3600)
            try:
                old = set(self.items)
                await self._loop.run_in_executor(None, self.refresh_products)
                new = set(self.items) - old
                if new and self._ws:
                    pass  # new expiries get subscribed when someone opens them
            except Exception as e:
                log.warning("delta: refresh failed: %s", e)

    def disconnect(self):
        """Master control: stop crypto prices (users see OFFLINE on crypto, orders rejected)."""
        self.paused = True
        if self._ws and self._loop:
            asyncio.run_coroutine_threadsafe(self._ws.close(), self._loop)
        self.connected = False; self.message = "paused by master"

    def reconnect(self):
        self.paused = False; self.message = "reconnecting"
        return True

    async def _run(self):
        import websockets
        while True:
            if self.paused:
                await asyncio.sleep(1)
                continue
            try:
                async with websockets.connect(WS, ping_interval=20, ping_timeout=20, max_size=8_000_000) as ws:
                    self._ws = ws
                    self.connected = True; self.message = "Delta Exchange India live"
                    await ws.send(json.dumps({"type": "subscribe", "payload": {"channels": [{"name": "spot_price", "symbols": [self.INR_INDEX]}]}}))
                    if self._subs:
                        await ws.send(json.dumps({"type": "subscribe", "payload": {"channels": self._channels(list(self._subs))}}))
                    async for raw in ws:
                        try:
                            self._handle(json.loads(raw))
                        except Exception:
                            log.exception("delta: bad message")
            except Exception as e:
                if not self.paused:
                    log.warning("delta: websocket dropped: %s", e)
            self.connected = False; self._ws = None
            if not self.paused:
                self.message = "reconnecting"
            await asyncio.sleep(1 if self.paused else 5)

    def _handle(self, m):
        t = m.get("type")
        sym = m.get("symbol")
        if t == "spot_price" and sym == self.INR_INDEX:
            try:
                self._inr = (float(m["price"]), time.time()); self._save_inr()
            except Exception:
                pass
            return
        tok = self.symbols.get(sym)
        if not tok:
            return
        prev = self.feed.prices.get(tok) or {}
        if t == "l2_orderbook":
            bids = [(float(x["limit_price"]), int(x["size"]), 0) for x in m.get("buy", [])[:5]]
            asks = [(float(x["limit_price"]), int(x["size"]), 0) for x in m.get("sell", [])[:5]]
            d = dict(prev)
            d.update({"token": tok, "bids": bids, "asks": asks, "bid": bids[0][0] if bids else None,
                      "ask": asks[0][0] if asks else None, "ts": time.time()})
            if "ltp" not in d:
                mid = (bids[0][0] + asks[0][0]) / 2 if bids and asks else None
                if mid is None:
                    return
                d["ltp"] = mid
            d["tbq"] = sum(b[1] for b in bids); d["tsq"] = sum(a[1] for a in asks)
            self.feed._publish(d)
        elif t == "v2/ticker":
            q = m.get("quotes") or {}
            d = dict(prev)
            ltp = m.get("close") or m.get("mark_price")
            if ltp is None:
                return
            ltp = float(ltp)
            op = m.get("open");
            d.update({"token": tok, "ltp": ltp, "ts": time.time(), "ltt": time.time(),
                      "volume": int(float(m.get("volume") or 0)), "oi": int(float(m.get("oi") or 0)),
                      "open": float(op) if op is not None else d.get("open"),
                      "high": float(m["high"]) if m.get("high") is not None else d.get("high"),
                      "low": float(m["low"]) if m.get("low") is not None else d.get("low"),
                      "turnover_usd": float(m.get("turnover_usd") or 0),
                      "funding": float(m.get("funding_rate") or 0) if m.get("funding_rate") is not None else None,
                      "mark_iv": float(q["mark_iv"]) if q.get("mark_iv") not in (None, "") else None})
            # 24h change: Delta gives ltp_change_24h as a fraction? it is "close - open" pct in mark_change_24h (string pct)
            chg = m.get("mark_change_24h")
            if chg is not None:
                try:
                    d["change"] = round(float(chg), 2)
                except Exception:
                    pass
            if op:
                d["close"] = float(op)   # "previous close" for a 24x7 market = price 24h ago
            if q.get("best_bid") is not None and q.get("best_ask") is not None:
                bb, ba = float(q["best_bid"]), float(q["best_ask"])
                bs, as_ = int(float(q.get("bid_size") or 0)), int(float(q.get("ask_size") or 0))
                ins = self.items.get(tok)
                if ins and ins.instrument_type != "FUT":
                    # options: top of book only (sizes in contracts)
                    d["bids"] = [(bb, bs, 0)] if bs else []
                    d["asks"] = [(ba, as_, 0)] if as_ else []
                    d["bid"] = bb if bs else None; d["ask"] = ba if as_ else None
                    d["tbq"] = bs; d["tsq"] = as_
                elif "bids" not in d:
                    d["bid"], d["ask"] = bb, ba
            self.feed._publish(d)

    # ---- candles -----------------------------------------------------------------------------------
    def _candles(self, token, interval):
        if token not in self.items:
            return self._orig_candles(token, interval)
        ins = self.items[token]
        res = {"1d": "1d", "5m": "5m", "15m": "15m", "1h": "1h", "1m": "1m"}.get(interval, "1d")
        end = int(time.time())
        start = end - (400 * 86400 if res == "1d" else 5 * 86400)
        with httpx.Client(timeout=20) as c:
            r = c.get(f"{REST}/v2/history/candles", params={"resolution": res, "symbol": ins.symbol, "start": start, "end": end})
            r.raise_for_status()
            rows = r.json().get("result") or []
        rows.sort(key=lambda x: x["time"])
        return [{"time": int(x["time"]), "open": float(x["open"]), "high": float(x["high"]), "low": float(x["low"]),
                 "close": float(x["close"]), "volume": float(x.get("volume") or 0), "oi": 0} for x in rows]

    def status(self):
        return {"connected": self.connected, "paused": self.paused, "message": self.message, "instruments": len(self.items),
                "subscribed": len(self._subs), "usdinr": self.usdinr(), "fx_source": self.fx_source()}
