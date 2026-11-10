"""
Price feed abstraction.

An Instrument is one tradable contract (or an index).
A feed keeps `prices[token] = {"ltp": float, "ts": epoch, ...}` in memory and
subscribes/unsubscribes to tokens on demand (Kite caps one socket at 3000).
"""
import asyncio
import time
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Callable


INDEX_NAMES = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50", "SENSEX", "BANKEX", "SENSEX50"}


def kind_of(exchange: str, name: str) -> str:
    """index | stock | mcx — used for grouping, margins and the public ticker."""
    if exchange == "MCX":
        return "mcx"
    if exchange == "CDS":
        return "currency"
    if exchange == "CRYPTO":
        return "crypto"
    if exchange == "FOREX":
        return "forex"
    return "index" if name in INDEX_NAMES else "stock"


@dataclass
class Instrument:
    token: int
    symbol: str           # tradingsymbol e.g. NIFTY24NOV24000CE
    name: str             # underlying e.g. NIFTY, CRUDEOIL
    exchange: str         # NFO / BFO / MCX / NSE / BSE
    segment: str          # NFO-OPT, NFO-FUT, MCX-FUT, MCX-OPT, INDICES
    instrument_type: str  # CE / PE / FUT / EQ
    expiry: str           # YYYY-MM-DD or ""
    strike: float
    lot_size: int
    tick_size: float
    lot_label: str = ""   # e.g. "1 kg (price per 10 g)" for MCX; blank for NSE/BSE
    multiplier: float = 1.0   # contract size per unit of qty when the price is per 1 underlying (crypto: 0.001 BTC)
    init_margin_pct: float = 0.0    # exchange-published initial margin % (0 = use platform setting)
    maint_margin_pct: float = 0.0   # exchange-published maintenance margin % (0 = half of blocked margin)
    pos_limit: int = 0              # exchange position size limit in qty units (0 = none)
    price_band_pct: float = 0.0     # exchange price band for limit/stop prices (0 = none)
    leverage_options: tuple = ()    # selectable leverage steps the exchange offers (crypto/forex)

    def to_dict(self):
        d = asdict(self)
        d["kind"] = kind_of(self.exchange, self.name)
        return d


class PriceFeed:
    """Base class. Subclasses implement start(), _subscribe(), _unsubscribe()."""

    name = "base"

    def __init__(self):
        self.instruments: Dict[int, Instrument] = {}
        self.by_symbol: Dict[str, Instrument] = {}
        self.prices: Dict[int, dict] = {}
        self._refcount: Dict[int, int] = {}
        self._listeners: List[Callable[[dict], None]] = []
        self.connected = False
        self.status_msg = "not started"
        self.loop: Optional[asyncio.AbstractEventLoop] = None

    # ---- instrument master -------------------------------------------------
    def load_instruments(self, items: List[Instrument]):
        self.instruments = {i.token: i for i in items}
        self.by_symbol = {f"{i.exchange}:{i.symbol}": i for i in items}

    def underlyings(self) -> Dict[str, List[str]]:
        """{exchange: [names]} for the UI."""
        out: Dict[str, set] = {}
        for i in self.instruments.values():
            if i.segment == "INDICES":
                continue
            out.setdefault(i.exchange, set()).add(i.name)
        return {k: sorted(v) for k, v in out.items()}

    def expiries(self, exchange: str, name: str) -> List[str]:
        return sorted({i.expiry for i in self.instruments.values()
                       if i.exchange == exchange and i.name == name and i.expiry})

    def chain(self, exchange: str, name: str, expiry: str) -> List[Instrument]:
        return sorted((i for i in self.instruments.values()
                       if i.exchange == exchange and i.name == name and i.expiry == expiry),
                      key=lambda x: (x.instrument_type, x.strike))

    def search(self, q: str, limit=30) -> List[Instrument]:
        """Every word in the query must appear in the symbol (so 'NIFTY FUT', 'GOLDM', 'BANKNIFTY 52000 CE' all work)."""
        words = [w for w in q.upper().split() if w]
        if not words:
            return []
        today = __import__("datetime").date.today().isoformat()
        out = [i for i in self.instruments.values()
               if (not i.expiry or i.expiry >= today)
               and all(w in i.symbol or w in i.name for w in words)]
        out.sort(key=lambda i: (i.expiry or "", len(i.symbol), i.symbol))
        return out[:limit]

    def index_token_for(self, name: str) -> Optional[int]:
        """Spot index / underlying token used for margin + option chain header."""
        for i in self.instruments.values():
            if i.segment == "INDICES" and i.name == name:
                return i.token
        # MCX / currency: nearest future acts as underlying. NSE currency also lists weekly futures,
        # which barely trade, so prefer the monthly contract (USDINR26NOVFUT, not USDINR26N13FUT).
        import re
        futs = sorted((i for i in self.instruments.values()
                       if i.name == name and i.instrument_type == "FUT" and i.expiry),
                      key=lambda x: x.expiry)
        if futs and futs[0].exchange == "CDS":
            monthly = [f for f in futs if re.fullmatch(rf"{re.escape(name)}\d\d[A-Z]{{3}}FUT", f.symbol)]
            if monthly:
                return monthly[0].token
        return futs[0].token if futs else None

    # ---- prices --------------------------------------------------------------
    def ltp(self, token: int) -> Optional[float]:
        p = self.prices.get(token)
        return p["ltp"] if p else None

    def tick_age(self, token: int) -> Optional[float]:
        p = self.prices.get(token)
        return time.time() - p["ts"] if p else None

    def on_tick(self, cb: Callable[[dict], None]):
        self._listeners.append(cb)

    def _publish(self, tick: dict):
        tick.setdefault("ts", time.time())
        self.prices[tick["token"]] = tick
        for cb in self._listeners:
            try:
                cb(tick)
            except Exception:
                pass

    # ---- subscription refcounting --------------------------------------------
    def subscribe(self, tokens: List[int]):
        fresh = []
        for t in tokens:
            if t not in self.instruments:
                continue
            self._refcount[t] = self._refcount.get(t, 0) + 1
            if self._refcount[t] == 1:
                fresh.append(t)
        if fresh:
            self._subscribe(fresh)

    def unsubscribe(self, tokens: List[int]):
        gone = []
        for t in tokens:
            if t in self._refcount:
                self._refcount[t] -= 1
                if self._refcount[t] <= 0:
                    del self._refcount[t]
                    gone.append(t)
        if gone:
            self._unsubscribe(gone)

    def pin(self, tokens: List[int]):
        """Permanent subscription (open positions, pending orders, indices)."""
        self.subscribe(tokens)

    # ---- to implement ----------------------------------------------------------
    async def start(self, loop: asyncio.AbstractEventLoop):
        self.loop = loop

    def _subscribe(self, tokens: List[int]):
        pass

    def _unsubscribe(self, tokens: List[int]):
        pass

    def candles(self, token: int, interval: str) -> List[dict]:
        """Return [{time(epoch s), open, high, low, close, volume}] for the contract's life. Override."""
        return []

    def status(self) -> dict:
        return {"feed": self.name, "connected": self.connected, "message": self.status_msg,
                "instruments": len(self.instruments), "subscribed": len(self._refcount)}
