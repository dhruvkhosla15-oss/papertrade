from datetime import datetime
from sqlalchemy import (create_engine, Column, Integer, String, Float, Boolean,
                        DateTime, ForeignKey, Text, event)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from .config import DB_URL

engine = create_engine(DB_URL, pool_size=40, max_overflow=80, pool_timeout=60,
                       connect_args={"check_same_thread": False, "timeout": 30} if DB_URL.startswith("sqlite") else {})


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_conn, _):
    if DB_URL.startswith("sqlite"):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
Base = declarative_base()


def now():
    return datetime.utcnow()


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String(64), unique=True, nullable=False, index=True)
    display_name = Column(String(128), default="")
    password_hash = Column(String(256), nullable=False)
    is_admin = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    must_change_password = Column(Boolean, default=False)   # set on creation / admin reset; cleared when the user changes it
    totp_secret = Column(String(64), default="")   # master 2FA (TOTP); empty = not set up
    totp_enabled = Column(Boolean, default=False)
    balance = Column(Float, default=0.0)        # coins (₹ equivalent). Realised P&L flows in here.
    created_at = Column(DateTime, default=now)

    positions = relationship("Position", back_populates="user", cascade="all, delete-orphan")
    orders = relationship("Order", back_populates="user", cascade="all, delete-orphan")


class Ledger(Base):
    """Every change to a user's coin balance."""
    __tablename__ = "ledger"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    amount = Column(Float, nullable=False)       # +credit / -debit
    balance_after = Column(Float, nullable=False)
    kind = Column(String(32), nullable=False)    # ADMIN_CREDIT, ADMIN_DEBIT, REALISED_PNL, EXPIRY_SETTLEMENT
    note = Column(String(256), default="")
    created_at = Column(DateTime, default=now)


class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    token = Column(Integer, nullable=False, index=True)     # instrument token
    symbol = Column(String(64), nullable=False)
    exchange = Column(String(8), nullable=False)
    side = Column(String(4), nullable=False)                # BUY / SELL
    order_type = Column(String(8), nullable=False)          # MARKET / LIMIT / SL
    lots = Column(Integer, nullable=False)
    qty = Column(Integer, nullable=False)                   # lots * lot_size
    limit_price = Column(Float)                             # for LIMIT / SL
    trigger_price = Column(Float)                           # for SL
    status = Column(String(12), nullable=False, default="OPEN")  # OPEN / FILLED / CANCELLED / REJECTED
    fill_price = Column(Float)
    reason = Column(String(256), default="")
    margin_blocked = Column(Float, default=0.0)
    created_at = Column(DateTime, default=now)
    updated_at = Column(DateTime, default=now, onupdate=now)

    user = relationship("User", back_populates="orders")


class Position(Base):
    __tablename__ = "positions"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    token = Column(Integer, nullable=False, index=True)
    symbol = Column(String(64), nullable=False)
    exchange = Column(String(8), nullable=False)
    lot_size = Column(Integer, nullable=False)
    qty = Column(Integer, nullable=False, default=0)       # signed: +long / -short (in units, not lots)
    avg_price = Column(Float, default=0.0)
    realised_pnl = Column(Float, default=0.0)               # cumulative realised on this position
    margin_blocked = Column(Float, default=0.0)
    expiry = Column(String(10))                             # YYYY-MM-DD
    is_closed = Column(Boolean, default=False)
    opened_at = Column(DateTime, default=now)
    updated_at = Column(DateTime, default=now, onupdate=now)

    user = relationship("User", back_populates="positions")


class Trade(Base):
    """Executed fills."""
    __tablename__ = "trades"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    order_id = Column(Integer, ForeignKey("orders.id"))
    token = Column(Integer, nullable=False)
    symbol = Column(String(64), nullable=False)
    exchange = Column(String(8), nullable=False)
    side = Column(String(4), nullable=False)
    qty = Column(Integer, nullable=False)
    price = Column(Float, nullable=False)
    realised_pnl = Column(Float, default=0.0)
    commission = Column(Float, default=0.0)
    created_at = Column(DateTime, default=now)


class Watch(Base):
    __tablename__ = "watchlist"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    token = Column(Integer, nullable=False)
    symbol = Column(String(64), nullable=False)
    exchange = Column(String(8), nullable=False)
    position = Column(Integer, default=0)
    created_at = Column(DateTime, default=now)


class Setting(Base):
    __tablename__ = "settings"
    key = Column(String(64), primary_key=True)
    value = Column(Text)


def init_db():
    Base.metadata.create_all(engine)
    # lightweight migrations for columns added after first release
    from sqlalchemy import text, inspect
    cols = {c["name"] for c in inspect(engine).get_columns("watchlist")}
    if "position" not in cols:
        with engine.begin() as con:
            con.execute(text("ALTER TABLE watchlist ADD COLUMN position INTEGER DEFAULT 0"))
            con.execute(text("UPDATE watchlist SET position = id"))
    ucols = {c["name"] for c in inspect(engine).get_columns("users")}
    with engine.begin() as con:
        if "totp_secret" not in ucols:
            con.execute(text("ALTER TABLE users ADD COLUMN totp_secret VARCHAR(64) DEFAULT ''"))
        if "totp_enabled" not in ucols:
            con.execute(text("ALTER TABLE users ADD COLUMN totp_enabled BOOLEAN DEFAULT 0"))
        if "must_change_password" not in ucols:
            con.execute(text("ALTER TABLE users ADD COLUMN must_change_password BOOLEAN DEFAULT 0"))
            # trainees created earlier who have never placed an order still get the first-login prompt
            con.execute(text("UPDATE users SET must_change_password = 1 WHERE is_admin = 0 "
                             "AND id NOT IN (SELECT DISTINCT user_id FROM orders)"))
    tcols = {c["name"] for c in inspect(engine).get_columns("trades")}
    if "commission" not in tcols:
        with engine.begin() as con:
            con.execute(text("ALTER TABLE trades ADD COLUMN commission FLOAT DEFAULT 0"))


def get_setting(db, key, default=None):
    row = db.get(Setting, key)
    return row.value if row else default


def set_setting(db, key, value):
    row = db.get(Setting, key)
    if row:
        row.value = value
    else:
        db.add(Setting(key=key, value=value))
    db.commit()
