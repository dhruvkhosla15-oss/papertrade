"""
Zerodha Kite Connect feed.

Flow: admin clicks "Connect Zerodha" -> Kite login page -> redirect back with
request_token -> we exchange it for an access_token (valid until ~6 AM next day)
-> download instrument master -> open KiteTicker WebSocket.
"""
import asyncio
import logging
import time
import threading
from datetime import date, datetime, timedelta
from typing import List
from kiteconnect import KiteConnect, KiteTicker

from .base import PriceFeed, Instrument
from ..config import CURRENCY_PAIRS, ALLOWED_UNDERLYINGS, ALLOW_STOCK_FNO
from .base import INDEX_NAMES

log = logging.getLogger("kite")

# MCX contract multipliers (units per lot). Price is quoted per unit; P&L = price diff x multiplier x lots.
MCX_MULTIPLIER = {
    "GOLD": 100, "GOLDM": 10, "GOLDGUINEA": 1, "GOLDPETAL": 1, "GOLDTEN": 1,
    "SILVER": 30, "SILVERM": 5, "SILVERMIC": 1,
    "CRUDEOIL": 100, "CRUDEOILM": 10, "NATURALGAS": 1250, "NATGASMINI": 250,
    "COPPER": 2500, "COPPERM": 250, "ZINC": 5000, "ZINCMINI": 1000, "ALUMINIUM": 5000, "ALUMINI": 1000,
    "LEAD": 5000, "LEADMINI": 1000, "NICKEL": 1500, "TIN": 1000,
    "MENTHAOIL": 360, "COTTONCNDY": 48, "COTTON": 48, "KAPAS": 200, "CPO": 1000, "RUBBER": 10, "CARDAMOM": 100,
}
# NSE currency futures/options: Zerodha quotes lot_size=1 (one lot); contract = 1,000 units of the base
# currency (JPYINR is priced per 100 JPY for a 1,00,000 JPY contract -> also x1000).
CDS_MULTIPLIER = {"USDINR": 1000, "EURINR": 1000, "GBPINR": 1000, "JPYINR": 1000}
CDS_UNIT = {"USDINR": "USD 1,000", "EURINR": "EUR 1,000", "GBPINR": "GBP 1,000", "JPYINR": "JPY 1,00,000 (price per 100 JPY)"}
# Human-readable contract size (shown on the order ticket)
MCX_UNIT = {
    "GOLD": "1 kg (price per 10 g)", "GOLDM": "100 g (price per 10 g)", "GOLDGUINEA": "8 g", "GOLDPETAL": "1 g", "GOLDTEN": "10 g",
    "SILVER": "30 kg (price per kg)", "SILVERM": "5 kg (price per kg)", "SILVERMIC": "1 kg",
    "CRUDEOIL": "100 barrels", "CRUDEOILM": "10 barrels", "NATURALGAS": "1,250 mmBtu", "NATGASMINI": "250 mmBtu",
    "COPPER": "2,500 kg", "COPPERM": "250 kg", "ZINC": "5 MT (price per kg)", "ZINCMINI": "1 MT (price per kg)",
    "ALUMINIUM": "5 MT (price per kg)", "ALUMINI": "1 MT (price per kg)", "LEAD": "5 MT (price per kg)", "LEADMINI": "1 MT (price per kg)",
    "NICKEL": "1,500 kg", "MENTHAOIL": "360 kg", "COTTONCNDY": "48 candies", "KAPAS": "4 MT (price per 20 kg)",
    "CPO": "10 MT (price per 10 kg)", "RUBBER": "1 MT (price per 100 kg)", "CARDAMOM": "100 kg", "COTTON": "48 candies",
}
MCX_MULTIPLIER.update({k: int(v) for k, v in
                       (p.split(":") for p in __import__("os").getenv("PT_MCX_MULTIPLIERS", "").split(",") if ":" in p)})

INDEX_SYMBOLS = {"NIFTY": ("NSE", "NIFTY 50"), "BANKNIFTY": ("NSE", "NIFTY BANK"),
                 "SENSEX": ("BSE", "SENSEX"), "FINNIFTY": ("NSE", "NIFTY FIN SERVICE"),
                 "MIDCPNIFTY": ("NSE", "NIFTY MID SELECT"), "BANKEX": ("BSE", "BANKEX")}


class KiteFeed(PriceFeed):
    name = "kite"

    cds_all: dict = {}

    def __init__(self, api_key: str, api_secret: str):
        super().__init__()
        self.api_key = api_key
        self.api_secret = api_secret
        self.kite = KiteConnect(api_key=api_key)
        self.access_token = None
        self.ticker: KiteTicker | None = None
        self.token_date: str | None = None
        self.status_msg = "Market data not connected"

    # ---- auth --------------------------------------------------------------
    def login_url(self) -> str:
        return self.kite.login_url()

    def set_access_token(self, access_token: str, token_date: str):
        """Reuse a token saved earlier today."""
        self.access_token = access_token
        self.token_date = token_date
        self.kite.set_access_token(access_token)

    def exchange_request_token(self, request_token: str) -> str:
        data = self.kite.generate_session(request_token, api_secret=self.api_secret)
        self.set_access_token(data["access_token"], date.today().isoformat())
        return data["access_token"]

    def token_valid_today(self) -> bool:
        return bool(self.access_token) and self.token_date == date.today().isoformat()

    # ---- instruments --------------------------------------------------------
    def download_instruments(self):
        items: List[Instrument] = []
        eq_rows = {}   # NSE cash rows by tradingsymbol -> used as spot for stock F&O
        for exch in ("NSE", "BSE"):
            for row in self.kite.instruments(exch):
                if row["segment"] == "INDICES":
                    for name, (ex, sym) in INDEX_SYMBOLS.items():
                        if ex == exch and row["tradingsymbol"] == sym:
                            items.append(Instrument(row["instrument_token"], name, name, exch, "INDICES",
                                                    "EQ", "", 0, 1, 0.05))
                elif exch == "NSE" and row["instrument_type"] == "EQ" and row["segment"] == "NSE":
                    eq_rows[row["tradingsymbol"]] = row
        stock_names = set()
        for exch in ("NFO", "BFO", "MCX", "CDS"):
            for row in self.kite.instruments(exch):
                if exch == "CDS":
                    self.cds_all.setdefault(row["name"], set()).add((row["instrument_type"], int(row["lot_size"] or 0), float(row["tick_size"] or 0)))
                    if row["name"] not in CURRENCY_PAIRS:
                        continue
                elif exch != "MCX" and row["name"] not in ALLOWED_UNDERLYINGS:
                    if not (ALLOW_STOCK_FNO and exch == "NFO" and row["name"] not in INDEX_NAMES and row["name"] in eq_rows):
                        continue
                    stock_names.add(row["name"])
                exp = row["expiry"]
                exp_s = exp.isoformat() if isinstance(exp, (date, datetime)) else (str(exp)[:10] if exp else "")
                items.append(Instrument(row["instrument_token"], row["tradingsymbol"], row["name"], exch,
                                        row["segment"], row["instrument_type"], exp_s,
                                        float(row["strike"] or 0), int(row["lot_size"] or 1),
                                        float(row["tick_size"] or 0.05)))
        # spot price for each stock underlying = its NSE cash quote (view-only, not tradable)
        for n in sorted(stock_names):
            r = eq_rows[n]
            items.append(Instrument(r["instrument_token"], n, n, "NSE", "INDICES", "EQ", "", 0, 1,
                                    float(r["tick_size"] or 0.05)))
        log.info("stock F&O underlyings: %d", len(stock_names))
        # Zerodha's instrument dump quotes MCX quantities in *lots* (lot_size=1) and omits the
        # contract multiplier. P&L and margin need the real multiplier, so apply it here.
        fixed, unknown = 0, set()
        kept = []
        raw_cds = {}
        self.cds_seen = sorted({i.name for i in items if i.exchange == "CDS"})
        for i in items:
            if i.exchange == "MCX" and i.lot_size <= 1:
                mult = MCX_MULTIPLIER.get(i.name)
                if mult:
                    i.lot_size = mult; fixed += 1
                    i.lot_label = MCX_UNIT.get(i.name, "")
                else:
                    unknown.add(i.name)
                    continue  # unknown contract size -> don't offer it rather than risk wrong P&L
            elif i.exchange == "CDS":
                raw_cds.setdefault(i.name, i.lot_size)
                if i.lot_size <= 1:
                    i.lot_size = CDS_MULTIPLIER.get(i.name, 1000)
                i.lot_label = CDS_UNIT.get(i.name, "")
            kept.append(i)
        self.cds_raw_lots = raw_cds
        if raw_cds:
            log.info("currency derivatives: %s (raw lot sizes from Zerodha: %s); all CDS names: %s", sorted(raw_cds), raw_cds, sorted(self.cds_all))
        items = kept
        self.load_instruments(items)
        log.info("loaded %d instruments (MCX multiplier applied to %d; unknown multiplier for %s)",
                 len(items), fixed, sorted(unknown) or "none")

    # ---- websocket ----------------------------------------------------------
    async def start(self, loop):
        await super().start(loop)
        if self.token_valid_today():
            self.connect()

    def connect(self):
        """Call after a valid access token is present."""
        try:
            self.download_instruments()
        except Exception as e:  # token invalid etc.
            self.status_msg = f"instrument download failed: {e}"
            self.connected = False
            return
        if self.ticker:
            try:
                self.ticker.close()
            except Exception:
                pass
        self.ticker = KiteTicker(self.api_key, self.access_token, reconnect=True, reconnect_max_tries=300)
        self.ticker.on_ticks = self._on_ticks
        self.ticker.on_connect = self._on_connect
        self.ticker.on_close = self._on_close
        self.ticker.on_error = lambda ws, code, reason: log.warning("ticker error %s %s", code, reason)
        self.ticker.on_reconnect = lambda ws, n: log.info("ticker reconnect %s", n)
        self.ticker.on_noreconnect = lambda ws: self._set_status(False, "ticker gave up reconnecting")
        self.ticker.connect(threaded=True)
        self.status_msg = "connecting to Kite ticker..."

    def disconnect(self):
        """Master-initiated: close the ticker and stop streaming until reconnect()/connect()."""
        self.paused = True
        if self.ticker:
            try:
                self.ticker.close()
            except Exception:
                pass
            self.ticker = None
        self._set_status(False, "Live feed paused by master")

    def reconnect(self):
        """Master-initiated: re-establish the ticker with today's token (no Zerodha login needed)."""
        self.paused = False
        if not self.token_valid_today():
            self._set_status(False, "Today's Zerodha login is needed first")
            return False
        self.connect()
        return True

    def _set_status(self, connected, msg):
        self.connected = connected
        self.status_msg = msg

    def _on_connect(self, ws, response):
        self._set_status(True, "Live market data")
        toks = list(self._refcount)
        if toks:
            ws.subscribe(toks)
            ws.set_mode(ws.MODE_FULL, toks)

    def _on_close(self, ws, code, reason):
        if getattr(self, "paused", False):
            return
        self._set_status(False, "Market data disconnected — reconnecting")

    def _on_ticks(self, ws, ticks):
        # runs in ticker thread; hand to asyncio loop
        out = []
        for t in ticks:
            d = {"token": t["instrument_token"], "ltp": float(t["last_price"])}
            ohlc = t.get("ohlc") or {}
            if ohlc.get("close"):
                d["close"] = float(ohlc["close"])
                d["change"] = round((d["ltp"] - d["close"]) / d["close"] * 100, 2)
            if "volume_traded" in t:
                d["volume"] = t["volume_traded"]
            if "oi" in t:
                d["oi"] = t["oi"]
            depth = t.get("depth") or {}
            # MCX quantities from Kite are in LOTS; convert to units so they match our lot_size (multiplier)
            ins = self.instruments.get(d["token"])
            m = ins.lot_size if (ins and ins.exchange in ("MCX", "CDS") and ins.lot_size > 1) else 1
            bids = [(float(x["price"]), int(x["quantity"]) * m, int(x.get("orders", 0))) for x in depth.get("buy", []) if x.get("quantity")]
            asks = [(float(x["price"]), int(x["quantity"]) * m, int(x.get("orders", 0))) for x in depth.get("sell", []) if x.get("quantity")]
            if ohlc:
                d["open"], d["high"], d["low"] = ohlc.get("open"), ohlc.get("high"), ohlc.get("low")
            d["tbq"] = (t.get("total_buy_quantity") or 0) * m; d["tsq"] = (t.get("total_sell_quantity") or 0) * m
            if m > 1 and "volume" in d and d["volume"] is not None:
                d["volume"] = d["volume"] * m
            d["qty_in_lots"] = m > 1
            d["bids"] = bids; d["asks"] = asks
            d["bid"] = bids[0][0] if bids else None
            d["ask"] = asks[0][0] if asks else None
            ltt = t.get("last_trade_time")
            if ltt:
                try:
                    d["ltt"] = ltt.timestamp() if hasattr(ltt, "timestamp") else None
                except Exception:
                    pass
            out.append(d)
        if self.loop:
            self.loop.call_soon_threadsafe(lambda: [self._publish(d) for d in out])

    def _subscribe(self, tokens):
        if self.ticker and self.connected:
            try:
                self.ticker.subscribe(tokens)
                self.ticker.set_mode(self.ticker.MODE_FULL, tokens)
            except Exception as e:
                log.warning("subscribe failed: %s", e)

    def _unsubscribe(self, tokens):
        if self.ticker and self.connected:
            try:
                self.ticker.unsubscribe(tokens)
            except Exception as e:
                log.warning("unsubscribe failed: %s", e)

    # ---- historical candles (cached) -------------------------------------------
    _INTERVALS = {"1m": "minute", "5m": "5minute", "15m": "15minute", "1h": "60minute", "1d": "day"}

    def candles(self, token: int, interval: str):
        if not self.token_valid_today():
            return []
        kint = self._INTERVALS.get(interval, "5minute")
        key = (token, kint)
        now = time.time()
        cached = getattr(self, "_candle_cache", None)
        if cached is None:
            self._candle_cache = cached = {}
        hit = cached.get(key)
        ttl = 30 if kint == "minute" else 90
        if hit and now - hit["ts"] < ttl:
            return hit["data"]
        ins = self.instruments.get(token)
        if not ins:
            return []
        # Kite treats naive datetimes as IST, so build the range in IST (server clock is UTC on Railway).
        to_d = datetime.utcnow() + timedelta(hours=5, minutes=30) + timedelta(minutes=5)
        # Kite caps the range per request by interval; options/futures are short-lived anyway.
        span = {"minute": 55, "5minute": 95, "15minute": 190, "60minute": 390, "day": 1900}[kint]
        from_d = to_d - timedelta(days=span)
        if ins.expiry:
            # a contract has no data before it was listed; don't ask for more than ~a year back
            from_d = max(from_d, to_d - timedelta(days=400))
        try:
            rows = self.kite.historical_data(token, from_d, to_d, kint, oi=True)
        except Exception as e:
            log.warning("historical failed %s: %s", ins.symbol, e)
            return hit["data"] if hit else []
        def _ts(d):
            # tz-aware (IST) from kiteconnect -> epoch; if naive, assume IST
            if d.tzinfo is None:
                d = d - timedelta(hours=5, minutes=30)
                return int(d.replace(tzinfo=None).timestamp())
            return int(d.timestamp())
        data = [{"time": _ts(r["date"]), "open": r["open"], "high": r["high"], "low": r["low"],
                 "close": r["close"], "volume": r.get("volume", 0), "oi": r.get("oi", 0)} for r in rows]
        if data:
            log.info("candles %s %s: %d rows, first %s last %s", ins.symbol, kint, len(data), rows[0]["date"], rows[-1]["date"])
        cached[key] = {"ts": now, "data": data}
        return data

    def status(self):
        s = super().status()
        s["token_valid_today"] = self.token_valid_today()
        s["needs_login"] = not self.token_valid_today()
        s["paused"] = bool(getattr(self, "paused", False))
        s["can_reconnect"] = self.token_valid_today() and not self.connected
        # diagnostic: what Zerodha lists on the currency segment and the raw lot sizes it reports
        s["cds"] = {"offered": sorted(getattr(self, "cds_all", {})),
                    "raw": {n: sorted(v) for n, v in getattr(self, "cds_all", {}).items()},
                    "loaded_raw_lot": getattr(self, "cds_raw_lots", {})}
        return s
