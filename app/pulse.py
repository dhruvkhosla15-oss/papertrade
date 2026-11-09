"""
Pulse: top gainers / losers / most traded for Today, This week, This month.

Universe = one row per underlying: index spot, stock spot (NSE cash quote) or MCX near-month future.
- Today's % change comes straight from the live tick (vs previous close).
- Week/month % change uses daily candles (previous closes), refreshed once per IST day in the background.
- "Most traded" = futures turnover (volume x price) of the near-month future, which is what F&O
  trainees actually trade; MCX volume is already in units.
"""
import asyncio
import logging
import threading
import time
from datetime import datetime, timedelta

from .feed.base import kind_of

log = logging.getLogger("app.pulse")
IST = timedelta(hours=5, minutes=30)


class Pulse:
    def __init__(self, feed):
        self.feed = feed
        self._pinned: set = set()
        self._universe_key = -1
        self._universe: list = []
        self._hist: dict = {}          # token -> list of (date_str, close) previous days, oldest first
        self._hist_day = ""            # IST date the history was built for
        self._hist_lock = threading.Lock()
        self._building = False

    # ---- universe ---------------------------------------------------------------------------------
    def universe(self):
        key = len(self.feed.instruments)
        if key == self._universe_key:
            return self._universe
        today = (datetime.utcnow() + IST).date().isoformat()
        out = []
        for exch, names in self.feed.underlyings().items():
            for n in names:
                kind = kind_of(exch, n)
                spot = self.feed.index_token_for(n)
                futs = sorted((i for i in self.feed.instruments.values()
                               if i.name == n and i.instrument_type == "FUT" and i.expiry >= today), key=lambda x: x.expiry)
                fut = futs[0] if futs else None
                if not spot and not fut:
                    continue
                price_tok = fut.token if kind == "mcx" and fut else spot
                if kind == "mcx" and fut:
                    label = "MCX · " + datetime.strptime(fut.expiry, "%Y-%m-%d").strftime("%b") + " fut"
                elif kind == "stock":
                    label = "NSE stock"
                else:
                    label = "BSE index" if exch == "BFO" else "NSE index"
                out.append({"name": n, "kind": kind, "exchange": exch, "spot_token": spot,
                            "fut_token": fut.token if fut else None, "price_token": price_tok,
                            "lot_size": fut.lot_size if fut else 1, "label": label})
        self._universe, self._universe_key = out, key
        # keep these streaming so Pulse is always current
        toks = {t for u in out for t in (u["price_token"], u["fut_token"]) if t} - self._pinned
        if toks:
            self.feed.pin(list(toks)); self._pinned |= toks
        return out

    # ---- history (daily closes) ----------------------------------------------------------------
    def ensure_history(self):
        day = (datetime.utcnow() + IST).date().isoformat()
        if self._hist_day == day or self._building:
            return
        self._building = True
        threading.Thread(target=self._build_history, args=(day,), daemon=True).start()

    def _build_history(self, day):
        try:
            hist = {}
            for u in list(self.universe()):
                tok = u["price_token"]
                try:
                    rows = self.feed.candles(tok, "1d")
                except Exception as e:
                    log.warning("pulse history %s: %s", u["name"], e); rows = []
                closes = []
                for r in rows:
                    d = (datetime.utcfromtimestamp(r["time"]) + IST).date().isoformat()
                    if d < day:
                        closes.append((d, r["close"]))
                hist[tok] = closes[-40:]
                time.sleep(0.35)   # stay under Kite's historical-data rate limit
            with self._hist_lock:
                self._hist = hist; self._hist_day = day
            log.info("pulse history built for %s (%d scrips)", day, len(hist))
        finally:
            self._building = False

    # ---- compute -------------------------------------------------------------------------------------
    def snapshot(self, period="today", kind="all", n=10):
        uni = self.universe()
        self.ensure_history()
        rows = []
        for u in uni:
            if kind != "all" and u["kind"] != kind:
                continue
            p = self.feed.prices.get(u["price_token"]) or {}
            ltp = p.get("ltp")
            if not ltp:
                continue
            closes = self._hist.get(u["price_token"], [])
            pct = None
            if period == "today":
                pct = p.get("change")
            else:
                back = 5 if period == "week" else 21
                if len(closes) >= back:
                    ref = closes[-back][1]
                    pct = round((ltp - ref) / ref * 100, 2) if ref else None
            spark = [c for _, c in closes[-10:]] + [ltp]
            f = self.feed.prices.get(u["fut_token"]) or {} if u["fut_token"] else {}
            vol = f.get("volume") or 0
            fltp = f.get("ltp") or ltp
            turnover = vol * fltp
            rows.append({"name": u["name"], "kind": u["kind"], "exchange": u["exchange"], "token": u["spot_token"] or u["price_token"],
                         "label": u["label"], "ltp": ltp, "pct": pct, "turnover": round(turnover, 2),
                         "lots": int(vol / u["lot_size"]) if u["lot_size"] else vol, "spark": spark})
        ranked = [r for r in rows if r["pct"] is not None]
        gainers = sorted(ranked, key=lambda r: -r["pct"])[:n]
        losers = sorted(ranked, key=lambda r: r["pct"])[:n]
        traded = sorted([r for r in rows if r["turnover"] > 0], key=lambda r: -r["turnover"])[:n]
        return {"period": period, "kind": kind, "asof": time.time(),
                "history_ready": bool(self._hist) and self._hist_day != "",
                "gainers": gainers, "losers": losers, "traded": traded,
                "hero": {"gainer": gainers[0] if gainers else None, "loser": losers[0] if losers else None,
                         "traded": traded[0] if traded else None}}
