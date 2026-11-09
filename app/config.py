import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("PT_DATA_DIR", BASE_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_URL = os.getenv("PT_DB_URL", f"sqlite:///{DATA_DIR / 'papertrade.db'}")
SECRET_KEY = os.getenv("PT_SECRET_KEY", "change-me-in-production-please")

# "mock" for simulated prices, "kite" for live Zerodha prices
FEED = os.getenv("PT_FEED", "mock")
KITE_API_KEY = os.getenv("KITE_API_KEY", "")
KITE_API_SECRET = os.getenv("KITE_API_SECRET", "")

# Initial admin credentials (used only when DB is first created)
ADMIN_USER = os.getenv("PT_ADMIN_USER", "admin")
ADMIN_PASSWORD = os.getenv("PT_ADMIN_PASSWORD", "admin123")

# Underlyings allowed on the platform (NFO/BFO). MCX: everything.
# Index underlyings offered for F&O. "STOCKS" = every NSE stock that has F&O (lot sizes from Zerodha's file).
ALLOWED_UNDERLYINGS = [u.strip().upper() for u in
                       os.getenv("PT_UNDERLYINGS", "NIFTY,BANKNIFTY,SENSEX,STOCKS").split(",") if u.strip()]
# Stock F&O is on unless PT_STOCK_FNO=0 (the STOCKS keyword above also turns it on).
ALLOW_STOCK_FNO = os.getenv("PT_STOCK_FNO", "1").strip().lower() not in ("0", "false", "no", "off") or "STOCKS" in ALLOWED_UNDERLYINGS

# Approximate margin % of contract notional for futures / short options
DEFAULT_MARGIN_PCT = {"NFO": 12.0, "BFO": 12.0, "MCX": 10.0, "STK": 20.0}  # STK = stock F&O (NFO non-index)

# Exchange trading hours (IST)
MARKET_HOURS = {
    "NFO": ("09:15", "15:30"),
    "BFO": ("09:15", "15:30"),
    "MCX": ("09:00", "23:55"),
}
ENFORCE_MARKET_HOURS = os.getenv("PT_ENFORCE_MARKET_HOURS", "true" if FEED == "kite" else "false").lower() == "true"

IST_OFFSET_HOURS = 5.5
