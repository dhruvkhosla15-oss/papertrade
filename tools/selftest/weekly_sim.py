"""Month-long simulation of the weekly settlement, on a throw-away database with prices this script controls.

Five weeks, many accounts, each one a different situation (hold for weeks, partial exits, adding to a
carried position, short options, flip, liquidation, crypto, coins added mid-week, a position with no
price at the cut-off, a cut-off that runs late, a missed week ...).

After every week and at the end it checks the books against an INDEPENDENT calculation that knows nothing
about weekly settlement: plain average-cost P&L from each account's own entry prices.

    python3 tools/selftest/weekly_sim.py          exit code 1 if any check fails
"""
import asyncio
import math
import os
import sys
import tempfile
import time
from datetime import datetime, date, timedelta

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
TMP = tempfile.mkdtemp(prefix="lfx-weeksim-")
os.environ.update(PT_DATA_DIR=TMP, PT_FEED="mock", PT_ENFORCE_MARKET_HOURS="false", PT_STRICT_LIQ_GRACE_MIN="0",
                  PT_TELEGRAM_TOKEN="", PT_TELEGRAM_CHAT="")
sys.path.insert(0, ROOT)

from app import db as D                                   # noqa: E402
from app.db import SessionLocal, User, Order, Position, Trade, Ledger, WeekSettlement   # noqa: E402
from app.engine import Engine, EngineError                # noqa: E402
from app.feed.base import PriceFeed, Instrument           # noqa: E402
from app import weekly as W                               # noqa: E402

IST = timedelta(hours=5, minutes=30)
FAR = "2027-12-30"


class SimFeed(PriceFeed):
    name = "sim"

    def __init__(self):
        super().__init__()
        self.connected = True
        self.usdinr = 90.0

    def set(self, token, mid, spread=None):
        ins = self.instruments[token]
        sp = ins.tick_size * 2 if spread is None else spread
        bid, ask = round(mid - sp / 2, 4), round(mid + sp / 2, 4)
        if ins.segment == "INDICES":
            self.prices[token] = {"token": token, "ltp": mid, "ts": time.time()}
        else:
            self.prices[token] = {"token": token, "ltp": mid, "bid": bid, "ask": ask, "ts": time.time(), "ltt": time.time(),
                                  "bids": [[bid, 10 ** 8, 1]], "asks": [[ask, 10 ** 8, 1]]}

    def live(self, token):
        return token in self.prices

    def pin(self, tokens):
        pass

    def subscribe(self, tokens):
        pass

    def unsubscribe(self, tokens):
        pass

    def value_factor(self, ins):
        return ins.multiplier * self.usdinr if ins.exchange == "CRYPTO" else 1.0


I_NIFTY, F_NIFTY, F_SILVER, F_SILVERM, O_CE, O_PE_EXP, F_BTC, F_GOLD, F_CRUDE = range(1, 10)
feed = SimFeed()
feed.load_instruments([
    Instrument(I_NIFTY, "NIFTY", "NIFTY", "NSE", "INDICES", "EQ", "", 0, 1, 0.05),
    Instrument(F_NIFTY, "NIFTY27DECFUT", "NIFTY", "NFO", "NFO-FUT", "FUT", FAR, 0, 75, 0.05),
    Instrument(F_SILVER, "SILVER27DECFUT", "SILVER", "MCX", "MCX-FUT", "FUT", FAR, 0, 30, 1.0),
    Instrument(F_SILVERM, "SILVERM27DECFUT", "SILVERM", "MCX", "MCX-FUT", "FUT", FAR, 0, 5, 1.0),
    Instrument(O_CE, "NIFTY27DEC26000CE", "NIFTY", "NFO", "NFO-OPT", "CE", FAR, 26000, 75, 0.05),
    Instrument(O_PE_EXP, "NIFTY26N2624000PE", "NIFTY", "NFO", "NFO-OPT", "PE", "2026-11-26", 24000, 75, 0.05),
    Instrument(F_BTC, "BTCUSD", "BTC", "CRYPTO", "CRYPTO-FUT", "FUT", "", 0, 1, 0.5, multiplier=0.001, init_margin_pct=10.0),
    Instrument(F_GOLD, "GOLD27DECFUT", "GOLD", "MCX", "MCX-FUT", "FUT", FAR, 0, 100, 1.0),
    Instrument(F_CRUDE, "CRUDEOIL27DECFUT", "CRUDEOIL", "MCX", "MCX-FUT", "FUT", FAR, 0, 100, 1.0),
])
D.init_db()
engine = Engine(feed)
db = SessionLocal()

checks = {"pass": 0, "fail": 0}
fails = []


def ok(name, cond, info=""):
    if cond:
        checks["pass"] += 1
    else:
        checks["fail"] += 1; fails.append(f"{name} | {info}")
        print("FAIL", name, "|", info)


def near(a, b, tol=0.06):
    return abs(a - b) <= tol


# ---- simulated clock: rows the engine writes get the simulated time -----------------------------------
T = datetime(2026, 11, 9, 9, 30)       # IST
_last = {"orders": 0, "trades": 0, "ledger": 0}


def at(dt):
    global T
    T = dt
    os.environ["PT_FAKE_NOW"] = dt.isoformat()


def stamp():
    """Give every row written since the last call the simulated time."""
    utc = T - IST
    db.flush()
    for o in db.query(Order).filter(Order.id > _last["orders"]).all():
        o.created_at = utc; _last["orders"] = max(_last["orders"], o.id)
    db.flush()
    db.execute(D.Order.__table__.update().where(D.Order.id <= _last["orders"]).where(D.Order.updated_at > datetime.utcnow() - timedelta(hours=1)).values(updated_at=utc))
    for t in db.query(Trade).filter(Trade.id > _last["trades"]).all():
        t.created_at = utc; _last["trades"] = max(_last["trades"], t.id)
        truth_trade(t)
    for l in db.query(Ledger).filter(Ledger.id > _last["ledger"]).all():
        if l.kind not in W.WEEK_KINDS:
            l.created_at = utc
        _last["ledger"] = max(_last["ledger"], l.id)
    db.commit()


# ---- the independent calculation: average cost from the account's own prices ---------------------------
truth = {}          # (user_id, token) -> {"qty", "avg"}
truth_real = {}     # user_id -> realised from own entry prices
truth_comm = {}     # user_id -> commission


def truth_trade(t):
    ins = feed.instruments[t.token]
    vf = engine.vf(ins)
    k = (t.user_id, t.token)
    p = truth.setdefault(k, {"qty": 0, "avg": 0.0})
    signed = t.qty if t.side == "BUY" else -t.qty
    truth_comm[t.user_id] = truth_comm.get(t.user_id, 0.0) + (t.commission or 0.0)
    if p["qty"] == 0 or (p["qty"] > 0) == (signed > 0):
        p["avg"] = (p["avg"] * abs(p["qty"]) + t.price * t.qty) / (abs(p["qty"]) + t.qty); p["qty"] += signed
    else:
        closing = min(abs(p["qty"]), t.qty)
        truth_real[t.user_id] = truth_real.get(t.user_id, 0.0) + (t.price - p["avg"]) * closing * (1 if p["qty"] > 0 else -1) * vf
        p["qty"] += signed
        if p["qty"] != 0 and (p["qty"] > 0) == (signed > 0):
            p["avg"] = t.price


def truth_unreal(uid):
    tot = 0.0
    for (u, tok), p in truth.items():
        if u != uid or not p["qty"]:
            continue
        mk = engine.mark_price(tok, p["qty"])
        if mk is None:
            mk = feed.ltp(tok)
        if mk is None:
            pos = db.query(Position).filter_by(user_id=uid, token=tok, is_closed=False).first()
            mk = pos.last_mark if pos and pos.last_mark is not None else (pos.avg_price if pos else p["avg"])   # last price known
        tot += (mk - p["avg"]) * p["qty"] * engine.vf(feed.instruments[tok])
    return tot


def truth_total(uid):
    return truth_real.get(uid, 0.0) + truth_unreal(uid) - truth_comm.get(uid, 0.0)


# ---- actions ------------------------------------------------------------------------------------------
users = {}


def mk_user(name, coins, admin=False):
    u = User(username=name, display_name=name.upper(), password_hash="x", is_admin=admin, balance=0.0)
    db.add(u); db.flush()
    engine._ledger(db, u, coins, "ADMIN_CREDIT", "initial allocation")
    db.commit(); stamp()
    users[name] = u
    return u


def trade(name, token, side, lots, expect=True, **kw):
    engine._consumed.clear()
    u = users[name]
    try:
        o = engine.place_order(db, u, token, side, lots, kw.pop("order_type", "MARKET"), **kw)
        stamp()
        if not expect:
            ok(f"{name}: order should have been refused", False, f"{side} {lots} {feed.instruments[token].symbol}")
        return o
    except EngineError as e:
        db.rollback(); stamp()
        if expect:
            ok(f"{name}: order accepted", False, f"{side} {lots} {feed.instruments[token].symbol}: {e}")
        return None


def coins(name, amount, note="master"):
    u = users[name]
    engine._ledger(db, u, amount, "ADMIN_CREDIT" if amount >= 0 else "ADMIN_DEBIT", note)
    db.commit(); stamp()


def run(coro):
    asyncio.get_event_loop().run_until_complete(coro)
    stamp()


def px(**kw):
    m = {"nifty": (I_NIFTY, F_NIFTY), "silver": (F_SILVER,), "silverm": (F_SILVERM,), "ce": (O_CE,), "pe": (O_PE_EXP,),
         "btc": (F_BTC,), "gold": (F_GOLD,), "crude": (F_CRUDE,)}
    for k, v in kw.items():
        for tok in m[k]:
            feed.set(tok, v)
    W.remember_marks(engine, db)


results = {}       # user_id -> sum of finished weeks' results


def close(week_end: date, exact=True, label=""):
    """Run the cut-off for one week and check every account."""
    db.expire_all()
    before = {u.id: {"truth": truth_total(u.id), "prov": W.running_row(engine, db, u)["result"], "alloc": W.allocated(db, u)} for u in users.values()}
    at(datetime.combine(week_end, datetime.max.time()).replace(microsecond=0))
    s = W.close_week(engine, db, week_end, exact=exact)
    _last["ledger"] = max([_last["ledger"]] + [l.id for l in db.query(Ledger).all()])
    db.commit(); db.expire_all()
    we = week_end.isoformat()
    for name, u in users.items():
        r = db.query(WeekSettlement).filter_by(week_end=we, user_id=u.id).first()
        tag = f"week {we} {label} {name}"
        ok(f"{tag}: has a settlement row", r is not None)
        if not r:
            continue
        results[u.id] = results.get(u.id, 0.0) + r.result
        f = engine.funds(db, u)
        last = db.query(Ledger).filter_by(user_id=u.id).order_by(Ledger.id.desc()).first()
        ok(f"{tag}: coins are back to the allocated amount", near(u.balance, before[u.id]["alloc"]), f"{u.balance} vs {before[u.id]['alloc']}")
        ok(f"{tag}: coins equal the last ledger line", near(u.balance, last.balance_after), f"{u.balance} vs {last.balance_after}")
        ok(f"{tag}: result = closed + valuation - commission", near(r.result, r.closed + r.valuation - r.commission + r.other, 0.02) and r.other == 0,
           f"result {r.result} closed {r.closed} valuation {r.valuation} commission {r.commission} other {r.other}")
        ok(f"{tag}: the final figure equals the provisional figure shown just before the cut-off", near(r.result, before[u.id]["prov"], 0.02),
           f"{r.result} vs {before[u.id]['prov']}")
        if not r.unpriced:
            ok(f"{tag}: open positions start the new week at zero", near(f["unrealised"], 0.0), f"unrealised {f['unrealised']}")
        ok(f"{tag}: all weeks so far add up to the P&L from the account's own prices", near(results[u.id] + f["unrealised"], before[u.id]["truth"], 0.5),
           f"weeks {results[u.id]:.2f} + open {f['unrealised']:.2f} vs own-price P&L {before[u.id]['truth']:.2f}")
        ok(f"{tag}: valuation lines in the ledger add up", near(sum(l.amount for l in db.query(Ledger).filter_by(user_id=u.id, kind=W.VALUATION).filter(Ledger.created_at == W.cutoff_utc(week_end))), r.valuation, 0.02))
        check_positions(name, tag)
    return s


def check_positions(name, tag):
    u = users[name]
    for p in db.query(Position).filter_by(user_id=u.id, is_closed=False).all():
        if not p.qty:
            continue
        d = engine.position_dict(p)
        t = truth.get((u.id, p.token), {"qty": 0, "avg": 0.0})
        ok(f"{tag}: {p.symbol} quantity matches", t["qty"] == p.qty, f"{p.qty} vs {t['qty']}")
        own = p.entry_avg if p.entry_avg is not None else p.avg_price
        ok(f"{tag}: {p.symbol} original average is kept", near(own, t["avg"], 0.01), f"{own} vs {t['avg']}")
        mk = d["mark"]
        if mk is not None:
            vf = engine.vf(feed.instruments[p.token])
            ok(f"{tag}: {p.symbol} settled earlier + this week = total since entry", near(d["settled_earlier"] + d["unrealised"], (mk - t["avg"]) * p.qty * vf, 0.05) and near(d["total_since_entry"], d["settled_earlier"] + d["unrealised"], 0.011),
               f"{d['settled_earlier']} + {d['unrealised']} vs {(mk - t['avg']) * p.qty * vf:.2f}")


def check_running(tag):
    """Mid-week: finished weeks + the running week must equal the own-price P&L, for every account."""
    db.expire_all()
    for name, u in users.items():
        f = engine.funds(db, u)
        run_row = W.running_row(engine, db, u)
        alloc = W.allocated(db, u)
        ok(f"{tag} {name}: running week = net balance - allocated", near(run_row["result"], f["equity"] - alloc, 0.02), f"{run_row['result']} vs {f['equity'] - alloc}")
        ok(f"{tag} {name}: running week adds up (closed + open - commission)", run_row["other"] == 0, f"other {run_row['other']} row {run_row}")
        ok(f"{tag} {name}: finished weeks + running week = P&L from own prices", near(results.get(u.id, 0.0) + run_row["result"], truth_total(u.id), 0.5),
           f"{results.get(u.id, 0.0):.2f} + {run_row['result']:.2f} vs {truth_total(u.id):.2f}")
        ok(f"{tag} {name}: finished weeks match the ledger", near(W.settled_total(db, u), results.get(u.id, 0.0), 0.02))
        last = db.query(Ledger).filter_by(user_id=u.id).order_by(Ledger.id.desc()).first()
        ok(f"{tag} {name}: coins equal the last ledger line", near(u.balance, last.balance_after))
        check_positions(name, f"{tag} {name}")


def day(week_monday: date, dow: int, hh=11, mm=0):
    return datetime.combine(week_monday + timedelta(days=dow), datetime.min.time()).replace(hour=hh, minute=mm)


# =========================================== the month ===================================================
W1, W2, W3, W4, W5 = (date(2026, 11, 9) + timedelta(days=7 * i) for i in range(5))
SUN = lambda monday: monday + timedelta(days=6)

at(day(W1, 0, 9, 0))
px(nifty=25000, silver=182000, silverm=182500, ce=300, pe=120, btc=74000, gold=98000, crude=6000)
for n, c in [("hold", 2_500_000), ("partial", 2_500_000), ("adder", 4_000_000), ("optseller", 2_000_000), ("expiry", 2_000_000),
             ("scalper", 1_000_000), ("flipper", 3_000_000), ("topup", 1_500_000), ("liq", 700_000), ("crypto", 500_000),
             ("idle", 100_000), ("noprice", 2_000_000), ("lastmark", 2_000_000), ("resting", 1_000_000), ("winner", 2_000_000)]:
    mk_user(n, c)
mk_user("master", 1_000_000, admin=True)

# ---- week 1 -------------------------------------------------------------------------------------------
at(day(W1, 1))
trade("hold", F_NIFTY, "BUY", 2)
trade("partial", F_SILVERM, "BUY", 4)
trade("adder", F_SILVER, "BUY", 1)
trade("optseller", O_CE, "SELL", 2)
trade("expiry", O_PE_EXP, "SELL", 1)
trade("flipper", F_NIFTY, "BUY", 2)
trade("topup", F_GOLD, "BUY", 1)
trade("liq", F_CRUDE, "BUY", 7)
trade("noprice", F_GOLD, "BUY", 1)
trade("lastmark", F_CRUDE, "SELL", 3)
trade("winner", F_NIFTY, "SELL", 3)
trade("master", F_NIFTY, "BUY", 1)
trade("scalper", F_NIFTY, "BUY", 1)
at(day(W1, 1, 14)); px(nifty=25080); trade("scalper", F_NIFTY, "SELL", 1)
at(day(W1, 3)); px(nifty=24900, silver=180000, silverm=180400, ce=260, pe=150, gold=97500, crude=5950)
trade("scalper", F_SILVERM, "SELL", 2)
at(day(W1, 3, 15)); px(silverm=180100); trade("scalper", F_SILVERM, "BUY", 2)
trade("resting", F_NIFTY, "BUY", 1, order_type="LIMIT", limit_price=24000.0, validity="GTT")
at(day(W1, 4, 20)); px(nifty=24800, silver=176565, silverm=178424, ce=230, pe=170, gold=97000, crude=5900, btc=73000)
trade("crypto", F_BTC, "BUY", 5)
check_running("mid week 1")
at(day(W1, 6, 22)); px(btc=71500)                         # crypto moves over the weekend
close(SUN(W1))
ok("closing the same week twice changes nothing", W.close_week(engine, db, SUN(W1))["accounts"] == 0)

# ---- week 2 -------------------------------------------------------------------------------------------
at(day(W2, 0, 10)); px(nifty=24950, silver=178000, silverm=179800, ce=250, pe=140, gold=97800, crude=5800, btc=72500)
check_running("monday week 2")
trade("partial", F_SILVERM, "SELL", 1)                    # partial exit of a carried position
trade("adder", F_SILVER, "BUY", 1)                        # add to a carried position
trade("flipper", F_NIFTY, "SELL", 5)                      # carried long 2 -> short 3
coins("topup", 200_000, "more coins")                     # master adds coins mid-week
trade("scalper", F_GOLD, "BUY", 1)
at(day(W2, 2)); px(nifty=25200, silver=175000, silverm=177000, ce=330, pe=90, gold=98400, crude=5450, btc=75500)
trade("scalper", F_GOLD, "SELL", 1)
run(engine._check_liquidations())                         # crude has fallen: "liq" is short of margin -> auto square-off
liq_pos = db.query(Position).filter_by(user_id=users["liq"].id, is_closed=False).first()
ok("liquidation: the carried position was squared off (fully or partly)", (liq_pos.qty if liq_pos else 0) < 7 * 100, f"qty {liq_pos.qty if liq_pos else 0}")
ok("liquidation: account is not left below zero", engine.funds(db, users["liq"])["available"] >= 0, str(engine.funds(db, users["liq"])["available"]))
check_running("mid week 2")
at(day(W2, 4, 21)); px(nifty=25300, silver=174000, silverm=176200, ce=380, pe=70, gold=98900, crude=5500, btc=76000)
trade("winner", F_NIFTY, "BUY", 1)                        # partial cover
at(day(W2, 6, 23)); px(btc=77000)
# "noprice": the feed has nothing for GOLD and no remembered price either -> left as it is this week
gold_tick = feed.prices.pop(F_GOLD)
for p in db.query(Position).filter_by(token=F_GOLD, is_closed=False).all():
    if p.user_id == users["noprice"].id:
        p.last_mark = None
    # "topup" also holds GOLD: it keeps its remembered price and is valued at it
db.commit()
# "lastmark": the feed has lost CRUDE (restart with the exchange shut) but the last price was remembered
crude_tick = feed.prices.pop(F_CRUDE)
s = close(SUN(W2))
ok("week 2: exactly one position had no price", s["unpriced"] == 1, str(s))
feed.prices[F_GOLD] = gold_tick; feed.prices[F_CRUDE] = crude_tick

# ---- week 3 -------------------------------------------------------------------------------------------
at(day(W3, 0, 10)); px(nifty=25250, silver=175500, silverm=177500, ce=360, pe=60, gold=99200, crude=5520, btc=76500)
check_running("monday week 3")
trade("partial", F_SILVERM, "SELL", 2)
trade("adder", F_SILVER, "BUY", 1)
trade("flipper", F_NIFTY, "BUY", 3)                       # flat
coins("topup", -50_000, "coins removed")
trade("optseller", O_CE, "BUY", 2)                        # buy back the short option carried two weeks
trade("crypto", F_BTC, "SELL", 5)
at(day(W3, 2)); px(nifty=24700, btc=74000)
trade("crypto", F_BTC, "SELL", 3)                         # new short
trade("scalper", F_NIFTY, "SELL", 2)
at(day(W3, 2, 15)); px(nifty=24650); trade("scalper", F_NIFTY, "BUY", 2)
at(day(W3, 3, 16)); px(nifty=24600, pe=0.05)              # expiry day of the put: index above the strike -> expires worthless
run(engine._settle_expired())
ok("expiry: the carried short option was settled", not db.query(Position).filter_by(user_id=users["expiry"].id, is_closed=False).filter(Position.qty != 0).count())
check_running("after expiry week 3")
at(day(W3, 4, 20)); px(nifty=24600, silver=177000, silverm=179000, ce=200, gold=99000, crude=5600, btc=73000)
at(day(W3, 6, 23)); px(btc=72000)
close(SUN(W3))

# ---- week 4: the cut-off runs late ---------------------------------------------------------------------
at(day(W4, 1)); px(nifty=25100, silver=179500, silverm=181000, ce=280, gold=99800, crude=5650, btc=71000)
check_running("tuesday week 4")
trade("hold", F_NIFTY, "SELL", 2)                         # exit after three weekly cut-offs
trade("partial", F_SILVERM, "SELL", 1)                    # last lot
trade("adder", F_SILVER, "SELL", 3)                       # all three lots, bought in three different weeks
trade("crypto", F_BTC, "BUY", 3)
trade("noprice", F_GOLD, "SELL", 1)
trade("lastmark", F_CRUDE, "BUY", 3)
trade("winner", F_NIFTY, "BUY", 2)
at(day(W4, 3)); px(nifty=25400)
trade("hold", F_NIFTY, "BUY", 1)                          # a fresh position in the same contract
check_running("thursday week 4")
at(day(W4, 6, 20)); px(nifty=25350, gold=100200)
close(SUN(W4), exact=False, label="(late)")

# ---- week 5 and a missed week ---------------------------------------------------------------------------
at(day(W5, 2)); px(nifty=25500, gold=100900, btc=70000)
check_running("wednesday week 5")
trade("hold", F_NIFTY, "SELL", 1)
trade("topup", F_GOLD, "SELL", 1)
trade("master", F_NIFTY, "SELL", 1)
close(SUN(W5))
W6 = W5 + timedelta(days=7)
at(day(W6, 0, 10)); px(nifty=25450)
check_running("monday week 6")
close(SUN(W6), label="(empty week)")
check_running("after an empty week")

# ---- end of the month: nothing left open except the resting order ----------------------------------------
db.expire_all()
for name, u in users.items():
    f = engine.funds(db, u)
    open_pos = [p for p in db.query(Position).filter_by(user_id=u.id, is_closed=False).all() if p.qty]
    if not open_pos:
        ok(f"end {name}: all weeks add up to the P&L from own prices", near(results.get(u.id, 0.0) + (f["equity"] - W.allocated(db, u)), truth_real.get(u.id, 0.0) - truth_comm.get(u.id, 0.0), 0.5),
           f"{results.get(u.id, 0.0) + f['equity'] - W.allocated(db, u):.2f} vs {truth_real.get(u.id, 0.0) - truth_comm.get(u.id, 0.0):.2f}")
    rows = db.query(WeekSettlement).filter_by(user_id=u.id).all()
    ok(f"end {name}: one row per week", len(rows) == 6, str(len(rows)))
    ok(f"end {name}: ledger is continuous (every line follows from the one before)", all(
        near(b.balance_after, a.balance_after + b.amount, 0.011) for a, b in zip(*(lambda L: (L, L[1:]))(db.query(Ledger).filter_by(user_id=u.id).order_by(Ledger.id).all()))))
carry_notes = [o.carry_note for o in db.query(Order).filter(Order.carry_note != "").all() if o.carry_note]
ok("exits of carried positions carry a note", len(carry_notes) >= 8, str(len(carry_notes)))
rest = db.query(Order).filter_by(user_id=users["resting"].id, status="OPEN").first()
ok("a resting order survives the weekly cut-offs with its margin", rest is not None and (rest.margin_blocked or 0) > 0)

if __name__ == "__main__":
    print(f"\nWEEKLY SIMULATION: {checks['pass']} passed, {checks['fail']} failed")
    sys.exit(1 if checks["fail"] else 0)
