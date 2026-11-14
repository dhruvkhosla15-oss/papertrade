"""Stand-in for cTrader Open API (JSON over WebSocket) for local tests."""
import asyncio, json, random, time
from fastapi import FastAPI, WebSocket
import uvicorn

app = FastAPI()
ASSETS = {1: "USD", 2: "EUR", 3: "GBP", 4: "JPY", 5: "XAU", 6: "INR", 7: "AUD", 8: "US500", 9: "US30", 10: "USTEC", 11: "US2000", 12: "UK100", 13: "DE40", 14: "STOXX50", 15: "JP225", 16: "AUS200", 17: "XTI", 18: "XBR", 19: "XNG", 20: "XPT", 21: "XPD"}
SYMS = {1: ("EURUSD", 2, 1, 5, 1.12313), 2: ("GBPUSD", 3, 1, 5, 1.34531), 3: ("USDJPY", 1, 4, 3, 157.945),
        4: ("XAUUSD", 5, 1, 2, 4117.24), 5: ("AUDUSD", 7, 1, 5, 0.69214), 6: ("USDINR", 1, 6, 4, 94.03),
        20: ("US500", 8, 1, 2, 7586.2), 21: ("US30", 9, 1, 2, 52277.6), 22: ("USTEC", 10, 1, 2, 28262.2), 23: ("US2000", 11, 1, 2, 2843.25),
        24: ("UK100", 12, 3, 2, 10793.4), 25: ("DE40", 13, 2, 2, 26531.7), 26: ("STOXX50", 14, 2, 2, 6367.6), 27: ("JP225", 15, 4, 2, 61817.0),
        28: ("AUS200", 16, 7, 2, 9117.4), 29: ("XTIUSD", 17, 1, 3, 87.526), 30: ("XBRUSD", 18, 1, 3, 95.735), 31: ("XNGUSD", 19, 1, 3, 3.213),
        32: ("XPTUSD", 20, 1, 2, 1558.92), 33: ("XPDUSD", 21, 1, 2, 1076.48)}
D=86400
def wk(pairs): return [{"startSecond": a, "endSecond": b} for a, b in pairs]
US = wk([(i*D+17*3600, (i+1)*D+15*3600+59*60) for i in range(5)])
import os
CLOSED = os.getenv("FAKE_CLOSED", "")
EXTRA = {20: (10, "America/Chicago", US), 21: (10, "America/Chicago", US), 22: (10, "America/Chicago", US), 23: (100, "America/Chicago", US),
         24: (10, "Europe/London", wk([(i*D+23*3600+300, (i+1)*D+21*3600+59*60) for i in range(5)])),
         25: (10, "Europe/Berlin", wk([((i+1)*D+120, (i+1)*D+22*3600+59*60) for i in range(5)])), 26: (10, "Europe/Berlin", wk([((i+1)*D+120, (i+1)*D+22*3600+59*60) for i in range(5)])),
         27: (100, "Asia/Tokyo", wk([((i+1)*D+7*3600, (i+2)*D+5*3600+59*60) for i in range(5)])), 28: (10, "Australia/Canberra", wk([((i+1)*D+9*3600+3000, (i+2)*D+6*3600+59*60) for i in range(5)])),
         29: (100, "America/New_York", US), 30: (100, "Europe/London", US), 31: (500000, "America/New_York", US), 32: (100, "America/New_York", US), 33: (100, "America/New_York", US)}
if os.getenv("FAKE_OPEN") == "1":   # every Global contract open all week (to exercise Global on a weekend)
    EXTRA = {k: (v[0], v[1], wk([(0, 7*D - 1)])) for k, v in EXTRA.items()}
PX = {k: v[4] for k, v in SYMS.items()}
for _kv in filter(None,os.getenv("FAKE_MULT","").split(",")):
    _n,_m=_kv.split(":")
    for _k,_v in SYMS.items():
        if _v[0]==_n: PX[_k]*=float(_m)

@app.websocket("/")
async def ws(sock: WebSocket):
    await sock.accept(); spots = set(); depth = set(); authed = {"app": False, "acc": False}
    async def reply(mid, pt, payload): await sock.send_text(json.dumps({"clientMsgId": mid, "payloadType": pt, "payload": payload}))
    async def reader():
        async for raw in sock.iter_text():
            m = json.loads(raw); pt = m.get("payloadType"); p = m.get("payload") or {}; mid = m.get("clientMsgId")
            if pt == 2100:
                if p.get("clientId") == "cid" and p.get("clientSecret") == "csec": authed["app"] = True; await reply(mid, 2101, {})
                else: await reply(mid, 2142, {"errorCode": "CH_CLIENT_AUTH_FAILURE", "description": "bad creds"})
            elif pt == 2149:
                if p.get("accessToken") == "tok-ok": await reply(mid, 2150, {"ctidTraderAccount": [{"ctidTraderAccountId": 999, "isLive": False, "traderLogin": 10135462}]})
                else: await reply(mid, 2142, {"errorCode": "INVALID_TOKEN", "description": "token"})
            elif pt == 2102: authed["acc"] = True; await reply(mid, 2103, {"ctidTraderAccountId": 999})
            elif pt == 2112: await reply(mid, 2113, {"asset": [{"assetId": k, "name": v} for k, v in ASSETS.items()]})
            elif pt == 2114: await reply(mid, 2115, {"symbol": [{"symbolId": k, "symbolName": v[0], "enabled": True, "baseAssetId": v[1], "quoteAssetId": v[2], "description": v[0]} for k, v in SYMS.items()]})
            elif pt == 2116: await reply(mid, 2117, {"symbol": [dict({"symbolId": k, "digits": SYMS[k][3], "pipPosition": SYMS[k][3] - 1, "lotSize": 10000000, "minVolume": 100000, "maxVolume": 10000000000, "stepVolume": 100000, "leverageId": 7}, **({"lotSize": 100, "minVolume": EXTRA[k][0], "maxVolume": 25000, "stepVolume": EXTRA[k][0], "scheduleTimeZone": EXTRA[k][1], "schedule": ([] if False else ([{"startSecond": 1, "endSecond": 2}] if SYMS[k][0] in CLOSED.split(",") else EXTRA[k][2]))} if k in EXTRA else {})) for k in p.get("symbolId", [])]})
            elif pt == 2148: await reply(mid, 2178, {"leverage": {"leverageId": 7, "tiers": [{"volume": 100000000000, "leverage": 50000}, {"volume": 200000000000, "leverage": 20000}]}})
            elif pt == 2127: spots.update(p.get("symbolId", [])); await reply(mid, 2128, {})
            elif pt == 2156: depth.update(p.get("symbolId", [])); await reply(mid, 2157, {})
            elif pt == 2129: spots.difference_update(p.get("symbolId", [])); await reply(mid, 2130, {})
            elif pt == 2158: depth.difference_update(p.get("symbolId", [])); await reply(mid, 2159, {})
            elif pt == 2137:
                sid = p["symbolId"]; bars = []; t = int(time.time() // 86400) * 86400 - 86400; c = PX[sid] * (1 + random.uniform(-0.002, 0.002))
                while t > time.time() - 300 * 86400:
                    o = c * (1 + random.uniform(-0.006, 0.006)); lo = min(o, c) * 0.998
                    bars.append({"volume": 1000, "period": 12, "low": int(lo * 1e5), "deltaOpen": int((o - lo) * 1e5), "deltaClose": int((c - lo) * 1e5), "deltaHigh": int((max(o, c) * 1.002 - lo) * 1e5), "utcTimestampInMinutes": t // 60}); t -= 86400; c = o
                bars.reverse()
                await reply(mid, 2138, {"trendbar": bars})
            elif pt == 51: pass
    asyncio.create_task(reader())
    try:
        qids = {}
        while True:
            for sid in list(PX): PX[sid] *= 1 + random.uniform(-0.0001, 0.0001)
            for sid in list(spots):
                px = PX[sid]; tick = 10 ** (-SYMS[sid][3]); sp = tick * 2
                await sock.send_text(json.dumps({"payloadType": 2131, "payload": {"symbolId": sid, "bid": int(round((px - sp / 2) * 1e5)), "ask": int(round((px + sp / 2) * 1e5)),
                    "trendbar": [{"period": 12, "low": int((px * 0.995) * 1e5), "deltaOpen": int(px * 0.003 * 1e5), "deltaHigh": int(px * 0.008 * 1e5), "deltaClose": 0}]}}))
            for sid in list(depth):
                px = PX[sid]; tick = 10 ** (-SYMS[sid][3]); new = []; base = sid * 100000 + qids.get(sid, 0); dele = list(range(base - 10, base)); qids[sid] = qids.get(sid, 0) + 10; qid = base
                for i in range(5):
                    qid += 1; new.append({"id": qid, "size": (500000 if sid != 4 else 100) * (i + 1) * 100, "bid": int(round((px - tick * (i + 1)) * 1e5))})
                    qid += 1; new.append({"id": qid, "size": (300000 if sid != 4 else 50) * (i + 1) * 100, "ask": int(round((px + tick * (i + 1)) * 1e5))})
                await sock.send_text(json.dumps({"payloadType": 2155, "payload": {"symbolId": sid, "newQuotes": new, "deletedQuotes": dele}}))
            await asyncio.sleep(1.0)
    except Exception:
        pass

uvicorn.run(app, port=8766, log_level="warning")
