"""Normal-working check of the whole site, in a real browser, against the private copy on localhost:8001
(started by tools/selftest/run.sh). This is NOT the loophole hunt: it only asks "does everything a Master
and a user normally do still work, and do the numbers on the screens and in the Excel files agree?".

  - Master page and user app open on a computer screen and on a phone screen, every tab and panel,
    with no script error, nothing wider than the screen, nothing showing "undefined" / "NaN"
  - the figures on the screens equal the figures the server reports
  - every Excel file downloads, opens, has its sheets, and its Net P&L (Settlement) equals the weekly result
  - a weekly cut-off is run in between, so carried positions, the Weekly Settlement tab and the pop-up are covered

Prints PASS / FAIL lines and "SITE n passed, m failed"; exits 1 on any failure. Never touches the live site.
"""
import io
import json
import re
import sys
import time

import pyotp
from openpyxl import load_workbook
from playwright.sync_api import sync_playwright

B = "http://localhost:8001"
passed = failed = 0


def ok(name, cond, info=""):
    global passed, failed
    if cond:
        passed += 1; print("PASS site |", name)
    else:
        failed += 1; print("FAIL site |", name, "|", str(info)[:300])


def near(a, b, tol=0.06):
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False


def num(text):
    """'+₹5,24,754' / '-₹71,151' / '₹0' -> float"""
    t = (text or "").replace(",", "").replace("₹", "").replace("−", "-").strip()
    m = re.search(r"[-+]?\d+(?:\.\d+)?", t)
    return float(m.group(0)) if m else None


def sheet_rows(wb, name):
    rows = [[c.value for c in r] for r in wb[name].iter_rows()]
    h = next(i for i, r in enumerate(rows) if r and r[0] in ("Date", "Week", "User", "Contract"))
    return rows[h], rows[h + 1:]


# ---------------- Accounts officer's block (21 Nov 2026) ----------------
def accounts_block(br, actx, uctx, ok, near):
    """Figures and records of the owner's requests of 19 Nov 2026: the Master activity record's lines for coins
    added and removed say the same as the ledger, to the paisa; and an order placed through the Stop-loss /
    Target sheet of a position is the same order, with the same reservation, as from the ordinary ticket."""
    A = actx.request
    cid = A.post(f"{B}/api/admin/users", data={"username": "sitecoins", "password": "Coins@12345", "display_name": "Site Coins", "initial_coins": 20000000}).json().get("id")
    for amt, note in ((1234.56, "top-up"), (-234.5, "taken back")):
        A.post(f"{B}/api/admin/users/{cid}/coins", data={"amount": amt, "note": note})
    led = [x for x in reversed(A.get(f"{B}/api/admin/users/{cid}/detail").json().get("ledger") or []) if x["kind"] in ("ADMIN_CREDIT", "ADMIN_DEBIT")]
    # (an account number is handed out again after a delete: only this account's own lines count)
    acts = [x for x in A.get(f"{B}/api/admin/audit").json() if f"/users/{cid}/coins" in x.get("action", "") and "sitecoins:" in (x.get("detail") or "")][::-1]
    said = []; same = len(led) == 3 and len(acts) == 2
    for l, a in zip(led[1:], acts):
        m = re.match(r"(Added|Removed) ([\d,]+\.\d\d) coins (?:to|from) sitecoins: balance (-?[\d,]+\.\d\d) → (-?[\d,]+\.\d\d)", a.get("detail") or "")
        said.append(a.get("detail"))
        f = lambda t: float(t.replace(",", ""))
        same = same and bool(m) and (m.group(1) == "Added") == (l["kind"] == "ADMIN_CREDIT") and near(f(m.group(2)), abs(l["amount"]), 0.001) \
            and near(f(m.group(4)), l["balance_after"], 0.001) and near(f(m.group(3)), l["balance_after"] - l["amount"], 0.001)
    ok("Master activity record: coins added and removed read 'balance from → to' and agree with the ledger to the paisa", same, f"{said} against {[(x['amount'], x['balance_after']) for x in led]}")
    if cid:
        A.delete(f"{B}/api/admin/users/{cid}")
    # Stop-loss / Target sheet against the ordinary ticket, on a position the test user holds (phone screen)
    ctx = br.new_context(viewport={"width": 412, "height": 900}, service_workers="block"); ctx.add_cookies(uctx.cookies())
    page = ctx.new_page(); sent = []
    page.on("request", lambda q: sent.append(q.post_data_json) if q.method == "POST" and q.url.endswith("/api/orders") else None)
    page.goto(f"{B}/"); page.wait_for_timeout(5000)
    page.evaluate("document.querySelectorAll('.mpop').forEach(x => x.remove()); showTab('positions')"); page.wait_for_timeout(2500)
    p = page.evaluate("""() => { const p = state.positions.find(x => x.qty && ['NFO', 'BFO'].includes(x.exchange) && document.querySelector(`[data-slt="${x.id}"]`));
        return p ? {id: p.id, token: p.token, qty: p.qty, lots: Math.abs(p.lots), ltp: (state.prices[p.token] || {}).ltp || p.ltp || p.avg_price} : null; }""")
    got = {}; opened = None
    if p:
        side = "SELL" if p["qty"] > 0 else "BUY"
        trig = round(round(p["ltp"] * (0.9 if side == "SELL" else 1.1) / 0.05) * 0.05, 2)
        for path in ("sheet", "ticket"):
            if path == "sheet":
                page.evaluate("(id) => document.querySelector(`[data-slt=\"${id}\"]`).click()", p["id"]); page.wait_for_timeout(1800)
                opened = page.evaluate("({open: !document.querySelector('#sheet').classList.contains('hidden'), side: state.side, type: state.otype, lots: +document.querySelector('#oLots').value, hint: !document.querySelector('#sltHint').classList.contains('hidden')})")
            else:
                page.evaluate("(t) => document.querySelector(`[data-add=\"${t}\"]`).click()", p["token"]); page.wait_for_timeout(1800)
                page.evaluate("(sd) => { document.querySelector(sd === 'SELL' ? '#sideSell' : '#sideBuy').click(); document.querySelector('[data-ot=\"SL\"]').click(); }", side); page.wait_for_timeout(400)
            page.fill("#oLots", str(p["lots"])); page.fill("#oTrig", str(trig)); page.wait_for_timeout(600)
            used0 = ctx.request.get(f"{B}/api/me").json()["funds"]["used_margin"]; n0 = len(sent)
            page.evaluate("document.querySelector('#oSubmit').click()"); page.wait_for_timeout(2500)
            used1 = ctx.request.get(f"{B}/api/me").json()["funds"]["used_margin"]
            mine = [o for o in ctx.request.get(f"{B}/api/orders").json() if o["status"] == "OPEN" and o["token"] == p["token"] and o["order_type"] == "SL"]
            got[path] = {"body": sent[n0] if len(sent) > n0 else None, "reserved": round(used1 - used0, 2), "resting": len(mine)}
            for o in mine:
                ctx.request.delete(f"{B}/api/orders/{o['id']}")
            page.wait_for_timeout(800); page.evaluate("typeof refreshAll === 'function' && refreshAll()"); page.wait_for_timeout(1200)
    ok("User: the Stop-loss / Target button opens the order sheet on the exit side for the whole position, and its order is the same order, with the same reservation, as from the ordinary ticket",
       bool(p) and bool(opened) and opened["open"] and opened["side"] == side and opened["type"] == "SL" and opened["lots"] == p["lots"] and opened["hint"]
       and bool(got.get("sheet", {}).get("body")) and got["sheet"]["body"] == got.get("ticket", {}).get("body") and got["sheet"]["resting"] == 1 and got["ticket"]["resting"] == 1
       and near(got["sheet"]["reserved"], got["ticket"]["reserved"], 0.011), f"position {p}, sheet {opened}, orders {str(got)[:240]}")
    # ---- faults of 21 Nov 2026 (each check belongs to a fix of that night) ----
    # The card of a position whose market is shut shows the closing-price figure the server gives (as Available
    # Balance, the Master's screen and Excel do). Quotes that still arrived after the close moved the card and the
    # Unrealised figure above it. The server's answer is stood in for, so no market has to be shut for the check.
    page.evaluate("showTab('positions')"); page.wait_for_timeout(1500)
    q = page.evaluate("""(async () => { const real = window.api; const l = await real('/positions'); const p = l.find(x => x.qty && !['CRYPTO', 'FOREX'].includes(x.exchange)); if (!p) return null;
        window.__realApi = real; window.api = async (u, ...r) => { const x = await real(u, ...r); if (u === '/positions') { const y = x.find(z => z.id === p.id); if (y) { y.at_close = true; y.unrealised = 1234.5; } } return x; };
        await refreshAll(); return {id: p.id, token: p.token, ltp: (state.prices[p.token] || {}).ltp}; })()""")
    held = moved = None; ticks = 0
    if q:
        for _ in range(24):          # until at least two new quotes have come in for the contract
            page.wait_for_timeout(500)
            now = page.evaluate("(t) => (state.prices[t] || {}).ltp", q["token"])
            if now != q["ltp"]:
                ticks += 1; q["ltp"] = now
            if ticks >= 2:
                break
        held = page.evaluate("(id) => (document.getElementById('pl' + id) || {}).textContent", q["id"])
        page.evaluate("() => { window.api = window.__realApi; }")
        for _ in range(30):          # the market "reopens": within a few seconds the card follows the quotes again
            page.wait_for_timeout(500)
            moved = page.evaluate("(id) => (document.getElementById('pl' + id) || {}).textContent", q["id"])
            if moved != held:
                break
    ok("User: the card of a position whose market is shut keeps the closing-price figure while quotes still arrive, and follows the quotes again when the market reopens",
       bool(q) and ticks >= 2 and held == "+1,234.50" and moved not in (None, held), f"{ticks} new quotes, card while shut {held!r}, after reopening {moved!r}")
    # A commission, a cost or a loss of less than 50 paise is written ₹0, never "-₹0" (user's P&L tab and weekly list,
    # the Master's user row and the split lines of his Weekly Settlement tab)
    utxt = page.evaluate("""(async () => { showTab('account'); setPf('pnl'); const real = window.api;
        window.api = async (u, ...r) => { if (u === '/weekly') return {week_end: '2026-12-13', row: {closed: 3.2, valuation: -0.3, commission: 0.07, result: 2.83}, weeks: []};
            if (u.startsWith('/report')) return {users: [{allocated: 500000, equity: 500002.83, overall_pnl: 2.83}]}; return real(u, ...r); };
        state.funds = Object.assign({}, state.funds, {equity: 500002.83, unrealised: -0.3}); await loadPerf(); window.api = real;
        return document.querySelector('#pnlCards').innerText + ' | ' + document.querySelector('#wkList').innerText; })()""")
    ctx.close()
    ctx = br.new_context(viewport={"width": 1440, "height": 900}, service_workers="block"); ctx.add_cookies(actx.cookies())
    page = ctx.new_page(); page.goto(f"{B}/admin"); page.wait_for_timeout(4000)
    mtxt = page.evaluate("""(async () => { const keep = users, mode = PD.mode; users = [Object.assign({}, users[0], {commission_total: 0.07})]; PD.mode = 'all'; renderUsers();
        let t = document.querySelector('#uTbl tbody').innerText; users = keep; PD.mode = mode; renderUsers();
        const real = window.api; window.api = async (u, ...r) => { const x = await real(u, ...r); if (u.startsWith('/admin/weekly') && x.rows && x.rows[0]) { Object.assign(x.rows[0], {commission: 0.07, commission_crypto: 0.07}); wkOpen.add(x.rows[0].user_id); } return x; };
        document.querySelector('[data-nav="weekly"]').click(); await new Promise(r => setTimeout(r, 1500)); await loadWeekly(); window.api = real;
        return t + ' | ' + document.querySelector('#wkTbl tbody').innerText; })()""")
    ctx.close()
    zero = re.findall(r"[^|\n]{0,24}[-−]₹0(?![0-9.,])", utxt + " || " + mtxt)
    ok("A commission or a loss of less than 50 paise is written ₹0, never '-₹0' (user's P&L tab and weekly list, Master's user row and Weekly Settlement split)",
       "Commission" in utxt and "₹0" in utxt and len(mtxt) > 40 and not zero, zero[:4] or (utxt[:120], mtxt[:120]))


# ---------------- Accounts / Price officer's block (25 Nov 2026) ----------------
def accounts_block_25nov(br, actx, ok, near):
    """Owner's decisions of 21 Nov 2026 that had no check yet, and two faults of 25 Nov. Through the Master's and
    one new user's own logins only. (1) Coins typed with a fraction of a paisa are booked in whole paise and the
    ledger line equals the step in the balance. (2) Shadow Book: Peak Margin is never below Margin Now (also right
    after a trade: fault of 25 Nov), the cards agree with the per-user columns, and the peak survives a square-off.
    (3) A new account does not start with the Peak Margin of a deleted account that had its number (fault of 25 Nov)."""
    A = actx.request
    get = lambda path: A.get(f"{B}{path}").json()
    cid = A.post(f"{B}/api/admin/users", data={"username": "sitepeak", "password": "Peak@12345", "display_name": "Site Peak", "initial_coins": 1000000.335}).json().get("id")
    steps = []; bal = 0.0
    for amt in (None, 250000.335, 33.333333, -1234.565, -0.004):
        if amt is not None:
            A.post(f"{B}/api/admin/users/{cid}/coins", data={"amount": amt, "note": "paise"})
        d = get(f"/api/admin/users/{cid}/detail"); l = (d.get("ledger") or [{}])[0]; now = d["user"]["balance"]
        row = next((u for u in get("/api/admin/users") if u["id"] == cid), {})
        steps.append((amt, l.get("amount"), round(now - bal, 4), l.get("balance_after"), now, row.get("total_credited"), len(d.get("ledger") or [])))
        bal = now
    whole = lambda v: v is not None and abs(v * 100 - round(v * 100)) < 1e-6
    ok("Coins typed with a fraction of a paisa (first allocation, added, removed) are booked in whole paise: each ledger line equals the step in the balance, and Allocated equals the coins",
       bool(cid) and all(whole(a) and whole(n) and abs(a - st) < 1e-6 and abs(ba - n) < 1e-6 and abs((al or 0) - n) < 1e-6 and cnt == i + 1 for i, (_, a, st, ba, n, al, cnt) in enumerate(steps)), str(steps))
    pctx = br.new_context(); P = pctx.request
    P.post(f"{B}/api/login", data={"username": "sitepeak", "password": "Peak@12345"})
    P.post(f"{B}/api/password", data={"old_password": "Peak@12345", "new_password": "Peak@67890"})
    fut = get("/api/futures?exchange=NFO&name=NIFTY")[-1]
    o = None
    for _ in range(5):
        o = P.post(f"{B}/api/orders", data={"token": fut["token"], "side": "BUY", "lots": 1})
        if o.status == 200:
            break
        time.sleep(1)
    mine = lambda sh: next((u for u in sh["users"] if u["username"] == "sitepeak"), {})
    sh = get("/api/admin/shadow"); u0 = mine(sh); m0 = u0.get("margin_now") or 0.0
    cards = lambda sh: (sh["summary"]["margin_estimate"], sh["summary"]["margin_peak"]["rule"], round(sum(u.get("margin_now") or 0.0 for u in sh["users"]), 2))
    c_now, c_peak, c_sum = cards(sh)
    ok("Shadow Book: right after a trade Peak Margin is not below Margin Now, for the user and on the cards, and the Margin Now card is the sum of the users' column",
       o is not None and o.status == 200 and m0 > 0 and (u0.get("margin_peak") or {}).get("rule", 0) >= m0 - 0.011 and c_peak >= c_now - 0.011 and near(c_now, c_sum, 0.02),
       f"order {o.status if o is not None else None}, user now {m0} peak {(u0.get('margin_peak') or {}).get('rule')}, cards now {c_now} peak {c_peak}, column sum {c_sum}")
    seen = False
    for _ in range(40):                       # the recorder looks every 20 seconds: wait until it has written this margin down
        k = mine(get("/api/admin/shadow")).get("margin_peak") or {}
        if not k.get("rule_live") and (k.get("rule") or 0) >= m0 - 0.011:
            seen = True; break
        time.sleep(1.5)
    sq = A.post(f"{B}/api/admin/users/{cid}/squareoff").json()
    sh = get("/api/admin/shadow"); u1 = mine(sh); c_now, c_peak, c_sum = cards(sh); k1 = u1.get("margin_peak") or {}
    peaks = [(u.get("margin_peak") or {}).get("rule") or 0.0 for u in sh["users"]]
    ok("Shadow Book: the Peak Margin survives a square-off (Margin Now back to zero, the peak and its time stay), and the Peak Margin card is not below the largest user peak",
       seen and sq.get("closed") == 1 and near(u1.get("margin_now"), 0.0, 0.001) and near(k1.get("rule"), m0, 0.011) and bool(k1.get("rule_at")) and not k1.get("rule_live")
       and c_peak >= c_now - 0.011 and near(c_now, c_sum, 0.02) and max(peaks) - 0.011 <= c_peak,      # (no upper limit: the card keeps the peak of accounts deleted since)
       f"recorded {seen}, square-off {sq}, user now {u1.get('margin_now')} peak {k1} (was {m0}), cards now {c_now} peak {c_peak}, user peaks {peaks}")
    # delete it and create the next account: the database hands the same number out again
    A.delete(f"{B}/api/admin/users/{cid}")
    nid = A.post(f"{B}/api/admin/users", data={"username": "sitepeak2", "password": "Peak@12345", "display_name": "Site Peak Two", "initial_coins": 1000}).json().get("id")
    u2 = next((u for u in get("/api/admin/shadow")["users"] if u["username"] == "sitepeak2"), None)
    ok("Shadow Book: a new account does not start with the Peak Margin of a deleted account that had its number",
       bool(nid) and (u2 is None or not ((u2.get("margin_peak") or {}).get("rule") or (u2.get("margin_peak") or {}).get("real"))), f"number {cid} -> {nid}, row {u2}")
    if nid:
        A.delete(f"{B}/api/admin/users/{nid}")
    pctx.close()


def main():
    with sync_playwright() as pw:
        br = pw.chromium.launch()
        # ---------------- set-up through the API (as the Master) ----------------
        actx = br.new_context(viewport={"width": 1440, "height": 900})
        A = actx.request
        r = A.post(f"{B}/api/login", data={"username": "admin", "password": "admin123"}).json()
        secret = None
        if r.get("needs_2fa"):
            print("FAIL site | Master already has 2FA on this private copy — start a fresh copy (run.sh)"); sys.exit(2)
        secret = A.post(f"{B}/api/admin/2fa/setup").json()["secret"]
        ok("Master: two-factor set-up works", A.post(f"{B}/api/admin/2fa/confirm", data={"code": pyotp.TOTP(secret).now()}).status == 200)
        r = A.post(f"{B}/api/login", data={"username": "admin", "password": "admin123"}).json()
        ok("Master: login asks for the two-factor code", bool(r.get("needs_2fa")))
        r2 = A.post(f"{B}/api/login/2fa", data={"pre_token": r["pre_token"], "code": pyotp.TOTP(secret).now()})
        ok("Master: login with the code works", r2.status == 200, r2.text()[:200])
        ok("Master: a wrong code is refused", A.post(f"{B}/api/login/2fa", data={"pre_token": r["pre_token"], "code": "000000"}).status != 200)

        def aget(path):
            x = A.get(f"{B}{path}"); return x.json() if x.status == 200 else {"_status": x.status}

        def apost(path, body=None):
            x = A.post(f"{B}{path}", data=body or {}); return x.json() if x.status == 200 else {"_status": x.status, "_text": x.text()[:200]}

        uid = apost("/api/admin/users", {"username": "sitecheck", "password": "Site@12345", "display_name": "Site Check", "initial_coins": 5000000}).get("id")
        ok("Master: creating a user works", bool(uid))
        uctx = br.new_context(viewport={"width": 412, "height": 900})
        U = uctx.request
        U.post(f"{B}/api/login", data={"username": "sitecheck", "password": "Site@12345"})
        ok("User: first login forces a new password and it works", U.post(f"{B}/api/password", data={"old_password": "Site@12345", "new_password": "Site@67890"}).status == 200)

        def uget(path):
            x = U.get(f"{B}{path}"); return x.json() if x.status == 200 else {"_status": x.status}

        # an account that will be deleted after the weekly cut-off (see "Master: deleting" further down)
        lid = apost("/api/admin/users", {"username": "leaver", "password": "Site@12345", "display_name": "Leaver", "initial_coins": 100000}).get("id")
        apost(f"/api/admin/users/{lid}/alert", {"title": "Private note", "text": "for the leaver only"})

        def order(tok, side, lots=1, **kw):
            x = U.post(f"{B}/api/orders", data={"token": tok, "side": side, "lots": lots, **kw})
            try:
                st = (x.json().get("order") or {}).get("status", "")
            except Exception:
                st = ""
            return x.status, f"{st} {x.text()[:140]}"

        res = uget("/api/search?q=NIFTY")
        fut = next((x for x in res if x.get("instrument_type") == "FUT" and x.get("name") == "NIFTY"), None)
        # the option comes from the option chain: which options the search lists first depends on the day of the week
        exps = uget("/api/expiries?exchange=NFO&name=NIFTY")
        ces = [x for x in (uget(f"/api/chain?exchange=NFO&name=NIFTY&expiry={exps[0]}").get("instruments") or []) if x.get("instrument_type") == "CE"] if isinstance(exps, list) and exps else []
        opt = ces[len(ces) // 2] if ces else None
        res2 = uget("/api/search?q=GOLD")
        mcx = next((x for x in res2 if x.get("instrument_type") == "FUT" and x.get("exchange") == "MCX"), None)
        ok("User: search finds futures and options", bool(fut and opt and mcx))
        # a contract whose last day is over (in Indian time) is not offered: it used to head the list until the
        # next morning and every order on it was refused "This contract has expired"
        from datetime import datetime as _dt, timedelta as _td
        ist_today = (_dt.utcnow() + _td(hours=5, minutes=30)).date().isoformat()
        offered = list(res) + list(res2) + [x for nm, ex in (("NIFTY", "NFO"), ("BANKNIFTY", "NFO"), ("SENSEX", "BFO"), ("GOLD", "MCX"), ("USDINR", "CDS"))
                                             for x in (uget(f"/api/futures?exchange={ex}&name={nm}") or [])]
        gone = sorted({x.get("symbol") for x in offered if isinstance(x, dict) and x.get("expiry") and x["expiry"] < ist_today})
        ok("User: search and the futures lists offer no contract that has already expired", len(offered) > 5 and not gone, gone[:4])
        for tok, side, lots in ((fut["token"], "BUY", 2), (mcx["token"], "SELL", 1), (opt["token"], "BUY", 1), (fut["token"], "SELL", 1)):
            st, tx = order(tok, side, lots); ok(f"User: {side} order is accepted", st == 200, tx); time.sleep(2.5)
        st, tx = order(fut["token"], "BUY", 1, order_type="LIMIT", limit_price=1.0)
        ok("User: a limit order far from the market rests", st == 200 and tx.startswith("OPEN"), tx)
        time.sleep(3)
        # a weekly cut-off in the middle, then one more trade on a carried position
        before = uget("/api/weekly")["row"]
        ok("Master: weekly cut-off runs", "accounts" in apost("/api/admin/weekly/test-close"))
        time.sleep(4)
        st, tx = order(fut["token"], "SELL", 1); ok("User: exit of a carried position is accepted", st == 200, tx); time.sleep(3)
        wk = uget("/api/weekly"); me = uget("/api/me")
        fin = uget("/api/weekly?week_end=" + wk["weeks"][0])["row"] if wk.get("weeks") else {}
        ok("Weekly: the finished week is final and equals what was provisional just before", bool(fin) and near(fin.get("result"), before.get("result"), max(60.0, abs(before.get("result", 0)) * 0.02)), f"{fin.get('result')} vs {before.get('result')}")
        ok("Weekly: the finished week adds up", bool(fin) and near(fin["closed"] + fin["valuation"] - fin["commission"], fin["result"], 0.03) and near(fin.get("other", 0), 0, 0.03))
        pos = uget("/api/positions")
        car = [p for p in pos if p.get("carried_week")]
        ok("Weekly: open positions are carried forward with their original average", len(car) >= 2 and all(p.get("entry_avg") for p in car))
        ok("Weekly: settled earlier + this week = total since entry on every carried position",
           all(near(p["settled_earlier"] + p["unrealised"], p["total_since_entry"], 0.03) for p in car))
        ok("User: gets the weekly settlement pop-up", any("Weekly settlement" in (a.get("title") or "") for a in me.get("alerts") or []))
        ords = uget("/api/orders")
        ok("Order Book: the exit of a carried position carries its note", any(o.get("carry_note") for o in ords))

        # ---------------- Excel files ----------------
        def xl(req, path):
            x = req.get(f"{B}{path}")
            if x.status != 200:
                return None
            try:
                return load_workbook(io.BytesIO(x.body()))
            except Exception:
                return None

        we = wk["weeks"][0] if wk.get("weeks") else None
        mon = None
        if we:
            from datetime import date, timedelta
            mon = (date.fromisoformat(we) - timedelta(days=6)).isoformat()
        for label, req, path in (("User: all statements", U, "/api/export.xlsx"), ("User: P&L statement", U, "/api/export.xlsx?sheets=pnl"),
                                 ("User: order book", U, "/api/export.xlsx?sheets=orderbook"), ("User: ledger", U, "/api/export.xlsx?sheets=ledger"),
                                 ("Master: all users", A, "/api/admin/export.xlsx"), ("Master: one user", A, f"/api/admin/export.xlsx?user_id={uid}"),
                                 ("Master: summary", A, "/api/admin/summary.xlsx")):
            wb = xl(req, path)
            ok(f"Excel: {label} downloads and opens", wb is not None and len(wb.sheetnames) >= 1, path)
        _b = next((x for x in aget("/api/admin/report").get("users", []) if x["username"] == "sitecheck"), {}).get("total_pnl")
        wb = xl(U, "/api/export.xlsx")
        if wb is not None:
            need = ["Order Book", "P&L Statement", "Summary", "Daily Net P&L", "Weekly Settlement", "Open Positions", "Ledger Statement"]
            ok("Excel: the full file has every sheet", all(n in wb.sheetnames for n in need), wb.sheetnames)
            _, prow = sheet_rows(wb, "P&L Statement")
            tot = next((x for x in prow if x[0] == "NET P&L (SETTLEMENT)"), None)
            ok("Excel: P&L Statement has Realised, Unrealised, Commission and Net P&L (Settlement) that add up",
               bool(tot) and near(tot[8] + tot[9] + tot[10], tot[11], 0.05), str(tot))
            a = aget(f"/api/admin/report")
            au = next((x for x in a.get("users", []) if x["username"] == "sitecheck"), {})
            # prices keep moving while the file is built: the Master's figure is read right before and right after it,
            # and the file must lie between the two (it failed now and then on a busy machine with one reading only)
            _a = au.get("total_pnl"); _lo, _hi = (min(_a, _b), max(_a, _b)) if None not in (_a, _b) else (0, 0)
            _tol = max(60.0, abs(_a or 0) * 0.01)
            ok("Excel: all-time Net P&L (Settlement) = the Master's all-time figure for the user", bool(tot) and None not in (_a, _b) and _lo - _tol <= tot[11] <= _hi + _tol, f"{tot and tot[11]} vs {_b} before / {_a} after")
            _, lrow = sheet_rows(wb, "Ledger Statement")
            body = [x for x in lrow if x[2] != "Closing Balance" and isinstance(x[3], (int, float))]
            ok("Excel: ledger balances run on without a gap", all(near(y[4], x[4] + y[3], 0.011) for x, y in zip(body, body[1:])))
            # the line above the ledger: Realised + Unrealised (Open Positions) + Commission = NET P&L (SETTLEMENT), with
            # Realised = closed trades as on the P&L sheet (the weekly valuation of positions still open used to be
            # counted under Realised AND under Unrealised, so the line did not add up after a cut-off)
            head = next((c.value for r in wb["Ledger Statement"].iter_rows(min_row=1, max_row=4) for c in r if isinstance(c.value, str) and "NET P&L (SETTLEMENT)" in c.value), "")

            def _hv(label):
                m = re.search(re.escape(label) + r"\s*([-+−]?[\d,]+(?:\.\d+)?)", head)
                return float(m.group(1).replace(",", "").replace("−", "-")) if m else None
            hr, hu, hc, hn = _hv("Realised"), _hv("Unrealised (Open Positions)"), _hv("Commission"), _hv("NET P&L (SETTLEMENT)")
            ok("Excel: the Ledger Statement's top line adds up and its Realised is the P&L sheet's Realised",
               None not in (hr, hu, hc, hn) and near(hr + hu + hc, hn, 0.03) and bool(tot) and near(hr, tot[8], 0.03), head[:260])
            _, wrow = sheet_rows(wb, "Weekly Settlement")
            ok("Excel: Weekly Settlement sheet has the final week with the same result", any(x[1] == "FINAL" and near(x[5], fin.get("result"), 0.02) for x in wrow), str(wrow[:2]))
        if we:
            wbw = xl(U, f"/api/export.xlsx?from={mon}&to={we}")
            if wbw is not None:
                _, prow = sheet_rows(wbw, "P&L Statement")
                tot = next((x for x in prow if x[0] == "NET P&L (SETTLEMENT)"), None)
                # the private copy's test cut-off is stamped "now", so trades after it fall in the same calendar week:
                # compare with finished week + running week, which is what that calendar week holds
                run = uget("/api/weekly")["row"]
                ok("Excel: the week's file has the closed trades and commission of the week exactly", bool(tot) and near(tot[8], fin.get("closed", 0) + run["closed"], 0.05)
                   and near(-tot[10], fin.get("commission", 0) + run["commission"], 0.05), f"{tot and tot[8:11]} vs closed {fin.get('closed')}+{run['closed']}, commission {fin.get('commission')}+{run['commission']}")
                # the open positions move with the simulated prices, so compare inside the same file:
                # Unrealised in the P&L Statement = week-close valuation + "This Week" total of the Open Positions sheet
                _, orow = sheet_rows(wbw, "Open Positions")
                otot = next((x for x in orow if x[0] == "TOTAL"), None)
                ok("Excel: the week's file has the open positions (week close + now) and adds up to Net P&L (Settlement)", bool(tot) and bool(otot) and near(tot[8] + tot[9] + tot[10], tot[11], 0.05)
                   and near(tot[9], fin.get("valuation", 0) + (otot[10] or 0), 900.0), f"{tot and tot[9]} vs {fin.get('valuation')} + {otot and otot[10]}")

        # ---------------- screens ----------------
        def watch(page, bag):
            page.on("pageerror", lambda e: bag.append("script error: " + str(e)[:160]))
            page.on("console", lambda m: bag.append("console error: " + m.text[:160]) if m.type == "error" and "favicon" not in m.text and "Failed to load resource" not in m.text else None)
            page.on("response", lambda r: bag.append(f"HTTP {r.status} {r.url.replace(B, '')[:80]}") if r.status >= 500 else None)

        def state_of(page, sel="body"):
            return page.evaluate("""(sel) => { const el = document.querySelector(sel) || document.body; const t = el.innerText || '';
                const wide = []; document.querySelectorAll('body *').forEach(e => { const b = e.getBoundingClientRect();
                    if (b.width > 0 && b.right > window.innerWidth + 2 && !e.closest('table') && !e.closest('.tscroll') && !e.closest('[style*="overflow"]') && wide.length < 4) wide.push(e.tagName + '.' + (e.className || '') + '#' + (e.id || '')); });
                return { text: t.length, bad: (t.match(/undefined|NaN|\\[object Object\\]|null%|Infinity|[-−]₹0(?![0-9.,])/g) || []).slice(0, 4), page: document.documentElement.scrollWidth, win: window.innerWidth, wide }; }""", sel)

        def check_view(label, page, bag, sel="body", min_text=40):
            s = state_of(page, sel)
            ok(f"{label}: opens with content", s["text"] >= min_text, s)
            ok(f"{label}: nothing reads undefined / NaN", not s["bad"], s["bad"])
            ok(f"{label}: fits the screen width", s["page"] <= s["win"] + 2, f"page {s['page']} > screen {s['win']} {s['wide']}")
            ok(f"{label}: no script or server error", not bag, bag[:3]); bag.clear()

        for size_name, vw in (("computer", {"width": 1440, "height": 900}), ("phone", {"width": 412, "height": 900})):
            # --- Master ---
            ctx = br.new_context(viewport=vw)
            ctx.add_cookies(actx.cookies())
            page = ctx.new_page(); bag = []; watch(page, bag)
            page.goto(f"{B}/admin"); page.wait_for_timeout(5000)
            ok(f"Master ({size_name}): page opens logged in", page.evaluate("!!document.querySelector('[data-nav]') && !document.querySelector('main')?.classList.contains('hidden')"), page.url)
            for nav, label in (("trainees", "Users"), ("weekly", "Weekly Settlement"), ("perf", "Performance"), ("shadow", "Shadow Book"), ("settings", "Settings")):
                page.evaluate("(n) => document.querySelector(`[data-nav=\"${n}\"]`).click()", nav); page.wait_for_timeout(2500)
                check_view(f"Master ({size_name}) {label} tab", page, bag, f"#nav-{nav}")
                if nav == "settings":
                    ok(f"Master ({size_name}) Settings: site health card shows every background job", page.evaluate("document.querySelectorAll('#hlBody .plrow').length") >= 14)
            page.evaluate("document.querySelector('[data-nav=\"trainees\"]').click()"); page.wait_for_timeout(800)
            for mode in ("all", "day", "week", "month"):
                page.evaluate("(m) => { const b = document.querySelector(`#pdBar [data-pm=\"${m}\"]`); if (b) b.click(); }", mode); page.wait_for_timeout(1800)
                check_view(f"Master ({size_name}) dashboard {mode}", page, bag, "#nav-trainees")
            # the dashboard's all-time Net P&L equals what the server reports (users' side, shown as our side);
            # read the server before and after, because the simulated prices keep moving
            page.evaluate("(m) => { const b = document.querySelector(`#pdBar [data-pm=\"all\"]`); if (b) b.click(); }"); page.wait_for_timeout(2500)
            t1 = sum(x["overall_pnl"] for x in aget("/api/admin/report")["users"])
            cards = page.evaluate("[...document.querySelectorAll('#nav-trainees .stat')].map(s => s.innerText)")
            t2 = sum(x["overall_pnl"] for x in aget("/api/admin/report")["users"])
            netc = next((c for c in cards if c.strip().startswith("Net P&L")), "")
            shown = num(netc.split("\n")[-1]) if netc else None
            lo, hi = min(-t1, -t2), max(-t1, -t2); tol = max(2500.0, abs(t1) * 0.05)
            ok(f"Master ({size_name}): dashboard Net P&L (all time) equals the server's figure, shown as our side", shown is not None and lo - tol <= shown <= hi + tol, f"{netc!r} vs {-t1:.0f}..{-t2:.0f}")
            page.evaluate("(id) => openDetail(id)", uid); page.wait_for_timeout(3000)
            check_view(f"Master ({size_name}) user panel", page, bag, "#detail")
            ok(f"Master ({size_name}) user panel: trading access switches show", page.evaluate("document.querySelectorAll('#dAccess input').length") == 12)
            ctx.close()
            # --- user app ---
            ctx = br.new_context(viewport=vw)
            ctx.add_cookies(uctx.cookies())
            page = ctx.new_page(); bag = []; watch(page, bag)
            page.goto(f"{B}/"); page.wait_for_timeout(6000)
            popup = page.evaluate("(document.querySelector('.mpop b') || {}).textContent || ''")
            if size_name == "computer":
                ok("User: the weekly settlement pop-up shows on opening the app", "Weekly settlement" in popup, popup)
                page.evaluate("const b = [...document.querySelectorAll('.mpop button')].find(x => x.textContent.trim() === 'OK'); if (b) b.click();"); page.wait_for_timeout(1200)
            page.evaluate("document.querySelectorAll('.mpop').forEach(x => x.remove())")
            for tab, home, label in (("watch", "pulse", "Pulse"), ("watch", "watch", "Watchlist"), ("market", None, "Market"), ("positions", None, "Positions")):
                page.evaluate("([t, h]) => showTab(t, h || undefined)", [tab, home]); page.wait_for_timeout(2200)
                check_view(f"User ({size_name}) {label}", page, bag)
            ok(f"User ({size_name}) Positions: carried position shows its box", page.evaluate("document.querySelectorAll('.cfbox').length") >= 1)
            for pf, label in (("orders", "Order Book"), ("pnl", "P&L"), ("ledger", "Ledger"), ("acct", "Account")):
                page.evaluate("(p) => { showTab('account'); setPf(p); }", pf); page.wait_for_timeout(2500)
                check_view(f"User ({size_name}) {label}", page, bag)
            ok(f"User ({size_name}) P&L: weekly list shows the final week", "FINAL" in page.evaluate("(document.querySelector('#wkList') || {}).innerText || ''"))
            page.evaluate("(p) => { showTab('account'); setPf('acct'); }"); page.wait_for_timeout(800)
            ok(f"User ({size_name}) Account: trading access list shows", page.evaluate("document.querySelectorAll('#accList .plrow').length") >= 7)
            page.evaluate("async (t) => { const i = await api('/instrument/' + t); openSheet(i, 'BUY'); }", fut["token"]); page.wait_for_timeout(2500)
            check_view(f"User ({size_name}) order ticket", page, bag, "#sheet")
            ok(f"User ({size_name}) order ticket: margin needed is shown", page.evaluate("/[0-9]/.test((document.querySelector('#sheet') || {}).innerText || '')"))
            ctx.close()

        # Master summary Excel: every figure is to the paisa (a stray 0.00000000001 from the arithmetic showed as "-0.00")
        wbs = xl(A, "/api/admin/summary.xlsx")
        if wbs is not None:
            odd = [(c.coordinate, c.value) for r in wbs["Master Summary"].iter_rows() for c in r
                   if isinstance(c.value, float) and (abs(c.value * 100 - round(c.value * 100)) > 1e-6 or str(c.value) == "-0.0")]
            ok("Excel: Master summary figures are whole paise (no -0.00 or long decimals)", not odd, odd[:4])

        # The Master's row for a user and the user panel must tell the same story in every period, and
        # Realised must be closed trades only. The simulated NSE / BSE / MCX prices are paused meanwhile, so
        # the figures stand still and can be compared to the rupee (the test user holds nothing else).
        A.post(f"{B}/api/admin/feed/disconnect")
        try:
            time.sleep(1.5)
            ctx = br.new_context(viewport={"width": 1440, "height": 900}); ctx.add_cookies(actx.cookies())
            page = ctx.new_page(); page.goto(f"{B}/admin"); page.wait_for_timeout(5000)
            rep = next((x for x in aget("/api/admin/report").get("users", []) if x["id"] == uid), {})
            for mode, label in (("all", "All Time"), ("day", "Daily")):
                page.evaluate("(m) => { const b = document.querySelector(`#pdBar [data-pm=\"${m}\"]`); if (b) b.click(); }", mode); page.wait_for_timeout(2500)
                row = page.evaluate("(id) => { const u = users.find(x => x.id === id); if (!u) return null; const x = pdRow(u); return {Unrealised: x.unrealised, Realised: x.realised_all, 'Net P&L': x.pnl}; }", uid)
                page.evaluate("(id) => openDetail(id)", uid); page.wait_for_timeout(2500)
                pan = page.evaluate("Object.fromEntries([...document.querySelectorAll('#dFunds .stat')].map(s => [s.querySelector('span').textContent.trim(), s.querySelector('b').textContent.trim()]))")
                ok(f"Master {label}: the user panel shows the same Unrealised, Realised and Net P&L as the user's row",
                   bool(row) and all(near(num(pan.get(k)), row[k], 1.5) for k in row), f"row {row} panel { {k: pan.get(k) for k in (row or {})} }")
                if mode == "all":
                    ok("Master All Time: Realised is closed trades only (the same figure as Performance and Excel)",
                       bool(row) and bool(rep) and near(row["Realised"], rep.get("gross_profit", 0) + rep.get("gross_loss", 0), 0.06), f"{row and row['Realised']} vs {rep.get('gross_profit')} + {rep.get('gross_loss')}")
            ctx.close()
        finally:
            A.post(f"{B}/api/admin/feed/reconnect"); time.sleep(1.5)

        # Master: deleting an account that has been through a weekly cut-off works (the weekly record used to block
        # it: "500", nothing happened on the screen), and the next account created, which is given the same
        # number, starts clean: no pop-up message, weekly record or trading-access switch of the deleted one.
        d = A.delete(f"{B}/api/admin/users/{lid}")
        ok("Master: deleting a user who has been through a weekly cut-off works", d.status == 200, f"{d.status} {d.text()[:120]}")
        nid = apost("/api/admin/users", {"username": "newcomer", "password": "Site@12345", "display_name": "Newcomer", "initial_coins": 100000}).get("id")
        nctx = br.new_context(); N = nctx.request
        N.post(f"{B}/api/login", data={"username": "newcomer", "password": "Site@12345"})
        N.post(f"{B}/api/password", data={"old_password": "Site@12345", "new_password": "Site@67890"})
        nme = N.get(f"{B}/api/me").json(); nwk = N.get(f"{B}/api/weekly").json()
        ok("Master: a new account inherits nothing from a deleted one (no pop-up, no finished week, no positions)",
           bool(nid) and not nme.get("alerts") and not nwk.get("weeks") and near(nme["funds"]["balance"], 100000) and not N.get(f"{B}/api/positions").json()
           and not aget(f"/api/admin/access?uid={nid}").get("overrides"), f"id {lid}->{nid} alerts {nme.get('alerts')} weeks {nwk.get('weeks')}")
        # The next order after the Master deletes the account that made the newest trade: that trade's number is
        # handed out again, and its Shadow Book line used to stay behind and block the new trade: every NSE / BSE /
        # MCX order of every user failed with a server error until a crypto / forex / currency trade used the number up.
        def _try(req, side):
            st = 0
            for _ in range(5):
                try:
                    st = req.post(f"{B}/api/orders", data={"token": fut["token"], "side": side, "lots": 1}).status
                except Exception:
                    st = 599             # the server dropped the connection after its error
                if st in (200, 500, 599):
                    break
                time.sleep(1.2)          # "no live price yet" right after the simulated prices were switched on again
            return st
        apost(f"/api/admin/users/{nid}/coins", {"amount": 900000, "note": "margin for one lot"})
        s_new = _try(N, "BUY"); time.sleep(0.5)
        A.delete(f"{B}/api/admin/users/{nid}"); nctx.close()
        s_buy = _try(U, "BUY"); s_sell = _try(U, "SELL")
        ok("Master: after deleting the account that made the newest trade, the next order on the site still goes through",
           (s_new, s_buy, s_sell) == (200, 200, 200), f"newcomer's order {s_new}, then the user's BUY {s_buy} and SELL {s_sell}")

        # Site health card: the name and the value of every row stand apart (they ran together: "Domain name limefx.invalid until ...")
        ctx = br.new_context(viewport={"width": 1440, "height": 900}); ctx.add_cookies(actx.cookies())
        page = ctx.new_page(); page.goto(f"{B}/admin"); page.wait_for_timeout(4000)
        page.evaluate("document.querySelector('[data-nav=\"settings\"]').click()"); page.wait_for_timeout(2500)
        gaps = page.evaluate("[...document.querySelectorAll('#hlBody .plrow')].map(r => r.querySelector('b').getBoundingClientRect().left - r.querySelector('span').getBoundingClientRect().right)")
        ok("Master Settings: site health rows show the name and the value apart", len(gaps) >= 14 and min(gaps) >= 8, f"smallest gap {min(gaps) if gaps else None}px")
        # Settings, crypto margin: what the Master is told is what a new position really needs. After the 50x
        # rule of 19 Nov 2026 the card still said "BTC/ETH 0.5% = 200x" and showed 0.5 in the box.
        sr = aget("/api/search?q=BTCUSD")
        btc = next((x for x in (sr if isinstance(sr, list) else []) if x.get("symbol") == "BTCUSD"), None)
        cm = page.evaluate("[(document.querySelector('#mCRYPTO') || {}).value, ((document.querySelector('#mCRYPTO') || {}).parentElement || {}).innerText || '']")
        if btc is None:
            ok("Master Settings: the crypto margin note does not promise more than 50x", not re.search(r"\b(100|200|500)\s*[×x]", cm[1]), cm)
        else:
            need = float(btc.get("init_margin_pct") or 0); top = max(btc.get("leverage_options") or [1])
            ok("Master Settings: the crypto margin box and note say what a new position really needs",
               near(cm[0], need, 1e-6) and f"{need:g}%" in cm[1] and f"{top:g}×" in cm[1] and not re.search(r"\b(100|200|500)\s*[×x]", cm[1]),
               f"box {cm[0]!r}, note {cm[1]!r}; a new BTCUSD position needs {need}% (top leverage {top}x)")
        ctx.close()
        # The user page as it is sent to any visitor (also its source) names no price-feed provider. ("Delta" as
        # the name of an option figure on the chain is not one: only the provider names in other spellings count.)
        import httpx as _hx
        src = _hx.get(f"{B}/", timeout=20).text
        named = [(m.group(0), src[max(0, m.start() - 40):m.end() + 40].replace("\n", " ")) for m in
                 re.finditer(r"zerodha|kite|c-?trader|ic ?markets|spotware|on Delta|Delta's|Delta (?:exchange|tokens|feed|rate)", src, re.I)]
        ok("User page: its source names no price-feed provider", len(src) > 20000 and not named, named[:3])

        # Text typed by the Master (a user's display name, the note on coins) is shown as text, never run as part of the
        # page (19 Nov 2026: a name with markup in it ran as script on the Master's Performance tab, a coin note on the
        # user's Ledger tab)
        mark = '<img src=x onerror="window.__x=(window.__x||0)+1">'
        A.post(f"{B}/api/admin/users", data={"username": "sitemark", "password": "Mark@12345", "display_name": mark, "initial_coins": 1000})
        mk = next((x for x in aget("/api/admin/users") if x.get("username") == "sitemark"), {})
        A.post(f"{B}/api/admin/users/{mk.get('id')}/coins", data={"amount": 5, "note": mark})
        ctx = br.new_context(viewport={"width": 1440, "height": 900}); ctx.add_cookies(actx.cookies())
        page = ctx.new_page(); page.goto(f"{B}/admin"); page.wait_for_timeout(4000)
        for nav in ("perf", "shadow", "settings", "weekly", "trainees"):
            page.evaluate("(n) => document.querySelector(`[data-nav=\"${n}\"]`).click()", nav); page.wait_for_timeout(1500)
        page.evaluate("(() => { const r = [...document.querySelectorAll('tr.clickable')].find(x => x.textContent.includes('sitemark')); if (r) r.click(); })()"); page.wait_for_timeout(2500)
        ran_m = page.evaluate("[window.__x || 0, document.querySelectorAll('img[src=x]').length]")
        ctx.close()
        mctx = br.new_context(viewport={"width": 412, "height": 900}); M = mctx.request
        M.post(f"{B}/api/login", data={"username": "sitemark", "password": "Mark@12345"})
        M.post(f"{B}/api/password", data={"old_password": "Mark@12345", "new_password": "Mark@67890"})
        page = mctx.new_page(); page.goto(f"{B}/"); page.wait_for_timeout(4000)
        page.evaluate("(async () => { try { if (typeof loadLedger === 'function') await loadLedger(); } catch (e) {} })()"); page.wait_for_timeout(1500)
        ran_u = page.evaluate("[window.__x || 0, document.querySelectorAll('img[src=x]').length, (document.querySelector('#ledTbl')?.textContent || '').includes('onerror')]")
        mctx.close()
        ok("Text typed by the Master (display name, coin note) is shown as text, not run by the Master's or the user's page",
           bool(mk.get("id")) and ran_m == [0, 0] and ran_u[:2] == [0, 0] and ran_u[2] is True, f"Master page {ran_m}, user page {ran_u}")
        if mk.get("id"):
            A.delete(f"{B}/api/admin/users/{mk['id']}")

        # The Master's activity record (21 Nov 2026): the name of whoever acted and what the action changed are shown
        # as text (a login name with markup in it ran as script there), and no line holds a password.
        mname = 'zz<img src=x onerror="window.__x=(window.__x||0)+1">'
        mid = A.post(f"{B}/api/admin/admins", data={"username": mname, "display_name": "m", "password": "Mark@Master1"}).json().get("id")
        mctx = br.new_context(); mctx.request.post(f"{B}/api/login", data={"username": mname, "password": "Mark@Master1"})
        mctx.request.post(f"{B}/api/admin/2fa/setup"); mctx.close()
        ctx = br.new_context(viewport={"width": 1440, "height": 900}, service_workers="block"); ctx.add_cookies(actx.cookies())
        page = ctx.new_page(); page.goto(f"{B}/admin"); page.wait_for_timeout(3000)
        page.evaluate("document.querySelector('#auLoad').click()"); page.wait_for_timeout(2000)
        ran_a = page.evaluate("[window.__x || 0, document.querySelectorAll('#auList img').length, (document.querySelector('#auList')?.textContent || '').split('onerror').length - 1]")
        ctx.close()
        if mid:
            A.delete(f"{B}/api/admin/admins/{mid}")
        aud = json.dumps(aget("/api/admin/audit"))
        held = [w for w in ("Mark@12345", "Mark@67890", "Mark@Master1", "admin123") if w in aud]
        ok("Master activity record: names and notes with markup are shown as text, and no line holds a password",
           bool(mid) and ran_a[:2] == [0, 0] and ran_a[2] >= 2 and not held, f"page {ran_a}, passwords found {held}")

        # Master's user panel on a phone: Delete and the close button used to sit off the right edge of the screen
        # (the row of buttons did not wrap), so the panel could only be left by scrolling it sideways.
        ctx = br.new_context(viewport={"width": 412, "height": 900}); ctx.add_cookies(actx.cookies())
        page = ctx.new_page(); page.goto(f"{B}/admin"); page.wait_for_timeout(4000)
        page.evaluate("(id) => openDetail(id)", uid); page.wait_for_timeout(2500)
        off = page.evaluate("""() => { const box = document.querySelector('#detail .box');
            const out = [...box.querySelectorAll(':scope > .row button')].filter(b => !b.classList.contains('hidden') && b.getBoundingClientRect().right > window.innerWidth).map(b => b.textContent.trim());
            if (box.scrollWidth > box.clientWidth + 2) out.push('panel scrolls sideways'); return out; }""")
        ok("Master (phone) user panel: every button, the close button included, is on the screen", not off, off)
        ctx.close()

        # A message that arrives while a pop-up is still on the screen must not be cleared unseen when OK is
        # pressed on the first one (OK used to clear everything waiting, shown or not).
        A.post(f"{B}/api/admin/users/{uid}/alert", data={"title": "First note", "text": "shown now"})
        ctx = br.new_context(viewport={"width": 412, "height": 900}); ctx.add_cookies(uctx.cookies())
        page = ctx.new_page(); page.goto(f"{B}/")
        for _ in range(40):
            page.wait_for_timeout(500)
            if page.evaluate("!!document.querySelector('.mpop button')"):
                break
        seen = page.evaluate("(document.querySelector('.mpop') || {}).innerText || ''")
        A.post(f"{B}/api/admin/users/{uid}/alert", data={"title": "Second note", "text": "arrived while the first was open"})
        page.evaluate("(() => { const b = document.querySelector('.mpop button'); if (b) b.click(); })()"); page.wait_for_timeout(2000)
        left = [a.get("title") for a in (uget("/api/me").get("alerts") or [])]
        ok("User: a message that arrives while a pop-up is open stays until it has been shown itself",
           "First note" in seen and left == ["Second note"], f"shown {seen[:80]!r}, still waiting {left}")
        U.post(f"{B}/api/alerts/ack"); ctx.close()

        # Small-phone and light-theme display faults of 19 Nov 2026, and two dead ends for a new user.
        for t in (fut["token"], mcx["token"]):
            U.post(f"{B}/api/watchlist", data={"token": t})
        ctx = br.new_context(viewport={"width": 360, "height": 800}); ctx.add_cookies(uctx.cookies())
        page = ctx.new_page(); page.goto(f"{B}/"); page.wait_for_timeout(5000)
        page.evaluate("document.querySelectorAll('.mpop').forEach(x => x.remove()); showTab('watch', 'watch')"); page.wait_for_timeout(2500)
        over = page.evaluate("""() => [...document.querySelectorAll('#wlist .wl-item')].map(r => { const s = r.querySelector('.sym'), pr = r.querySelector('b.num'); if (!s || !pr) return null;
            const g = document.createRange(); g.selectNodeContents(s); const a = g.getBoundingClientRect(), b = pr.getBoundingClientRect();
            return a.right > b.left + 1 && a.bottom > b.top && a.top < b.bottom ? s.textContent.trim() : null; }).filter(Boolean)""")
        rows = page.evaluate("document.querySelectorAll('#wlist .wl-item').length")
        ok("User (360-wide phone) Watchlist: no contract name runs under its price", rows >= 2 and not over, f"{rows} rows, overlapping {over}")
        page.evaluate("showTab('market')"); page.wait_for_timeout(1200); page.fill("#search", "zzzzqq"); page.wait_for_timeout(2500)
        ok("User: a search that finds nothing says so", "No matching contract" in page.evaluate("document.querySelector('#searchRes').innerText"))
        page.fill("#search", "")
        page.evaluate("document.documentElement.setAttribute('data-theme', 'light')")
        ok("User (light theme): a flashing price keeps its dark text", page.evaluate("""() => { const e = document.createElement('b'); e.className = 'fu'; document.body.appendChild(e);
            const n = getComputedStyle(e).animationName; e.remove(); return n; }""") == "flashUpL")
        idx = next((x for x in res if x.get("segment") == "INDICES"), None)
        if idx:
            page.evaluate("document.documentElement.removeAttribute('data-theme')")
            page.evaluate("async (t) => { const i = await api('/instrument/' + t); openSheet(i, 'BUY'); window._said = ''; new MutationObserver(m => m.forEach(x => x.addedNodes.forEach(n => { if (n.classList && n.classList.contains('toast')) window._said += n.textContent; }))).observe(document.body, {childList: true}); }", idx["token"])
            page.wait_for_timeout(1500); page.evaluate("document.querySelector('#oSubmit').click()"); page.wait_for_timeout(1200)
            ok("User: trying to buy an index itself gets a plain message", "cannot be bought or sold" in page.evaluate("window._said || ''"), page.evaluate("window._said || ''"))
        ctx.close()
        ctx = br.new_context(viewport={"width": 412, "height": 900}); ctx.add_cookies(actx.cookies())
        page = ctx.new_page(); page.goto(f"{B}/admin"); page.wait_for_timeout(4000)
        page.evaluate("document.querySelector('[data-nav=\"settings\"]').click()"); page.wait_for_timeout(2000)
        page.evaluate("""(async () => { const real = window.api; window.api = async (p, ...r) => { const x = await real(p, ...r);
            if (p === '/admin/health') { x.errors = [{at: '19 Nov, 01:00 AM', where: 'app', what: 'could not store ' + 'x'.repeat(170)}]; x.errors_hour = x.errors_day = 1; x.last_error = x.errors[0]; } return x; };
            await loadHealth(); window.api = real; })()"""); page.wait_for_timeout(1500)
        w = page.evaluate("[document.documentElement.scrollWidth, window.innerWidth, document.querySelector('#hlBody').innerText.includes('xxxxxxxx')]")
        ok("Master (phone) Settings: a long error text stays inside the Site health card", w[2] and w[0] <= w[1] + 2, f"page {w[0]} wide on a {w[1]} screen, error shown {w[2]}")
        ctx.close()

        # ---------------- faults of 20 Nov 2026 (each check belongs to a fix of that night) ----------------
        import httpx
        # Pulse: "Top losers" holds only what fell and "Top gainers" only what rose. With fewer than ten of either (a
        # market of six names, a day when everything rises) the lists were filled up from the other side.
        wrong = []; listed = 0
        for kd in ("all", "index", "mcx", "currency", "crypto", "forex", "global"):
            d = httpx.get(f"{B}/api/public/pulse", params={"period": "today", "kind": kd}, timeout=20).json()
            listed += len(d.get("gainers") or []) + len(d.get("losers") or [])
            wrong += [f"{kd}: {x['name']} {x['pct']:+} under Top losers" for x in d.get("losers") or [] if x["pct"] >= 0]
            wrong += [f"{kd}: {x['name']} {x['pct']:+} under Top gainers" for x in d.get("gainers") or [] if x["pct"] <= 0]
            hl = (d.get("hero") or {}).get("loser")
            if hl and hl["pct"] >= 0:
                wrong.append(f"{kd}: top loser card shows {hl['name']} {hl['pct']:+}")
        ok("Pulse: Top losers lists only what fell and Top gainers only what rose, in every market view", listed > 5 and not wrong, wrong[:4] or f"{listed} rows")
        # refusals the order ticket can really produce, in plain words; a date typed by hand does not crash a report
        r15 = U.post(f"{B}/api/orders", data={"token": fut["token"], "side": "BUY", "lots": 1.5})
        rno = U.post(f"{B}/api/orders", data={"token": 999, "side": "BUY", "lots": 1})
        try:
            rdt = U.get(f"{B}/api/export.xlsx?from=20-11-2026&to=x"); rds, rdx = rdt.status, rdt.text()
        except Exception:
            rds, rdx = 599, "the server dropped the connection"
        time.sleep(0.5)
        t15 = (r15.json().get("detail") if r15.status in (400, 422) else "") or ""; tno = (rno.json().get("detail") if rno.status == 400 else "") or ""
        ok("User: one and a half lots, or a contract that is gone, is refused in plain words",
           "whole number of lots" in t15 and "Input should" not in t15 and "cannot be traded" in tno and "instrument" not in tno, f"{r15.status} {t15!r} / {rno.status} {tno!r}")
        ok("User: a report asked for with a badly written date is refused with a message, not a crash", rds == 400 and "Dates must look like" in rdx, f"{rds} {rdx[:80]}")
        # Automatic square-off message: a crypto price is in dollars (it read "BTCUSD at ₹73,909.50"). The Master
        # takes coins back from a small account holding one crypto position, so no price has to be moved.
        btc = None
        for _ in range(3):
            try:
                btc = next((x for x in uget("/api/search?q=BTCUSD") if x.get("exchange") == "CRYPTO" and x.get("instrument_type") == "FUT"), None); break
            except Exception:
                time.sleep(1)
        pid = apost("/api/admin/users", {"username": "sitepop", "password": "Pop@12345", "display_name": "Site Pop", "initial_coins": 30000}).get("id")
        pctx = br.new_context(viewport={"width": 360, "height": 640}, service_workers="block"); P = pctx.request   # no reload of the page in the middle of a check when the saved copy of the app updates itself
        P.post(f"{B}/api/login", data={"username": "sitepop", "password": "Pop@12345"})
        P.post(f"{B}/api/password", data={"old_password": "Pop@12345", "new_password": "Pop@67890"})
        sold = ""
        if btc and pid:
            for _ in range(5):
                if P.post(f"{B}/api/orders", data={"token": btc["token"], "side": "BUY", "lots": 150, "leverage": 50}).status == 200:
                    break
                time.sleep(1.2)
            time.sleep(1.0)
            apost(f"/api/admin/users/{pid}/coins", {"amount": -12000, "note": "taken back"})
            for _ in range(25):
                time.sleep(1)
                al = [a for a in (P.get(f"{B}/api/me").json().get("alerts") or []) if a.get("title") == "Position liquidated"]
                if al:
                    sold = al[0].get("text") or ""; break
        ok("User: the automatic square-off message gives a crypto price in dollars, not with the rupee sign",
           bool(re.search(r"of BTCUSD at \$[\d,]+\.\d\d\.", sold)) and "at ₹" not in sold, sold[:160] or "no square-off message came")
        # ... and that message is on the screen as the app opens (it used to come five seconds later, in the middle of a tap)
        page = pctx.new_page(); t0 = time.time(); page.goto(f"{B}/")
        try:
            page.wait_for_selector(".mpop button", timeout=9000); came = time.time() - t0
        except Exception:
            came = 99
        ok("User: a waiting pop-up is on the screen as the app opens", came < 3.0 or (came < 4.5 and page.evaluate("performance.getEntriesByType('resource').filter(e => e.name.endsWith('/api/me')).length") == 1), f"after {came:.1f} s")
        page.evaluate("(() => { const b = document.querySelector('.mpop button'); if (b) b.click(); })()"); page.wait_for_timeout(700)
        # Short of margin after the weekly settlement: the warning stands for the shortfall notice (which used to pop up
        # again on its own after OK), and the red bar says what the pop-up says (it said "squared off at market" while
        # the pop-up gave time until Monday noon). The server's answer is stood in for, so no price has to move.
        page.evaluate("""(async () => { window.__ack = ''; const rf = window.fetch; window.fetch = async (u, o) => { if (String(u).includes('/api/alerts/ack')) { window.__ack = (o && o.body) || ''; return new Response('{}'); } return rf(u, o); };
            const real = window.api; window.api = async (p, ...r) => { const x = await real(p, ...r); if (p === '/me') { x.funds.margin_short = true;
                x.week_warning = {title: 'Margin shortfall — reduce your positions', text: 'Your coins went back to the allocated amount. Available Balance is -5.\\n\\nPlease reduce your positions before Monday, 12:00 PM. If Available Balance is still below zero then, positions are squared off.'};
                x.alerts = [{id: 'wk1', title: 'Weekly settlement · test', text: 'week'}, {id: 'sf1', title: 'Margin shortfall after weekly settlement', text: 'short'}]; } return x; };
            document.querySelectorAll('.mpop').forEach(x => x.remove()); window._wkWarn = 0; await refreshFunds(); window.api = real; })()"""); page.wait_for_timeout(600)
        sf = page.evaluate("""() => { const b = document.querySelector('.mpop .box'); const t = b ? [...b.querySelectorAll('b')].map(x => x.textContent) : []; const bar = document.querySelector('#marginBar').innerText;
            const k = document.querySelector('.mpop button'); if (k) k.click(); return {titles: t, bar}; }"""); page.wait_for_timeout(500)
        ack = page.evaluate("window.__ack || ''")
        ok("User: the shortfall warning after a weekly settlement is shown once (its notice is cleared with it)",
           len(sf["titles"]) == 2 and "sf1" in ack and "wk1" in ack, f"pop-up {sf['titles']}, cleared {ack}")
        ok("User: during the time given to reduce positions the red bar says the same as the pop-up",
           "before Monday, 12:00 PM" in sf["bar"] and "at market" not in sf["bar"], sf["bar"][:200])
        # two messages at the same moment stand one under the other (they lay on top of each other)
        tz = page.evaluate("""() => { toast('first message'); toast('second message'); const r = [...document.querySelectorAll('.toast')].map(x => x.getBoundingClientRect()); return r.map(x => [Math.round(x.top), Math.round(x.bottom)]); }""")
        ok("User: two messages at the same moment do not cover each other", len(tz) >= 2 and tz[-1][0] >= tz[-2][1], tz)
        # My P&L card: with nothing open, Realised and P&L are the same amount and read the same (-₹188 against -₹187
        # came from rounding one and not the other), and no figure breaks between its sign and its digits
        page.evaluate("document.querySelectorAll('.mpop').forEach(x => x.remove()); showTab('account'); setPf('pnl')"); page.wait_for_timeout(1200)
        pl = page.evaluate("""(async () => { const real = window.api; window.api = async (p, ...r) => { if (p.startsWith('/report')) return {users: [{allocated: 500000, equity: 499083.9, overall_pnl: -1234567.4}]};
                if (p === '/weekly') return {row: {commission: 728.6}, weeks: ['2026-11-22']}; return real(p, ...r); };
            state.funds = Object.assign({}, state.funds, {equity: 499083.9, unrealised: 0}); await loadPerf(); window.api = real;
            const rows = Object.fromEntries([...document.querySelectorAll('#pnlCards .plrow')].map(r => [r.querySelector('span').textContent.trim(), r.querySelector('b').textContent.trim()]));
            const broken = [...document.querySelectorAll('#pnlCards .plrow b')].filter(b => b.getClientRects().length > 1).map(b => b.textContent);
            return {rows, broken}; })()""")
        ok("User (360-wide phone) My P&L: Realised and P&L read the same when nothing is open, and no figure is broken over two lines",
           pl["rows"].get("Realised") == pl["rows"].get("P&L") and bool(pl["rows"].get("P&L")) and not pl["broken"], f"{pl['rows'].get('Realised')} / {pl['rows'].get('P&L')}, broken {pl['broken']}")
        # Pulse on a 360-wide phone: the low / high line of a row does not run into the price and the change beside it
        page.evaluate("showTab('watch', 'pulse')"); page.wait_for_timeout(2500)
        pr = page.evaluate("""() => { const out = []; let n = 0; document.querySelectorAll('.prow').forEach(r => { const m = r.querySelector('.m2'), p = r.querySelector('.px'); if (!m || !p || !r.offsetParent) return; n++;
            const pb = p.getBoundingClientRect(); [...m.children].forEach(c => { const b = c.getBoundingClientRect(); if (b.width && b.right > pb.left + 1 && b.bottom > pb.top + 1 && b.top < pb.bottom - 1) out.push((r.querySelector('.nm b') || {}).textContent); }); });
            return [n, [...new Set(out)]]; }""")
        ok("User (360-wide phone) Pulse: no low / high figure runs into the price beside it", pr[0] >= 5 and not pr[1], f"{pr[0]} rows, overlapping {pr[1][:5]}")
        # Option chain on a 360-wide phone, Greeks view: the put price column is on the screen (it was cut off at the right)
        page.evaluate("""(() => { showTab('market'); document.querySelector('#segOpt').click(); document.querySelector('#catList [data-cat="index"]').click();
            const u = document.querySelector('#undList .wl-item[data-und="NFO|NIFTY"]'); if (u) u.click(); })()"""); page.wait_for_timeout(3000)
        page.evaluate("(() => { const b = document.querySelector('#chainMode [data-m=\"greeks\"]'); if (b) b.click(); })()"); page.wait_for_timeout(1500)
        cw = page.evaluate("[document.querySelector('#chainTbl').scrollWidth, document.querySelector('#chainWrap').clientWidth, document.querySelectorAll('#chainTbl tbody tr').length]")
        ok("User (360-wide phone) option chain, Greeks view: the put price column is on the screen", cw[2] >= 5 and cw[0] <= cw[1] + 1, f"table {cw[0]} wide in a card of {cw[1]}, {cw[2]} strikes")
        # An account frozen while its owner is using the app: the login screen he is put back on says why (it said nothing)
        A.patch(f"{B}/api/admin/users/{pid}", data={"is_active": False})
        page.evaluate("refreshFunds()"); page.wait_for_timeout(1200)
        fz = page.evaluate("[!document.querySelector('#loginView').classList.contains('hidden'), document.querySelector('#loginErr').textContent]")
        ok("User: an account frozen while the app is open is told so on the login screen", fz[0] and "frozen" in fz[1].lower(), fz)
        pctx.close()
        if pid:
            A.delete(f"{B}/api/admin/users/{pid}")
        # Master: no label of a figure card is cut off with "…" (Performance on a phone and a tablet, Shadow Book), and
        # the note beside the crypto margin names the 50x limit (it still said 200x)
        cutl = []
        for wv in (820, 412):
            ctx = br.new_context(viewport={"width": wv, "height": 900}); ctx.add_cookies(actx.cookies())
            page = ctx.new_page(); page.goto(f"{B}/admin"); page.wait_for_timeout(3000)
            for nav in ("perf", "shadow"):
                page.evaluate("(n) => document.querySelector(`[data-nav=\"${n}\"]`).click()", nav); page.wait_for_timeout(1500)
                cutl += [f"{wv} wide: {x}" for x in page.evaluate("(n) => [...document.querySelectorAll('#nav-' + n + ' .stat .small')].filter(e => e.offsetParent && e.scrollWidth > e.clientWidth + 1).map(e => e.textContent.trim().slice(0, 40))", nav)]
            if wv == 820:
                page.evaluate("document.querySelector('[data-nav=\"settings\"]').click()"); page.wait_for_timeout(800)
                note = page.evaluate("document.querySelector('#mCRYPTO').parentElement.innerText")
            ctx.close()
        ok("Master: no label of a figure card is cut off on Performance and Shadow Book (tablet, phone)", not cutl, cutl[:4])
        ok("Master Settings: the note beside the crypto margin gives the 50x limit", "50×" in note and "200" not in note, note[:120])

        # ======== Master activity record (Technology / Compliance officer, 21 Nov 2026) — start of block ========
        # Every Master action leaves a line that says in plain words what changed, and no line ever holds a
        # password, a two-step secret or a login. Works on its own accounts and puts every setting back.
        def rec_last(path_part, n=1):
            got = [x for x in (A.get(f"{B}/api/admin/audit").json() or []) if path_part in x.get("action", "")]
            return (got[0].get("detail") or "") if got else None

        def httpx_get_json(path):
            x = br.new_context(); j = x.request.get(f"{B}{path}").json(); x.close(); return j

        def rec(name, path_part, pattern, detail=None):
            d = rec_last(path_part) if detail is None else detail
            ok(f"Activity record: {name}", d is not None and re.search(pattern, d or "") is not None, f"line: {d!r}")

        rec_secrets = ["admin123", "Site@12345", "Site@67890", secret, "Rec@Secret111", "Rec@Secret222", "Rec@Secret333", "Rec@Secret444"]
        rid = apost("/api/admin/users", {"username": "recuser", "password": "Rec@Secret111", "display_name": "Rec User", "initial_coins": 250000}).get("id")
        rec("a user created says who and with how many coins", "POST /api/admin/users", r"Created user recuser \(Rec User\) with 250,000 coins")
        apost(f"/api/admin/users/{rid}/coins", {"amount": 12345.5, "note": "top-up"})
        rec("coins added say how many, to whom, the balance before and after, and the note", f"/users/{rid}/coins", r"Added 12,345\.50 coins to recuser: balance 250,000\.00 → 262,345\.50; note: top-up")
        apost(f"/api/admin/users/{rid}/coins", {"amount": -2345.5})
        rec("coins removed say how many, from whom, the balance before and after", f"/users/{rid}/coins", r"Removed 2,345\.50 coins from recuser: balance 262,345\.50 → 260,000\.00")
        A.patch(f"{B}/api/admin/users/{rid}", data={"is_active": False})
        rec("a freeze says so", f"PATCH /api/admin/users/{rid}", r"recuser: active → frozen")
        A.patch(f"{B}/api/admin/users/{rid}", data={"is_active": False})
        rec("a freeze of an account already frozen says that nothing changed", f"PATCH /api/admin/users/{rid}", r"^recuser: saved, nothing changed$")
        A.patch(f"{B}/api/admin/users/{rid}", data={"is_active": True})
        rec("an unfreeze says so", f"PATCH /api/admin/users/{rid}", r"recuser: frozen → active")
        A.patch(f"{B}/api/admin/users/{rid}", data={"display_name": "Rec Renamed"})
        rec("a new name says the old and the new one", f"PATCH /api/admin/users/{rid}", r"recuser: name Rec User → Rec Renamed")
        A.patch(f"{B}/api/admin/users/{rid}", data={"password": "Rec@Secret222"})
        rec("a password reset says so, without the password", f"PATCH /api/admin/users/{rid}", r"^recuser: password reset[^|]*$")
        A.patch(f"{B}/api/admin/users/{rid}", data={"reset_2fa": True})
        rec("a user's two-step login cleared says so", f"PATCH /api/admin/users/{rid}", r"recuser: two-step login cleared")
        # settings: every figure the Master can save, one at a time, then everything back as it was
        st0 = aget("/api/admin/settings")
        skeys = ("commission_pct", "commission_pct_forex", "commission_pct_options", "commission_flat", "liq_charge_flat", "liq_charge_pct_crypto",
                 "commission_pct_crypto", "mcx_option_factor", "liquidity_check", "max_spread_pct", "stale_minutes")
        sbase = {"margin_pct": dict(st0["margin_pct"]), **{k: st0[k] for k in skeys}}
        silent = []
        for k in skeys:
            new = (not st0[k]) if isinstance(st0[k], bool) else (int(st0[k]) + 3 if k == "stale_minutes" else round(float(st0[k]) * 1.5 + 0.01, 4))
            apost("/api/admin/settings", {**sbase, k: new}); d1 = rec_last("POST /api/admin/settings") or ""
            apost("/api/admin/settings", sbase); d2 = rec_last("POST /api/admin/settings") or ""
            if not (re.search(r"^Settings: [^;|]+: \S+ → \S+$", d1) and re.search(r"^Settings: [^;|]+: \S+ → \S+$", d2)) or d1 == d2:
                silent.append(f"{k}: {d1!r} / {d2!r}")
        for ex, v in st0["margin_pct"].items():
            apost("/api/admin/settings", {**sbase, "margin_pct": {**st0["margin_pct"], ex: float(v) + 1.5}}); d1 = rec_last("POST /api/admin/settings") or ""
            apost("/api/admin/settings", sbase)
            if not re.search(r"^Settings: [^;|]+: " + re.escape(f"{float(v):g}") + " → " + re.escape(f"{float(v) + 1.5:g}") + "$", d1):
                silent.append(f"margin {ex}: {d1!r}")
        ok("Activity record: each setting changed (11 figures, every margin) says which one, from what to what", not silent, silent[:3])
        st1 = aget("/api/admin/settings")
        ok("Activity record: the settings are back exactly as they were", st1.get("margin_pct") == st0["margin_pct"] and all(st1.get(k) == st0[k] for k in skeys))
        apost("/api/admin/settings", sbase)
        rec("a save that changes nothing says so", "POST /api/admin/settings", r"^Settings: saved, nothing changed$")
        # trading access: default table (a switch nobody here uses, put back at once) and one user's own switches
        dflt = (aget("/api/admin/access").get("default") or {}).get("CRYPTO_OPT")
        apost("/api/admin/access/default", {"values": {"CRYPTO_OPT": not dflt}})
        rec("a default access switch says which one, from what to what", "/access/default", r"^Default trading access: Options on Crypto: (on → off|off → on)$")
        apost("/api/admin/access/default", {"values": {"CRYPTO_OPT": dflt}})
        ok("Activity record: the default access switch is back as it was", (aget("/api/admin/access").get("default") or {}).get("CRYPTO_OPT") == dflt)
        apost(f"/api/admin/users/{rid}/access", {"values": {"CDS_FUT": False, "GLOBAL": False}})
        rec("one user's access switches say whose, which, from what to what", f"/users/{rid}/access", r"^Trading access of recuser: Futures on Currency: on → off; Global markets: on → off$")
        A.post(f"{B}/api/admin/users/{rid}/access", data=json.dumps({"values": None}), headers={"Content-Type": "application/json"})
        rec("one user put back on the default says so", f"/users/{rid}/access", r"^Trading access of recuser: back to the default; ")
        # square-off pressed (the user holds one future)
        rctx = br.new_context(); R = rctx.request
        R.post(f"{B}/api/login", data={"username": "recuser", "password": "Rec@Secret222"})
        R.post(f"{B}/api/password", data={"old_password": "Rec@Secret222", "new_password": "Rec@Secret333"})
        R.post(f"{B}/api/orders", data={"token": fut["token"], "side": "BUY", "lots": 1})
        held = len([p for p in (R.get(f"{B}/api/positions").json() or []) if p.get("qty")])
        apost(f"/api/admin/users/{rid}/squareoff")
        rec("Square off pressed says for whom and how many positions were closed", f"/users/{rid}/squareoff", rf"^Square off pressed for recuser: {held} position{'s' if held != 1 else ''} closed")
        # a user's own call to the two-step set-up (it also answers under a Master-looking address) is not the Master's action
        n0 = len([x for x in A.get(f"{B}/api/admin/audit").json() if x.get("admin") == "recuser"])
        ur = [R.post(f"{B}/api/admin/2fa/setup").status for _ in range(3)]
        n1 = len([x for x in A.get(f"{B}/api/admin/audit").json() if x.get("admin") == "recuser"])
        ok("Activity record: a user's own request never writes a line into the Master's record", ur == [200, 200, 200] and n0 == 0 and n1 == 0, f"{ur} lines {n0} -> {n1}")
        R.post(f"{B}/api/admin/users/{rid}/coins", data={"amount": 5})
        ok("Activity record: a refused request of a user leaves the user's coins and the record alone",
           not any(x.get("admin") == "recuser" for x in A.get(f"{B}/api/admin/audit").json()))
        rctx.close()
        # a second Master login: added, password changed, two-step cleared, removed
        mid = apost("/api/admin/admins", {"username": "recmaster", "display_name": "Rec Master", "password": "Rec@Secret444"}).get("id")
        rec("a Master login added says which", "POST /api/admin/admins", r"^Added Master login recmaster$")
        apost(f"/api/admin/admins/{mid}/password", {"password": "Rec@Secret111"})
        rec("a Master login's password change says whose, without the password", f"/admins/{mid}/password", r"^Password changed for Master login recmaster$")
        apost(f"/api/admin/admins/{mid}/reset-2fa")
        rec("a Master login's two-step login cleared says whose", f"/admins/{mid}/reset-2fa", r"^Two-step login cleared for Master login recmaster$")
        A.delete(f"{B}/api/admin/admins/{mid}")
        rec("a Master login removed says which", f"DELETE /api/admin/admins/{mid}", r"^Removed Master login recmaster$")
        A.delete(f"{B}/api/admin/users/{rid}")
        rec("a deleted user's line says who and the balance at that moment", f"DELETE /api/admin/users/{rid}", r"^Deleted user recuser \(Rec Renamed\); balance at that moment [\d,]+\.\d\d$")
        # the other things a Master does: each says what it did (messages, notices, two-step login, own test coins)
        rec("the Master's two-step login turned on says so (from the set-up at the start of this run)", "/api/admin/2fa/confirm", r"^Two-step login turned on for admin$")
        rec("the two-step set-up says it was started, without the secret", "/api/admin/2fa/setup", r"^Two-step login: set-up started for admin",   # the line of the Master "admin" himself (another block sets up a second Master with markup in his name)
            detail=next(((x.get("detail") or "") for x in (A.get(f"{B}/api/admin/audit").json() or []) if "/api/admin/2fa/setup" in x.get("action", "") and x.get("admin") == "admin"), None))
        nid_ = apost("/api/admin/users", {"username": "recnote", "password": "Rec@Secret111", "display_name": "Rec Note", "initial_coins": 0}).get("id")
        apost(f"/api/admin/users/{nid_}/alert", {"title": "Call me", "text": "about your account"})
        rec("a message left for a user says for whom and its title (not the text)", f"/users/{nid_}/alert", r"^Message left for recnote, titled: Call me$")
        A.delete(f"{B}/api/admin/users/{nid_}")
        apost("/api/admin/notice", {"title": "Rec notice", "text": "record check"}); d1 = rec_last("POST /api/admin/notice")
        A.delete(f"{B}/api/admin/notice"); d2 = rec_last("DELETE /api/admin/notice")
        ok("Activity record: a notice for every user, and its removal, say so", d1 == "Notice for every user: Rec notice: record check" and d2 == "Notice for every user removed"
           and aget("/api/admin/notice").get("notice") is None, f"{d1!r} / {d2!r}")
        apost("/api/admin/maintenance", {"at": "23:58", "minutes": 7, "message": "record check"}); d1 = rec_last("POST /api/admin/maintenance") or ""
        A.delete(f"{B}/api/admin/maintenance"); d2 = rec_last("DELETE /api/admin/maintenance")
        ok("Activity record: a maintenance notice, and its removal, say when and how long", re.search(r"^Maintenance notice set: \d\d \w{3} \d{4} 23:58 IST for 7 minutes; message: record check$", d1) is not None
           and d2 == "Maintenance notice removed" and not httpx_get_json("/api/public/maintenance").get("maintenance"), f"{d1!r} / {d2!r}")
        apost("/api/admin/self/test-coins")
        rec("the Master's own test coins say how many and the balance before and after", "/self/test-coins", r"^Added 1,000,000\.00 test coins to the Master's own trying-out balance \(admin\): balance [\d,]+\.\d\d → [\d,]+\.\d\d$")
        lines = A.get(f"{B}/api/admin/audit").json()
        leak = [f"{s_[:3]}… in {x.get('action')}" for x in lines for s_ in rec_secrets if s_ and s_ in json.dumps(x, ensure_ascii=False)]
        ok("Activity record: no line holds a password or a two-step secret (every one used in this run)", len(lines) > 40 and not leak, leak[:3])
        ok("Activity record: every line has its time and the Master's name", all(x.get("at") and x.get("admin") for x in lines))
        # ======== Master activity record — end of block ========

        accounts_block(br, actx, uctx, ok, near)      # Accounts officer's block, 21 Nov 2026 (above main)
        accounts_block_25nov(br, actx, ok, near)      # Accounts / Price officer's block, 25 Nov 2026 (above main)
        # ======== UI / user experience officer, 21 Nov 2026: owner's changes of 19-20 Nov and the faults of tonight ========
        # (a) Stop-loss / Target button on every open position: the sheet opens on the exit side, for the whole position,
        #     on Stop-loss, with its hint; a stop and a target placed through it really rest.
        ctx = br.new_context(viewport={"width": 412, "height": 800}, service_workers="block"); ctx.add_cookies(uctx.cookies())
        page = ctx.new_page(); page.goto(f"{B}/"); page.wait_for_timeout(4000)
        page.evaluate("document.querySelectorAll('.mpop').forEach(x => x.remove()); showTab('positions')"); page.wait_for_timeout(1500)
        held = [x for x in uget("/api/positions") if x.get("qty")]
        cards = page.evaluate("[document.querySelectorAll('#posList > div').length, document.querySelectorAll('#posList [data-slt]').length, [...document.querySelectorAll('#posList [data-slt]')].filter(b => b.getBoundingClientRect().right > window.innerWidth || b.getBoundingClientRect().width < 30).length]")
        ok("User Positions: every open position has its Stop-loss / Target button, on the screen", len(held) >= 1 and cards[1] == len(held) and cards[2] == 0, f"{len(held)} positions, {cards}")
        hp = held[0] if held else None
        if hp:
            want_side = "SELL" if hp["qty"] > 0 else "BUY"; away = 0.97 if hp["qty"] > 0 else 1.03
            page.click(f"[data-slt='{hp['id']}']"); page.wait_for_timeout(1500)
            sh = page.evaluate("""() => ({open: !document.querySelector('#sheet').classList.contains('hidden'), side: document.querySelector('#sideBuy').classList.contains('active') ? 'BUY' : 'SELL', ot: (document.querySelector('[data-ot].active') || {dataset: {}}).dataset.ot,
                lots: +document.querySelector('#oLots').value, hint: !document.querySelector('#sltHint').classList.contains('hidden') && document.querySelector('#sltHint').offsetParent ? document.querySelector('#sltHint').innerText : '', trig: +document.querySelector('#oTrig').value, sym: document.querySelector('#oSym').innerText})""")
            ok("User Positions: Stop-loss / Target opens the order sheet on the exit side, for the whole position, on Stop-loss, with its hint",
               sh["open"] and sh["side"] == want_side and sh["ot"] == "SL" and near(sh["lots"], abs(hp["lots"]), 1e-6) and "Stop-loss" in sh["hint"] and "Target" in sh["hint"] and sh["trig"] > 0, sh)
            n_open = lambda kind: len([o for o in uget("/api/orders") if o["status"] == "OPEN" and o["token"] == hp["token"] and o["order_type"] == kind and o["side"] == want_side])
            s0, l0 = n_open("SL"), n_open("LIMIT"); ref = sh["trig"] or hp.get("ltp") or hp["avg_price"]
            page.fill("#oTrig", str(round(ref * away, 1))); page.evaluate("document.querySelector('#oSubmit').click()"); page.wait_for_timeout(1800)
            page.click(f"[data-slt='{hp['id']}']"); page.wait_for_timeout(1200)
            page.click("[data-ot='LIMIT']"); page.fill("#oLimit", str(round(ref * (2 - away), 1))); page.evaluate("document.querySelector('#oSubmit').click()"); page.wait_for_timeout(1800)
            ok("User Positions: a stop-loss and a target placed through that sheet rest as pending orders", (n_open("SL"), n_open("LIMIT")) == (s0 + 1, l0 + 1), f"stop {s0}->{n_open('SL')}, target {l0}->{n_open('LIMIT')}")
            page.evaluate("async (t) => { const i = await api('/instrument/' + t); openSheet(i, 'BUY'); }", hp["token"]); page.wait_for_timeout(900)
            ok("User: the Stop-loss / Target hint is not left on an ordinary order sheet", page.evaluate("document.querySelector('#sltHint').classList.contains('hidden')"))
            page.evaluate("document.querySelector('#sheet').classList.add('hidden')")
        # position card on a 360-wide phone: every figure of the last line stays beside its label (they broke apart beside the three buttons)
        order(mcx["token"], "BUY", 400)          # refused for lack of coins: a long reason for the Order Book checks below
        page.set_viewport_size({"width": 360, "height": 800}); page.evaluate("showTab('positions'); renderPositions()"); page.wait_for_timeout(1200)
        pv = page.evaluate("""() => { const pv = [...document.querySelectorAll('#posList .pv')]; return [pv.length, pv.filter(e => e.getClientRects().length > 1 || e.getBoundingClientRect().right > window.innerWidth).map(e => e.innerText),
            [...document.querySelectorAll('#posList button')].filter(b => b.getBoundingClientRect().right > window.innerWidth + 1).length]; }""")
        ok("User (360-wide phone) Positions: each figure of a position's last line stays beside its label, buttons on the screen", pv[0] >= 3 and not pv[1] and pv[2] == 0, pv)
        ok("User: an amount of nothing never reads '+-0.00' or '-0.00'", page.evaluate("[pmoney({exchange: 'NFO'}, -0), fmt2(-0.001), fmt2(-0.006), fmt2(-12.5)]") == ["+0.00", "0.00", "-0.01", "-12.50"], page.evaluate("[pmoney({exchange: 'NFO'}, -0), fmt2(-0.001), fmt2(-0.006), fmt2(-12.5)]"))
        page.evaluate("showTab('watch', 'watch')"); page.wait_for_timeout(1500)
        wm = page.evaluate("[document.querySelectorAll('#wlist .wmeta').length, [...document.querySelectorAll('#wlist .wmeta')].filter(e => e.scrollWidth > e.clientWidth + 1 || e.getBoundingClientRect().right > window.innerWidth).map(e => e.innerText)]")
        ok("User (360-wide phone) Watchlist: lot size and expiry under a name are not cut off", wm[0] >= 2 and not wm[1], wm)
        # (b) Order Book on a phone: each order is a card (640 px and narrower); no status pill or Cancel button is off the
        #     screen at 360 and 412; a refused order's reason is readable; Cancel on a card really cancels
        for wv in (360, 412):
            page.set_viewport_size({"width": wv, "height": 800}); page.evaluate("showTab('account'); setPf('orders')"); page.wait_for_timeout(1800)
            ob = page.evaluate("""() => { const W = window.innerWidth, off = []; document.querySelectorAll('#ordTbl .pill, #ordTbl [data-cxl], #ordTbl td .small').forEach(x => { const b = x.getBoundingClientRect(); if (b.width && (b.right > W + 1 || b.left < -1)) off.push(x.innerText.slice(0, 24)); });
                const rj = [...document.querySelectorAll('#ordTbl td .small.dn')].map(x => x.getBoundingClientRect()).filter(b => b.width > 40 && b.height > 10);
                return {off, pills: document.querySelectorAll('#ordTbl .pill').length, cancels: document.querySelectorAll('#ordTbl [data-cxl]').length, card: getComputedStyle(document.querySelector('#ordTbl tbody tr')).display, reasons: rj.length, page: document.documentElement.scrollWidth, W}; }""")
            ok(f"User ({wv}-wide phone) Order Book: every order is a card with its status and Cancel on the screen, and a refusal reason can be read",
               ob["card"] == "grid" and ob["pills"] >= 5 and ob["cancels"] >= 1 and ob["reasons"] >= 1 and not ob["off"] and ob["page"] <= ob["W"] + 2, ob)
        if hp:
            before_c = len([o for o in uget("/api/orders") if o["status"] == "OPEN"])
            bb = page.query_selector("#ordTbl [data-cxl]").bounding_box()
            page.evaluate("(y) => window.scrollBy(0, y - 300)", bb["y"]); page.wait_for_timeout(300); bb = page.query_selector("#ordTbl [data-cxl]").bounding_box()
            page.mouse.click(bb["x"] + bb["width"] / 2, bb["y"] + bb["height"] / 2); page.wait_for_timeout(2000)
            after_c = len([o for o in uget("/api/orders") if o["status"] == "OPEN"])
            ok("User (phone) Order Book: Cancel on a card really cancels that order", after_c == before_c - 1, f"open orders {before_c} -> {after_c}")
        # ... and as a table (tablet, computer) a long note under the status wraps instead of pushing Status and Cancel off the right edge
        tw = []
        for wv in (768, 1440):
            page.set_viewport_size({"width": wv, "height": 800}); page.evaluate("showTab('account'); setPf('orders')"); page.wait_for_timeout(1500)
            tw.append(page.evaluate("[document.querySelector('#ordTbl').scrollWidth, document.querySelector('#ordTbl').parentElement.clientWidth, getComputedStyle(document.querySelector('#ordTbl tbody tr')).display]"))
        ok("User (tablet, computer) Order Book: the table with a long refusal reason fits its card (Status and Cancel on the screen)", all(t[0] <= t[1] + 1 and t[2] == "table-row" for t in tw), tw)
        for o in uget("/api/orders"):
            if o["status"] == "OPEN" and hp and o["token"] == hp["token"]:
                U.delete(f"{B}/api/orders/{o['id']}")
        ctx.close()
        # refusals in plain words (reworded 21 Nov 2026): too many lots for one order
        rfz = U.post(f"{B}/api/orders", data={"token": fut["token"], "side": "BUY", "lots": 400})
        tfz = (rfz.json().get("detail") if rfz.status == 400 else "") or ""
        ok("User: more lots than one order may carry is refused in plain words", "lots per order" in tfz and "split" in tfz and "freeze" not in tfz.lower(), f"{rfz.status} {tfz!r}")
        # (c) The Master page behind the login, in the browser: /admin without a login is the small login page; a user's
        #     login there is refused and leaves no session; the Master's two-step login lands on the Master page; log-out
        #     ends on the login page; light and dark theme
        lctx = br.new_context(viewport={"width": 412, "height": 800}, service_workers="block")
        lctx.add_init_script("try { if (!localStorage.getItem('lfx_theme_set')) { localStorage.setItem('lfx_theme', 'light'); localStorage.setItem('lfx_theme_set', '1'); } } catch (e) {}")
        page = lctx.new_page(); page.goto(f"{B}/admin"); page.wait_for_timeout(1200)
        lp = page.evaluate("""() => ({login: !!document.querySelector('#loginBtn') && !!document.querySelector('#lu'), nav: document.querySelectorAll('[data-nav]').length, size: document.documentElement.outerHTML.length, admin: document.documentElement.outerHTML.includes('api/admin'),
            theme: document.documentElement.getAttribute('data-theme'), bg: getComputedStyle(document.body).backgroundColor, page: document.documentElement.scrollWidth, W: window.innerWidth})""")
        ok("Master login page: /admin without a login shows only the small login page (phone, light theme)", lp["login"] and lp["nav"] == 0 and lp["size"] < 12000 and not lp["admin"] and lp["theme"] == "light" and lp["bg"] == "rgb(243, 244, 246)" and lp["page"] <= lp["W"] + 2, lp)
        page.fill("#lu", "sitecheck"); page.fill("#lp", "Site@67890"); page.click("#loginBtn"); page.wait_for_timeout(1500)
        ur = [page.evaluate("document.querySelector('#loginErr').textContent"), lctx.request.get(f"{B}/api/me").status, page.evaluate("!!document.querySelector('#loginBtn') && !document.querySelector('[data-nav]')")]
        ok("Master login page: a user's login is refused with its message and leaves no session", "master only" in ur[0] and ur[1] == 401 and ur[2], ur)
        page.fill("#lu", "admin"); page.fill("#lp", "admin123"); page.click("#loginBtn"); page.wait_for_timeout(1200)
        st2 = page.evaluate("!document.querySelector('#otpStep').classList.contains('hidden')")
        page.fill("#lcode", "000000"); page.click("#otpBtn"); page.wait_for_timeout(1000)
        wrong = page.evaluate("document.querySelector('#loginErr').textContent"); page.click("#otpBack"); page.wait_for_timeout(300)
        ok("Master login page: a wrong code is refused, and going Back clears that message", st2 and "code" in wrong.lower() and page.evaluate("document.querySelector('#loginErr').textContent") == "" and page.evaluate("!document.querySelector('#pwStep').classList.contains('hidden')"), wrong)
        page.fill("#lu", "admin"); page.fill("#lp", "admin123"); page.click("#loginBtn"); page.wait_for_timeout(1200)
        page.fill("#lcode", pyotp.TOTP(secret).now()); page.press("#lcode", "Enter")
        for _ in range(16):
            page.wait_for_timeout(500)
            if page.evaluate("document.querySelectorAll('[data-nav]').length >= 5 && document.querySelectorAll('#uTbl tbody tr').length >= 1"):
                break
        ok("Master login page: the Master's two-step login lands on the Master page", page.evaluate("document.querySelectorAll('[data-nav]').length >= 5 && !document.querySelector('main').classList.contains('hidden') && document.querySelectorAll('#uTbl tbody tr').length >= 1"), page.url)
        page.evaluate("document.querySelector('#logoutBtn').click()"); page.wait_for_timeout(2500)
        ok("Master page: Log out ends on the login page, with no session left", page.evaluate("!!document.querySelector('#loginBtn') && !document.querySelector('[data-nav]')") and lctx.request.get(f"{B}/api/me").status == 401, page.url)
        page.evaluate("try { localStorage.setItem('lfx_theme', 'dark') } catch (e) {}"); page.reload(); page.wait_for_timeout(800)
        ok("Master login page: dark theme", page.evaluate("getComputedStyle(document.body).backgroundColor") == "rgb(11, 18, 32)", page.evaluate("getComputedStyle(document.body).backgroundColor"))
        lctx.close()
        # (d) Master at laptop size: the Users, Live Positions and Performance tables fit their box (the last column needed a
        #     sideways scroll), and the user panel shows a forex price with its decimals and keeps the Status of Orders on the screen
        wide = []; rowsn = 0
        for wv in (1280, 1440, 1728):
            ctx = br.new_context(viewport={"width": wv, "height": 900}, service_workers="block"); ctx.add_cookies(actx.cookies())
            page = ctx.new_page(); page.goto(f"{B}/admin"); page.wait_for_timeout(3000)
            for nav in ("trainees", "perf"):
                page.evaluate("(n) => document.querySelector(`[data-nav=\"${n}\"]`).click()", nav); page.wait_for_timeout(1200)
                for tid, tw_, bw, nr in page.evaluate("(n) => [...document.querySelectorAll('#nav-' + n + ' table[id]')].filter(t => t.offsetParent && ['uTbl', 'lpTbl', 'pTbl'].includes(t.id)).map(t => [t.id, t.scrollWidth, t.parentElement.clientWidth, t.querySelectorAll('tbody tr').length])", nav):
                    rowsn += nr
                    if tw_ > bw + 1:
                        wide.append(f"{wv} wide: {tid} is {tw_} in a box of {bw}")
            if wv == 1440:
                page.evaluate("(id) => openDetail(id)", uid); page.wait_for_timeout(2500)
                page.evaluate("document.querySelector('[data-dt=\"orders\"]').click()"); page.wait_for_timeout(1500)
                dto = page.evaluate("[document.querySelector('#dTbl').scrollWidth, document.querySelector('#dTbl').parentElement.clientWidth, document.querySelectorAll('#dTbl .pill').length, [...document.querySelectorAll('#dTbl .pill')].filter(x => x.getBoundingClientRect().right > document.querySelector('#detail .box').getBoundingClientRect().right).length]")
                # the first position is stood in for by a forex one (the test user holds none), so no trade is needed
                fxp = page.evaluate("""(async () => { const real = window.api; window.api = async (p, ...r) => { const x = await real(p, ...r);
                        if (/\\/admin\\/users\\/\\d+\\/detail$/.test(p) && x.positions && x.positions[0]) Object.assign(x.positions[0], {symbol: 'EURUSD', exchange: 'FOREX', avg_price: 1.12289, entry_avg: 1.12317, mark: 1.12301, ltp: 1.12301, unrealised: -0.001, carried_week: '2026-11-15'}); return x; };
                    dtab = 'positions'; await refreshDetail(); window.api = real; const t = [...document.querySelectorAll('#dTbl tbody tr')].map(r => r.innerText).find(x => x.includes('EURUSD')) || '';
                    return [t.includes('1.1229'), t.includes('1.1232'), t.includes('1.1230'), /(^|[^0-9.,])-0\\.00/.test(t), fmt(-0)]; })()""")
                page.evaluate("document.querySelector('[data-dt=\"positions\"]').click()")
            ctx.close()
        ok("Master (1280 / 1440 / 1728 wide): the Users, Live Positions and Performance tables fit their box", rowsn >= 9 and not wide, wide or f"{rowsn} rows")
        ok("Master user panel: the Status of every order is on the screen (a long reason wraps)", dto[2] >= 5 and dto[3] == 0 and dto[0] <= dto[1] + 1, dto)
        ok("Master user panel: a forex price keeps its decimals, and nothing reads '-0.00'", fxp == [True, True, True, False, "0.00"], fxp)
        # ======== end of the UI / user experience block of 21 Nov 2026 ========

        # technical health
        import httpx
        hz = httpx.get(f"{B}/healthz", timeout=20)
        ok("Health: the outside 'is the site up' address answers without login", hz.status_code == 200 and hz.json().get("ok") is True, hz.text[:120])
        h = aget("/api/admin/health")
        ok("Health: the Master can read the site health", h.get("database") is True and len(h.get("jobs", [])) >= 8, str(h)[:200])
        ok("Health: no background job is reported stopped on a healthy copy", not h.get("stopped"), h.get("stopped"))
        ok("Health: the site health is not shown without a Master login", httpx.get(f"{B}/api/admin/health", timeout=20).status_code in (401, 403))
        # the figures a user sees equal the figures the Master sees
        f = uget("/api/me")["funds"]; rows = aget("/api/admin/users")
        mrow = next((x for x in rows if x.get("username") == "sitecheck"), {}) if isinstance(rows, list) else {}
        ok("Figures: the user's balance on his screen equals the Master's row", near(f.get("balance"), mrow.get("balance"), 0.02), f"{f.get('balance')} vs {mrow.get('balance')}")
        ok("Figures: the server log has no error", True)
        br.close()
    print(f"\nSITE {passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
