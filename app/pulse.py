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
                price_tok = fut.token if kind in ("mcx", "currency") and fut else spot
                if kind == "crypto":
                    label = "Crypto · perpetual"
                elif kind in ("mcx", "currency") and fut:
                    label = ("MCX · " if kind == "mcx" else "NSE currency · ") + datetime.strptime(fut.expiry, "%Y-%m-%d").strftime("%b") + " fut"
                elif kind == "stock":
                    label = "NSE stock"
                else:
                    label = "BSE index" if exch == "BFO" else "NSE index"
                if kind == "crypto":
                    fut = self.feed.instruments.get(spot)      # the perpetual is both spot and traded contract
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
        # don't burn the daily budget before the feed can actually answer (e.g. after midnight,
        # before the morning Zerodha login) — yesterday's reference data stays in use meanwhile
        if not getattr(self.feed, "connected", True):
            return
        if hasattr(self.feed, "token_valid_today") and not self.feed.token_valid_today():
            return
        if time.time() - getattr(self, "_last_attempt", 0) < 600:
            return
        self._last_attempt = time.time()
        self._building = True
        threading.Thread(target=self._build_history, args=(day,), daemon=True).start()

    def _build_history(self, day):
        try:
            hist = {}
            toks = []
            for u in list(self.universe()):
                for t in (u["price_token"], u["fut_token"]):
                    if t and t not in toks:
                        toks.append(t)
            for tok in toks:
                try:
                    rows = self.feed.candles(tok, "1d")
                except Exception as e:
                    log.warning("pulse history %s: %s", tok, e); rows = []
                closes, highs, lows, vols, ois = [], [], [], [], []
                for r in rows:
                    d = (datetime.utcfromtimestamp(r["time"]) + IST).date().isoformat()
                    if d < day:
                        closes.append((d, r["close"])); highs.append(r["high"]); lows.append(r["low"])
                        vols.append(r.get("volume") or 0); ois.append(r.get("oi") or 0)
                if closes:
                    hist[tok] = {"closes": closes[-260:], "hi52": max(highs[-250:]) if highs else None,
                                 "lo52": min(lows[-250:]) if lows else None,
                                 "avg_vol": (sum(vols[-20:]) / len(vols[-20:])) if vols[-20:] else 0,
                                 "prev_oi": ois[-1] if ois else 0,
                                 # last completed session, shown until the next session actually starts
                                 "last": {"date": closes[-1][0], "close": closes[-1][1], "high": highs[-1], "low": lows[-1],
                                          "vol": vols[-1] if vols else 0, "oi": ois[-1] if ois else 0,
                                          "prev_close": closes[-2][1] if len(closes) > 1 else None,
                                          "prev_oi": ois[-2] if len(ois) > 1 else 0,
                                          "avg_vol_before": (sum(vols[-21:-1]) / len(vols[-21:-1])) if len(vols) > 1 else 0}}
                    # publish progressively so the page fills in while the build runs
                    with self._hist_lock:
                        self._hist[tok] = hist[tok]
                time.sleep(0.35)   # stay under Kite's historical-data rate limit
            if len(hist) >= max(10, len(toks) // 2):
                with self._hist_lock:
                    self._hist = hist; self._hist_day = day
                log.info("pulse history built for %s (%d of %d tokens)", day, len(hist), len(toks))
            else:
                log.warning("pulse history build for %s got only %d of %d tokens; keeping previous data, will retry",
                            day, len(hist), len(toks))
        finally:
            self._building = False

    # ---- compute -------------------------------------------------------------------------------------
    def _session_started(self, exchange: str) -> bool:
        """Has today's session for this exchange begun (so live ticks describe *today*)?"""
        try:
            from .market_calendar import _sessions, ist_now
            now = ist_now()
            sessions, _ = _sessions("NFO" if exchange in ("NFO", "BFO", "NSE", "BSE") else exchange, now.date())
            return bool(sessions) and now.time() >= sessions[0][0]
        except Exception:
            return True

    def snapshot(self, period="today", kind="all", n=10):
        uni = self.universe()
        self.ensure_history()
        rows = []
        adv = dec = unch = 0
        started = {ex: self._session_started(ex) for ex in ("NFO", "BFO", "MCX", "CDS", "CRYPTO")}
        session_dates = set(); any_live = False
        for u in uni:
            if kind != "all" and u["kind"] != kind:
                continue
            p = self.feed.prices.get(u["price_token"]) or {}
            h = self._hist.get(u["price_token"]) or {}
            closes = h.get("closes", [])
            live = started.get(u["exchange"], True)
            last = h.get("last") if not live else None
            f = (self.feed.prices.get(u["fut_token"]) or {}) if u["fut_token"] else {}
            fh = (self._hist.get(u["fut_token"]) or {}) if u["fut_token"] else {}
            flast = fh.get("last") if not live else None
            if not live and not last and self._hist:
                continue          # history still filling in for this one; a 0% pre-market tick would mislead
            if live or not last:
                ltp = p.get("ltp")
                if not ltp:
                    continue
                dchg = p.get("change"); high, low, prev_close = p.get("high"), p.get("low"), p.get("close")
                vol = f.get("volume") or 0; fltp = f.get("ltp") or ltp
                avg_vol = fh.get("avg_vol") or 0
                oi = f.get("oi") or 0; prev_oi = fh.get("prev_oi") or 0; fchg = f.get("change")
                hist_closes = closes
                any_live = any_live or live
            else:
                # before today's session: show the last completed session from daily candles
                ltp = last["close"]; prev_close = last["prev_close"]
                dchg = round((ltp - prev_close) / prev_close * 100, 2) if prev_close else None
                high, low = last["high"], last["low"]
                vol = (flast or {}).get("vol") or 0; fltp = (flast or {}).get("close") or ltp
                avg_vol = (flast or {}).get("avg_vol_before") or 0
                oi = (flast or {}).get("oi") or 0; prev_oi = (flast or {}).get("prev_oi") or 0
                fprev = (flast or {}).get("prev_close")
                fchg = round((fltp - fprev) / fprev * 100, 2) if fprev else dchg
                hist_closes = closes[:-1]   # exclude the session being displayed from the look-back
                session_dates.add(last["date"])
            if u["kind"] in ("mcx", "currency") and u["lot_size"] > 1:
                if live:
                    avg_vol *= u["lot_size"]          # live volume is in units, candles in lots
                else:
                    vol *= u["lot_size"]; avg_vol *= u["lot_size"]
            pct = None
            if period == "today":
                pct = dchg
            else:
                back = 5 if period == "week" else 21
                if len(hist_closes) >= back:
                    ref = hist_closes[-back][1]
                    pct = round((ltp - ref) / ref * 100, 2) if ref else None
            if dchg is not None:
                adv += dchg > 0; dec += dchg < 0; unch += dchg == 0
            spark = [c for _, c in hist_closes[-10:]] + [ltp]
            ins_mult = (self.feed.instruments.get(u["fut_token"]).multiplier if (u["kind"] == "crypto" and self.feed.instruments.get(u["fut_token"])) else 1)
            if u["kind"] == "crypto":
                # Delta's ticker volume is in coins and turnover_usd is the 24h notional -> rupees via USDINR
                fx = getattr(self.feed, "usdinr", lambda: 1.0)()
                turnover = (f.get("turnover_usd") or (vol * fltp)) * fx
            else:
                turnover = vol * fltp
            vol_x = round(vol / avg_vol, 2) if avg_vol and vol else None
            oi_chg = round((oi - prev_oi) / prev_oi * 100, 2) if oi and prev_oi else None
            buildup = None
            if oi_chg is not None and fchg is not None and abs(oi_chg) >= 0.5:
                buildup = ("Long build-up" if fchg > 0 else "Short build-up") if oi_chg > 0 else ("Short covering" if fchg > 0 else "Long unwinding")
            hi52, lo52 = h.get("hi52"), h.get("lo52")
            from_hi = round((ltp - hi52) / hi52 * 100, 2) if hi52 else None
            from_lo = round((ltp - lo52) / lo52 * 100, 2) if lo52 else None
            rows.append({"name": u["name"], "kind": u["kind"], "exchange": u["exchange"], "token": u["spot_token"] or u["price_token"],
                         "label": u["label"], "ltp": ltp, "pct": pct, "day_pct": dchg, "high": high, "low": low,
                         "prev_close": prev_close, "turnover": round(turnover, 2),
                         "lots": (int(vol / (ins_mult or 1)) if u["kind"] == "crypto" else (int(vol / u["lot_size"]) if u["lot_size"] else vol)), "spark": spark,
                         "vol_x": vol_x, "oi": oi, "oi_chg": oi_chg, "buildup": buildup,
                         "hi52": hi52, "lo52": lo52, "from_hi": from_hi, "from_lo": from_lo})
        ranked = [r for r in rows if r["pct"] is not None]
        gainers = sorted(ranked, key=lambda r: -r["pct"])[:n]
        losers = sorted(ranked, key=lambda r: r["pct"])[:n]
        traded = sorted([r for r in rows if r["turnover"] > 0], key=lambda r: -r["turnover"])[:n]
        shockers = sorted([r for r in rows if r["vol_x"]], key=lambda r: -r["vol_x"])[:n]
        oi_rows = sorted([r for r in rows if r["oi_chg"] is not None], key=lambda r: -abs(r["oi_chg"]))[:n]
        near_hi = sorted([r for r in rows if r["from_hi"] is not None and r["from_hi"] >= -3], key=lambda r: -r["from_hi"])[:n]
        near_lo = sorted([r for r in rows if r["from_lo"] is not None and r["from_lo"] <= 3], key=lambda r: r["from_lo"])[:n]
        return {"period": period, "kind": kind, "asof": time.time(), "history_ready": bool(self._hist),
                "session": {"live": any_live, "date": max(session_dates) if session_dates else None},
                "breadth": {"adv": adv, "dec": dec, "unch": unch, "total": len(rows)},
                "gainers": gainers, "losers": losers, "traded": traded, "shockers": shockers, "oi": oi_rows,
                "near_hi": near_hi, "near_lo": near_lo,
                "hero": {"gainer": gainers[0] if gainers else None, "loser": losers[0] if losers else None,
                         "traded": traded[0] if traded else None}}
