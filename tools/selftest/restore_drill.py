"""Restore drill on the private copy: prove that a backup really brings the site back.

  1. trade on the private copy (several users, several markets, a weekly cut-off, trading-access switches)
  2. take a backup exactly as the live site does, encrypt it exactly as the off-server copy is encrypted
  3. decrypt it with the restore tool (tools/decrypt_backup.py), as one would after losing the server
  4. start a brand-new site from nothing but that file (new folder, new port, no other state)
  5. compare every account: coins, positions (incl. carried price and original average), orders, trades,
     ledger, finished weeks, trading access; then log in, trade, and run the safety check on the restored site

Needs a fresh copy: `PT_SITE_CHECK=0 bash tools/selftest/run.sh keep`. Never touches the live site.
Prints "RESTORE n passed, m failed"; exit 1 on any failure.
"""
import os
import shutil
import subprocess
import sys
import time

import httpx

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
A_URL, B_URL = "http://localhost:8001", "http://localhost:8002"
NEW = "/tmp/lfx-restore"
passed = failed = 0


def ok(name, cond, info=""):
    global passed, failed
    if cond:
        passed += 1; print("PASS restore |", name)
    else:
        failed += 1; print("FAIL restore |", name, "|", str(info)[:300])


def facts(a: httpx.Client) -> dict:
    """Everything that is stored (not live prices) for every account, as the Master's own screens report it."""
    out = {}
    for u in sorted(a.get("/api/admin/users").json(), key=lambda x: x["username"]):
        d = a.get(f"/api/admin/users/{u['id']}/detail").json()
        acc = a.get(f"/api/admin/access?uid={u['id']}").json()
        out[u["username"]] = {
            "balance": round(u["balance"], 2), "active": u.get("is_active"), "allocated": round(u.get("total_credited", 0), 2),
            "positions": sorted((p["symbol"], p["qty"], round(p["avg_price"], 4), round(p.get("entry_avg") or 0, 4), p.get("carried_week") or "", round(p.get("margin") or 0, 2)) for p in d["positions"] if p["qty"]),
            "orders": sorted((o["id"], o["symbol"], o["side"], o["status"], o.get("fill_price"), o.get("carry_note") or "") for o in d["orders"]),
            "trades": sorted((t["id"], t["symbol"], t["side"], t["qty"], t["price"], round(t.get("realised_pnl") or 0, 2), round(t.get("commission") or 0, 2)) for t in d["trades"]),
            "ledger": sorted((l["created_at"], l["kind"], round(l["amount"], 2), round(l["balance_after"], 2)) for l in d["ledger"]),
            "access": acc.get("overrides"),
        }
    wk = a.get("/api/admin/weekly").json()
    out["__weeks__"] = wk.get("weeks")
    for w in wk.get("weeks") or []:
        r = a.get(f"/api/admin/weekly?week_end={w}").json()
        out["__week_" + w] = sorted((x["username"], x["closed"], x["valuation"], x["commission"], x["result"], x["allocated"], x["carried"]) for x in r["rows"])
    out["__access_default__"] = a.get("/api/admin/access").json()["default"]
    return out


def main():
    a = httpx.Client(base_url=A_URL, timeout=600)
    r = a.post("/api/login", json={"username": "admin", "password": "admin123"})
    assert r.status_code == 200 and not r.json().get("needs_2fa"), "start a fresh private copy: PT_SITE_CHECK=0 bash tools/selftest/run.sh keep"
    # ---- 1. activity ----
    users = {}
    for n, coins in (("drilla", 3000000), ("drillb", 1500000), ("drillc", 800000)):
        uid = a.post("/api/admin/users", json={"username": n, "password": "Drill@12345", "display_name": n.title(), "initial_coins": coins}).json()["id"]
        c = httpx.Client(base_url=A_URL, timeout=60)
        c.post("/api/login", json={"username": n, "password": "Drill@12345"}); c.post("/api/password", json={"old_password": "Drill@12345", "new_password": "Drill@67890"})
        users[n] = (uid, c)
    find = lambda c, q, pick: next(x for x in c.get("/api/search", params={"q": q}).json() if pick(x))
    c0 = users["drilla"][1]
    fut = find(c0, "NIFTY", lambda x: x.get("instrument_type") == "FUT" and x.get("name") == "NIFTY")
    # the option comes from the option chain: which options the search lists first depends on the weekday (on
    # 25 Nov 2026 it listed no NIFTY call at all and the drill stopped here before testing anything)
    exps = c0.get("/api/expiries", params={"exchange": "NFO", "name": "NIFTY"}).json()
    ces = [x for x in (c0.get("/api/chain", params={"exchange": "NFO", "name": "NIFTY", "expiry": exps[0]}).json().get("instruments") or []) if x.get("instrument_type") == "CE"]
    opt = ces[len(ces) // 2]
    mcx = find(c0, "GOLD", lambda x: x.get("instrument_type") == "FUT" and x.get("exchange") == "MCX")
    btc = find(c0, "BTC", lambda x: x.get("exchange") == "CRYPTO")
    plan = {"drilla": [(fut, "BUY", 2), (mcx, "SELL", 1), (fut, "SELL", 1)], "drillb": [(opt, "SELL", 1), (btc, "BUY", 2)], "drillc": [(mcx, "BUY", 1)]}
    for n, steps in plan.items():
        for ins, side, lots in steps:
            users[n][1].post("/api/orders", json={"token": ins["token"], "side": side, "lots": lots}); time.sleep(2)
    users["drillc"][1].post("/api/orders", json={"token": fut["token"], "side": "BUY", "lots": 1, "order_type": "LIMIT", "limit_price": 1.0})   # a resting order
    a.post("/api/admin/weekly/test-close"); time.sleep(4)
    users["drilla"][1].post("/api/orders", json={"token": fut["token"], "side": "SELL", "lots": 1}); time.sleep(2)   # exit of a carried position
    a.post(f"/api/admin/users/{users['drillb'][0]}/coins", json={"amount": 250000, "note": "drill top-up"})
    eff = a.get(f"/api/admin/access?uid={users['drillc'][0]}").json()["effective"]; eff["CRYPTO_FUT"] = not eff["CRYPTO_FUT"]
    a.post(f"/api/admin/users/{users['drillc'][0]}/access", json={"values": eff})
    time.sleep(3)
    before = facts(a)
    ok("there is real activity to restore (positions, carried positions, a finished week, a resting order)",
       any(p[4] for p in before["drilla"]["positions"] + before["drillb"]["positions"]) and before["__weeks__"] and any(o[3] == "OPEN" for o in before["drillc"]["orders"]), str(before["__weeks__"]))
    # ---- 2. backup + encrypt as the live site does ----
    raw = a.get("/api/admin/backup").content
    ok("the backup downloads", len(raw) > 50000, len(raw))
    os.environ.setdefault("PT_FEED", "mock"); os.environ["PT_DATA_DIR"] = "/tmp/lfx-restore-import"; os.makedirs("/tmp/lfx-restore-import", exist_ok=True)
    from app.main import _encrypt_backup          # the very function that makes the off-server copy
    from app import watchdog
    import decrypt_backup                         # the restore tool
    password = "drill-password-not-the-real-one"
    blob = _encrypt_backup(raw, password)
    ok("the encrypted copy is not readable as it is", blob[:5] == b"LFXB1" and raw[:16] not in blob)
    # ---- 3. decrypt with the restore tool ----
    try:
        decrypt_backup.decrypt(blob, "a wrong password"); wrong_ok = True
    except Exception:
        wrong_ok = False
    ok("a wrong password does not open the backup", not wrong_ok)
    back = decrypt_backup.decrypt(blob, password)
    ok("the right password gives back exactly the same file", back == raw)
    # ---- 4. a brand-new site from nothing but that file ----
    subprocess.run("pkill -f 'uvicorn app.main:app --port 8002'", shell=True); time.sleep(1)
    shutil.rmtree(NEW, ignore_errors=True); os.makedirs(NEW)
    open(os.path.join(NEW, "papertrade.db"), "wb").write(back)
    from pathlib import Path
    chk = watchdog.check_backup(Path(NEW) / "papertrade.db", None)
    ok("the restored file passes the backup check", chk["ok"], chk)
    env = dict(os.environ, PT_FEED="mock", PT_DATA_DIR=NEW, PT_CANONICAL_HOST="www.limefx.in", PT_PROBE_AT="99:99", PT_WEEK_TEST="1", PT_ACCESS_ALL="1",
               PT_STRICT_LIQ_GRACE_MIN="0", PT_DELTA_REST="http://localhost:8765", PT_DELTA_WS="ws://localhost:8765", PT_CTRADER_WS="ws://localhost:8766",
               PT_CTRADER_CLIENT_ID="cid", PT_CTRADER_CLIENT_SECRET="csec", PT_CTRADER_ACCOUNT="10135462", PT_CTRADER_TOKEN="tok-ok")
    log = open(os.path.join(NEW, "server.log"), "w")
    srv = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", "8002"], cwd=ROOT, env=env, stdout=log, stderr=log)
    try:
        up = False
        for _ in range(60):
            time.sleep(1)
            try:
                if httpx.get(B_URL + "/healthz", timeout=5).status_code == 200:
                    up = True; break
            except Exception:
                pass
        ok("the restored site starts and answers", up)
        time.sleep(40)                                 # the simulated feeds need half a minute to list their contracts
        b = httpx.Client(base_url=B_URL, timeout=600)
        ok("the Master can log in on the restored site with the same password", b.post("/api/login", json={"username": "admin", "password": "admin123"}).status_code == 200)
        ok("a login token from the old server is not accepted on the new one (new signing key)", httpx.get(B_URL + "/api/admin/users", cookies=dict(a.cookies), timeout=20).status_code in (401, 403))
        # ---- 5. compare ----
        after = facts(b)
        ok("the same accounts exist", sorted(before) == sorted(after), f"{sorted(before)} vs {sorted(after)}")
        for name in sorted(before):
            if name.startswith("__"):
                ok(f"restored: {name.strip('_').replace('_', ' ')} identical", before[name] == after.get(name), f"{before[name]} vs {after.get(name)}")
                continue
            for part in ("balance", "allocated", "active", "positions", "orders", "trades", "ledger", "access"):
                x, y = before[name][part], after.get(name, {}).get(part)
                if part == "orders":             # a resting order may fill or stay; everything already decided must be identical
                    x = [o for o in x if o[3] != "OPEN"]; y = [o for o in (y or []) if o[0] in {o2[0] for o2 in x}]
                ok(f"restored: {name} {part} identical", x == y, f"{str(x)[:140]} vs {str(y)[:140]}")
        ub = httpx.Client(base_url=B_URL, timeout=60)
        ok("a user can log in on the restored site with his password", ub.post("/api/login", json={"username": "drilla", "password": "Drill@67890"}).status_code == 200)
        r = ub.post("/api/orders", json={"token": mcx["token"], "side": "BUY", "lots": 1})
        ok("a user can trade on the restored site (closing his carried position)", r.status_code == 200, r.text[:160])
        wk = ub.get("/api/weekly").json()
        ok("the restored site still shows his finished week", bool(wk.get("weeks")))
        pj = b.post("/api/admin/probe/run").json()
        ok("the full safety check passes on the restored site", pj.get("failed") == 0 and pj.get("passed", 0) > 200, f"{pj.get('passed')} passed, {pj.get('failed')} failed: {[x['check'] for x in pj.get('rows', []) if x['ok'] is False][:4]}")
        ok("the restored site logged no error", "Traceback" not in open(os.path.join(NEW, "server.log")).read())
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=10)
        except Exception:
            srv.kill()
    print(f"\nRESTORE {passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
