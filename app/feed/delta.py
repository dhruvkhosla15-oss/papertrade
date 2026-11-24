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
import math
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
QUIET_SECS = float(os.getenv("PT_FEED_QUIET_SECS", "8"))   # nothing at all from the exchange for this long = prices cannot be trusted


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
        self._last_msg = 0.0             # when the exchange last sent anything
        self._stale_book = set()         # perpetuals whose order book in memory is from before the last (re)connect
        self._seen: dict = {}            # perpetual -> when its last message arrived
        self._gap: dict = {}             # perpetual -> longest wait between two of its messages since the start (outages left out)
        self.drops: list = []            # the last 30 drops: [when (unix), seconds the connection lasted, messages received, why]
        self._fails = 0                  # drops in a row that came soon after connecting (for the waiting time before the next try)
        self._run_task = None
        self._last_fresh = 0.0           # when the connection was last rebuilt from scratch
        self._fresh_busy = False         # a rebuild from scratch is under way
        self._runs = 0                   # connection loops alive right now: one, never more (the daily check reads it)
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
            if v and math.isfinite(float(v)) and float(v) > 0:
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
        self._run_task = loop.create_task(self._run())
        loop.create_task(self._refresh_loop())

    async def _refresh_loop(self):
        while True:
            # no list at all (the exchange could not be reached when the site started): try again every
            # minute, not once an hour; until it is there no crypto contract can be traded or streamed
            await asyncio.sleep(3600 if self.items else 60)
            try:
                old = set(self.items)
                await self._loop.run_in_executor(None, self.refresh_products)
                new = set(self.items) - old
                if not old and self.items:
                    self.feed.pin([t for t, i in self.items.items() if i.instrument_type == "FUT"])   # as start() does
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
        """Master's Reconnect: rebuild the crypto connection from scratch, the same as a restart of the site
        does for it (owner's request, 23 Nov 2026: pressing reconnect while the exchange kept cutting the
        connection did nothing, only a restart of the whole site brought the prices back)."""
        self.paused = False; self.message = "reconnecting from scratch"
        if self._loop:
            asyncio.run_coroutine_threadsafe(self._fresh(), self._loop)
        return True

    async def _fresh(self):
        """Stop the old connection and its retry loop, reload the contract list, start a new connection at once.
        One at a time: two of these at the same moment (Reconnect pressed twice, or pressed while the automatic
        rebuild after six quick drops was reloading the contract list) each started a connection loop of its
        own. The site then held two connections to the exchange for good, every price was handled twice,
        "Disconnect" closed only one of them (prices went on arriving on a paused feed) and every later
        Reconnect left the extra one running (found 24 Nov 2026). The second call now leaves the work to the
        first, which does everything it would do."""
        if self._fresh_busy:
            return
        self._fresh_busy = True
        try:
            self._last_fresh = time.time()
            old = self._run_task
            if old is not None and not old.done():
                old.cancel()
                try:
                    await asyncio.wait_for(asyncio.shield(old), 5)
                except BaseException:
                    pass
            try:
                if self._ws:
                    await asyncio.wait_for(self._ws.close(), 3)
            except BaseException:
                pass
            self._ws = None; self.connected = False; self._fails = 0; self._last_msg = 0.0
            try:
                await self._loop.run_in_executor(None, self.refresh_products)
            except Exception as e:
                log.warning("delta: product list failed on a fresh start: %s", e)
            self._run_task = self._loop.create_task(self._run())
        finally:
            self._fresh_busy = False

    def last_data_secs(self):
        """Seconds since the exchange last sent anything (None if never)."""
        return round(time.time() - self._last_msg, 1) if self._last_msg else None

    def quiet(self) -> bool:
        """True when the connection is up but the exchange has sent nothing for a while. The prices in
        memory are then standing still while the real market moves; an order filled against them is the
        same free money as one filled at a frozen price (found 16 Nov 2026: 8 s of silence, +7,500 coins)."""
        return bool(self.connected and self._last_msg and time.time() - self._last_msg > QUIET_SECS)

    def _resync(self):
        """The connection is back (or delivering again after a silence): every price in memory is as old
        as the gap. None of them counts as live until a new one arrives. A perpetual gets its order book
        and its last price in separate messages; until the new book is in, the last-price message is not
        taken either, so a fresh timestamp can never sit on an old book."""
        subs = list(self._subs)
        self.feed.restart_live(subs)
        self._stale_book = {t for t in subs if t in self.items and self.items[t].instrument_type == "FUT"}

    async def _run(self):
        self._runs += 1
        try:
            await self._run_loop()
        finally:
            self._runs -= 1

    async def _run_loop(self):
        import websockets
        while True:
            if self.paused:
                await asyncio.sleep(1)
                continue
            try:
                t_open = time.time(); n_msgs = 0; why = "closed by the exchange"
                async with websockets.connect(WS, ping_interval=20, ping_timeout=20, max_size=8_000_000, open_timeout=20) as ws:
                    self._ws = ws
                    self._resync(); self._last_msg = time.time()
                    self.connected = True; self.message = "Delta Exchange India live"
                    await ws.send(json.dumps({"type": "subscribe", "payload": {"channels": [{"name": "spot_price", "symbols": [self.INR_INDEX]}]}}))
                    if self._subs:
                        await ws.send(json.dumps({"type": "subscribe", "payload": {"channels": self._channels(list(self._subs))}}))
                    async for raw in ws:
                        n_msgs += 1
                        if n_msgs > 50:
                            self._fails = 0            # a connection that really delivers resets the waiting time
                        now = time.time()
                        if now - self._last_msg > QUIET_SECS:
                            self._resync()         # first message after a silence: same as a reconnect
                        self._last_msg = now
                        try:
                            self._handle(json.loads(raw))
                        except Exception:
                            log.exception("delta: bad message")
                try:
                    why = f"closed by the exchange (code {ws.close_code}{', ' + ws.close_reason if ws.close_reason else ''})"
                except Exception:
                    pass
            except Exception as e:
                why = f"{type(e).__name__}: {str(e)[:200]}"
                if not self.paused:
                    log.warning("delta: websocket dropped: %s", e)
            self.connected = False; self._ws = None
            if self.paused:
                await asyncio.sleep(1)
                continue
            # Why it dropped, kept for the Master's crypto card and the Site health card (found 23 Nov 2026: the
            # connection was cut again within seconds all night and nothing said why).
            try:
                lasted = round(time.time() - t_open, 1)
            except Exception:
                lasted, n_msgs = 0.0, 0
            self.drops = (self.drops + [[time.time(), lasted, n_msgs, why]])[-30:]
            # Retry at once after a connection that worked for a while; after quick drops wait longer each time
            # (5, 10, 20, 40, 80, 120 seconds) instead of knocking every 5 seconds all night, which can get the
            # site's address limited by the exchange.
            self._fails = 0 if lasted > 300 and n_msgs > 50 else self._fails + 1
            if self._fails >= 6 and time.time() - self._last_fresh > 900:
                # six quick drops in a row: do what a restart of the site does, at most every 15 minutes
                self.message = f"rebuilding the connection from scratch (last drop: {why[:120]})"
                log.warning("delta: %d quick drops in a row, rebuilding the connection from scratch", self._fails)
                asyncio.get_event_loop().create_task(self._fresh())
                return
            wait = 5 if self._fails <= 1 else min(120, 5 * 2 ** (self._fails - 1))
            self.message = f"reconnecting (next try in {wait} s; last drop: {why[:120]})"
            await asyncio.sleep(wait)

    def _handle(self, m):
        t = m.get("type")
        sym = m.get("symbol")
        if t == "spot_price" and sym == self.INR_INDEX:
            try:
                v = float(m["price"])
                # Only an ordinary positive number is a rate. A zero (or a negative or not-a-number value)
                # from a hiccup of the index was taken as the dollar-rupee rate: every crypto contract was
                # then worth nothing in rupees and an order needed no margin at all (an account with 1,000
                # coins bought 500 BTC lots, tried 21 Nov 2026 with the message fed by hand). The last
                # good rate stays in use.
                if math.isfinite(v) and v > 0:
                    self._inr = (v, time.time()); self._save_inr()
            except Exception:
                pass
            return
        tok = self.symbols.get(sym)
        if not tok:
            return
        prev = self.feed.prices.get(tok) or {}
        if tok in self._subs and self.items[tok].instrument_type == "FUT":
            # how long this perpetual has gone without any message while the connection as a whole was alive
            # (the daily check reports it: the figure a per-contract silence rule would have to be set by)
            now = time.time(); last = self._seen.get(tok)
            if last and prev.get("ts", 0) >= self.feed._since.get(tok, 0) and now - last > self._gap.get(tok, 0.0):
                self._gap[tok] = now - last
            self._seen[tok] = now
        if t == "l2_orderbook":
            bids = [(float(x["limit_price"]), int(x["size"]), 0) for x in m.get("buy", [])[:5]]
            asks = [(float(x["limit_price"]), int(x["size"]), 0) for x in m.get("sell", [])[:5]]
            d = dict(prev)
            d.update({"token": tok, "bids": bids, "asks": asks, "bid": bids[0][0] if bids else None,
                      "ask": asks[0][0] if asks else None, "ts": time.time()})
            if "ltp" not in d or tok in self._stale_book:
                # first book ever, or first book after a reconnect (the last price in memory is from
                # before the outage): the middle of the new book stands in until the next last-price message
                mid = (bids[0][0] + asks[0][0]) / 2 if bids and asks else None
                if mid is None:
                    return
                d["ltp"] = mid
                self._stale_book.discard(tok)
            d["tbq"] = sum(b[1] for b in bids); d["tsq"] = sum(a[1] for a in asks)
            d["_book_ts"] = time.time()
            self.feed._publish(d)
        elif t == "v2/ticker":
            if tok in self._stale_book:
                return                     # the book in memory is from before the reconnect: wait for the new one
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
                elif time.time() - (d.get("_book_ts") or 0) > QUIET_SECS:
                    # A perpetual gets its order book and its last price in separate messages. When the
                    # book messages stop (or lag) while these go on, the price looks seconds old but the
                    # book that orders are filled against stands still: after a minute with the market 1%
                    # higher a buy was still filled at the old offer (+143,914 coins on a 15,000,000
                    # position, found 20 Nov 2026). This message carries the best bid and offer of its own
                    # moment: they replace the old book until the next book message arrives.
                    d["bids"] = [(bb, bs, 0)] if bs else []
                    d["asks"] = [(ba, as_, 0)] if as_ else []
                    d["bid"] = bb if bs else None; d["ask"] = ba if as_ else None
                    d["tbq"] = bs; d["tsq"] = as_
            elif self.items.get(tok) is not None and self.items[tok].instrument_type == "FUT" and d.get("bids") is not None \
                    and time.time() - (d.get("_book_ts") or 0) > QUIET_SECS:
                # the book is old and this message does not say where the market is: nothing to fill against
                d["bids"] = []; d["asks"] = []; d["bid"] = d["ask"] = None; d["tbq"] = d["tsq"] = 0
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
        ist = lambda ts: (datetime.utcfromtimestamp(ts) + timedelta(hours=5, minutes=30)).strftime("%d %b, %I:%M:%S %p")
        return {"connected": self.connected, "paused": self.paused, "message": self.message, "instruments": len(self.items),
                "subscribed": len(self._subs), "usdinr": self.usdinr(), "fx_source": self.fx_source(),
                "drops": [{"at": ist(d[0]), "lasted_s": d[1], "messages": d[2], "why": d[3]} for d in self.drops[-10:]][::-1]}
