"""Tiny stand-in for Delta Exchange India public API (products, candles, websocket) for local tests."""
import asyncio, json, random, time
from datetime import datetime, timedelta, timezone
from fastapi import FastAPI, WebSocket
import uvicorn

app = FastAPI()
PX = {"BTCUSD": 74776.0, "ETHUSD": 2520.0, "SOLUSD": 158.25, "XRPUSD": 2.3456, "BNBUSD": 612.1, "XAUTUSD": 4120.5}
CV = {"BTCUSD": "0.001", "ETHUSD": "0.01", "SOLUSD": "1", "XRPUSD": "1", "BNBUSD": "0.1", "XAUTUSD": "0.001"}
TICK = {"BTCUSD": "0.5", "ETHUSD": "0.05", "SOLUSD": "0.0001", "XRPUSD": "0.0001", "BNBUSD": "0.001", "XAUTUSD": "0.01"}
products = []
pid = 1
for s in PX:
    pid += 1
    products.append({"id": pid, "symbol": s, "contract_type": "perpetual_futures", "contract_value": CV[s], "tick_size": TICK[s],
                     "underlying_asset": {"symbol": s.replace("USD", "")}, "quoting_asset": {"symbol": "USD"}, "settling_asset": {"symbol": "USD"},
                     "settlement_time": None, "initial_margin": "0.5" if s in ("BTCUSD","ETHUSD") else "1", "maintenance_margin": "0.25" if s in ("BTCUSD","ETHUSD") else "0.5",
                     "position_size_limit": 125000, "price_band": "5", "trading_status": "operational", "state": "live"})
now = datetime.now(timezone.utc)
for d in (0, 1, 2):
    st = (now + timedelta(days=d)).replace(hour=16, minute=0, second=0, microsecond=0)
    if st < now: continue
    for und, step in (("BTC", 1000), ("ETH", 50)):
        atm = round(PX[und + "USD"] / step) * step
        for k in range(-6, 7):
            strike = atm + k * step
            for ct, pfx in (("call_options", "C"), ("put_options", "P")):
                pid += 1
                products.append({"id": pid, "symbol": f"{pfx}-{und}-{strike}-{st.strftime('%d%m%y')}", "contract_type": ct,
                                 "contract_value": CV[und + "USD"], "tick_size": "0.1", "strike_price": str(strike),
                                 "underlying_asset": {"symbol": und}, "quoting_asset": {"symbol": "USD"}, "settling_asset": {"symbol": "USD"},
                                 "settlement_time": st.strftime("%Y-%m-%dT%H:%M:%SZ"), "initial_margin": "4", "maintenance_margin": "2", "position_size_limit": 10000, "price_band": "25", "trading_status": "operational", "state": "live"})
BYSYM = {p["symbol"]: p for p in products}

@app.get("/v2/products")
def prods(contract_types: str = "", states: str = "live", page_size: int = 100, after: str = None):
    ct = set(contract_types.split(",")) if contract_types else None
    res = [p for p in products if not ct or p["contract_type"] in ct]
    return {"success": True, "result": res, "meta": {"after": None, "total_count": len(res)}}

@app.get("/debug/shift")
def shift(symbol: str, pct: float):
    PX[symbol] *= 1 + pct / 100; return {"ok": True, "px": PX[symbol]}

INR = 100.1
@app.get("/v2/history/candles")
def candles(symbol: str, resolution: str = "1d", start: int = 0, end: int = 0):
    p = PX.get(symbol, 100.0); out = []; t = end - 300 * 86400; px = p * 0.8
    while t < end:
        o = px; c = px * (1 + random.uniform(-0.03, 0.03)); px = c
        out.append({"time": t, "open": o, "high": max(o, c) * 1.01, "low": min(o, c) * 0.99, "close": c, "volume": random.randint(1000, 50000)})
        t += 86400
    return {"success": True, "result": out}

def opt_px(sym):
    pfx, und, strike, _ = sym.split("-"); s = PX[und + "USD"]; k = float(strike)
    intr = max(0.0, (s - k) if pfx == "C" else (k - s)); return round(intr + s * 0.01, 1)

@app.websocket("/")
async def ws(sock: WebSocket):
    await sock.accept(); subs = {"ticker": set(), "l2": set()}
    async def reader():
        async for raw in sock.iter_text():
            m = json.loads(raw)
            if m.get("type") in ("subscribe", "unsubscribe"):
                for ch in m["payload"]["channels"]:
                    key = "l2" if ch["name"] == "l2_orderbook" else "ticker"
                    (subs[key].update if m["type"] == "subscribe" else subs[key].difference_update)(ch["symbols"])
                await sock.send_text(json.dumps({"type": "subscriptions", "channels": m["payload"]["channels"]}))
    asyncio.create_task(reader())
    try:
        while True:
            for s in list(PX): PX[s] *= 1 + random.uniform(-0.0002, 0.0002)
            await sock.send_text(json.dumps({"type": "spot_price", "symbol": ".DEUSDTINR", "price": INR}))
            for s in list(subs["ticker"]):
                if s in PX:
                    px = PX[s]; tick = float(TICK[s])
                    await sock.send_text(json.dumps({"type": "v2/ticker", "symbol": s, "close": px, "mark_price": str(px), "open": px * 0.99, "high": px * 1.02, "low": px * 0.98,
                        "volume": 14407.77, "oi": "974.87", "turnover_usd": 1.07e9, "mark_change_24h": "1.01", "funding_rate": "0.01",
                        "quotes": {"best_bid": str(round(px - tick, 4)), "best_ask": str(round(px + tick, 4)), "bid_size": "5351", "ask_size": "572", "mark_iv": None}}))
                elif s in BYSYM:
                    px = opt_px(s)
                    await sock.send_text(json.dumps({"type": "v2/ticker", "symbol": s, "close": px, "mark_price": str(px), "open": px, "volume": 120, "oi": "350", "turnover_usd": 1000,
                        "mark_change_24h": "0", "quotes": {"best_bid": str(max(0.1, px - 0.5)), "best_ask": str(px + 0.5), "bid_size": "3", "ask_size": "2", "mark_iv": "0.45"}}))
            for s in list(subs["l2"]):
                px = PX[s]; tick = float(TICK[s])
                buy = [{"limit_price": str(round(px - tick * (i + 1), 4)), "size": 500 + i * 300, "depth": "0"} for i in range(5)]
                sell = [{"limit_price": str(round(px + tick * (i + 1), 4)), "size": 400 + i * 300, "depth": "0"} for i in range(5)]
                await sock.send_text(json.dumps({"type": "l2_orderbook", "symbol": s, "buy": buy, "sell": sell}))
            await asyncio.sleep(1.0)
    except Exception:
        pass

uvicorn.run(app, port=8765, log_level="warning")
