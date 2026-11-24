"""A crypto perpetual / a forex pair: the last-price message arrives BEFORE the order-book message of the same move.
A resting stop is triggered by the new price and filled against the book of the moment before. Real feed classes, fed by hand."""
from rk import *
from app.feed.delta import DeltaCrypto, TOKEN_BASE as CB
from app.feed.ctrader import CTraderForex, TOKEN_BASE as FB, PT_SPOT_EVENT as SPOT, PT_DEPTH_EVENT as DEPTH
at(datetime(2026, 11, 25, 11, 0))
f2 = PriceFeed(); cry = DeltaCrypto(f2); fx = CTraderForex(f2)
B, EU = CB + 2, FB + 1
cry.items = {B: Instrument(B, "BTCUSD", "BTC", "CRYPTO", "CRYPTO-PERP", "FUT", "", 0, 1, 0.5, multiplier=0.001, init_margin_pct=0.5, maint_margin_pct=0.25, pos_limit=125000, leverage_options=(1, 50))}
cry.symbols = {"BTCUSD": B}; cry._merge(); cry._inr = (100.1, time.time()); cry.connected = True
fx.items = {EU: Instrument(EU, "EURUSD", "EURUSD", "FOREX", "FOREX-SPOT", "FUT", "", 0, 1000, 0.00001, init_margin_pct=0.2, maint_margin_pct=0.1, leverage_options=(1, 50))}
fx.by_symbol_id = {1: EU}; fx._merge(); fx.connected = True
f2.subscribe([B, EU]); f2.connected = True
eng = Engine(f2); eng._lock = asyncio.Lock()
bk = lambda p: cry._handle({"type": "l2_orderbook", "symbol": "BTCUSD", "buy": [{"limit_price": str(p - 0.5 * i), "size": 5000} for i in (1, 2, 3)],
                            "sell": [{"limit_price": str(p + 0.5 * i), "size": 5000} for i in (1, 2, 3)]})
tk = lambda p: cry._handle({"type": "v2/ticker", "symbol": "BTCUSD", "close": p, "mark_price": str(p), "quotes": {"best_bid": str(p - 0.5), "best_ask": str(p + 0.5), "bid_size": "40", "ask_size": "30"}})
print("vf", eng.vf(cry.items[B]), "fx_ready", cry.fx_ready())
bk(75000); tk(75000)
u = User(username="lag1", display_name="LAG", password_hash="x", is_admin=False, balance=0.0); db.add(u); db.flush(); eng._ledger(db, u, 1_000_000, "ADMIN_CREDIT", "x"); db.commit()
try:
    o = eng.place_order(db, u, B, "BUY", 5000)
    s = eng.place_order(db, u, B, "SELL", 5000, "SL", trigger_price=74000.0, validity="GTT")
    print("bought", o.status, o.fill_price, "| stop", s.status, s.trigger_price)
    tk(73875)                                                 # the market gaps 1.5% lower: the last-price message comes first
    t = f2.prices[B]; print("in memory after the price message: last", t["ltp"], "best bid of the book", t["bid"], "(the message itself said best bid 73874.5)")
    loop.run_until_complete(eng._process_pending(B, 73875)); db.expire_all(); s = db.get(Order, s.id)
    print("STOP:", s.status, "filled at", s.fill_price, "| the market's bid at that moment was 73874.5 |", f"better than the market by {(s.fill_price - 73874.5) * 5000 * 0.001 * 100.1:,.0f} coins" if s.fill_price else s.reason)
    bk(73875)
    print("after the book message: bid", f2.prices[B]["bid"], "| account coins", db.get(User, u.id).balance)
except EngineError as e:
    print("ERR", e)
