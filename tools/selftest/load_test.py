"""Load test on the private copy (localhost:8001, started by `PT_SITE_CHECK=0 bash tools/selftest/run.sh keep`).
Never run against the live site.

Simulates N users at the same time, each with the app open (live price socket), refreshing screens and
placing orders, and measures how fast the site answers and whether the books still add up afterwards.

  python3 tools/selftest/load_test.py [users=100] [seconds=120] [prefix=load] [login spread seconds=30]
"""
import asyncio
import json
import random
import statistics
import sys
import time

import httpx
import websockets

B = "http://localhost:8001"
N = int(sys.argv[1]) if len(sys.argv) > 1 else 100
SECS = int(sys.argv[2]) if len(sys.argv) > 2 else 120
PREFIX = sys.argv[3] if len(sys.argv) > 3 else "load"
STAGGER = float(sys.argv[4]) if len(sys.argv) > 4 else 30.0     # seconds over which the users log in (0 = all at once)

lat = {"read": [], "order": [], "login": []}
errs = {"read": 0, "order_5xx": 0, "order_refused": 0, "order_ok": 0, "ws_drop": 0, "ws_msgs": 0, "timeouts": 0}
refusals: dict = {}


async def timed(kind, coro):
    t = time.perf_counter()
    try:
        r = await coro
        lat[kind].append((time.perf_counter() - t) * 1000)
        return r
    except (httpx.TimeoutException, httpx.TransportError):
        errs["timeouts"] += 1
        lat[kind].append((time.perf_counter() - t) * 1000)
        return None


async def sign_in(i, sem):
    """Set-up, not part of the measurement: the account logs in once and sets its password, a few at a time
    (in real life people do not all do this in the same second; a session then lasts for weeks)."""
    name = f"{PREFIX}{i:03d}"
    c = httpx.AsyncClient(base_url=B, timeout=60)
    async with sem:
        r = await timed("login", c.post("/api/login", json={"username": name, "password": "Load@12345"}))
        if r is None or r.status_code != 200:
            errs["read"] += 1; return None
        await c.post("/api/password", json={"old_password": "Load@12345", "new_password": "Load@67890"})
    return c


async def user_task(c, toks, stop_at):
    if c is None:
        return
    mine = random.sample(toks, k=min(3, len(toks)))

    async def socket():
        try:
            cookie = "; ".join(f"{k}={v}" for k, v in c.cookies.items())
            async with websockets.connect(B.replace("http", "ws") + "/ws", additional_headers={"Cookie": cookie}, max_size=None) as ws:
                await ws.send(json.dumps({"type": "subscribe", "tokens": mine}))
                while time.time() < stop_at:
                    try:
                        await asyncio.wait_for(ws.recv(), timeout=5); errs["ws_msgs"] += 1
                    except asyncio.TimeoutError:
                        pass
        except Exception:
            errs["ws_drop"] += 1

    sock = asyncio.create_task(socket())
    await asyncio.sleep(random.random() * 4)
    k = 0
    while time.time() < stop_at:
        k += 1
        path = ("/api/me", "/api/positions", "/api/orders", "/api/weekly", "/api/me")[k % 5]
        r = await timed("read", c.get(path))
        if r is None or r.status_code != 200:
            errs["read"] += 1
        if k % 4 == 0:
            tok = random.choice(mine)
            r = await timed("order", c.post("/api/orders", json={"token": tok, "side": random.choice(("BUY", "SELL")), "lots": 1}))
            if r is None:
                pass
            elif r.status_code == 200:
                errs["order_ok"] += 1
            elif r.status_code >= 500:
                errs["order_5xx"] += 1
            else:
                errs["order_refused"] += 1
                try:
                    d = str(r.json().get("detail", ""))[:60]
                except Exception:
                    d = str(r.status_code)
                refusals[d] = refusals.get(d, 0) + 1
        await asyncio.sleep(1.5 + random.random())
    sock.cancel()
    await c.aclose()


def pct(xs, p):
    if not xs:
        return 0
    xs = sorted(xs); return xs[min(len(xs) - 1, int(len(xs) * p / 100))]


async def main():
    async with httpx.AsyncClient(base_url=B, timeout=600) as a:
        r = await a.post("/api/login", json={"username": "admin", "password": "admin123"})
        assert r.status_code == 200 and not r.json().get("needs_2fa"), "start a fresh private copy with PT_SITE_CHECK=0"
        t = time.time()
        for i in range(N):
            await a.post("/api/admin/users", json={"username": f"{PREFIX}{i:03d}", "password": "Load@12345", "display_name": f"Load {i}", "initial_coins": 5000000})
        print(f"created {N} users in {time.time() - t:.1f}s")
        toks = []
        for q, pick in (("NIFTY", lambda x: x.get("instrument_type") == "FUT" and x.get("name") == "NIFTY"),
                        ("BANKNIFTY", lambda x: x.get("instrument_type") == "FUT" and x.get("name") == "BANKNIFTY"),
                        ("GOLD", lambda x: x.get("instrument_type") == "FUT" and x.get("exchange") == "MCX"),
                        ("SILVER", lambda x: x.get("instrument_type") == "FUT" and x.get("exchange") == "MCX"),
                        ("BTC", lambda x: x.get("exchange") == "CRYPTO"), ("ETH", lambda x: x.get("exchange") == "CRYPTO"),
                        ("NIFTY", lambda x: x.get("instrument_type") == "CE" and x.get("name") == "NIFTY")):
            res = (await a.get("/api/search", params={"q": q})).json()
            x = next((y for y in res if pick(y)), None)
            if x:
                toks.append(x["token"])
        print("contracts used:", len(toks))
        t = time.time(); sem = asyncio.Semaphore(4)
        sessions = await asyncio.gather(*[sign_in(i, sem) for i in range(N)])
        print(f"signed in {sum(1 for x in sessions if x)} users in {time.time() - t:.1f}s (set-up, not measured)")
        stop_at = time.time() + SECS
        t0 = time.time()
        # the Master keeps his page open meanwhile
        async def master():
            ml = []
            while time.time() < stop_at:
                for p in ("/api/admin/users", "/api/admin/positions", "/api/admin/weekly", "/api/admin/report"):
                    t = time.perf_counter(); r = await a.get(p); ml.append((time.perf_counter() - t) * 1000)
                    if r.status_code != 200:
                        errs["read"] += 1
                await asyncio.sleep(5)
            return ml
        res = await asyncio.gather(master(), *[user_task(c, toks, stop_at) for c in sessions])
        ml = res[0]; took = time.time() - t0
        h = (await a.get("/api/admin/health")).json()
        t = time.perf_counter(); x = await a.get("/api/admin/export.xlsx"); xl = time.perf_counter() - t
        pr = await a.post("/api/admin/probe/run"); pj = pr.json() if pr.status_code == 200 else {}
    print(f"\nLOAD {N} users for {took:.0f}s")
    for k in ("login", "read", "order"):
        v = lat[k]
        if v:
            print(f"  {k:6s} n={len(v):6d}  median {statistics.median(v):7.0f} ms   95% under {pct(v, 95):7.0f} ms   slowest {max(v):7.0f} ms")
    print(f"  master n={len(ml):6d}  median {statistics.median(ml):7.0f} ms   95% under {pct(ml, 95):7.0f} ms   slowest {max(ml):7.0f} ms")
    print(f"  requests/second: {(len(lat['read']) + len(lat['order'])) / took:.0f}")
    print(f"  orders filled/accepted {errs['order_ok']}, refused {errs['order_refused']} {dict(sorted(refusals.items(), key=lambda kv: -kv[1])[:4])}, server errors {errs['order_5xx']}")
    print(f"  failed screen loads {errs['read']}, timeouts {errs['timeouts']}, dropped price sockets {errs['ws_drop']}, price messages received {errs['ws_msgs']}")
    print(f"  all-users Excel after the test: {xl:.1f}s ({x.status_code}, {len(x.content) // 1024} KB)")
    print(f"  server errors logged in the hour: {h.get('errors_hour')}, stopped jobs: {h.get('stopped')}, database {h.get('db_mb')} MB")
    print(f"  safety check after the load: {pj.get('passed')} passed, {pj.get('failed')} failed", [r['check'] for r in pj.get('rows', []) if r['ok'] is False][:5])
    bad = errs["order_5xx"] or errs["read"] > 0.01 * len(lat["read"]) or errs["timeouts"] > 0.01 * (len(lat["read"]) + len(lat["order"])) or pj.get("failed")
    print("LOAD RESULT:", "PROBLEMS" if bad else "OK")


if __name__ == "__main__":
    asyncio.run(main())
