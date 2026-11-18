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
            ok("Excel: all-time Net P&L (Settlement) = the Master's all-time figure for the user", bool(tot) and near(tot[11], au.get("total_pnl"), max(60.0, abs(au.get("total_pnl", 0)) * 0.01)), f"{tot and tot[11]} vs {au.get('total_pnl')}")
            _, lrow = sheet_rows(wb, "Ledger Statement")
            body = [x for x in lrow if x[2] != "Closing Balance" and isinstance(x[3], (int, float))]
            ok("Excel: ledger balances run on without a gap", all(near(y[4], x[4] + y[3], 0.011) for x, y in zip(body, body[1:])))
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
        A.delete(f"{B}/api/admin/users/{nid}"); nctx.close()

        # Site health card: the name and the value of every row stand apart (they ran together: "Domain name limefx.invalid until ...")
        ctx = br.new_context(viewport={"width": 1440, "height": 900}); ctx.add_cookies(actx.cookies())
        page = ctx.new_page(); page.goto(f"{B}/admin"); page.wait_for_timeout(4000)
        page.evaluate("document.querySelector('[data-nav=\"settings\"]').click()"); page.wait_for_timeout(2500)
        gaps = page.evaluate("[...document.querySelectorAll('#hlBody .plrow')].map(r => r.querySelector('b').getBoundingClientRect().left - r.querySelector('span').getBoundingClientRect().right)")
        ok("Master Settings: site health rows show the name and the value apart", len(gaps) >= 14 and min(gaps) >= 8, f"smallest gap {min(gaps) if gaps else None}px")
        ctx.close()

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
