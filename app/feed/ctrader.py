"""
Forex (and metals / index CFDs) from a cTrader broker account via Spotware's Open API, JSON over
WebSocket. Attached on top of the primary feed like the Delta extension.

- Symbols come from the broker (IC Markets demo): only what they offer is listed.
- Spot bid/ask plus the broker's depth-of-market ladder (price tiers with liquidity), so fills are
  bounded by visible liquidity exactly like exchange order books.
- Margin: the broker's dynamic leverage for the symbol (first tier) -> initial margin %; stop-out
  (maintenance) at half of that, which is IC Markets' 50% margin level.
- Prices are quoted in the symbol's quote currency (USD, JPY, ...). Rupee value of a 1.0 move on one
  unit = quote-currency -> USD (via the broker's own pair) x USDINR (NSE monthly future).
- 1 lot = 1,000 units (a micro lot), sized for rupee-denominated training accounts.

Env: PT_CTRADER_CLIENT_ID / PT_CTRADER_CLIENT_SECRET / PT_CTRADER_ACCOUNT (broker login number) /
PT_CTRADER_TOKEN (initial access token; later tokens are refreshed and kept in settings).
Protocol reference: https://help.ctrader.com/open-api/ (payload types used are listed in PT_* below).
"""
import asyncio
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone

from .base import Instrument

log = logging.getLogger("app.feed.ctrader")

WS_URL = os.getenv("PT_CTRADER_WS", "wss://demo.ctraderapi.com:5036")
CLIENT_ID = os.getenv("PT_CTRADER_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("PT_CTRADER_CLIENT_SECRET", "")
ACCOUNT_LOGIN = os.getenv("PT_CTRADER_ACCOUNT", "")
ENV_TOKEN = os.getenv("PT_CTRADER_TOKEN", "")
TOKEN_BASE = 6_000_000_000
LOT_UNITS = int(os.getenv("PT_FOREX_LOT_UNITS", "1000"))
# symbols offered (broker names). Everything else the broker lists is ignored.
WANTED = [s.strip().upper() for s in os.getenv(
    "PT_FOREX_SYMBOLS",
    "EURUSD,GBPUSD,USDJPY,USDCHF,AUDUSD,USDCAD,NZDUSD,EURGBP,EURJPY,GBPJPY,EURAUD,AUDJPY,USDINR,XAUUSD,XAGUSD").split(",") if s.strip()]

# World indices, energy and extra metals from the same feed, shown under "Global" (off until PT_GLOBAL_SYMBOLS is set).
GLOBAL = [s.strip().upper() for s in os.getenv("PT_GLOBAL_SYMBOLS", "").split(",") if s.strip()]
GLOBAL_INFO = {   # broker name -> (what the trainee sees, group)
    "US500": ("S&P 500", "US index"), "US30": ("Dow Jones 30", "US index"), "USTEC": ("Nasdaq 100", "US index"), "US2000": ("Russell 2000", "US index"),
    "UK100": ("UK 100", "World index"), "DE40": ("Germany 40", "World index"), "STOXX50": ("Euro Stoxx 50", "World index"),
    "JP225": ("Japan 225", "World index"), "AUS200": ("Australia 200", "World index"), "HK50": ("Hong Kong 50", "World index"),
    "XTIUSD": ("WTI Crude Oil", "Energy"), "XBRUSD": ("Brent Crude Oil", "Energy"), "XNGUSD": ("Natural Gas", "Energy"),
    "XPTUSD": ("Platinum", "Metal"), "XPDUSD": ("Palladium", "Metal"),
}

# ProtoOA payload types
PT_APP_AUTH, PT_APP_AUTH_RES = 2100, 2101
PT_ACC_AUTH, PT_ACC_AUTH_RES = 2102, 2103
PT_ERROR = 2142
PT_ACC_LIST, PT_ACC_LIST_RES = 2149, 2150
PT_SYMBOLS, PT_SYMBOLS_RES = 2114, 2115
PT_SYMBOL_BY_ID, PT_SYMBOL_BY_ID_RES = 2116, 2117
PT_ASSETS, PT_ASSETS_RES = 2112, 2113
PT_SUB_SPOTS, PT_SUB_SPOTS_RES = 2127, 2128
PT_UNSUB_SPOTS = 2129
PT_SPOT_EVENT = 2131
PT_SUB_DEPTH, PT_SUB_DEPTH_RES = 2156, 2157
PT_UNSUB_DEPTH = 2158
PT_DEPTH_EVENT = 2155
PT_TRENDBARS, PT_TRENDBARS_RES = 2137, 2138
# ProtoOATrendbarPeriod: M1=1 M2=2 M3=3 M4=4 M5=5 M10=6 M15=7 M30=8 H1=9 H4=10 H12=11 D1=12 W1=13 MN1=14
D1 = 12
PT_LEVERAGE, PT_LEVERAGE_RES = 2148, 2178
PT_TRADER, PT_TRADER_RES = 2121, 2122     # ProtoOATraderReq -> account leverage (fallback)
PT_REFRESH, PT_REFRESH_RES = 2173, 2174
PT_HEARTBEAT = 51
PRICE_SCALE = 100000.0
VOL_SCALE = 100            # cTrader volumes are in cents of units


class CTraderForex:
    def __init__(self, feed):
        self.feed = feed
        self.items: dict = {}          # token -> Instrument
        self.by_symbol_id: dict = {}   # cTrader symbolId -> token
        self.meta: dict = {}           # token -> {quote asset, digits, leverage...}
        self._subs: set = set()
        self._ws = None
        self._loop = None
        self._msg_id = 0
        self._pending: dict = {}       # clientMsgId -> Future
        self.connected = False
        self.paused = False
        self.message = "not started"
        self.account_id = None
        self.token = None
        self.refresh_token = None
        self._depth: dict = {}         # token -> {quote id: (price, size, side)}
        self._assets: dict = {}        # assetId -> name
        self._orig_sub, self._orig_unsub = feed._subscribe, feed._unsubscribe
        self._orig_candles = feed.candles
        self._orig_vf = getattr(feed, "value_factor", lambda ins: 1.0)
        self._orig_load = feed.load_instruments
        self._orig_index = feed.index_token_for
        feed._subscribe = self._subscribe
        feed._unsubscribe = self._unsubscribe
        feed.candles = self._candles
        feed.value_factor = self.value_factor
        feed.load_instruments = self._load_instruments
        feed.index_token_for = self._index_token_for
        feed.forex = self

    def _index_token_for(self, name):
        for t, i in self.items.items():
            if i.name == name and name != "USDINR":     # NSE currency keeps its own reference for USDINR
                return t
        return self._orig_index(name)

    # ---- instruments -----------------------------------------------------------------------------
    def _load_instruments(self, items):
        self._orig_load(list(items) + list(self.items.values()))

    def _merge(self):
        base = [i for i in self.feed.instruments.values() if i.exchange != "FOREX"]
        self._orig_load(base + list(self.items.values()))

    # ---- helpers for engine / pulse ---------------------------------------------------------------
    def _usdinr(self):
        """Broker's own USDINR quote when it streams (consistent with the broker's conversions),
        else the NSE USDINR monthly future."""
        for t, i in self.items.items():
            if i.symbol == "USDINR":
                p = self.feed.prices.get(t)
                if p and p.get("ltp"):
                    return float(p["ltp"])
        tok = self._orig_index("USDINR")
        p = self.feed.prices.get(tok) if tok else None
        return float(p["ltp"]) if p and p.get("ltp") else None

    def quote_to_inr(self, quote: str):
        """Rupees per 1 unit of the quote currency."""
        if quote == "INR":
            return 1.0
        usdinr = self._usdinr()
        if usdinr is None:
            return None
        if quote == "USD":
            return usdinr
        # quote -> USD via the broker's own pairs (USDJPY -> 1/price; EURUSD -> price)
        for tok, ins in self.items.items():
            p = self.feed.prices.get(tok)
            if not p or not p.get("ltp"):
                continue
            if ins.symbol == f"USD{quote}":
                return usdinr / p["ltp"]
            if ins.symbol == f"{quote}USD":
                return usdinr * p["ltp"]
        return None

    def value_factor(self, ins):
        if ins is None or ins.exchange != "FOREX":
            return self._orig_vf(ins)
        m = self.meta.get(ins.token) or {}
        r = self.quote_to_inr(m.get("quote", "USD"))
        return (r or 0.0) * (ins.multiplier or 1.0)

    def fx_ready(self, ins) -> bool:
        return self.value_factor(ins) > 0

    def market_open(self, token, now=None):
        """(open?, next opening as an IST string) from the contract's own weekly timetable and holidays.
        Only enforced for Global contracts — currency pairs keep the plain 24x5 calendar."""
        m = self.meta.get(token) or {}
        ins = self.items.get(token)
        if not ins or ins.segment != "GLOBAL-SPOT" or not m.get("schedule"):
            return True, ""
        from datetime import datetime, timedelta, timezone
        try:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo(m.get("tz") or "UTC")
        except Exception:
            return True, ""
        now = now or datetime.now(timezone.utc)
        loc = now.astimezone(tz)
        week0 = (loc - timedelta(days=(loc.weekday() + 1) % 7)).replace(hour=0, minute=0, second=0, microsecond=0)   # Sunday 00:00 local
        sec = (loc - week0).total_seconds()
        is_open = any(a <= sec < b for a, b in m["schedule"])
        for h in m.get("holidays", []):
            try:
                hl = now.astimezone(ZoneInfo(h["tz"]))
            except Exception:
                continue
            hd = datetime(1970, 1, 1).date() + timedelta(days=h["day"])
            same = (hl.month, hl.day) == (hd.month, hd.day) if h["recurring"] else hl.date() == hd
            if same:
                s_ = hl.hour * 3600 + hl.minute * 60 + hl.second
                if h["start"] is None or h["end"] is None or int(h["start"]) <= s_ < int(h["end"]):
                    is_open = False
        if is_open:
            return True, ""
        nxt = min((a for a, b in m["schedule"] if a > sec), default=None)
        if nxt is None:
            nxt = min(a for a, b in m["schedule"]) + 7 * 86400
        opens = (week0 + timedelta(seconds=nxt)).astimezone(timezone(timedelta(hours=5, minutes=30)))
        return False, opens.strftime("%a %-I:%M %p") + " IST"

    # ---- token persistence ----------------------------------------------------------------------
    def _load_token(self):
        try:
            from ..db import SessionLocal, get_setting
            db = SessionLocal()
            try:
                t = get_setting(db, "ctrader_token"); r = get_setting(db, "ctrader_refresh")
            finally:
                db.close()
            if t:
                self.token, self.refresh_token = t, r
                return
        except Exception:
            log.exception("ctrader: token load")
        self.token = ENV_TOKEN or None

    def save_token(self, token, refresh=None):
        self.token = token
        if refresh:
            self.refresh_token = refresh
        try:
            from ..db import SessionLocal, set_setting
            db = SessionLocal()
            try:
                set_setting(db, "ctrader_token", token)
                if refresh:
                    set_setting(db, "ctrader_refresh", refresh)
                db.commit()
            finally:
                db.close()
        except Exception:
            log.exception("ctrader: token save")

    # ---- websocket plumbing ------------------------------------------------------------------------
    async def _send(self, payload_type, payload, wait=True, timeout=15):
        self._msg_id += 1
        mid = str(self._msg_id)
        fut = self._loop.create_future() if wait else None
        if wait:
            self._pending[mid] = fut
        await self._ws.send(json.dumps({"clientMsgId": mid, "payloadType": payload_type, "payload": payload}))
        if not wait:
            return None
        try:
            return await asyncio.wait_for(fut, timeout)
        finally:
            self._pending.pop(mid, None)

    def _send_nowait(self, payload_type, payload):
        if self._ws and self._loop:
            asyncio.run_coroutine_threadsafe(self._send(payload_type, payload, wait=False), self._loop)

    async def start(self, loop):
        self._loop = loop
        self._load_token()
        if not (CLIENT_ID and CLIENT_SECRET):
            self.message = "not configured (PT_CTRADER_CLIENT_ID/SECRET missing)"
            log.info("ctrader: %s", self.message)
            return
        loop.create_task(self._run())

    async def _run(self):
        import websockets
        while True:
            if self.paused or not self.token:
                self.message = "paused by master" if self.paused else "waiting for access token (master panel → Connect forex)"
                await asyncio.sleep(3)
                continue
            try:
                async with websockets.connect(WS_URL, ping_interval=None, max_size=8_000_000) as ws:
                    self._ws = ws
                    reader = self._loop.create_task(self._reader(ws))
                    try:
                        await self._session()
                        self.connected = True
                        self.message = "cTrader live"
                        hb = 0
                        while not self.paused:
                            await asyncio.sleep(1)
                            hb += 1
                            if hb % 10 == 0:
                                await self._send(PT_HEARTBEAT, {}, wait=False)
                            if reader.done():
                                break
                    finally:
                        reader.cancel()
            except Exception as e:
                log.warning("ctrader: connection error: %s", e)
                self.message = f"reconnecting ({str(e)[:80]})"
            self.connected = False; self._ws = None
            await asyncio.sleep(5)

    async def _reader(self, ws):
        async for raw in ws:
            try:
                m = json.loads(raw)
            except Exception:
                continue
            mid = m.get("clientMsgId")
            fut = self._pending.get(mid) if mid else None
            if fut and not fut.done():
                fut.set_result(m)
            self._handle(m)

    async def _session(self):
        r = await self._send(PT_APP_AUTH, {"clientId": CLIENT_ID, "clientSecret": CLIENT_SECRET})
        if r.get("payloadType") != PT_APP_AUTH_RES:
            raise RuntimeError("app auth: " + json.dumps(r.get("payload"))[:200])
        # find the ctidTraderAccountId for the broker login
        r = await self._send(PT_ACC_LIST, {"accessToken": self.token})
        if r.get("payloadType") == PT_ERROR:
            desc = (r.get("payload") or {}).get("errorCode", "")
            if "TOKEN" in desc.upper() and self.refresh_token:
                rr = await self._send(PT_REFRESH, {"refreshToken": self.refresh_token})
                if rr.get("payloadType") == PT_REFRESH_RES:
                    p = rr["payload"]; self.save_token(p["accessToken"], p.get("refreshToken"))
                    r = await self._send(PT_ACC_LIST, {"accessToken": self.token})
            if r.get("payloadType") == PT_ERROR:
                raise RuntimeError("account list: " + json.dumps(r.get("payload"))[:200])
        accs = r["payload"].get("ctidTraderAccount", [])
        acc = next((a for a in accs if str(a.get("traderLogin")) == str(ACCOUNT_LOGIN)), None) or (accs[0] if accs else None)
        if not acc:
            raise RuntimeError("no trading account on this token")
        self.account_id = int(acc["ctidTraderAccountId"])
        r = await self._send(PT_ACC_AUTH, {"ctidTraderAccountId": self.account_id, "accessToken": self.token})
        if r.get("payloadType") != PT_ACC_AUTH_RES:
            raise RuntimeError("account auth: " + json.dumps(r.get("payload"))[:200])
        if not self.items:
            await self._load_symbols()
        if self._subs:
            ids = [self.items[t].token - TOKEN_BASE for t in self._subs if t in self.items]
            await self._send(PT_SUB_SPOTS, {"ctidTraderAccountId": self.account_id, "symbolId": ids})
            await self._send(PT_SUB_DEPTH, {"ctidTraderAccountId": self.account_id, "symbolId": ids})

    async def _load_symbols(self):
        r = await self._send(PT_ASSETS, {"ctidTraderAccountId": self.account_id})
        for a in (r.get("payload") or {}).get("asset", []):
            self._assets[int(a["assetId"])] = a["name"]
        r = await self._send(PT_SYMBOLS, {"ctidTraderAccountId": self.account_id, "includeArchivedSymbols": False}, timeout=30)
        every = (r.get("payload") or {}).get("symbol", [])
        cats = {}
        try:   # category names (Forex, Indices, Shares…) — only used by the master's "what does this account carry" list
            rc = await self._send(2160, {"ctidTraderAccountId": self.account_id}, timeout=15)
            cats = {int(c["id"]): c.get("name", "") for c in (rc.get("payload") or {}).get("symbolCategory", [])}
        except Exception:
            pass
        self._all_ids = {s.get("symbolName", "").upper(): int(s["symbolId"]) for s in every if s.get("symbolName")}
        self.all_symbols = sorted(({"name": s.get("symbolName", ""), "desc": s.get("description", ""), "enabled": bool(s.get("enabled", True)),
                                    "base": self._assets.get(int(s.get("baseAssetId", 0) or 0), ""), "quote": self._assets.get(int(s.get("quoteAssetId", 0) or 0), ""),
                                    "category": cats.get(int(s.get("symbolCategoryId", 0) or 0), "")} for s in every), key=lambda x: (x["category"], x["name"]))
        light = [s for s in every if s.get("symbolName", "").upper() in WANTED + GLOBAL and s.get("enabled", True)]
        if not light:
            log.warning("ctrader: none of %s found among %d broker symbols", WANTED, len((r.get("payload") or {}).get("symbol", [])))
            return
        ids = [int(s["symbolId"]) for s in light]
        r = await self._send(PT_SYMBOL_BY_ID, {"ctidTraderAccountId": self.account_id, "symbolId": ids}, timeout=30)
        full = {int(s["symbolId"]): s for s in (r.get("payload") or {}).get("symbol", [])}
        lev_cache = {}
        items = {}
        self.diag = {}
        acct_lev = None
        try:                                   # account-level leverage, used when a symbol has no dynamic tiers
            rr = await self._send(PT_TRADER, {"ctidTraderAccountId": self.account_id}, timeout=15)
            lic = ((rr.get("payload") or {}).get("trader") or {}).get("leverageInCents")
            acct_lev = int(lic) / 100.0 if lic else None
        except Exception as e:
            self.diag["trader_err"] = str(e)[:120]
        for s in light:
            sid = int(s["symbolId"]); d = full.get(sid, {})
            tok = TOKEN_BASE + sid
            digits = int(d.get("digits", 5))
            quote = self._assets.get(int(s.get("quoteAssetId", 0)), "USD")
            base = self._assets.get(int(s.get("baseAssetId", 0)), s["symbolName"][:3])
            lev_id = d.get("leverageId")
            lev = None
            if lev_id is not None:
                if lev_id not in lev_cache:
                    try:
                        rr = await self._send(PT_LEVERAGE, {"ctidTraderAccountId": self.account_id, "leverageId": int(lev_id)})
                        tiers = ((rr.get("payload") or {}).get("leverage") or {}).get("tiers", [])
                        lev_cache[lev_id] = (int(tiers[0]["leverage"]) / 100.0) if tiers else None
                    except Exception as e:
                        lev_cache[lev_id] = None
                        self.diag[f"lev_err_{lev_id}"] = str(e)[:120]
                lev = lev_cache[lev_id]
            lev = lev or acct_lev
            init_pct = (100.0 / lev) if lev else 1.0          # 1:500 -> 0.2 %
            name = s["symbolName"].upper()
            # One limeFX lot = the broker's minimum volume (0.01 standard lot): 1,000 units for a currency
            # pair, 1 oz for gold, 50 oz for silver. A flat 1,000 units made gold a ₹38 lakh-margin contract.
            min_vol = int(int(d.get("minVolume", 0)) / VOL_SCALE) if d.get("minVolume") else 0
            lot_units = min_vol or LOT_UNITS
            unit = "oz" if base in ("XAU", "XAG", "XPT", "XPD") else base
            is_global = name in GLOBAL
            if is_global:
                # an index's minimum is a fraction of one index (0.1): one limeFX lot = 1 index, never the 1,000-unit forex default
                lot_units = max(1, min_vol)
                grp = GLOBAL_INFO.get(name, (name, "Global"))[1]
                unit = {"XTI": "barrel", "XBR": "barrel", "XNG": "MMBtu"}.get(name[:3], "oz" if grp == "Metal" else "× index")
                from .base import GLOBAL_NAMES
                GLOBAL_NAMES.add(name)
            items[tok] = Instrument(tok, name, name, "FOREX", "GLOBAL-SPOT" if is_global else "FOREX-SPOT", "FUT", "", 0, lot_units,
                                    10 ** (-digits), f"{lot_units:,} {unit} (price in {quote})",
                                    multiplier=1.0, init_margin_pct=round(init_pct, 4), maint_margin_pct=round(init_pct / 2, 4),
                                    pos_limit=int(int(d.get("maxVolume", 0)) / VOL_SCALE) if d.get("maxVolume") else 0,
                                    leverage_options=tuple(s for s in (1, 2, 5, 10, 20, 30, 50, 100, 200, 500) if s <= (lev or 1)))
            self.diag[name] = {"lev_id": lev_id, "lev": lev, "min_vol": min_vol, "lot": lot_units}
            self.meta[tok] = {"quote": quote, "base": base, "digits": digits, "leverage": lev,
                              "min_volume": int(int(d.get("minVolume", 0)) / VOL_SCALE) if d.get("minVolume") else 0,
                              "description": s.get("description", ""),
                              "title": GLOBAL_INFO.get(name, ("", ""))[0] if is_global else "", "group": GLOBAL_INFO.get(name, ("", "Global"))[1] if is_global else "",
                              "tz": d.get("scheduleTimeZone") or "UTC", "schedule": [(int(x["startSecond"]), int(x["endSecond"])) for x in d.get("schedule", [])],
                              "holidays": [{"day": int(h.get("holidayDate", -1)), "tz": h.get("scheduleTimeZone") or d.get("scheduleTimeZone") or "UTC",
                                            "start": h.get("startSecond"), "end": h.get("endSecond"), "recurring": bool(h.get("isRecurring"))}
                                           for h in d.get("holiday", [])]}
        self.items = items
        self.by_symbol_id = {t - TOKEN_BASE: t for t in items}
        self._merge()
        log.info("ctrader: %d forex symbols loaded: %s", len(items), sorted(i.symbol for i in items.values()))
        # conversion pairs must always stream: USDINR (if the broker has it) and the USD legs of cross pairs
        pin = [t for t, i in items.items() if i.symbol in ("USDINR",) or i.symbol.startswith("USD") or i.symbol.endswith("USD") or i.segment == "GLOBAL-SPOT"]
        self.feed.pin(pin)

    # ---- events --------------------------------------------------------------------------------------
    async def probe(self, names, secs=8):
        """Master diagnostic: full contract details + a few seconds of live quotes for symbols limeFX does not offer yet."""
        ids = {n: self._all_ids.get(n.upper()) for n in names}
        want = [i for i in ids.values() if i]
        if not want:
            return {"error": "none of these symbols exist on the account", "asked": names}
        r = await self._send(PT_SYMBOL_BY_ID, {"ctidTraderAccountId": self.account_id, "symbolId": want}, timeout=30)
        full = {int(x["symbolId"]): x for x in (r.get("payload") or {}).get("symbol", [])}
        self._probe = {i: {"ticks": 0} for i in want if i not in self.by_symbol_id}
        if self._probe:
            await self._send(PT_SUB_SPOTS, {"ctidTraderAccountId": self.account_id, "symbolId": list(self._probe)}, wait=False)
        await asyncio.sleep(secs)
        got = self._probe; self._probe = {}
        if got:
            await self._send(PT_UNSUB_SPOTS, {"ctidTraderAccountId": self.account_id, "symbolId": list(got)}, wait=False)
        out = {}
        for n, i in ids.items():
            if not i:
                out[n] = {"missing": True}; continue
            d = full.get(i, {})
            keep = {k: d.get(k) for k in ("digits", "pipPosition", "lotSize", "minVolume", "maxVolume", "stepVolume", "leverageId", "tradingMode",
                                         "scheduleTimeZone", "schedule", "holiday", "measurementUnits", "enableShortSelling", "swapLong", "swapShort")}
            keep["quote"] = got.get(i) or ({"already_live": True} if i in self.by_symbol_id else {})
            a = next((x for x in getattr(self, "all_symbols", []) if x["name"].upper() == n.upper()), {})
            keep["base_asset"], keep["quote_asset"] = a.get("base"), a.get("quote")
            if d.get("leverageId") is not None:
                try:
                    rr = await self._send(PT_LEVERAGE, {"ctidTraderAccountId": self.account_id, "leverageId": int(d["leverageId"])})
                    keep["leverage_tiers"] = [(int(t.get("volume", 0)), int(t["leverage"]) / 100.0) for t in ((rr.get("payload") or {}).get("leverage") or {}).get("tiers", [])]
                except Exception as e:
                    keep["leverage_tiers"] = "error: " + type(e).__name__
            out[n] = keep
        return out

    def _handle(self, m):
        pt = m.get("payloadType"); p = m.get("payload") or {}
        if pt == PT_SPOT_EVENT and getattr(self, "_probe", None) and int(p.get("symbolId", -1)) in self._probe:
            q = self._probe[int(p["symbolId"])]
            q["ticks"] += 1
            for k in ("bid", "ask"):
                if p.get(k) is not None:
                    q[k] = int(p[k]) / PRICE_SCALE
            return
        if pt == PT_SPOT_EVENT:
            tok = self.by_symbol_id.get(int(p.get("symbolId", -1)))
            if not tok:
                return
            prev = dict(self.feed.prices.get(tok) or {})
            d = prev
            if p.get("bid") is not None:
                d["bid"] = int(p["bid"]) / PRICE_SCALE
            if p.get("ask") is not None:
                d["ask"] = int(p["ask"]) / PRICE_SCALE
            if d.get("bid") is None or d.get("ask") is None:
                return
            mid = (d["bid"] + d["ask"]) / 2
            d.update({"token": tok, "ltp": round(mid, 6), "ltt": time.time(), "ts": time.time()})
            tb = p.get("trendbar") or []
            for bar in tb:
                if int(bar.get("period", 0)) == D1:    # D1
                    low = int(bar.get("low", 0)) / PRICE_SCALE
                    d["open"] = low + int(bar.get("deltaOpen", 0)) / PRICE_SCALE
                    d["high"] = low + int(bar.get("deltaHigh", 0)) / PRICE_SCALE
                    d["low"] = low
            # Day high/low: the spot stream carries no session range, so keep it ourselves — seeded from
            # today's daily candle (see candles()) and extended tick by tick. The forex day rolls at
            # 22:00 UTC (5 pm New York).
            fxday = int((time.time() + 2 * 3600) // 86400)
            if d.get("_hlday") != fxday:
                if d.get("_hlday") is not None or d.get("high") is None:
                    d["high"] = d["low"] = d["ltp"]; d["open"] = d["ltp"]
                d["_hlday"] = fxday
            d["high"] = max(d.get("high") or d["ltp"], d["ltp"]); d["low"] = min(d.get("low") or d["ltp"], d["ltp"])
            if "bids" not in d:
                # no depth yet: top of book with the broker's typical liquidity unknown -> 1 lot each side
                _lot = self.items[tok].lot_size if tok in self.items else LOT_UNITS
                d["bids"] = [(d["bid"], _lot * 100, 0)]; d["asks"] = [(d["ask"], _lot * 100, 0)]
            if d.get("close"):
                d["change"] = round((d["ltp"] - d["close"]) / d["close"] * 100, 2)
            self.feed._publish(d)
        elif pt == PT_DEPTH_EVENT:
            tok = self.by_symbol_id.get(int(p.get("symbolId", -1)))
            if not tok:
                return
            book = self._depth.setdefault(tok, {})
            for q in p.get("newQuotes", []):
                qid = int(q["id"]); size = int(int(q.get("size", 0)) / VOL_SCALE)
                if q.get("bid") is not None:
                    book[qid] = (int(q["bid"]) / PRICE_SCALE, size, "bid")
                elif q.get("ask") is not None:
                    book[qid] = (int(q["ask"]) / PRICE_SCALE, size, "ask")
            for qid in p.get("deletedQuotes", []):
                book.pop(int(qid), None)
            bids = sorted(((px, sz, 0) for px, sz, side in book.values() if side == "bid" and sz > 0), key=lambda x: -x[0])[:5]
            asks = sorted(((px, sz, 0) for px, sz, side in book.values() if side == "ask" and sz > 0), key=lambda x: x[0])[:5]
            if bids and asks and bids[0][0] >= asks[0][0]:
                # crossed ladder = stale quotes we missed a delete for; drop them and keep only the fresh ones
                fresh = {int(q["id"]) for q in p.get("newQuotes", [])}
                for k in list(book):
                    if k not in fresh:
                        book.pop(k)
                bids = sorted(((px, sz, 0) for px, sz, side in book.values() if side == "bid" and sz > 0), key=lambda x: -x[0])[:5]
                asks = sorted(((px, sz, 0) for px, sz, side in book.values() if side == "ask" and sz > 0), key=lambda x: x[0])[:5]
            d = dict(self.feed.prices.get(tok) or {"token": tok})
            d.update({"token": tok, "bids": bids, "asks": asks, "ts": time.time(),
                      "tbq": sum(b[1] for b in bids), "tsq": sum(a[1] for a in asks)})
            if bids:
                d["bid"] = bids[0][0]
            if asks:
                d["ask"] = asks[0][0]
            if d.get("bid") is not None and d.get("ask") is not None:
                d["ltp"] = round((d["bid"] + d["ask"]) / 2, 6)
                self.feed._publish(d)

    # ---- subscriptions ----------------------------------------------------------------------------
    def _split(self, tokens):
        return [t for t in tokens if t in self.items], [t for t in tokens if t not in self.items]

    def _subscribe(self, tokens):
        mine, other = self._split(tokens)
        if other:
            self._orig_sub(other)
        if mine:
            self._subs |= set(mine)
            if self.connected and self.account_id:
                ids = [t - TOKEN_BASE for t in mine]
                self._send_nowait(PT_SUB_SPOTS, {"ctidTraderAccountId": self.account_id, "symbolId": ids})
                self._send_nowait(PT_SUB_DEPTH, {"ctidTraderAccountId": self.account_id, "symbolId": ids})

    def _unsubscribe(self, tokens):
        mine, other = self._split(tokens)
        if other:
            self._orig_unsub(other)
        if mine:
            self._subs -= set(mine)
            if self.connected and self.account_id:
                ids = [t - TOKEN_BASE for t in mine]
                self._send_nowait(PT_UNSUB_DEPTH, {"ctidTraderAccountId": self.account_id, "symbolId": ids})
                self._send_nowait(PT_UNSUB_SPOTS, {"ctidTraderAccountId": self.account_id, "symbolId": ids})
                for t in mine:
                    self._depth.pop(t, None)

    # ---- candles ---------------------------------------------------------------------------------------
    def _candles(self, token, interval):
        if token not in self.items or not (self.connected and self._loop):
            return self._orig_candles(token, interval) if token not in self.items else []
        period = {"1d": D1, "1h": 9, "15m": 7, "5m": 5, "1m": 1}.get(interval, D1)   # ProtoOATrendbarPeriod
        end = int(time.time() * 1000)
        # cTrader caps the span per period (D1: one year, intraday: a few weeks) — stay inside it
        start = end - (360 * 86400 * 1000 if period == D1 else 5 * 86400 * 1000)
        fut = asyncio.run_coroutine_threadsafe(
            self._send(PT_TRENDBARS, {"ctidTraderAccountId": self.account_id, "fromTimestamp": start, "toTimestamp": end,
                                      "period": period, "symbolId": token - TOKEN_BASE, "count": 400}, timeout=30), self._loop)
        r = fut.result(35)
        if r.get("payloadType") == 2142:
            self.diag["candles_err"] = str((r.get("payload") or {}).get("description", ""))[:120]
            log.warning("ctrader: trendbars error for %s: %s", token, (r.get("payload") or {}))
            return []
        out = []
        for b in (r.get("payload") or {}).get("trendbar", []):
            low = int(b.get("low", 0)) / PRICE_SCALE
            out.append({"time": int(b["utcTimestampInMinutes"]) * 60, "open": low + int(b.get("deltaOpen", 0)) / PRICE_SCALE,
                        "high": low + int(b.get("deltaHigh", 0)) / PRICE_SCALE, "low": low,
                        "close": low + int(b.get("deltaClose", 0)) / PRICE_SCALE, "volume": int(b.get("volume", 0)), "oi": 0})
        out.sort(key=lambda x: x["time"])
        if period == D1 and out and time.time() - out[-1]["time"] < 86400:
            # today's (still forming) daily bar gives the true session range so far
            cur = self.feed.prices.get(token)
            if cur is not None:
                t = out[-1]
                cur["open"] = t["open"]; cur["high"] = max(t["high"], cur.get("ltp") or t["high"]); cur["low"] = min(t["low"], cur.get("ltp") or t["low"])
                cur["_hlday"] = int((time.time() + 2 * 3600) // 86400)
        return out

    # ---- master controls --------------------------------------------------------------------------------
    def disconnect(self):
        self.paused = True
        if self._ws and self._loop:
            asyncio.run_coroutine_threadsafe(self._ws.close(), self._loop)
        self.connected = False; self.message = "paused by master"

    def reconnect(self):
        self.paused = False; self.message = "reconnecting"
        return True

    def status(self):
        return {"configured": bool(CLIENT_ID and CLIENT_SECRET), "has_token": bool(self.token), "connected": self.connected,
                "paused": self.paused, "message": self.message, "instruments": len(self.items), "subscribed": len(self._subs),
                "account": ACCOUNT_LOGIN, "usdinr": self._usdinr(), "diag": getattr(self, "diag", {})}
