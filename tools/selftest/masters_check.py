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
# (26 Nov 2026) the page's own text held six unused style rules named after a price-feed provider's product, copied
# from the owner's page: anyone reading the page source saw the name. No provider name anywhere in what a master is sent.
named = sorted({x.group(0).lower() for x in re.finditer(r"zerodha|kite|c-?trader|ic ?markets|spotware|delta|telegram", pg, re.I)})
ok("no price-feed provider is named anywhere in the page a master is sent (styles and script included)", not named, ", ".join(named))

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

# ---- the owner's own users: records always remain too (owner's decision, 25 Nov 2026, 14:20) ----
o1 = login(o1n, "mine12345")
o1.post("/api/orders", json={"token": tok, "side": "BUY", "lots": 1}); time.sleep(1)
ok("owner: a user with an open position cannot be deleted", own.delete(f"/api/admin/users/{O1}").status_code == 400)
own.post(f"/api/admin/users/{O1}/squareoff"); time.sleep(1)
w0 = next(x for x in own.get("/api/admin/weekly").json()["rows"] if x["user_id"] == O1)
r = own.delete(f"/api/admin/users/{O1}")
rows = own.get("/api/admin/weekly").json()["rows"]; w1 = next((x for x in rows if x["user_id"] == O1), None)
ok("owner deletes his user: the running week still counts him, to the paisa", r.status_code == 200 and w1 is not None and w1["deleted"]
   and abs(w1["result"] - w0["result"]) < 0.006 and abs(w1["commission"] - w0["commission"]) < 0.006 and w0["result"] != 0, f"{w0} -> {w1}")
lst = [u for u in own.get("/api/admin/users").json() if u["id"] == O1]
ok("... he stays in the Users list marked deleted, with his trades and no coins", len(lst) == 1 and lst[0]["deleted"] and lst[0]["trades"] == 2 and lst[0]["total_credited"] == 0, str(lst)[:200])
ok("... his trades can still be read, he cannot log in, and he cannot be changed", len(own.get(f"/api/admin/users/{O1}/detail").json()["trades"]) == 2
   and o1.get("/api/me").status_code == 401 and own.post(f"/api/admin/users/{O1}/coins", json={"amount": 5}).status_code == 400
   and own.patch(f"/api/admin/users/{O1}", json={"is_active": True}).status_code == 400)
ok("... and his name is free for a new account with a number of its own", own.post("/api/admin/users", json={"username": o1n, "password": "first123"}).json().get("id") not in (None, O1))

# ---- a deleted account is treated the same on every list and in every Excel file (Accounts officer, 26 Nov 2026) ----
# Found 26 Nov 2026: the Users list left out an account deleted before it ever traded, while Performance, the
# Master summary Excel and the all-users Excel still listed it (and counted it as a user); the summary Excel called
# a deleted account "frozen"; and the Weekly Settlement sheet of both files gave a deleted account a line of zeros
# in every later week, which the Weekly Settlement tab leaves out.
import io
from openpyxl import load_workbook
zn = f"uz{tag}"
OZ = own.post("/api/admin/users", json={"username": zn, "password": "first123", "display_name": "Never traded", "initial_coins": 5000}).json()["id"]
own.delete(f"/api/admin/users/{OZ}")
ids = lambda rows: sorted(x["id"] for x in rows)
users_l = own.get("/api/admin/users").json(); perf = own.get("/api/admin/report").json()["users"]
ok("deleted accounts: Users and Performance list the same accounts (one that never traded is in neither)",
   ids(users_l) == ids(perf) and OZ not in ids(perf) and O1 in ids(perf), f"{ids(users_l)} / {ids(perf)}")
ok("... and Performance says which rows are deleted accounts", [x["deleted"] for x in perf if x["id"] == O1] == [True] and all(x["deleted"] == ("~deleted" in x["username"]) for x in perf))
wbk = load_workbook(io.BytesIO(own.get("/api/admin/summary.xlsx").content))
ms = [r for r in wbk["Master Summary"].iter_rows(values_only=True)]
urows = [r for r in ms[8:] if r[1] and r[0] != "TOTAL"]
ok("Master summary Excel: the same accounts as the Users list, a deleted one marked deleted (not frozen) under its plain name",
   sorted(r[1] for r in urows) == sorted(re.sub(r"~deleted\d+$", "", u["username"]) for u in users_l)
   and [r[2] for r in urows if r[1] == o1n] and all(r[2] == "deleted" for r in urows if r[0] == "Owner user" and r[13] == 2)
   and "~deleted" not in str(ms) and f"{len([u for u in users_l if u['deleted']])} deleted" in str(ms[1][0])
   and f"{len([u for u in users_l if not u['deleted']])} Users" in str(ms[1][0]), str([(r[1], r[2]) for r in urows]) + str(ms[1][0]))
def sheet_weeks(wb_):
    rows = [r for r in wb_["Weekly Settlement"].iter_rows(values_only=True)][4:]
    return sorted((r[1], str(r[2])) for r in rows if r[1] in ("FINAL", "PROVISIONAL"))
tab = []
for we in [None] + own.get("/api/admin/weekly").json()["weeks"]:
    rep = own.get("/api/admin/weekly", params={"week_end": we} if we else {}).json()
    tab += [("FINAL" if rep["final"] else "PROVISIONAL", x["display_name"] + (" (deleted)" if x["deleted"] else "")) for x in rep["rows"]]
ok("Excel Weekly Settlement sheet (summary file): the same lines as the Weekly Settlement tab, week by week; a deleted account only in weeks it did something in",
   sheet_weeks(wbk) == sorted(tab) and ("PROVISIONAL", "Owner user (deleted)") in tab and not any("Never traded" in t[1] for t in tab), f"{sheet_weeks(wbk)} / {sorted(tab)}")
wbe = load_workbook(io.BytesIO(own.get("/api/admin/export.xlsx").content))
ok("Excel for all users: the same Weekly Settlement lines, and its Summary lists the accounts of the Users list",
   sheet_weeks(wbe) == sorted(tab) and "Never traded" not in str([r for r in wbe["Summary"].iter_rows(values_only=True)])
   and "~deleted" not in str([r for r in wbe["Summary"].iter_rows(values_only=True)]), str(sheet_weeks(wbe)))
ok("a master's Performance figures leave out an account deleted before it traded, as his Users list does",
   ids(m2.get("/api/master/users").json()) == ids(m2.get("/api/master/report").json()["users"]))

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

# ---- Technology officer, 26 Nov 2026: coins move one at a time ----
# Found: two movements of coins at the same instant (two tabs, a double click) each read the stock, worked out its
# own new figure and wrote it: from a stock of 100,000 a master gave 100,000 to each of two users, both accepted,
# and taking them back left him 200,000. Each movement now waits for its turn, as an order does.
import threading


def at_once(*calls):
    gate, out = threading.Barrier(len(calls)), [None] * len(calls)

    def go(i, f):
        gate.wait()
        try:
            out[i] = f().status_code
        except Exception as e:      # a dropped connection is not an answer
            out[i] = type(e).__name__
    th = [threading.Thread(target=go, args=(i, f)) for i, f in enumerate(calls)]
    [t.start() for t in th]; [t.join() for t in th]
    return out


m3n = f"mthree{tag}"
M3 = own.post("/api/admin/masters", json={"username": m3n, "display_name": "Master Three", "password": "first123", "share_pct": 10, "stock": 100000}).json()["id"]
m3 = login(m3n, "first123", "mine12345"); m3b = login(m3n, "mine12345")
c1 = m3.post("/api/master/users", json={"username": f"uc{tag}", "password": "first123", "initial_coins": 0}).json()["id"]
c2 = m3.post("/api/master/users", json={"username": f"ud{tag}", "password": "first123", "initial_coins": 0}).json()["id"]
books = lambda: (lambda d: (d["stock"], d["with_users"], d["given"]))(own.get(f"/api/admin/masters/{M3}").json())
coins_of = lambda uid: own.get(f"/api/admin/users/{uid}/detail").json()["user"]["balance"]
bad, answers = [], set()
for _ in range(12):
    r = at_once(lambda: m3.post(f"/api/master/users/{c1}/coins", json={"amount": 100000}), lambda: m3b.post(f"/api/master/users/{c2}/coins", json={"amount": 100000}))
    answers.add(tuple(sorted(r)))
    s_, w_, g_ = books()
    if sorted(r) != [200, 400] or (s_, w_, g_) != (0.0, 100000.0, 100000.0) or coins_of(c1) + coins_of(c2) != 100000.0:
        bad.append((r, s_, w_, g_))
    for u_ in (c1, c2):
        if coins_of(u_) > 0:
            m3.post(f"/api/master/users/{u_}/coins", json={"amount": -coins_of(u_)})
    if books() != (100000.0, 0.0, 100000.0):
        bad.append(("after taking back", books())); break
ok("coins at once: a stock of 100,000 given whole to two users at the same instant goes to one of them only, every time (12 rounds)", not bad, f"{bad[:2]} answers {answers}")
bad = []
for _ in range(12):
    r = at_once(lambda: m3.post(f"/api/master/users/{c1}/coins", json={"amount": 60000}), lambda: m3b.post(f"/api/master/users/{c1}/coins", json={"amount": 60000}))
    if sorted(r) != [200, 400] or books() != (40000.0, 60000.0, 100000.0) or coins_of(c1) != 60000.0:
        bad.append((r, books(), coins_of(c1)))
    m3.post(f"/api/master/users/{c1}/coins", json={"amount": -coins_of(c1)})
ok("coins at once: the same gift pressed twice at the same instant is given once when the stock covers only one (12 rounds)", not bad and books() == (100000.0, 0.0, 100000.0), f"{bad[:2]} {books()}")
bad = []
for k in range(8):
    r = at_once(lambda: m3.post("/api/master/users", json={"username": f"ue{k}{tag}", "password": "first123", "initial_coins": 100000}),
                lambda: m3b.post("/api/master/users", json={"username": f"uf{k}{tag}", "password": "first123", "initial_coins": 100000}))
    s_, w_, g_ = books()
    if sorted(r) != [200, 400] or (s_, w_, g_) != (0.0, 100000.0, 100000.0):
        bad.append((r, s_, w_, g_))
    for u_ in m3.get("/api/master/users").json():
        if u_["balance"] > 0:
            m3.post(f"/api/master/users/{u_['id']}/coins", json={"amount": -u_["balance"]})
ok("coins at once: two new users each given the whole stock at the same instant: one is created with the coins, the other refused (8 rounds)", not bad, str(bad[:2]))
r = at_once(lambda: own.post(f"/api/admin/masters/{M3}/stock", json={"amount": -100000}), lambda: m3.post(f"/api/master/users/{c1}/coins", json={"amount": 100000}))
s_, w_, g_ = books()
ok("coins at once: the owner takes the stock back while the master hands it out: one of the two happens, the books add up",
   sorted(r) == [200, 400] and s_ == 0.0 and (w_, g_) in ((0.0, 0.0), (100000.0, 100000.0)), f"{r} {s_} {w_} {g_}")
o2 = own.post("/api/admin/users", json={"username": f"uo2{tag}", "password": "first123", "initial_coins": 1000}).json()["id"]
r = at_once(*[(lambda: client_own.post(f"/api/admin/users/{o2}/coins", json={"amount": 10})) for client_own in [own, login("admin", "admin123"), login("admin", "admin123"), login("admin", "admin123")] for _ in range(5)])
led = own.get(f"/api/admin/users/{o2}/detail").json()
ok("coins at once: twenty gifts of 10 coins from the owner at the same instant all arrive (ledger and coins agree)",
   r == [200] * 20 and led["user"]["balance"] == 1200.0 and round(sum(l["amount"] for l in led["ledger"]), 2) == 1200.0, f"{r} {led['user']['balance']}")

# The same between a movement of coins and a fill of that user's own order: the coin call wrote the balance it had
# read before the fill, so the fill's profit, loss or commission never reached the balance (ledger line written,
# coins unchanged): 20 of 300 owner's gifts and 49 of 300 master's gifts made during non-stop trading went wrong.


def gifts_during_fills(trader, give, uid):
    stop, fills = [False], [0]

    def trade():
        k = 0
        while not stop[0]:
            k += 1
            fills[0] += trader.post("/api/orders", json={"token": tok, "side": "BUY" if k % 2 else "SELL", "lots": 1}).status_code == 200
    t = threading.Thread(target=trade); t.start(); time.sleep(0.5)
    codes = {give().status_code for _ in range(120)}
    stop[0] = True; t.join(); time.sleep(0.5)
    d = own.get(f"/api/admin/users/{uid}/detail").json()
    led = d["ledger"]                     # newest first
    broken = [(led[i]["kind"], led[i]["amount"]) for i in range(len(led) - 1) if abs(led[i + 1]["balance_after"] + led[i]["amount"] - led[i]["balance_after"]) > 0.011]
    return codes == {200} and fills[0] >= 5 and not broken and abs(led[0]["balance_after"] - d["user"]["balance"]) < 0.011, f"answers {codes}, fills {fills[0]}, lines that do not follow from the one before: {broken[:3]}"


t1 = own.post("/api/admin/users", json={"username": f"ut1{tag}", "password": "first123", "initial_coins": 3000000}).json()["id"]
own.post(f"/api/admin/masters/{M3}/stock", json={"amount": 3100000})
t2 = m3.post("/api/master/users", json={"username": f"ut2{tag}", "password": "first123", "initial_coins": 3000000}).json()["id"]
ok("coins at once: 120 gifts from the owner while that user's orders fill: every ledger line follows from the one before, coins = last line",
   *gifts_during_fills(login(f"ut1{tag}", "first123", "mine12345"), lambda: own.post(f"/api/admin/users/{t1}/coins", json={"amount": 1}), t1))
ok("coins at once: 120 gifts from a master while that user's orders fill: the same",
   *gifts_during_fills(login(f"ut2{tag}", "first123", "mine12345"), lambda: m3.post(f"/api/master/users/{t2}/coins", json={"amount": 1}), t2))
s3_, w3_, g3_ = books()
ok("coins at once: the master's books still add up after it", abs(s3_ + w3_ - g3_) < 0.01, f"{s3_} {w3_} {g3_}")

# A deleted account's name is marked with its number; cut at the end, a name of 57 letters or more lost the number:
# a 64-letter name was not freed, and the second account of a 60-letter name could never be deleted (an error).
for n_ in (64, 60, 57):
    long_name, got = ("z" + tag) * 10, []
    long_name = long_name[:n_]
    for _ in range(3):
        r = own.post("/api/admin/users", json={"username": long_name, "password": "first123", "initial_coins": 500})
        got.append(r.status_code)
        if r.status_code == 200:
            got.append(own.delete(f"/api/admin/users/{r.json()['id']}").status_code)
    ok(f"delete: a name of {n_} letters is freed and can be created and deleted again and again", got == [200] * 6, str(got))
r = m3.post("/api/master/users", json={"username": ("y" + tag) * 9 + "y", "password": "first123", "initial_coins": 0})
r2 = m3.delete(f"/api/master/users/{r.json()['id']}") if r.status_code == 200 else r
r3 = m3.post("/api/master/users", json={"username": ("y" + tag) * 9 + "y", "password": "first123", "initial_coins": 0})
ok("delete: the same for a master's user with a 64-letter name", (r.status_code, r2.status_code, r3.status_code) == (200, 200, 200), f"{r.status_code} {r2.status_code} {r3.status_code}")
# ---- coins cannot be made out of nothing by firing deposits at the same instant (26 Nov 2026) ----
# A master's stock is read, checked to be enough, then the move is booked. Two deposits firing together used
# to read the same stock, both pass and both book: coins the owner never gave. The stock moves now take their
# turn, so stock + coins with his users = coins the owner gave, however many fire at once.
import threading
rc = own.post("/api/admin/masters", json={"username": f"mrace{tag}", "display_name": "Race", "password": "first123", "share_pct": 20, "stock": 1000000})
if rc.status_code == 200:
    MR = rc.json()["id"]; mr = login(f"mrace{tag}", "first123", "mine12345")
    N, AMT = 12, 90000                                   # a stock of 1,000,000 funds only 11 such deposits
    ruids = [mr.post("/api/master/users", json={"username": f"ur{tag}{i}", "password": "first123", "initial_coins": 0}).json()["id"] for i in range(N)]
    bar = threading.Barrier(N); succ = [0] * N
    def _dep(i, uid):
        cl = httpx.Client(base_url=BASE, timeout=120, cookies=mr.cookies)
        bar.wait()
        succ[i] = 1 if cl.post(f"/api/master/users/{uid}/coins", json={"amount": AMT}).status_code == 200 else 0
    ts = [threading.Thread(target=_dep, args=(i, uid)) for i, uid in enumerate(ruids)]
    [t.start() for t in ts]; [t.join() for t in ts]
    meR = mr.get("/api/master/me").json(); nsucc = sum(succ)
    ok("deposits firing together cannot overspend the stock (coins from nothing)",
       abs(meR["stock"] + meR["with_users"] - meR["given"]) < 0.01 and nsucc <= 1000000 // AMT,
       f"{nsucc}/{N} succeeded; stock={meR['stock']} with_users={meR['with_users']} given={meR['given']}")
    for uid in ruids:
        mr.post(f"/api/master/users/{uid}/coins", json={"amount": -AMT})
        mr.delete(f"/api/master/users/{uid}")

    # ---- deleting a user at the same instant his order fills: never a shut account still holding a position ----
    # The delete's "no open positions" check and the fill used to run side by side (delete has the stock lock,
    # the fill has the order lock): the check saw no position, the account was shut, then the fill opened one on
    # the shut account (seen 26 Nov 2026, 5 of 15 tries). The delete now takes the order lock too, so the two
    # take turns: the fill goes first (delete refused — open position) or the delete goes first (order refused —
    # account frozen). Never both.
    ctok = next((x["token"] for x in own.get("/api/search?q=BTC").json() if x.get("exchange") == "CRYPTO"), None)
    stuck = 0
    if ctok:
        for i in range(10):
            ruid = mr.post("/api/master/users", json={"username": f"udr{tag}{i}", "password": "first123", "initial_coins": 400000}).json()["id"]
            ru = login(f"udr{tag}{i}", "first123", "mine12345")
            bar2 = threading.Barrier(2)
            def _ord():
                cl = httpx.Client(base_url=BASE, timeout=120, cookies=ru.cookies); bar2.wait()
                cl.post("/api/orders", json={"token": ctok, "side": "BUY", "lots": 1})
            def _del():
                cl = httpx.Client(base_url=BASE, timeout=120, cookies=mr.cookies); bar2.wait()
                cl.delete(f"/api/master/users/{ruid}")
            t1 = threading.Thread(target=_ord); t2 = threading.Thread(target=_del)
            t1.start(); t2.start(); t1.join(); t2.join(); time.sleep(0.3)
            row = [x for x in mr.get("/api/master/users").json() if x["id"] == ruid]
            poss = mr.get(f"/api/master/users/{ruid}/detail").json().get("positions", [])
            if row and row[0].get("deleted") and poss:
                stuck += 1
            else:
                mr.post(f"/api/master/users/{ruid}/squareoff"); time.sleep(0.3); mr.delete(f"/api/master/users/{ruid}")
    ok("deleting a user as his order fills never shuts the account with a position still open", ctok is not None and stuck == 0, f"stuck={stuck}")
else:
    ok("a master for the concurrency check can be created", False, rc.text[:120])

print(f"\nMASTERS {sum(res)} passed, {len(res) - sum(res)} failed")
sys.exit(0 if all(res) else 1)
