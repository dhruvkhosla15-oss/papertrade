import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("PT_DATA_DIR", BASE_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_URL = os.getenv("PT_DB_URL", f"sqlite:///{DATA_DIR / 'papertrade.db'}")
def _secret_key() -> str:
    """Signing key for login tokens. PT_SECRET_KEY wins; otherwise a random key is generated once and
    kept beside the database, so a deployment can never run on a guessable built-in default."""
    env = os.getenv("PT_SECRET_KEY", "").strip()
    if env and env != "change-me-in-production-please":
        return env
    f = DATA_DIR / "secret.key"
    try:
        if f.exists() and len(f.read_text().strip()) >= 32:
            return f.read_text().strip()
        import secrets
        k = secrets.token_urlsafe(48)
        f.write_text(k)
        try:
            os.chmod(f, 0o600)
        except OSError:
            pass
        return k
    except OSError:
        import secrets
        return secrets.token_urlsafe(48)   # read-only disk: still never the default (sessions reset on restart)


SECRET_KEY = _secret_key()

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
DEFAULT_COMMISSION_PCT = 0.02   # % of traded value charged on every fill (buy and sell)
# Forex: IC Markets Raw charges USD 3.5 per 100,000 lot per side = 0.0035 % of notional
DEFAULT_COMMISSION_PCT_FOREX = 0.0035
DEFAULT_MARGIN_PCT = {"NFO": 12.0, "BFO": 12.0, "MCX": 10.0, "STK": 20.0, "CDS": 3.0, "CRYPTO": 0.5, "FOREX": 1.0,
                      # MCX per-commodity groups (roughly SPAN + exposure as Zerodha shows them, Nov 2026)
                      "MCX_SILVER": 15.0, "MCX_GOLD": 8.0, "MCX_CRUDE": 12.0, "MCX_NATGAS": 16.0, "MCX_METALS": 10.0}
MCX_GROUPS = {"SILVER": "MCX_SILVER", "SILVERM": "MCX_SILVER", "SILVERMIC": "MCX_SILVER",
              "GOLD": "MCX_GOLD", "GOLDM": "MCX_GOLD", "GOLDGUINEA": "MCX_GOLD", "GOLDPETAL": "MCX_GOLD", "GOLDTEN": "MCX_GOLD",
              "CRUDEOIL": "MCX_CRUDE", "CRUDEOILM": "MCX_CRUDE",
              "NATURALGAS": "MCX_NATGAS", "NATGASMINI": "MCX_NATGAS",
              "COPPER": "MCX_METALS", "ZINC": "MCX_METALS", "ZINCMINI": "MCX_METALS", "ALUMINIUM": "MCX_METALS", "ALUMINI": "MCX_METALS",
              "LEAD": "MCX_METALS", "LEADMINI": "MCX_METALS", "NICKEL": "MCX_METALS"}
MCX_GROUP_LABELS = {"MCX_SILVER": "Silver (SILVER · SILVERM · SILVERMIC)", "MCX_GOLD": "Gold (GOLD · GOLDM · GUINEA · PETAL)",
                    "MCX_CRUDE": "Crude (CRUDEOIL · CRUDEOILM)", "MCX_NATGAS": "Natural gas (NATURALGAS · NATGASMINI)",
                    "MCX_METALS": "Base metals (COPPER · ZINC · ALU · LEAD · NICKEL)"}
DEFAULT_MCX_OPTION_FACTOR = 0.87   # short MCX options: SPAN charges a bit less than the future for OTM delta  # CRYPTO 0.5% = 200x, Delta's own max  # STK = stock F&O (NFO non-index); CDS = NSE currency
# NSE currency derivatives offered (CDS segment). Set PT_CURRENCIES= to turn off.
CURRENCY_PAIRS = [c.strip().upper() for c in os.getenv("PT_CURRENCIES", "USDINR,EURINR,GBPINR,JPYINR").split(",") if c.strip()]

# Exchange trading hours (IST)
MARKET_HOURS = {"NFO": ("09:15", "15:40"), "BFO": ("09:15", "15:40"), "MCX": ("09:00", "23:55"), "CDS": ("09:00", "17:00"), "CRYPTO": ("00:00", "23:59"), "FOREX": ("00:00", "23:59")}
# NSE/BSE freeze quantities (max qty per order, exchange rule; bigger orders are rejected by the exchange).
# Override with PT_FREEZE_QTY="NIFTY:1800,BANKNIFTY:900,..."
FREEZE_QTY = {"NIFTY": 1800, "BANKNIFTY": 900, "FINNIFTY": 1800, "MIDCPNIFTY": 2800, "NIFTYNXT50": 600,
              "SENSEX": 1000, "BANKEX": 600, "SENSEX50": 600}
FREEZE_QTY.update({k.strip().upper(): int(v) for k, v in
                   (p.split(":") for p in os.getenv("PT_FREEZE_QTY", "").split(",") if ":" in p)})
# Liquidation: positions are force-closed at market when equity (coins + unrealised) falls below the
# maintenance requirement. Exchange-published maintenance % where available (Delta), else this share
# of the blocked margin (brokers square off well before the full margin is lost).
MAINT_SHARE = float(os.getenv("PT_MAINT_SHARE", "0.5"))
# Margin shortfall: a user may only carry what their coins cover. The moment running losses take the
# Available Balance (coins − margin blocked − running loss) below zero, positions are squared off at
# market, worst loser first, just enough lots to bring it back above zero. A warning goes out earlier,
# when Available Balance drops under this share of the margin blocked.
MARGIN_WARN_SHARE = float(os.getenv("PT_MARGIN_WARN_SHARE", "0.2"))
# One-time grace (minutes) after this rule first ships, so accounts already below zero are warned first.
STRICT_LIQ_GRACE_MIN = float(os.getenv("PT_STRICT_LIQ_GRACE_MIN", "15"))
# Crypto derivatives via Delta Exchange India public data. PT_CRYPTO=0 turns it off.
ENABLE_CRYPTO = os.getenv("PT_CRYPTO", "1").strip().lower() not in ("0", "false", "no", "off")
# Forex via a cTrader broker account (Open API). On when the client credentials are set.
ENABLE_FOREX = bool(os.getenv("PT_CTRADER_CLIENT_ID")) and os.getenv("PT_FOREX", "1").strip().lower() not in ("0", "false", "no", "off")  # see market_calendar.py (holidays, MCX DST close)
ENFORCE_MARKET_HOURS = os.getenv("PT_ENFORCE_MARKET_HOURS", "true" if FEED == "kite" else "false").lower() == "true"

IST_OFFSET_HOURS = 5.5
