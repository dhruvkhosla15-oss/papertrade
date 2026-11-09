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
from ..config import ALLOWED_UNDERLYINGS

log = logging.getLogger("kite")

# MCX contract multipliers (units per lot). Price is quoted per unit; P&L = price diff x multiplier x lots.
MCX_MULTIPLIER = {
    "GOLD": 100, "GOLDM": 10, "GOLDGUINEA": 1, "GOLDPETAL": 1, "GOLDTEN": 10,
    "SILVER": 30, "SILVERM": 5, "SILVERMIC": 1,
    "CRUDEOIL": 100, "CRUDEOILM": 10, "NATURALGAS": 1250, "NATGASMINI": 250,
    "COPPER": 2500, "ZINC": 5000, "ZINCMINI": 1000, "ALUMINIUM": 5000, "ALUMINI": 1000,
    "LEAD": 5000, "LEADMINI": 1000, "NICKEL": 1500, "TIN": 1000,
    "MENTHAOIL": 360, "COTTONCNDY": 48, "KAPAS": 200, "CPO": 10, "RUBBER": 1000, "CARDAMOM": 100,
}
MCX_MULTIPLIER.update({k: int(v) for k, v in
                       (p.split(":") for p in __import__("os").getenv("PT_MCX_MULTIPLIERS", "").split(",") if ":" in p)})

INDEX_SYMBOLS = {"NIFTY": ("NSE", "NIFTY 50"), "BANKNIFTY": ("NSE", "NIFTY BANK"),
                 "SENSEX": ("BSE", "SENSEX"), "FINNIFTY": ("NSE", "NIFTY FIN SERVICE"),
                 "MIDCPNIFTY": ("NSE", "NIFTY MID SELECT"), "BANKEX": ("BSE", "BANKEX")}


class KiteFeed(PriceFeed):
    name = "kite"

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
        for exch in ("NSE", "BSE"):
            for row in self.kite.instruments(exch):
                if row["segment"] == "INDICES":
                    for name, (ex, sym) in INDEX_SYMBOLS.items():
                        if ex == exch and row["tradingsymbol"] == sym:
                            items.append(Instrument(row["instrument_token"], name, name, exch, "INDICES",
                                                    "EQ", "", 0, 1, 0.05))
        for exch in ("NFO", "BFO", "MCX"):
            for row in self.kite.instruments(exch):
                if exch != "MCX" and row["name"] not in ALLOWED_UNDERLYINGS:
                    continue
                exp = row["expiry"]
                exp_s = exp.isoformat() if isinstance(exp, (date, datetime)) else (str(exp)[:10] if exp else "")
                items.append(Instrument(row["instrument_token"], row["tradingsymbol"], row["name"], exch,
                                        row["segment"], row["instrument_type"], exp_s,
                                        float(row["strike"] or 0), int(row["lot_size"] or 1),
                                        float(row["tick_size"] or 0.05)))
        # Zerodha's instrument dump quotes MCX quantities in *lots* (lot_size=1) and omits the
        # contract multiplier. P&L and margin need the real multiplier, so apply it here.
        fixed, unknown = 0, set()
        for i in items:
            if i.exchange == "MCX" and i.lot_size <= 1:
                mult = MCX_MULTIPLIER.get(i.name)
                if mult:
                    i.lot_size = mult; fixed += 1
                else:
                    unknown.add(i.name)
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
            bids = [(float(x["price"]), int(x["quantity"]), int(x.get("orders", 0))) for x in depth.get("buy", []) if x.get("quantity")]
            asks = [(float(x["price"]), int(x["quantity"]), int(x.get("orders", 0))) for x in depth.get("sell", []) if x.get("quantity")]
            if ohlc:
                d["open"], d["high"], d["low"] = ohlc.get("open"), ohlc.get("high"), ohlc.get("low")
            d["tbq"] = t.get("total_buy_quantity"); d["tsq"] = t.get("total_sell_quantity")
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
        return s
