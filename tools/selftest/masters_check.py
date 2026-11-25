"""Masters under the owner (owner's decision, 25 Nov 2026): the walls between the books, the stock of coins and
the weekly share. Run against the private copy:  tools/selftest/run.sh keep ; python3 tools/selftest/masters_check.py
Prints one line per check and 'MASTERS n passed, m failed'. Nothing here touches the live site."""
import re, sys, time, secrets, pathlib
import httpx

BASE = "http://localhost:8001"
ROOT = pathlib.Path(__file__).resolve().parents[2]
res = []


def ok(name, cond, info=""):
    res.append(bool(cond)); print("PASS" if cond else "FAIL", "|", name, "|", info if not cond else "")


def client():
    return httpx.Client(base_url=BASE, timeout=120)


def login(u, p, new=None):
    c = client()
    r = c.post("/api/login", json={"username": u, "password": p})
    assert r.status_code == 200, (u, r.status_code, r.text)
    if new:
        r = c.post("/api/password", json={"old_password": p, "new_password": new})
        assert r.status_code == 200, r.text
    return c


tag = secrets.token_hex(3)
own = login("admin", "admin123")
m1n, m2n, a1n, b1n, o1n = f"mone{tag}", f"mtwo{tag}", f"ua{tag}", f"ub{tag}", f"uo{tag}"

# ---- the owner creates two masters and one user of his own ----
r = own.post("/api/admin/masters", json={"username": m1n, "display_name": "Master One", "password": "first123", "share_pct": 40, "stock": 500000})
ok("owner creates a master", r.status_code == 200 and r.json()["stock"] == 500000 and r.json()["share_pct"] == 40, r.text)
M1 = r.json()["id"]
M2 = own.post("/api/admin/masters", json={"username": m2n, "display_name": "Master Two", "password": "first123", "share_pct": 25, "stock": 100000}).json()["id"]
O1 = own.post("/api/admin/users", json={"username": o1n, "password": "first123", "display_name": "Owner user", "initial_coins": 300000}).json()["id"]
ok("a share above 100% is refused", own.post("/api/admin/masters", json={"username": "x" + tag, "password": "first123", "share_pct": 140}).status_code == 400)
ok("a master is not listed among the full-control logins", all(a["username"] != m1n for a in own.get("/api/admin/admins").json()))
ok("a master cannot be removed or reset as a full-control login", own.delete(f"/api/admin/admins/{M1}").status_code == 404
   and own.post(f"/api/admin/admins/{M1}/password", json={"password": "hacked123"}).status_code == 404)

# ---- first login: nothing answers before he chose his own password ----
c = client(); c.post("/api/login", json={"username": m1n, "password": "first123"})
ok("new master: nothing before his own password", c.get("/api/master/me").status_code == 403)
pg = c.get("/admin").text
ok("new master is sent his own page to choose the password", "pwGate" in pg and "nav-shadow" not in pg)
m1 = login(m1n, "first123", "mine12345"); m2 = login(m2n, "first123", "mine12345")
pg = m1.get("/admin").text
ok("a master's page is his own small page, never the owner's", "nav-coins" in pg and "nav-shadow" not in pg and "/api/admin/" not in pg and "kiteBox" not in pg)
ok("the owner still gets the owner's page", "nav-shadow" in own.get("/admin").text)

# ---- every owner call is closed to a master ----
src = (ROOT / "app" / "main.py").read_text()
routes = re.findall(r'^@app\.(get|post|put|patch|delete)\("(/api/admin/[^"]*)"', src, re.M)
allowed = {"/api/admin/2fa/setup", "/api/admin/2fa/confirm", "/api/admin/2fa/disable"}      # each login's own two-step set-up
leaks = []
for meth, path in routes:
    if path in allowed or path.startswith("/api/admin/weekly/test-close"):
        continue
    url = path.replace("{uid}", str(O1)).replace("{mid}", str(M2))
    rr = m1.request(meth.upper(), url, json={} if meth != "get" else None)
    if rr.status_code != 403:
        leaks.append(f"{meth} {path} -> {rr.status_code}")
ok(f"all {len(routes)} owner calls answer a master with 'not allowed'", not leaks and len(routes) > 50, "; ".join(leaks[:8]))
ok("the weekly test switch is closed to a master", m1.post("/api/admin/weekly/test-close").status_code == 403)
ok("an ordinary user gets nothing from the master calls", login(o1n, "first123", "mine12345").get("/api/master/users").status_code == 403)
ok("the owner is not a 'master under the owner'", own.get("/api/master/users").status_code == 403)
ok("a visitor gets nothing from the master calls", client().get("/api/master/users").status_code == 401)

# ---- the stock of coins ----
r = m1.post("/api/master/users", json={"username": a1n, "password": "first123", "display_name": "User A", "initial_coins": 200000})
ok("master creates a user from his stock", r.status_code == 200 and m1.get("/api/master/me").json()["stock"] == 300000, r.text)
A1 = r.json()["id"]
B1 = m2.post("/api/master/users", json={"username": b1n, "password": "first123", "display_name": "User B", "initial_coins": 50000}).json()["id"]
ok("more first coins than he holds: refused", m1.post("/api/master/users", json={"username": "y" + tag, "password": "first123", "initial_coins": 300000.01}).status_code == 400)
ok("deposit above his stock: refused", m1.post(f"/api/master/users/{A1}/coins", json={"amount": 300001}).status_code == 400)
ok("deposit from the stock", m1.post(f"/api/master/users/{A1}/coins", json={"amount": 100000}).json()["stock"] == 200000)
ok("withdrawal returns to the stock", m1.post(f"/api/master/users/{A1}/coins", json={"amount": -50000}).json()["stock"] == 250000)
ok("withdrawing more than the user was given: refused", m1.post(f"/api/master/users/{A1}/coins", json={"amount": -250000.01}).status_code == 400)
for bad in ("nan", "inf", 1e15):
    rr = m1.post(f"/api/master/users/{A1}/coins", content='{"amount": %s}' % ("NaN" if bad == "nan" else "Infinity" if bad == "inf" else bad), headers={"Content-Type": "application/json"})
    ok(f"an impossible amount ({bad}) is refused", rr.status_code in (400, 422), rr.text[:80])
me = m1.get("/api/master/me").json()
ok("stock + coins with users = coins the owner gave", abs(me["stock"] + me["with_users"] - me["given"]) < 0.01 and me["given"] == 500000, str(me))
ok("owner takes back more than the master holds: refused", own.post(f"/api/admin/masters/{M1}/stock", json={"amount": -250000.01}).status_code == 400)
ok("owner gives and takes back stock", own.post(f"/api/admin/masters/{M1}/stock", json={"amount": 50000}).json()["stock"] == 300000
   and own.post(f"/api/admin/masters/{M1}/stock", json={"amount": -50000}).json()["stock"] == 250000)
ok("the owner's ordinary coins call does not reach a master's stock", own.post(f"/api/admin/users/{M1}/coins", json={"amount": 999}).status_code == 400)

# ---- the walls between the books ----
ok("a master sees only his own users", [u["username"] for u in m1.get("/api/master/users").json()] == [a1n])
for who, uid in (("the owner's user", O1), ("another master's user", B1), ("another master", M2), ("the owner", 1)):
    codes = [m1.get(f"/api/master/users/{uid}/detail").status_code, m1.post(f"/api/master/users/{uid}/coins", json={"amount": 10}).status_code,
             m1.patch(f"/api/master/users/{uid}", json={"password": "hacked123"}).status_code]
    ok(f"a master cannot look at or change {who}", codes == [404, 404, 404], str(codes))
ok("the owner's user list holds only his own users", a1n not in [u["username"] for u in own.get("/api/admin/users").json()] and o1n in [u["username"] for u in own.get("/api/admin/users").json()])
ok("the owner sees a master's users under that master", [u["username"] for u in own.get(f"/api/admin/users?master={M1}").json()] == [a1n])
ok("the owner can look at a master's user", own.get(f"/api/admin/users/{A1}/detail").status_code == 200)
codes = [own.post(f"/api/admin/users/{A1}/coins", json={"amount": 10}).status_code, own.patch(f"/api/admin/users/{A1}", json={"is_active": False}).status_code,
         own.delete(f"/api/admin/users/{A1}").status_code, own.post(f"/api/admin/users/{A1}/squareoff").status_code,
         own.post(f"/api/admin/users/{A1}/alert", json={"text": "hello"}).status_code]
ok("the owner cannot change a master's user (look only)", codes == [403] * 5, str(codes))
ok("a master can reset his user's password and freeze him", m1.patch(f"/api/master/users/{A1}", json={"is_active": False}).json()["is_active"] is False
   and m1.patch(f"/api/master/users/{A1}", json={"is_active": True}).json()["is_active"] is True)

# ---- a master's stock is never trading money ----
tok = own.get("/api/futures", params={"exchange": "NFO", "name": "NIFTY"}).json()
tok = (tok if isinstance(tok, list) else tok.get("futures") or tok.get("rows"))[0]["token"]
r = m1.post("/api/orders", json={"token": tok, "side": "BUY", "lots": 1})
ok("a master cannot trade with his stock", r.status_code >= 400 or r.json().get("status") == "REJECTED", r.text[:120])
ok("... and holds no position", m1.get("/api/master/me").json()["stock"] == 250000)

# ---- his user trades; the week, the share (the percentage is what the OWNER takes of the master's book) ----
def adds_up(w, pct):
    return (abs(w["book_pnl"] + w["users_pnl"]) < 0.006 and abs(w["users_pnl"] - (w["users_result"] + w["commission"])) < 0.006
            and abs(w["book_pnl"] + w["commission"] - w["our_side"]) < 0.006 and abs(w["our_side"] + w["users_result"]) < 0.006
            and abs(w["owner_share"] - round(w["our_side"] * pct / 100, 2)) < 0.006 and abs(w["owner_share"] + w["master_share"] - w["our_side"]) < 0.006
            and abs(w["owner_from_pnl"] + w["owner_from_brokerage"] - w["owner_share"]) < 0.006
            and abs(w["owner_from_brokerage"] - round(w["commission"] * pct / 100, 2)) < 0.006 and w["share_pct"] == pct)


a1 = login(a1n, "first123", "mine12345")
r = a1.post("/api/orders", json={"token": tok, "side": "BUY", "lots": 1}); time.sleep(1)
ok("the master's user trades like any user", r.status_code == 200 and r.json()["order"]["status"] == "FILLED", r.text[:200])
wk = m1.get("/api/master/weeks").json()[0]
ok("running week: book P&L + brokerage = book total = owner's share + master's share; the owner takes his % of P&L and brokerage alike",
   wk["users_result"] != 0 and wk["commission"] > 0 and adds_up(wk, 40), str(wk))
ok("the owner's weekly table holds only his own users", a1n not in [x["username"] for x in own.get("/api/admin/weekly").json()["rows"]])
ok("the owner's Masters list shows the same week to the paisa", abs(next(m for m in own.get("/api/admin/masters").json() if m["id"] == M1)["this_week"]["commission"] - wk["commission"]) < 0.006)
ok("a user with an open position cannot be deleted", m1.delete(f"/api/master/users/{A1}").status_code == 400)
r = m1.post(f"/api/master/users/{A1}/squareoff")
ok("a master squares his own user off", r.status_code == 200 and r.json()["closed"] == 1 and not m1.get(f"/api/master/users/{A1}/detail").json()["positions"], r.text[:160])
ok("a master cannot square off or delete anybody else's user", [m1.post(f"/api/master/users/{u}/squareoff").status_code for u in (O1, B1)] + [m1.delete(f"/api/master/users/{u}").status_code for u in (O1, B1, M2)] == [404] * 5)
wk = m1.get("/api/master/weeks").json()[0]
# ---- deleting a user who traded: the account goes, its records stay (owner's decision) ----
r = m1.delete(f"/api/master/users/{A1}")
me = m1.get("/api/master/me").json()
ok("a flat user is deleted, his coins return to the master", r.status_code == 200 and me["stock"] == 500000 and me["with_users"] == 0 and me["users"] == 0 and me["deleted_users"] == 1, r.text[:120] + str(me))
ok("stock + coins with users = coins the owner gave, after the delete too", abs(me["stock"] + me["with_users"] - me["given"]) < 0.01)
wk2 = m1.get("/api/master/weeks").json()[0]
ok("the running week still counts what the deleted user made or lost, to the paisa", wk2 == wk and wk["users_result"] != 0, f"{wk} -> {wk2}")
ok("... on the owner's side too", own.get(f"/api/admin/masters/{M1}").json()["weeks"][0] == wk)
ok("the deleted user is still in the master's list and week, marked deleted", [u["deleted"] for u in m1.get("/api/master/users").json()] == [True]
   and [x["deleted"] for x in m1.get("/api/master/weekly").json()["rows"]] == [True])
d = m1.get(f"/api/master/users/{A1}/detail")
ok("his trades and ledger can still be read", d.status_code == 200 and len(d.json()["trades"]) == 2 and own.get(f"/api/admin/users/{A1}/detail").status_code == 200)
ok("the deleted account cannot log in and its open login ended", a1.get("/api/me").status_code == 401 and client().post("/api/login", json={"username": a1n, "password": "mine12345"}).status_code == 401)
codes = [m1.post(f"/api/master/users/{A1}/coins", json={"amount": 10}).status_code, m1.patch(f"/api/master/users/{A1}", json={"is_active": True}).status_code,
         m1.delete(f"/api/master/users/{A1}").status_code, m1.post(f"/api/master/users/{A1}/squareoff").status_code]
ok("a deleted account cannot be given coins, unfrozen or deleted again", codes == [404] * 4, str(codes))
before = m1.get("/api/master/me").json()
r = own.post("/api/admin/weekly/test-close")
if r.status_code == 200:
    time.sleep(2)
    after = m1.get("/api/master/me").json()
    ok("the weekly cut-off leaves a master's stock alone", after["stock"] == before["stock"] and after["given"] == before["given"], f"{before} -> {after}")
    weeks = m1.get("/api/master/weeks").json(); fin = [w for w in weeks if w["final"]][0]
    ok("the finished week is booked as it stood, deleted user included, and adds up", adds_up(fin, 40) and abs(fin["users_result"] - wk["users_result"]) < 0.006 and abs(fin["commission"] - wk["commission"]) < 0.006 and fin["users"] == 1, str(fin))
    ok("the new week starts empty: a deleted account shows only in weeks it did something in", weeks[0]["users"] == 0 and weeks[0]["users_result"] == 0, str(weeks[0]))
    own.patch(f"/api/admin/masters/{M1}", json={"share_pct": 55})
    weeks = own.get(f"/api/admin/masters/{M1}").json()["weeks"]
    ok("changing the percentage later does not rewrite a finished week", [w for w in weeks if w["final"]][0] == fin and weeks[0]["share_pct"] == 55, str(weeks[:2]))
    me = m1.get("/api/master/me").json()
    ok("the deleted account's coins stayed at nothing through the cut-off", me["with_users"] == 0 and abs(me["stock"] + me["with_users"] - me["given"]) < 0.01, str(me))
    r = m1.post("/api/master/users", json={"username": a1n, "password": "first123", "display_name": "User A", "initial_coins": 1000})
    ok("the deleted user's name is free for a new account", r.status_code == 200, r.text[:120])
    A1 = r.json()["id"]; a1 = login(a1n, "first123", "mine12345")
else:
    ok("weekly test switch available on the private copy", False, r.text[:100])

# ---- the record, pause, removal ----
aud = " ".join(x["detail"] for x in own.get("/api/admin/audit").json())
ok("the master's deposits and withdrawals are in the owner's activity record", f"Master {m1n} gave" in aud and f"Master {m1n} took back" in aud and f"Created master {m1n}" in aud)
ok("no password in the activity record", "first123" not in aud and "mine12345" not in aud)
ok("a master with users cannot be removed", own.delete(f"/api/admin/masters/{M1}").status_code == 400)
own.patch(f"/api/admin/masters/{M1}", json={"is_active": False})
ok("a paused master is logged out at once and cannot log in", m1.get("/api/master/me").status_code == 401
   and client().post("/api/login", json={"username": m1n, "password": "mine12345"}).status_code == 403)
ok("... while his user trades on", a1.get("/api/me").status_code == 200)
own.patch(f"/api/admin/masters/{M1}", json={"is_active": True})
ok("resumed", login(m1n, "mine12345").get("/api/master/me").status_code == 200)
own.patch(f"/api/admin/masters/{M1}", json={"password": "again1234"})
ok("owner's password reset ends the master's old logins", m1.get("/api/master/me").status_code == 401)

print(f"\nMASTERS {sum(res)} passed, {len(res) - sum(res)} failed")
sys.exit(0 if all(res) else 1)
