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
        self.load_instruments(items)
        log.info("loaded %d instruments", len(items))

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
            ws.set_mode(ws.MODE_QUOTE, toks)

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
            out.append(d)
        if self.loop:
            self.loop.call_soon_threadsafe(lambda: [self._publish(d) for d in out])

    def _subscribe(self, tokens):
        if self.ticker and self.connected:
            try:
                self.ticker.subscribe(tokens)
                self.ticker.set_mode(self.ticker.MODE_QUOTE, tokens)
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
        to_d = datetime.now()
        # Kite caps the range per request by interval; options/futures are short-lived anyway.
        span = {"minute": 55, "5minute": 95, "15minute": 190, "60minute": 390, "day": 1900}[kint]
        from_d = to_d - timedelta(days=span)
        try:
            rows = self.kite.historical_data(token, from_d, to_d, kint, oi=True)
        except Exception as e:
            log.warning("historical failed %s: %s", ins.symbol, e)
            return hit["data"] if hit else []
        data = [{"time": int(r["date"].timestamp()), "open": r["open"], "high": r["high"], "low": r["low"],
                 "close": r["close"], "volume": r.get("volume", 0), "oi": r.get("oi", 0)} for r in rows]
        cached[key] = {"ts": now, "data": data}
        return data

    def status(self):
        s = super().status()
        s["token_valid_today"] = self.token_valid_today()
        s["needs_login"] = not self.token_valid_today()
        return s
