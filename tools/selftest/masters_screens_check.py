"""Whole run through the screens, by clicks, on the private copy: the owner creates a master on the Masters page,
the master logs in, chooses his password, sets up two-step login, adds a user, deposits, withdraws, squares off,
deletes; the owner looks at his tab. Needs a FRESH private copy:
    PT_MASTERS_CHECK=0 PT_SITE_CHECK=0 bash tools/selftest/run.sh keep ; python3 tools/selftest/masters_screens_check.py
Added 25 Nov 2026 after the master's page went live showing nothing: its list was loaded by a line that threw
(assignment to a constant) and the page swallowed the error. The 71 checks of masters_check.py speak to the server
only and could not see it. Run this before every release that touches app/pages/master.html or the Masters section."""
import asyncio, re, pyotp, httpx
from playwright.async_api import async_playwright
B="http://localhost:8001"; res=[]
def ok(n,c,i=""): res.append(bool(c)); print("PASS" if c else "FAIL","|",n,"|","" if c else i)
num=lambda t: float(re.sub(r"[^\d.\-]","",t) or 0)
async def main():
    async with async_playwright() as p:
        b=await p.chromium.launch()
        # ---- owner ----
        oc=await b.new_context(viewport={"width":1280,"height":900}); o=await oc.new_page(); oerr=[]; o.on("pageerror",lambda e:oerr.append(str(e)))
        o.on("dialog",lambda d: asyncio.ensure_future(d.accept(o._ans.pop(0) if getattr(o,"_ans",None) else "")))
        await o.goto(B+"/admin"); await o.fill("#lu","admin"); await o.fill("#lp","admin123"); await o.click("#loginBtn"); await o.wait_for_timeout(2500)
        if await o.locator("#tfaGate:not(.hidden), #gCode").first.is_visible():
            sec=(await o.inner_text("#gSecret")).strip(); await o.fill("#gCode",pyotp.TOTP(sec).now()); await o.click("#gConfirm"); await o.wait_for_timeout(3000)
        await o.click("[data-nav=masters]"); await o.wait_for_timeout(1000)
        await o.fill("#mName","Test Master"); await o.fill("#mUser","testmaster"); await o.fill("#mPass","first123"); await o.fill("#mPct","40"); await o.fill("#mStock","1000000"); await o.click("#mBtn"); await o.wait_for_timeout(2000)
        row=await o.inner_text("#mTbl tbody")
        ok("owner: the new master appears in the Masters table with his coins","Test Master" in row and "10,00,000" in row,row)
        # ---- master, first login ----
        mc=await b.new_context(viewport={"width":390,"height":800}); m=await mc.new_page(); merr=[]; m.on("pageerror",lambda e:merr.append(str(e)))
        m._ans=[]; m.on("dialog",lambda d: asyncio.ensure_future(d.accept(m._ans.pop(0) if m._ans else "")))
        await m.goto(B+"/admin"); await m.fill("#lu","testmaster"); await m.fill("#lp","first123"); await m.click("#loginBtn"); await m.wait_for_timeout(3000)
        ok("master: first login asks for his own password", await m.is_visible("#pwGate") and not await m.is_visible("#appView"))
        await m.fill("#pwOld","first123"); await m.fill("#pwNew","mine12345"); await m.fill("#pwNew2","mine12345"); await m.click("#pwGo"); await m.wait_for_timeout(3000)
        ok("master: then two-step login set-up, with a code to scan", await m.is_visible("#tfaGate") and await m.locator("#gQr img").count()==1)
        sec=(await m.inner_text("#gSecret")).strip(); await m.fill("#gCode",pyotp.TOTP(sec).now()); await m.click("#gConfirm"); await m.wait_for_timeout(3500)
        ok("master: his page opens, with his name and coins", await m.is_visible("#appView") and "Test Master" in await m.inner_text("#meName") and num(await m.inner_text("#sStock"))==1000000, await m.inner_text("header"))
        ok("master: nothing of the owner's page is on his", await m.locator("[data-nav=shadow],[data-nav=settings],[data-nav=masters],#kiteBox").count()==0)
        # log out and in again with the code
        await m.click("#appView [data-logout]"); await m.wait_for_timeout(2000)
        await m.fill("#lu","testmaster"); await m.fill("#lp","mine12345"); await m.click("#loginBtn"); await m.wait_for_timeout(1500)
        await m.fill("#lcode",pyotp.TOTP(sec).now()); await m.click("#otpBtn"); await m.wait_for_timeout(3500)
        ok("master: logs in again with password and code", await m.is_visible("#appView"))
        # add user
        await m.fill("#nUser","testuser"); await m.fill("#nName","Test User"); await m.fill("#nPass","first123"); await m.fill("#nCoins","500000"); await m.click("#nBtn"); await m.wait_for_timeout(2500)
        ok("master: user created, coins left 50,000, coins with users 50,000", num(await m.inner_text("#sStock"))==500000 and num(await m.inner_text("#sWith"))==500000 and "Test User" in await m.inner_text("#uT tbody"), await m.inner_text("#sStock"))
        await m.click("#uT tr[data-u]"); await m.wait_for_timeout(1500)
        await m.fill("#dAmt","10000"); await m.click("#dDep"); await m.wait_for_timeout(2500)
        await m.fill("#dAmt","5000"); await m.click("#dWd"); await m.wait_for_timeout(2500)
        ok("master: deposit 10,000 and withdraw 5,000 by the buttons: coins left 45,000", num(await m.inner_text("#sStock"))==495000 and num(await m.inner_text("#sWith"))==505000, await m.inner_text("#sStock"))
        await m.fill("#dAmt","99999999"); await m.click("#dDep"); await m.wait_for_timeout(1500)
        ok("master: a deposit above his coins is refused with a plain message", "You hold" in (await m.inner_text("body")) and num(await m.inner_text("#sStock"))==495000)
        # the user trades (through the API, as the app would)
        u=httpx.Client(base_url=B,timeout=60); u.post("/api/login",json={"username":"testuser","password":"first123"}); u.post("/api/password",json={"old_password":"first123","new_password":"mine12345"})
        ow=httpx.Client(base_url=B,timeout=60); ow.cookies.update({c["name"]:c["value"] for c in await oc.cookies()})
        tk=ow.get("/api/futures",params={"exchange":"NFO","name":"NIFTY"}).json(); tk=(tk if isinstance(tk,list) else tk.get("futures") or tk.get("rows"))[0]["token"]
        r=u.post("/api/orders",json={"token":tk,"side":"BUY","lots":1}); ok("his user's order fills (needs enough coins for one lot)", r.status_code==200 and r.json()["order"]["status"]=="FILLED", r.text[:200])
        await m.wait_for_timeout(6000)
        ok("master: the open position shows on his page and in the user's panel", "NIFTY" in await m.inner_text("#pT tbody") and "NIFTY" in await m.inner_text("#dT tbody"), await m.inner_text("#pT tbody"))
        await m.click("#dDel"); await m.wait_for_timeout(1500)
        ok("master: Delete with an open position is refused", "Square him off first" in await m.inner_text("body"))
        await m.click("#dSq"); await m.wait_for_timeout(3500)
        ok("master: Square off closes the position", "position(s) closed" in await m.inner_text("body") or "Nothing here" in await m.inner_text("#dT tbody"), await m.inner_text("#dT tbody"))
        await m.click("#dClose"); await m.click("[data-nav=weekly]"); await m.wait_for_timeout(2500)
        bp,br_,bt,ow_,mi=[num(await m.inner_text(x)) for x in ("#wRes","#wCom","#wOurs","#wOwner","#wMine")]
        ok("master: Weekly Record adds up on the screen (book P&L + brokerage = total = owner's 40% + his)", br_>0 and abs(bp+br_-bt)<=1.01 and abs(ow_+mi-bt)<=1.01 and abs(ow_-bt*0.4)<=1.01 and "40%" in await m.inner_text("#wPctL"), f"{bp} {br_} {bt} {ow_} {mi}")
        await m.click("[data-nav=coins]"); await m.wait_for_timeout(1500); led=await m.inner_text("#cT tbody")
        ok("master: My Coins lists what he received, gave and took back", all(x in led for x in ("Received from the owner","Given to a user","Taken back from a user")), led[:200])
        # ---- owner looks ----
        await o.click("#mTbl tr[data-m]"); await o.wait_for_timeout(3500)
        ok("owner: his tab shows coins 45,000 with him and 55,000 with users", "4,95,000" in await o.inner_text("#moStats") and "5,05,000" in await o.inner_text("#moStats"), await o.inner_text("#moStats"))
        wk=await o.inner_text("#moWk tbody tr:first-child"); ok("owner: the week row shows the same book total and 40%", "40%" in wk and f"{int(round(abs(bt))):,}".replace(",","")[:2] in wk.replace(",",""), wk)
        ok("owner: his user is under his tab", "Test User" in await o.inner_text("#moU tbody"))
        await o.click("[data-nav=trainees]"); await o.wait_for_timeout(2500)
        ok("owner: his user is NOT in the owner's own Users list", "Test User" not in await o.inner_text("#uTbl tbody"))
        await o.click("[data-nav=masters]"); await o.wait_for_timeout(1500); await o.click("#moU tr[data-vu]"); await o.wait_for_timeout(2500)
        ok("owner: can open his user's details to look", await o.is_visible("#detail") or await o.locator(".modal:not(.hidden)").count()>0)
        # ---- master deletes ----
        await m.click("[data-nav=users]"); await m.wait_for_timeout(800); await m.click("#uT tr[data-u]"); await m.wait_for_timeout(1500); await m.click("#dDel"); await m.wait_for_timeout(3000)
        ok("master: the flat user is deleted, coins all back (1,00,000), user greyed 'deleted'", num(await m.inner_text("#sStock"))==1000000 and num(await m.inner_text("#sWith"))==0 and "deleted" in await m.inner_text("#uT tbody"), await m.inner_text("#uT tbody"))
        await m.click("[data-nav=weekly]"); await m.wait_for_timeout(2500)
        ok("master: the week still shows the deleted user's result", abs(num(await m.inner_text("#wOurs"))-bt)<=1.01 and "deleted" in await m.inner_text("#wT tbody"), await m.inner_text("#wT tbody"))
        # ---- owner: take coins back, pause ----
        o._ans=["1000000"]; await o.keyboard.press("Escape"); await o.evaluate("document.querySelectorAll('.modal').forEach(x=>x.classList.add('hidden'))"); await o.click("#moTake"); await o.wait_for_timeout(2500)
        ok("owner: takes all 1,00,000 coins back", "0" == (await o.inner_text("#moStats .stat:first-child b")).strip(), await o.inner_text("#moStats"))
        await o.click("#moPause"); await o.wait_for_timeout(2500); await m.reload(); await m.wait_for_timeout(2500)
        ok("owner: Pause logs the master out at once", await m.is_visible("#lu"))
        ok("no script error on either page", not oerr and not merr, f"owner {oerr[:2]} master {merr[:2]}")
        await b.close()
    print(f"\nSCREENS {sum(res)} passed, {len(res)-sum(res)} failed")
asyncio.run(main())
import sys
sys.exit(0 if all(res) and res else 1)
