"""
Simulated feed: realistic-looking random-walk prices for NIFTY / BANKNIFTY / SENSEX
option chains + futures, and MCX futures/options. Used for development and demos.
"""
import asyncio
import math
import random
import time
from datetime import date, timedelta
from typing import List
from .base import PriceFeed, Instrument

random.seed(7)

INDICES = {  # name: (exchange for F&O, spot, strike step, lot size, annual vol)
    "NIFTY": ("NFO", 24300.0, 50, 75, 0.14),
    "BANKNIFTY": ("NFO", 52400.0, 100, 35, 0.18),
    "SENSEX": ("BFO", 79800.0, 100, 20, 0.14),
}
MCX = {  # name: (price, tick, lot, vol, strike step)
    "CRUDEOIL": (5800.0, 1.0, 100, 0.35, 50),
    "NATURALGAS": (260.0, 0.1, 1250, 0.60, 5),
    "GOLD": (76500.0, 1.0, 100, 0.14, 100),
    "GOLDM": (76500.0, 1.0, 10, 0.14, 100),
    "SILVER": (92000.0, 1.0, 30, 0.22, 250),
    "SILVERM": (92000.0, 1.0, 5, 0.22, 250),
    "COPPER": (820.0, 0.05, 2500, 0.20, 5),
    "ZINC": (280.0, 0.05, 5000, 0.20, 2.5),
    "ALUMINIUM": (240.0, 0.05, 5000, 0.18, 1),
}


def _n(x):  # standard normal cdf
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs(spot, strike, t_years, vol, kind, r=0.065):
    t = max(t_years, 1 / (365 * 24))
    d1 = (math.log(spot / strike) + (r + vol * vol / 2) * t) / (vol * math.sqrt(t))
    d2 = d1 - vol * math.sqrt(t)
    if kind == "CE":
        return spot * _n(d1) - strike * math.exp(-r * t) * _n(d2)
    return strike * math.exp(-r * t) * _n(-d2) - spot * _n(-d1)


def _weekly_expiries(weekday, n):
    today = date.today()
    d = today + timedelta((weekday - today.weekday()) % 7)
    return [d + timedelta(weeks=i) for i in range(n)]


def _month_end_expiry(months_ahead):
    today = date.today()
    y, m = today.year, today.month + months_ahead
    while m > 12:
        m -= 12; y += 1
    nxt_y, nxt_m = (y, m + 1) if m < 12 else (y + 1, 1)
    last = date(nxt_y, nxt_m, 1) - timedelta(days=1)
    while last.weekday() > 4:
        last -= timedelta(days=1)
    return last


def _sym(name, exp: date, strike=None, kind="FUT"):
    mon = exp.strftime("%b").upper()
    yy = exp.strftime("%y")
    if kind == "FUT":
        return f"{name}{yy}{mon}FUT"
    return f"{name}{yy}{mon}{int(strike) if strike == int(strike) else strike}{kind}"


class MockFeed(PriceFeed):
    name = "mock"

    def __init__(self):
        super().__init__()
        self.spot = {}
        self.vol = {}
        self._build()

    def _build(self):
        items: List[Instrument] = []
        tok = 100000
        # index spot
        for name, (exch, spot, step, lot, vol) in INDICES.items():
            self.spot[name] = spot
            self.vol[name] = vol
            tok += 1
            items.append(Instrument(tok, name, name, "NSE" if exch == "NFO" else "BSE",
                                    "INDICES", "EQ", "", 0, 1, 0.05))
            expiries = _weekly_expiries(1 if name == "NIFTY" else (3 if name == "BANKNIFTY" else 1), 3)
            expiries += [_month_end_expiry(1)]
            for exp in sorted(set(expiries)):
                e = exp.isoformat()
                tok += 1
                items.append(Instrument(tok, _sym(name, exp), name, exch, f"{exch}-FUT", "FUT", e, 0, lot, 0.05))
                atm = round(spot / step) * step
                for k in range(-25, 26):
                    strike = atm + k * step
                    for kind in ("CE", "PE"):
                        tok += 1
                        items.append(Instrument(tok, _sym(name, exp, strike, kind), name, exch,
                                                f"{exch}-OPT", kind, e, strike, lot, 0.05))
        # MCX
        for name, (price, tick, lot, vol, step) in MCX.items():
            self.spot[name] = price
            self.vol[name] = vol
            for mi in (0, 1, 2):
                exp = _month_end_expiry(mi) - timedelta(days=10)
                e = exp.isoformat()
                tok += 1
                items.append(Instrument(tok, _sym(name, exp), name, "MCX", "MCX-FUT", "FUT", e, 0, lot, tick))
                if mi == 0 and name in ("CRUDEOIL", "NATURALGAS", "GOLD", "SILVER", "COPPER"):
                    atm = round(price / step) * step
                    for k in range(-12, 13):
                        strike = atm + k * step
                        for kind in ("CE", "PE"):
                            tok += 1
                            items.append(Instrument(tok, _sym(name, exp, strike, kind), name, "MCX",
                                                    "MCX-OPT", kind, e, strike, lot, tick))
        self.load_instruments(items)

    def _price(self, ins: Instrument) -> float:
        s = self.spot[ins.name]
        if ins.segment == "INDICES":
            return s
        exp = date.fromisoformat(ins.expiry)
        t = max((exp - date.today()).days + 0.3, 0.05) / 365
        if ins.instrument_type == "FUT":
            p = s * math.exp(0.065 * t)
        else:
            p = bs(s, ins.strike, t, self.vol[ins.name], ins.instrument_type)
            p += random.uniform(-0.3, 0.3) * ins.tick_size
        p = max(ins.tick_size, round(p / ins.tick_size) * ins.tick_size)
        return round(p, 2)

    def candles(self, token, interval):
        ins = self.instruments.get(token)
        if not ins:
            return []
        step = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "1d": 86400}.get(interval, 300)
        n = 300
        now = int(time.time()) // step * step
        p = self.ltp(token) or self._price(ins)
        rng = random.Random(token)
        out = []
        # walk backwards then reverse
        closes = [p]
        for _ in range(n - 1):
            closes.append(max(ins.tick_size, closes[-1] * math.exp(rng.gauss(0, 0.004 * math.sqrt(step / 300)))))
        closes.reverse()
        for i, c in enumerate(closes):
            o = closes[i - 1] if i else c
            h = max(o, c) * (1 + abs(rng.gauss(0, 0.002))); l = min(o, c) * (1 - abs(rng.gauss(0, 0.002)))
            out.append({"time": now - (n - 1 - i) * step, "open": round(o, 2), "high": round(h, 2), "low": round(l, 2),
                        "close": round(c, 2), "volume": rng.randint(100, 5000), "oi": 0})
        return out

    async def start(self, loop):
        await super().start(loop)
        self.connected = True
        self.status_msg = "simulated prices"
        asyncio.create_task(self._run())

    async def _run(self):
        while True:
            dt = 0.5
            for name in self.spot:
                vol = self.vol[name]
                step = vol * math.sqrt(dt / (252 * 6.25 * 3600))
                self.spot[name] *= math.exp(random.gauss(0, step))
            now = time.time()
            for t in list(self._refcount):
                ins = self.instruments[t]
                ltp = self._price(ins)
                prev = self.prices.get(t, {})
                close = prev.get("close") or ltp * (1 + random.uniform(-0.01, 0.01))
                # synthetic order book: liquid near ATM, wide/empty far OTM (to exercise liquidity rules)
                tick = ins.tick_size
                dist = 0
                if ins.instrument_type in ("CE", "PE"):
                    dist = abs(ins.strike - self.spot[ins.name]) / self.spot[ins.name]
                if dist > 0.09 and ins.exchange != "MCX":
                    bids, asks = [], []            # dead strike: no book at all
                elif dist > 0.06:
                    bids = [(round(ltp * 0.9, 2), ins.lot_size)]; asks = [(round(ltp * 1.1, 2), ins.lot_size)]
                else:
                    lots = ins.lot_size
                    bids = [(round(max(tick, ltp - tick * (i + 1)), 2), lots * random.randint(3, 40)) for i in range(5)]
                    asks = [(round(ltp + tick * (i + 1), 2), lots * random.randint(3, 40)) for i in range(5)]
                self._publish({"token": t, "ltp": ltp, "ts": now, "close": round(close, 2),
                               "change": round((ltp - close) / close * 100, 2) if close else 0,
                               "volume": prev.get("volume", random.randint(100, 50000)) + random.randint(0, 50),
                               "oi": prev.get("oi", random.randint(1000, 900000)),
                               "bids": bids, "asks": asks, "bid": bids[0][0] if bids else None,
                               "ask": asks[0][0] if asks else None, "ltt": now})
            await asyncio.sleep(dt)
