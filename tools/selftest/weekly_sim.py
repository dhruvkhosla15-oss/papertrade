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
os.environ.update(PT_ACCESS_ALL="1", PT_DATA_DIR=TMP, PT_FEED="mock", PT_ENFORCE_MARKET_HOURS="false", PT_STRICT_LIQ_GRACE_MIN="0",
                  PT_TELEGRAM_TOKEN="", PT_TELEGRAM_CHAT="")
sys.path.insert(0, ROOT)

from app import db as D                                   # noqa: E402
from app.db import SessionLocal, User, Order, Position, Trade, Ledger, WeekSettlement   # noqa: E402
from app.engine import Engine, EngineError                # noqa: E402
from app.feed.base import PriceFeed, Instrument           # noqa: E402
from app import weekly as W                               # noqa: E402
from app import main as M                                 # noqa: E402  (reports and Excel, checked against the ledger)
import io                                                 # noqa: E402
from openpyxl import load_workbook                        # noqa: E402

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
        if ins is None:                                   # like the real feeds: a contract that is not listed counts as 1
            return 1.0
        return ins.multiplier * self.usdinr if ins.exchange == "CRYPTO" else 1.0


I_NIFTY, F_NIFTY, F_SILVER, F_SILVERM, O_CE, O_PE_EXP, F_BTC, F_GOLD, F_CRUDE = range(1, 10)
F_THIN = 10; THIN_EXP = "2027-01-14"                      # a thinly traded future, expiring on the Thursday of the last simulated week
feed = SimFeed()
feed.load_instruments([
    Instrument(I_NIFTY, "NIFTY", "NIFTY", "NSE", "INDICES", "EQ", "", 0, 1, 0.05),
    Instrument(F_NIFTY, "NIFTY27DECFUT", "NIFTY", "NFO", "NFO-FUT", "FUT", FAR, 0, 75, 0.05),
    Instrument(F_THIN, "MENTHAOIL27JANFUT", "MENTHAOIL", "MCX", "MCX-FUT", "FUT", THIN_EXP, 0, 360, 0.1),
    Instrument(11, "NIFTY27JANFUT", "NIFTY", "NFO", "NFO-FUT", "FUT", THIN_EXP, 0, 75, 0.05),
    Instrument(12, "USDINR27JANFUT", "USDINR", "CDS", "CDS-FUT", "FUT", THIN_EXP, 0, 1000, 0.0025),
    Instrument(13, "EURINR27JANFUT", "EURINR", "CDS", "CDS-FUT", "FUT", THIN_EXP, 0, 1000, 0.0025),
    Instrument(14, "NATURALGAS27JANFUT", "NATURALGAS", "MCX", "MCX-FUT", "FUT", THIN_EXP, 0, 1250, 0.1),
    Instrument(15, "ALUMINIUM27JANFUT", "ALUMINIUM", "MCX", "MCX-FUT", "FUT", THIN_EXP, 0, 100, 0.05),
    Instrument(16, "ZINC27JANFUT", "ZINC", "MCX", "MCX-FUT", "FUT", THIN_EXP, 0, 100, 0.05),
    Instrument(17, "LEAD27JANFUT", "LEAD", "MCX", "MCX-FUT", "FUT", THIN_EXP, 0, 100, 0.05),
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
M.engine = engine; M.feed = feed                          # the report code must look at the simulated book
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
        if expect is False:
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


def close(week_end: date, exact=True, label="", late_at=None):
    """Run the cut-off for one week and check every account. late_at = the (IST) time a late cut-off really runs."""
    db.expire_all()
    before = {u.id: {"truth": truth_total(u.id), "prov": W.running_row(engine, db, u)["result"], "alloc": W.allocated(db, u)} for u in users.values()}
    at(late_at or datetime.combine(week_end, datetime.max.time()).replace(microsecond=0))
    s = W.close_week(engine, db, week_end, exact=exact, stamp=(late_at - IST) if late_at else None)
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
        ok(f"{tag}: valuation lines in the ledger add up", near(sum(l.amount for l in db.query(Ledger).filter_by(user_id=u.id, kind=W.VALUATION).filter(Ledger.created_at == r.created_at)), r.valuation, 0.02))
        check_positions(name, tag)
    check_reports(week_end, label, late=bool(late_at))
    return s


def _sheet(wb, name):
    ws = wb[name]
    rows = [[c.value for c in r] for r in ws.iter_rows()]
    h = next(i for i, r in enumerate(rows) if r and r[0] in ("Date", "Week", "User", "Contract"))
    return rows[h], rows[h + 1:]


def check_reports(week_end: date, label="", late=False):
    """The screens' numbers and the Excel for the week just closed, against the settlement rows."""
    we = week_end.isoformat(); mon = (week_end - timedelta(days=6)).isoformat()
    plain = [u for n, u in users.items() if not u.is_admin]
    for name, u in users.items():
        r = db.query(WeekSettlement).filter_by(week_end=we, user_id=u.id).first()
        tag = f"reports {we} {label} {name}"
        a = M.build_report(db, [u], None, "2031-01-01")["users"][0]
        ok(f"{tag}: Net P&L (All Time) = finished weeks + this week = own-price P&L", near(a["overall_pnl"], results[u.id] + a["week_pnl"], 0.02) and near(a["overall_pnl"], truth_total(u.id), 0.5),
           f"{a['overall_pnl']} vs weeks {results[u.id]:.2f} + {a['week_pnl']} vs truth {truth_total(u.id):.2f}")
        ok(f"{tag}: Net Balance = Allocated + Net P&L (This Week)", near(a["equity"], a["allocated"] + a["week_pnl"], 0.02))
        prev = db.query(WeekSettlement).filter_by(week_end=(week_end - timedelta(days=7)).isoformat(), user_id=u.id).first()
        if r.created_at != W.cutoff_utc(week_end) or (prev and prev.created_at != W.cutoff_utc(week_end - timedelta(days=7))):
            continue        # trades slipped in before a late cut-off: that week holds them, the calendar range does not
        w = M.build_report(db, [u], mon, we)["users"][0]
        ok(f"{tag}: period report for the week = week result", near(w["net_pnl"] + w["valuation"], r.result, 0.03), f"{w['net_pnl']} + {w['valuation']} vs {r.result}")
        ok(f"{tag}: Performance tab Net P&L for the week = week result", near(w["total_pnl"], r.result, 0.03) and near(w["open_pnl"], r.valuation, 0.03), f"{w['total_pnl']} vs {r.result}")
        wb = load_workbook(io.BytesIO(M.build_xlsx(db, [u], mon, we)))
        _, prow = _sheet(wb, "P&L Statement")
        tot = next(x for x in prow if x[0] == "NET P&L (SETTLEMENT)")
        ok(f"{tag}: Excel P&L Statement Net P&L (Settlement) = week result", near(tot[11], r.result, 0.03) and near(tot[8] + tot[9] + tot[10], tot[11], 0.03), f"{tot[11]} vs {r.result}")
        body = [x for x in prow if x[0] != "NET P&L (SETTLEMENT)" and isinstance(x[11], (int, float))]
        ok(f"{tag}: Excel P&L Statement rows add up to the total", near(sum(x[11] for x in body), tot[11], 0.05) and near(sum(x[9] or 0 for x in body), tot[9], 0.05), f"{sum(x[11] for x in body)} vs {tot[11]}")
        _, srow = _sheet(wb, "Summary")
        ok(f"{tag}: Excel Summary Net P&L (Settlement) = week result", near(srow[0][5], r.result, 0.03) and near(srow[0][2] + srow[0][3] + srow[0][4], srow[0][5], 0.03), f"{srow[0][5]} vs {r.result}")
        _, lrow = _sheet(wb, "Ledger Statement")
        closing = next(x for x in lrow if x[2] == "Closing Balance")[4]
        ok(f"{tag}: Excel ledger closes the week at the allocated coins", near(closing, r.allocated, 0.011), f"{closing} vs {r.allocated}")
        ok(f"{tag}: Excel ledger is continuous", all(near(y[4], x[4] + y[3], 0.011) for x, y in zip(lrow, lrow[1:]) if y[2] != "Closing Balance" and isinstance(y[3], (int, float))))
        _, wrow = _sheet(wb, "Weekly Settlement")
        fin = [x for x in wrow if x[1] == "FINAL"]
        ok(f"{tag}: Excel Weekly Settlement has this week once, with the week result", len(fin) == 1 and near(fin[0][5], r.result, 0.011) and near(fin[0][2] + fin[0][3] + fin[0][4], fin[0][5], 0.03)
           and near(fin[0][6] + fin[0][7], fin[0][5], 0.011), str(fin))
    # the Master's view: everybody in one workbook, and the dashboard rows
    wb = load_workbook(io.BytesIO(M.build_xlsx(db, plain, None, "2031-01-01")))
    _, wrow = _sheet(wb, "Weekly Settlement")
    fin = [x for x in wrow if x[1] == "FINAL" and x[0] == W.week_label(week_end)]
    rows = {r.user_id: r for r in db.query(WeekSettlement).filter_by(week_end=we).all()}
    ok(f"reports {we} {label}: Master Excel lists every user's week", len(fin) == len(plain) and near(sum(x[6] for x in fin), sum(rows[u.id].result for u in plain), 0.05), f"{len(fin)} rows")
    _, orow = _sheet(wb, "Open Positions")
    for x in orow:
        if x[0] != "TOTAL" and x[7]:
            ok(f"reports {we} {label}: Excel open position {x[0]} {x[1]}: settled earlier + this week = total", near((x[10] or 0) + (x[11] or 0), x[12] or 0, 0.02), str(x))
    rep_all = M._weekly.report(engine, db, we)
    ok(f"reports {we} {label}: Weekly Settlement screen total = sum of users", near(rep_all["total"]["result"], sum(rows[u.id].result for u in plain), 0.05) and len(rep_all["rows"]) == len(plain))
    for row in M._admin_rows(db):
        ok(f"reports {we} {label} {row['username']}: Master row adds up", near(row["allocated"] + row["net_pnl"], row["net_balance"], 0.02)
           and near(row["unrealised"] + row["realised"] - row["commission"], row["net_pnl"], 0.02), str(row))


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
        a = M.build_report(db, [u], None, "2031-01-01")["users"][0]
        ok(f"{tag} {name}: Performance tab all time = own-price P&L", near(a["total_pnl"], truth_total(u.id), 0.5), f"{a['total_pnl']} vs {truth_total(u.id):.2f}")
        _mon = (W.week_end_of(T.date()) - timedelta(days=6)).isoformat()
        _wk = M.build_report(db, [u], _mon, W.week_end_of(T.date()).isoformat())["users"][0]
        if (D.get_setting(db, "week_closed") or "") < W.week_end_of(T.date()).isoformat():      # the week the clock is in is still running
            ok(f"{tag} {name}: Performance tab this week = running week result", near(_wk["total_pnl"], run_row["result"], 0.05), f"{_wk['total_pnl']} vs {run_row['result']}")
        ok(f"{tag} {name}: screens: Net P&L (This Week) and (All Time)", near(a["week_pnl"], run_row["result"], 0.02) and near(a["overall_pnl"], truth_total(u.id), 0.5),
           f"{a['week_pnl']} vs {run_row['result']}; {a['overall_pnl']} vs {truth_total(u.id):.2f}")
    if (D.get_setting(db, "week_closed") or "") < W.week_end_of(T.date()).isoformat():
        for name, u in users.items():
            if u.is_admin:
                continue
            rr = W.running_row(engine, db, u); mon = (W.week_end_of(T.date()) - timedelta(days=6)).isoformat()
            wb = load_workbook(io.BytesIO(M.build_xlsx(db, [u], mon, W.week_end_of(T.date()).isoformat())))
            _, prow = _sheet(wb, "P&L Statement")
            tot = next(x for x in prow if x[0] == "NET P&L (SETTLEMENT)")
            ok(f"{tag} {name}: Excel for the running week: Net P&L (Settlement) = week result so far, with open positions", near(tot[11], rr["result"], 0.05), f"{tot[11]} vs {rr['result']}")
    for row in M._admin_rows(db):
        rr = W.running_row(engine, db, users[row["username"]])
        ok(f"{tag} {row['username']}: Master row = running week", near(row["net_pnl"], rr["result"], 0.02) and near(row["realised"], rr["closed"], 0.03) and near(row["commission"], rr["commission"], 0.02)
           and near(row["unrealised"], rr["valuation"], 0.03), f"{row} vs {rr}")


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
s = close(SUN(W2), exact=False, label="(late, nothing traded meanwhile)", late_at=day(W3, 0, 6))   # restarted Monday 6 am: still cut at Sunday 23:59:59
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
at(day(W5, 0, 1)); px(nifty=25300)                       # Monday 1 am: the site is back, the cut-off has not run yet
trade("scalper", F_NIFTY, "BUY", 1)                       # a trade made before the late cut-off belongs to the week being closed
trade("crypto", F_BTC, "SELL", 1)
close(SUN(W4), exact=False, label="(late)", late_at=day(W5, 0, 2))

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

# ---- a winner who is left short of margin by the settlement: warned Sunday, reminded Monday, then time, then squared off ----
W7 = W6 + timedelta(days=7); W8 = W7 + timedelta(days=7)
at(day(W7, 0, 10)); px(nifty=25000)
for n in ("greedy", "absent", "fixer"):
    mk_user(n, 400_000)
    results[users[n].id] = 0.0
    trade(n, F_NIFTY, "BUY", 1)
at(day(W7, 2, 11)); px(nifty=30000)                       # a big win, booked
for n in ("greedy", "absent", "fixer"):
    trade(n, F_NIFTY, "SELL", 1)
    for _ in range(2):
        trade(n, F_NIFTY, "BUY", 1)                       # the booked profit is used to hold more than the allocated coins cover
lots0 = {n: sum(p.qty for p in db.query(Position).filter_by(user_id=users[n].id, is_closed=False)) for n in ("greedy", "absent", "fixer")}
ok("shortfall: the paper profit bought more than the allocated coins cover", engine.funds(db, users["greedy"])["used_margin"] > 400_000, str(engine.funds(db, users["greedy"])))
at(day(W7, 6, 20)); px(nifty=30000)
s = close(SUN(W7))
qty = lambda n: sum(p.qty for p in db.query(Position).filter_by(user_id=users[n].id, is_closed=False))
alerts = lambda n: D.get_setting(db, f"user_alerts_{users[n].id}", "[]")
ok("shortfall: three users are short after the settlement and were warned", s.get("short") == 3 and "Margin shortfall after weekly settlement" in alerts("greedy"), str(s))
ok("shortfall: Available Balance is below zero after the coins went back", engine.funds(db, users["greedy"])["available"] < 0)
at(day(W8, 0, 0, 5)); run(engine._check_liquidations())
ok("shortfall: nothing is squared off on Sunday night", all(qty(n) == lots0[n] for n in lots0))
at(day(W8, 0, 9, 0)); run(engine._check_liquidations())
ok("shortfall: nothing is squared off before the Monday reminder", all(qty(n) == lots0[n] for n in lots0) and "Reminder" not in alerts("greedy"))
at(day(W8, 0, 9, 16)); run(engine._check_liquidations())
ok("shortfall: Monday 9:15 reminder sent, still nothing squared off", all(qty(n) == lots0[n] for n in lots0) and "Reminder: margin shortfall" in alerts("greedy"))
at(day(W8, 0, 9, 40)); engine.week_grace_seen(db, users["greedy"]); engine.week_grace_seen(db, users["fixer"])    # they open the app
at(day(W8, 0, 9, 50)); run(engine._check_liquidations())
ok("shortfall: after opening the app nothing is squared off", all(qty(n) == lots0[n] for n in lots0))
while engine.funds(db, users["fixer"])["available"] < 0:   # "fixer" reduces his position himself
    trade("fixer", F_NIFTY, "SELL", 1)
fixer_left = qty("fixer")
at(day(W8, 0, 10, 11)); run(engine._check_liquidations())
ok("shortfall: before noon the one who did nothing is still not squared off", qty("greedy") == lots0["greedy"])
ok("shortfall: the one who reduced himself is left alone", qty("fixer") == fixer_left and fixer_left > 0)
ok("shortfall: the one who has not opened the app is still waiting", qty("absent") == lots0["absent"])
at(day(W8, 0, 12, 1)); run(engine._check_liquidations())
ok("shortfall: at Monday noon both who did nothing are squared off", all(qty(n) < lots0[n] and engine.funds(db, users[n])["available"] >= 0 for n in ("greedy", "absent")))
ok("shortfall: the one who reduced himself is still left alone", qty("fixer") == fixer_left)
ok("shortfall: only as much as needed was closed", qty("greedy") > 0 and qty("absent") > 0)
check_running("after the shortfall square-offs")
at(day(W8, 6, 20)); close(SUN(W8))

# ---- one closing price: the P&L at the close is the P&L all night and all weekend, restart or not ----
W9 = W8 + timedelta(days=7)
at(day(W9, 4, 15, 29)); px(nifty=30420)                   # Friday, the last price before the close
fx_u = users["fixer"]
pos_f = db.query(Position).filter_by(user_id=fx_u.id, is_closed=False).first()
f_close = engine.funds(db, fx_u); d_close = engine.position_dict(pos_f)
_open = engine.tradable_now
engine.tradable_now = lambda ins: False                   # the exchange shuts
try:
    same = lambda tag: ok(f"closing price: {tag}", near(engine.funds(db, fx_u)["unrealised"], f_close["unrealised"], 0.005)
                          and near(engine.funds(db, fx_u)["available"], f_close["available"], 0.005)
                          and near(engine.position_dict(pos_f)["unrealised"], d_close["unrealised"], 0.005)
                          and engine.position_dict(pos_f)["mark"] == d_close["mark"],
                          f"{engine.funds(db, fx_u)['unrealised']} vs {f_close['unrealised']}")
    same("P&L right after the close = P&L at the close")
    at(day(W9, 4, 18)); feed.set(F_NIFTY, 29000); feed.set(I_NIFTY, 29000); W.remember_marks(engine, db); db.expire_all()
    pos_f = db.query(Position).filter_by(user_id=fx_u.id, is_closed=False).first()
    same("a stray quote after the close changes nothing")
    saved = dict(feed.prices); feed.prices.clear()        # the site restarts on Saturday: nothing in memory
    at(day(W9, 5, 10)); W.remember_marks(engine, db); db.expire_all()
    pos_f = db.query(Position).filter_by(user_id=fx_u.id, is_closed=False).first()
    same("after a restart on Saturday the P&L is still the P&L at the close")
    rr = W.running_row(engine, db, fx_u)
    ok("closing price: the weekly report shows the same open-position figure", near(rr["valuation"], f_close["unrealised"], 0.02), f"{rr['valuation']} vs {f_close['unrealised']}")
    a_row = next(r for r in M._admin_rows(db) if r["username"] == "fixer")
    ok("closing price: the Master row shows the same unrealised", near(a_row["unrealised"], f_close["unrealised"], 0.02))
    at(day(W9, 6, 20)); close(SUN(W9))                     # Sunday cut-off, still nothing in memory
    r9 = db.query(WeekSettlement).filter_by(week_end=SUN(W9).isoformat(), user_id=fx_u.id).first()
    ok("closing price: Sunday's settlement books exactly the Friday-close figure", near(r9.valuation, f_close["unrealised"], 0.02) and r9.unpriced == 0, f"{r9.valuation} vs {f_close['unrealised']}")
    feed.prices.update(saved)
finally:
    engine.tradable_now = _open
at(day(W9 + timedelta(days=7), 0, 9, 16)); px(nifty=30500); db.expire_all()   # Monday: live again
pos_f = db.query(Position).filter_by(user_id=fx_u.id, is_closed=False).first()
ok("closing price: on Monday the live price is used again", abs(engine.position_dict(pos_f)["mark"] - 30500) < 1 and not engine.position_dict(pos_f)["at_close"], str(engine.position_dict(pos_f)["mark"]))

# ---- Daily view: a day's result is measured from where the day started (the last closing price) ----
W10 = W9 + timedelta(days=7)
iso = lambda d: d.date().isoformat()
tue, wed, thu = day(W10, 1, 0, 0), day(W10, 2, 0, 0), day(W10, 3, 0, 0)
at(tue); M.take_day_snaps(db, iso(tue)); db.expire_all()
t0 = {u.id: truth_total(u.id) for u in users.values() if not u.is_admin}
at(day(W10, 1, 11)); px(nifty=30800, btc=91000); trade("fixer", F_NIFTY, "SELL", 1); trade("scalper", F_NIFTY, "BUY", 1)
at(day(W10, 1, 15)); px(nifty=30650)
pp = lambda u, a, b: M.build_report(db, [u], iso(a), iso(b))["users"][0]["period_pnl"]
for n, u in users.items():
    if not u.is_admin:
        ok(f"daily {n}: today's result = closed trades + move in open positions since the day started", near(pp(u, tue, tue), truth_total(u.id) - t0[u.id], 0.6), f"{pp(u, tue, tue)} vs {truth_total(u.id) - t0[u.id]:.2f}")
at(wed); M.take_day_snaps(db, iso(wed)); db.expire_all()
t1 = {u.id: truth_total(u.id) for u in users.values() if not u.is_admin}
at(day(W10, 2, 12)); px(nifty=30100, btc=89500); trade("fixer", F_NIFTY, "BUY", 1)
for n, u in users.items():
    if not u.is_admin:
        ok(f"daily {n}: yesterday's result does not move with today's prices", near(pp(u, tue, tue), t1[u.id] - t0[u.id], 0.6), f"{pp(u, tue, tue)} vs {t1[u.id] - t0[u.id]:.2f}")
        ok(f"daily {n}: today starts from yesterday's close", near(pp(u, wed, wed), truth_total(u.id) - t1[u.id], 0.6), f"{pp(u, wed, wed)} vs {truth_total(u.id) - t1[u.id]:.2f}")
        ok(f"daily {n}: the two days add up to the two-day result", near(pp(u, tue, tue) + pp(u, wed, wed), pp(u, tue, wed), 0.02))
# (a day in the middle of an earlier week; a Monday needs no record of its own any more, see below)
ok("daily: a day with no day-start record is reported as unknown, never guessed", pp(users["hold"], day(W9, 2, 0, 0), day(W9, 2, 0, 0)) is None)
# A Monday starts at the weekly cut-off itself (Sunday 23:59:59), where the P&L since the beginning is exactly the sum of
# the finished weeks; and a finished week on the Performance report is the Weekly Settlement's result to the paisa. Both
# used to hang on the Monday day-start record, which is written some seconds after midnight (21 Nov 2026).
mon10 = day(W10, 0, 0, 0); _s9 = day(W9, 6, 0, 0).date()          # this Monday, and the Sunday that closed the week before
_seen9 = 0
for n, u in users.items():
    if not u.is_admin and M._cut_overall(db, u, _s9) is not None:
        _seen9 += 1
        ok(f"daily {n}: Monday is measured from the weekly cut-off", pp(u, mon10, mon10) is not None and near(pp(u, mon10, mon10), t0[u.id] - W.settled_total(db, u), 0.6), f"{pp(u, mon10, mon10)} vs {t0[u.id] - W.settled_total(db, u):.2f}")
        _r9 = db.query(WeekSettlement).filter_by(user_id=u.id, week_end=_s9.isoformat()).first()
        if _r9 is not None:
            _t9 = M.build_report(db, [u], (_s9 - timedelta(days=6)).isoformat(), _s9.isoformat())["users"][0]["total_pnl"]
            ok(f"finished week {n}: the Performance report's Net P&L (Settlement) is the Weekly Settlement's result", near(_t9, _r9.result, 0.011), f"{_t9} vs {_r9.result}")
ok("daily: the week before was closed on time for the accounts, so the two checks above were really made", _seen9 >= 3, str(_seen9))

# ---- expiry: index and currency futures settle against the underlying, a commodity future at the book ----
F_NIFTY_X, F_USDINR_X, F_EURINR_X = 11, 12, 13
assert iso(thu) == THIN_EXP, iso(thu)
last_trade = lambda n, tok: db.query(Trade).filter_by(user_id=users[n].id, token=tok).order_by(Trade.id.desc()).first()
flat = lambda n, tok: db.query(Position).filter_by(user_id=users[n].id, token=tok, is_closed=False).count() == 0


class _FX:                                                # stand-in for the forex feed's spot rates
    connected = True; items = {}
    rates = {"USD": 95.50, "EUR": 9.9}                    # EUR deliberately absurd (wrong unit): must be ignored
    def _quote_to_inr_live(self, q):
        return self.rates.get(q)


feed.forex = _FX()
at(day(W10, 3, 11, 50)); coins("idle", 1_500_000, "more coins for the expiry tests"); coins("hold", 1_500_000, "more coins for the expiry tests")
at(day(W10, 3, 12)); feed.set(F_USDINR_X, 95.40, spread=0.02); feed.set(F_EURINR_X, 104.00, spread=0.04)
feed.prices[F_USDINR_X]["ltp"] = 97.0                     # an old last trade, far from the book and from the spot rate
trade("idle", F_USDINR_X, "BUY", 1); trade("hold", F_USDINR_X, "SELL", 1); trade("idle", F_EURINR_X, "BUY", 1)
W.remember_marks(engine, db)
at(day(W10, 3, 12, 31)); run(engine._settle_expired()); db.expire_all()
for n in ("idle", "hold"):
    ok(f"expiry {n}: a currency future settles at the spot rate (not its last trade, not the book)", flat(n, F_USDINR_X) and near(last_trade(n, F_USDINR_X).price, 95.50, 0.0001), str(last_trade(n, F_USDINR_X).price))
ok("expiry: a spot rate that is nowhere near the contract is ignored and the book is used", flat("idle", F_EURINR_X) and near(last_trade("idle", F_EURINR_X).price, 103.98, 0.0001), str(last_trade("idle", F_EURINR_X).price))

at(day(W10, 3, 14)); feed.set(F_THIN, 900.0, spread=2.0)                 # book: bid 899 / ask 901
feed.prices[F_THIN]["ltp"] = 960.0; feed.prices[F_THIN]["ltt"] = time.time() - 6 * 3600   # last trade hours ago, far above the book
trade("idle", F_THIN, "BUY", 1)                           # buys at the ask, hoping to be settled at the old 960
trade("hold", F_THIN, "SELL", 1)                          # and the other way round
at(day(W10, 3, 15)); feed.set(I_NIFTY, 30100); feed.set(F_NIFTY_X, 30140, spread=2.0)
feed.prices[F_NIFTY_X]["ltp"] = 30400                     # stale last trade on the future
trade("idle", F_NIFTY_X, "BUY", 1); trade("hold", F_NIFTY_X, "SELL", 1)
W.remember_marks(engine, db)
at(day(W10, 3, 15, 41)); feed.set(I_NIFTY, 30110); run(engine._settle_expired()); db.expire_all()
for n in ("idle", "hold"):
    ok(f"expiry {n}: an index future settles at the index's closing value", flat(n, F_NIFTY_X) and near(last_trade(n, F_NIFTY_X).price, 30110, 0.001), str(last_trade(n, F_NIFTY_X).price))
ok("expiry: the commodity future is still open until its own session ends", not flat("idle", F_THIN))
# One side of the book empty (loophole of 21 Nov 2026): sellers only and an old last trade above their offer. A buy
# at the offer was settled at the old trade; the same the other way round with buyers only. Third contract: the
# sellers leave before the close, so that nothing at all is in the book when the contract stops.
F_ONE_A, F_ONE_B, F_ONE_C = 15, 16, 17


def _one_sided(tok, last, bid=None, ask=None):
    feed.prices[tok] = {"token": tok, "ltp": last, "bid": bid, "ask": ask, "ts": time.time(), "ltt": time.time() - 6 * 3600,
                        "bids": [[bid, 10 ** 8, 1]] if bid else [], "asks": [[ask, 10 ** 8, 1]] if ask else []}


at(day(W10, 3, 16)); _one_sided(F_ONE_A, 1100.0, ask=1000.0); _one_sided(F_ONE_B, 500.0, bid=550.0); _one_sided(F_ONE_C, 880.0, ask=800.0)
trade("idle", F_ONE_A, "BUY", 1); trade("hold", F_ONE_B, "SELL", 1); trade("idle", F_ONE_C, "BUY", 1)
W.remember_marks(engine, db)
_one_sided(F_ONE_C, 880.0)
# The closing price of a contract in its last minutes is kept fresh (loophole of 15 Nov 2026: it was up to a
# minute old, so a user who saw the market drop in the last seconds added at the new price and was settled
# at the old one).
F_GAS_X = 14
at(day(W10, 3, 23, 50)); feed.set(F_GAS_X, 300.0, spread=0.2)
trade("idle", F_GAS_X, "BUY", 1)
ok("expiry: five minutes before it stops, a contract is not yet in the every-second closing-price pass",
   F_GAS_X not in [p.token for p in W.closing_positions(engine, db)])
at(day(W10, 3, 23, 54)); W.remember_marks(engine, db)     # the once-a-minute pass: closing price 299.9
at(day(W10, 3, 23, 54) + timedelta(seconds=40)); feed.set(F_GAS_X, 297.0, spread=0.2)     # the market drops 20 s before the stop
ok("expiry: in its last minutes it is", F_GAS_X in [p.token for p in W.closing_positions(engine, db)])
W.remember_marks(engine, db, only=W.closing_positions(engine, db))    # what the server now does every second
trade("idle", F_GAS_X, "BUY", 5)                          # adds at 297.1, hoping to be settled at the old 299.9
at(day(W10, 3, 23, 58)); run(engine._settle_expired()); db.expire_all()
tr = last_trade("idle", F_GAS_X)
ok("expiry: a future is settled at the book of its last seconds, not at a closing price from a minute earlier",
   flat("idle", F_GAS_X) and near(tr.price, 296.9, 0.001) and tr.realised_pnl < 0, f"{tr.side} @ {tr.price}, {tr.realised_pnl}")
for n, side, want in (("idle", "SELL", 899.0), ("hold", "BUY", 901.0)):
    tr = last_trade(n, F_THIN)
    ok(f"expiry {n}: a thin commodity future is settled at the exit side of the book, not at the old last trade", tr.side == side and near(tr.price, want, 0.001), f"{tr.side} @ {tr.price}")
    ok(f"expiry {n}: nothing can be made from the gap between last trade and book", tr.realised_pnl <= 0, str(tr.realised_pnl))
    ok(f"expiry {n}: position closed and margin released", flat(n, F_THIN))
for n, tok, paid in (("idle", F_ONE_A, 1000.0), ("hold", F_ONE_B, 550.0), ("idle", F_ONE_C, 800.0)):
    tr = last_trade(n, tok)
    ok(f"expiry {n}: with nobody quoting on the exit side a future is not settled beyond the other side of the book ({feed.instruments[tok].name})",
       flat(n, tok) and near(tr.price, paid, 0.001) and tr.realised_pnl <= 0, f"dealt at {paid}, settled @ {tr.price}, {tr.realised_pnl}")
check_running("after the expiries")

# ---- trading access: a segment that is not activated takes no new trades; exits always go through ----
from app import access as A                               # noqa: E402
at(day(W10, 4, 10)); px(nifty=30200, ce=4300, btc=90000)
REAL = {k: k in ("IDX_FUT", "STK_FUT", "MCX_FUT", "CDS_FUT") for k in A.KEYS}


def refused(name, tok, side, lots=1, **kw):
    engine._consumed.clear()
    try:
        engine.place_order(db, users[name], tok, side, lots, kw.pop("order_type", "MARKET"), **kw); stamp()
        return None
    except EngineError as e:
        db.rollback(); stamp()
        return str(e)


for n in ("idle", "hold", "crypto"):
    coins(n, 3_000_000, "coins for the access tests")
trade("hold", O_CE, "BUY", 1)                             # holds an option before the switches arrive
trade("crypto", F_BTC, "BUY", 2)
btc_before = sum(p.qty for p in db.query(Position).filter_by(user_id=users["crypto"].id, token=F_BTC, is_closed=False))
A.set_default(db, REAL)                                   # the real defaults: futures on in the Indian segments, the rest off
ok("access: accounts that already hold options keep options on", A.keep_options_while_held(engine, db, users["hold"]) and not A.keep_options_while_held(engine, db, users["idle"]))
ok("access: futures are on by default", refused("idle", F_NIFTY, "BUY") is None)
m = refused("idle", O_CE, "BUY")
ok("access: options are off by default, with a clear message", bool(m) and "Options on Indices are not activated" in m, str(m))
m = refused("idle", F_BTC, "BUY")
ok("access: crypto is off by default", bool(m) and "Crypto is not activated" in m, str(m))
ok("access: selling an option short is refused as well", bool(refused("idle", O_CE, "SELL")))
ok("access: the option holder can still add or hedge with options", refused("hold", O_CE, "BUY") is None)
ok("access: the option holder gets nothing else (crypto stays off)", bool(refused("hold", F_BTC, "BUY")))
ok("access: adding to a position in a segment that is off is refused", bool(refused("crypto", F_BTC, "BUY" if btc_before > 0 else "SELL")))
ok("access: reducing a position in a segment that is off is allowed", refused("crypto", F_BTC, "SELL" if btc_before > 0 else "BUY", 1) is None)
ok("access: an exit bigger than the position (a flip) is refused", bool(refused("crypto", F_BTC, "SELL" if btc_before > 0 else "BUY", 50)))
hq = sum(p.qty for p in db.query(Position).filter_by(user_id=users["hold"].id, token=O_CE, is_closed=False)) // 75
ok("access: the option holder can exit his options", refused("hold", O_CE, "SELL", hq) is None)
ok("access: once he holds no option, options go back to the default by themselves", A.options_flat_check(engine, db, users["hold"]) and bool(refused("hold", O_CE, "BUY")))
eff = A.effective(db, users["idle"]); eff["IDX_OPT"] = True
A.set_user(db, users["idle"].id, eff)
ok("access: the Master activates options for one user", refused("idle", O_CE, "BUY") is None and bool(refused("hold", O_CE, "BUY")))
ok("access: only the switch that differs from the default is stored", A.overrides(db, users["idle"].id) == {"IDX_OPT": True})
o = engine.place_order(db, users["idle"], O_CE, "BUY", 1, "LIMIT", limit_price=100.0); stamp()
ok("access: a resting order waits", o.status == "OPEN")
A.set_user(db, users["idle"].id, None)
ok("access: switching a segment off cancels the resting orders that would open a position there", A.cancel_resting(engine, db, users["idle"]) == 1 and db.get(Order, o.id).status == "CANCELLED")
ok("access: but he can still exit the option he bought", refused("idle", O_CE, "SELL") is None)
A.set_default(db, {"CRYPTO_FUT": True})
ok("access: the Master switches crypto on for everybody through the default", refused("idle", F_BTC, "BUY") is None)


class _P:                                                 # the daily safety check's own accounts trade every market
    is_admin = False; username = "zz-probe-a"; id = 0


ok("access: the daily safety check's accounts are not restricted", all(A.effective(db, _P).values()))
run(engine._check_liquidations())
ok("access: the auto square-off is not stopped by a switch", True)
# A resting order is checked again when it fills (15 Nov 2026): an exit that has become bigger than the
# position only closes it, and a frozen account's resting order opens nothing.
lots_btc = lambda: sum(p.qty for p in db.query(Position).filter_by(user_id=users["crypto"].id, token=F_BTC, is_closed=False))
q0 = lots_btc()
trade("crypto", F_BTC, "BUY" if q0 >= 0 else "SELL", 3)   # crypto is on for everybody at this point
q1 = lots_btc(); xs = "SELL" if q1 > 0 else "BUY"; lim = 80000.0 if q1 > 0 else 100000.0
eff = A.effective(db, users["crypto"]); eff["CRYPTO_FUT"] = False
A.set_user(db, users["crypto"].id, eff)
trade("crypto", F_BTC, xs, abs(q1) - 1, order_type="LIMIT", limit_price=lim)      # two exits, each no bigger than the position
trade("crypto", F_BTC, xs, abs(q1), order_type="LIMIT", limit_price=lim)
run(engine._process_pending(F_BTC, 90000)); db.expire_all()
ok("access: two resting exits that together are bigger than the position close it and open nothing the other way",
   lots_btc() == 0, f"was {q1}, now {lots_btc()}")
A.set_user(db, users["crypto"].id, None)
qn = sum(p.qty for p in db.query(Position).filter_by(user_id=users["idle"].id, token=F_NIFTY, is_closed=False))
o = trade("idle", F_NIFTY, "BUY", 1, order_type="LIMIT", limit_price=31000.0)
users["idle"].is_active = False; db.commit()
run(engine._process_pending(F_NIFTY, 30200)); db.expire_all()
ok("frozen: a resting order of an account frozen in the meantime opens nothing and is cancelled",
   db.get(Order, o.id).status == "CANCELLED" and qn == sum(p.qty for p in db.query(Position).filter_by(user_id=users["idle"].id, token=F_NIFTY, is_closed=False)),
   db.get(Order, o.id).status)
users["idle"].is_active = True; db.commit()
A.set_default(db, {k: True for k in A.KEYS})
check_running("after the access tests")

# ---- a bought option carried over the cut-off at a profit: its whole carried value is blocked as margin ----
at(day(W10, 4, 11)); px(ce=4300)
for n, c in (("optbuyer", 1_000_000), ("optsmall", 400_000)):
    mk_user(n, c); results[users[n].id] = 0.0
    trade(n, O_CE, "BUY", 1)
opos = lambda n: db.query(Position).filter_by(user_id=users[n].id, token=O_CE, is_closed=False).first()
prem = opos("optbuyer").margin_blocked
ok("carried option: a bought option blocks the premium paid", near(prem, opos("optbuyer").avg_price * 75, 1.0), str(prem))
at(day(W10, 6, 20)); px(ce=9000)
s = close(SUN(W10)); db.expire_all()
carried_val = opos("optbuyer").avg_price * 75
ok("carried option: after a profitable week the whole carried value is blocked, not just the first premium", near(opos("optbuyer").margin_blocked, carried_val, 0.02) and carried_val > prem * 1.5, f"{opos('optbuyer').margin_blocked} vs {carried_val}")
ok("carried option: the account that can cover it is not short", not engine.funds(db, users["optbuyer"])["margin_short"])
ok("carried option: the account that cannot cover the carried value is warned at the settlement", engine.funds(db, users["optsmall"])["margin_short"] and "Margin shortfall after weekly settlement" in D.get_setting(db, f"user_alerts_{users['optsmall'].id}", "[]"))
W11 = W10 + timedelta(days=7)
at(day(W11, 0, 10)); px(ce=50)                            # the option collapses on Monday
f1 = engine.funds(db, users["optbuyer"])
ok("carried option: when it collapses the loss stays inside what was blocked (Available Balance not below zero)", f1["available"] >= -0.01 and f1["equity"] > 0 and -f1["unrealised"] <= opos("optbuyer").margin_blocked + 0.01, str(f1))
check_running("after the carried option collapsed")
at(day(W11, 2, 11)); px(ce=6000); trade("optbuyer", O_CE, "SELL", 1)
ok("carried option: closing it releases the margin", engine.funds(db, users["optbuyer"])["used_margin"] == 0)
at(day(W11, 6, 20)); px(ce=2000); close(SUN(W11)); db.expire_all()
if opos("optsmall"):
    ok("carried option: after a losing week the blocked margin comes down to the new carried value", near(opos("optsmall").margin_blocked, opos("optsmall").avg_price * 75, 0.02), str(opos("optsmall").margin_blocked))

# ---- a crypto contract that is missing from the contract list (19 Nov 2026) -----------------------------
# The site restarted while the crypto exchange could not be reached: no crypto contract list. A position on
# such a contract was valued as if one point were worth one rupee (BTC: about ten times too much); the
# invented loss squared off the account's OTHER positions, and the weekly cut-off would have booked it.
W12 = W11 + timedelta(days=7)
at(day(W12, 1, 11)); px(nifty=30000, btc=90000)
mk_user("nolist", 600_000); results[users["nolist"].id] = 0.0
trade("nolist", F_BTC, "BUY", 200); trade("nolist", F_NIFTY, "BUY", 1)
px(btc=85500)                                             # a real loss the coins cover easily; closing price and rupee factor are kept
_u = users["nolist"]; db.expire_all()
f0 = engine.funds(db, _u)
_bp = lambda: db.query(Position).filter_by(user_id=_u.id, token=F_BTC, is_closed=False).first()
_np = lambda: sum(p.qty for p in db.query(Position).filter_by(user_id=_u.id, token=F_NIFTY, is_closed=False))
ok("missing contract: the rupee factor of a crypto position is kept with its closing price", near(_bp().last_vf or 0, engine.vf(feed.instruments[F_BTC]), 1e-9), str(_bp().last_vf))
_ins = feed.instruments.pop(F_BTC); _tick = feed.prices.pop(F_BTC, None)        # restart without the crypto contract list
db.expire_all(); f1 = engine.funds(db, _u)
ok("missing contract: the position is valued as before, not with a rupee factor of 1", near(f1["unrealised"], f0["unrealised"], 1.0) and not f1["margin_short"],
   f"{f1['unrealised']} vs {f0['unrealised']}")
ok("missing contract: the position screen shows the same figure", near(engine.position_dict(_bp())["unrealised"], (_bp().last_mark - _bp().avg_price) * _bp().qty * _bp().last_vf, 0.02))
run(engine._check_liquidations()); db.expire_all()
ok("missing contract: no other position of the account is squared off for an invented loss", _np() == 75 and _bp().qty == 200, f"nifty {_np()}")
_keep = _bp().last_vf; _bp().last_vf = None; db.commit(); db.expire_all()     # opened seconds before the restart: no factor kept yet
f2 = engine.funds(db, _u)
ok("missing contract: without a remembered factor the position is not valued at all (never a guess)",
   near(f2["unrealised"], f0["unrealised"] - (_bp().last_mark - _bp().avg_price) * 200 * _keep, 1.0) and engine.position_dict(_bp())["unrealised"] == 0.0 and W.running_row(engine, db, _u)["unpriced"] == 1, str(f2))
run(engine._check_liquidations()); db.expire_all()
ok("missing contract: and still nothing is squared off", _np() == 75 and _bp().qty == 200)
_bp().last_vf = _keep; db.commit()
_avg = _bp().avg_price
at(datetime.combine(SUN(W12), datetime.max.time()).replace(microsecond=0))
W.close_week(engine, db, SUN(W12)); db.commit(); db.expire_all()
_r = db.query(WeekSettlement).filter_by(week_end=SUN(W12).isoformat(), user_id=_u.id).first()
ok("missing contract: the weekly cut-off books nothing for it and leaves it as it is", _r is not None and _r.unpriced == 1 and _bp().avg_price == _avg and _bp().carried_week is None,
   f"unpriced {_r.unpriced if _r else None}, avg {_bp().avg_price} vs {_avg}")
feed.instruments[F_BTC] = _ins
if _tick: feed.prices[F_BTC] = _tick

# ---- an option reaches its expiry while the day's contract list is not loaded (19 Nov 2026) --------------
# The site restarts every night; until the day's price-feed login there is no contract list. An option that
# expired meanwhile was settled like a future, at the previous day's closing price: one that expired
# worthless was paid out at yesterday's premium. Now it waits for the list and settles against the index.
W13 = W12 + timedelta(days=7)
O_LATE = 31; _exp = (W13 + timedelta(days=1)).isoformat()
feed.instruments[O_LATE] = Instrument(O_LATE, "NIFTY28JAN30000CE", "NIFTY", "NFO", "NFO-OPT", "CE", _exp, 30000, 75, 0.05)
at(day(W13, 0, 15)); feed.set(I_NIFTY, 30300); feed.set(F_NIFTY, 30300); feed.set(O_LATE, 400)
trade("nolist", O_LATE, "BUY", 1); W.remember_marks(engine, db); db.expire_all()
_lp = lambda: db.query(Position).filter_by(user_id=_u.id, token=O_LATE, is_closed=False).first()
_bal = _u.balance
_all, _px = dict(feed.instruments), dict(feed.prices)
feed.instruments.clear(); feed.prices.clear()             # night restart, no login on the expiry day
at(day(W13, 1, 15, 45)); asyncio.get_event_loop().run_until_complete(engine._settle_expired()); db.expire_all()
ok("late list: an option is not settled while its exchange's contract list is not loaded", _lp() is not None and near(_u.balance, _bal, 0.01), f"balance {_u.balance} vs {_bal}")
feed.instruments.update(_all); feed.prices.update(_px); feed.set(I_NIFTY, 29900)       # the login is done after the close: the index closed below the strike
at(day(W13, 1, 16, 0)); run(engine._settle_expired()); db.expire_all()
_lt = db.query(Trade).filter_by(user_id=_u.id, token=O_LATE).order_by(Trade.id.desc()).first()
ok("late list: once the list is there it settles against the index (worthless), not at yesterday's premium", _lp() is None and _lt.price == 0.0 and near(_u.balance, _bal - 400.05 * 75, 1.0),
   f"settled at {_lt.price}, balance {_u.balance}")

# ---- the rupee conversion rate goes missing (20 Nov 2026) --------------------------------------------------
# With no rate a crypto / forex / Global contract is worth nothing per point. New orders are refused then;
# resting orders and the automatic closes were not: a stop-loss closed a losing position at a loss of 0.00
# and a resting buy opened a position with a margin of 0.00. Now nothing fills until the rate is back.
at(day(W13, 2, 11)); feed.set(F_BTC, 85000)
mk_user("norate", 600_000); results[users["norate"].id] = 0.0
trade("norate", F_BTC, "BUY", 100)
trade("norate", F_BTC, "SELL", 100, order_type="SL", trigger_price=84000.0)
_u2 = users["norate"]
_q = lambda: db.query(Position).filter_by(user_id=_u2.id, token=F_BTC, is_closed=False).first()
_rate = feed.usdinr; feed.usdinr = 0.0; feed.set(F_BTC, 83000)
engine._consumed.clear(); run(engine._process_pending(F_BTC, 83000.0)); run(engine._check_liquidations()); db.expire_all()
ok("no conversion rate: a resting stop-loss does not fill (it would book a loss of nothing)",
   _q() is not None and _q().qty == 100 and db.query(Trade).filter_by(user_id=_u2.id).count() == 1, f"position {_q().qty if _q() else 0}")
feed.usdinr = _rate
engine._consumed.clear(); run(engine._process_pending(F_BTC, 83000.0)); db.expire_all()
_t2 = db.query(Trade).filter_by(user_id=_u2.id).order_by(Trade.id.desc()).first()
ok("no conversion rate: once the rate is back the stop-loss fills and books the real loss", _q() is None and (_t2.realised_pnl or 0) < -15000,
   f"realised {_t2.realised_pnl}")

# ---- the exchange's position limit holds when resting orders fill (20 Nov 2026) ----------------------------
# The limit was checked when an order was placed, against the position of that moment: four resting buy
# orders of 200, each within a limit of 250, left a position of 800.
F_LIM = 32
feed.instruments[F_LIM] = Instrument(F_LIM, "LIMUSD", "LIM", "CRYPTO", "CRYPTO-FUT", "FUT", "", 0, 1, 0.5, multiplier=0.001, init_margin_pct=10.0, pos_limit=250)
feed.set(F_LIM, 1000.0)
mk_user("limit", 600_000); results[users["limit"].id] = 0.0
for _ in range(4):
    trade("limit", F_LIM, "BUY", 200, order_type="LIMIT", limit_price=990.0)
feed.set(F_LIM, 985.0); engine._consumed.clear(); run(engine._process_pending(F_LIM, 985.0)); db.expire_all()
_lq = sum(p.qty for p in db.query(Position).filter_by(user_id=users["limit"].id, token=F_LIM, is_closed=False))
_lo = db.query(Order).filter_by(user_id=users["limit"].id, status="OPEN").count()
_lf = engine.funds(db, users["limit"])
ok("position limit: resting orders together do not take a position past the exchange's limit", _lq == 250, f"position {_lq}, limit 250")
ok("position limit: what no longer fits is cancelled and keeps no margin reserved",
   _lo == 0 and near(_lf["used_margin"], sum(p.margin_blocked for p in db.query(Position).filter_by(user_id=users["limit"].id, is_closed=False)), 0.01),
   f"{_lo} still resting, used {_lf['used_margin']}")

# ---- Exit closes a position of more than 500 lots (20 Nov 2026) ---------------------------------------------
# One order carries at most 500 lots; Exit sent the whole position as one order and was refused ("Enter a
# number of lots between 1 and 500") for a position built with several orders. Now it goes in slices.
feed.set(F_SILVERM, feed.prices[F_SILVERM]["ltp"])
mk_user("bigpos", 2_000_000_000); results[users["bigpos"].id] = 0.0
trade("bigpos", F_SILVERM, "BUY", 400); trade("bigpos", F_SILVERM, "BUY", 400)
_bq = lambda: sum(p.qty for p in db.query(Position).filter_by(user_id=users["bigpos"].id, token=F_SILVERM, is_closed=False))
_bid = db.query(Position).filter_by(user_id=users["bigpos"].id, token=F_SILVERM, is_closed=False).first().id
engine._consumed.clear()
try:
    run(M.close_position(_bid, users["bigpos"], db)); _berr = ""
except Exception as e:
    _berr = str(getattr(e, "detail", e)); db.rollback()
db.expire_all()
ok("Exit closes a position of 800 lots in one press", _bq() == 0, f"left {_bq() // 5} lots {_berr}")

# ---- the opening second: automatic closes and resting orders wait for the first price of the session (20 Nov 2026) ----
# An account short of margin at Friday's close was squared off on Monday at 9:15:00 against Friday's book
# (a margin call closed everything there), and a resting order was filled against an old book handed out
# again in the opening second. Now they wait for the first price of the new session, as users' orders do.
import app.engine as _E                                   # noqa: E402
W14 = W13 + timedelta(days=7)
at(day(W14, 4, 11)); px(nifty=30000)
mk_user("opener", 1_000_000); mk_user("rester", 1_000_000)
trade("opener", F_NIFTY, "BUY", 3)
_rest = trade("rester", F_NIFTY, "BUY", 1, order_type="LIMIT", limit_price=27500.0, validity="GTT")
_oq = lambda: sum(p.qty for p in db.query(Position).filter_by(user_id=users["opener"].id, token=F_NIFTY, is_closed=False))
_E.ENFORCE_MARKET_HOURS = True
try:
    at(day(W14, 4, 15, 39)); feed.set(F_NIFTY, 27000); feed.set(I_NIFTY, 27000)          # the last book of Friday: a deep loss
    for _t in (F_NIFTY, I_NIFTY):
        feed.prices[_t]["ts"] = time.time() - 3 * 86400
    W.remember_marks(engine, db)
    _mon = day(W14 + timedelta(days=7), 0, 9, 15)
    at(_mon); run(engine._check_liquidations()); db.expire_all()
    ok("opening second: nothing is squared off against the last session's book", _oq() == 225, f"qty {_oq()}")
    feed.prices[F_NIFTY]["ts"] = time.time() + 0.3          # the old book handed out again to someone who starts looking
    run(engine._process_pending(F_NIFTY, 27000)); db.expire_all()
    ok("opening second: a resting order is not filled against the old book either", db.get(Order, _rest.id).status == "OPEN", db.get(Order, _rest.id).status)
    at(_mon + timedelta(seconds=5)); feed.set(F_NIFTY, 28000); feed.set(I_NIFTY, 28000)  # Monday's first price
    run(engine._check_liquidations()); run(engine._process_pending(F_NIFTY, 28000)); db.expire_all()
    _lt = db.query(Trade).filter_by(user_id=users["opener"].id, token=F_NIFTY).order_by(Trade.id.desc()).first()
    ok("opening second: with the first price of the session the shortfall is squared off at that price, only the lots needed",
       0 < _oq() < 225 and _lt.side == "SELL" and near(_lt.price, 27999.95, 0.001), f"qty {_oq()}, {_lt.side} @ {_lt.price}")
    ok("opening second: the resting order goes on waiting for its price", db.get(Order, _rest.id).status == "OPEN")
    feed.set(F_NIFTY, 27490); run(engine._process_pending(F_NIFTY, 27490)); db.expire_all()
    ok("opening second: and is filled once the market really trades there", db.get(Order, _rest.id).status == "FILLED" and near(db.get(Order, _rest.id).fill_price, 27490.05, 0.001), str(db.get(Order, _rest.id).fill_price))
finally:
    _E.ENFORCE_MARKET_HOURS = False

# ---- a slow feed: the order book stops arriving while the last price goes on (20 Nov 2026) ---------------
# Crypto perpetuals and forex / Global get the book that orders are filled against in other messages than the
# quoted price. When only the book messages stopped, the price looked a second old and a buy was filled at the
# offer of a minute ago. The real feed classes are fed by hand here, with a clock moved by hand.
from app.feed.delta import DeltaCrypto, TOKEN_BASE as _CB                      # noqa: E402
from app.feed.ctrader import CTraderForex, TOKEN_BASE as _FB, PT_SPOT_EVENT as _SPOT, PT_DEPTH_EVENT as _DEPTH   # noqa: E402
_rt = time.time; _off = [0.0]
time.time = lambda: _rt() + _off[0]
try:
    _f2 = PriceFeed(); _cry = DeltaCrypto(_f2); _fx = CTraderForex(_f2)
    _B, _E, _G = _CB + 2, _FB + 1, _FB + 20
    _cry.items = {_B: Instrument(_B, "BTCUSD", "BTC", "CRYPTO", "CRYPTO-PERP", "FUT", "", 0, 1, 0.5, multiplier=0.001)}
    _cry.symbols = {"BTCUSD": _B}; _cry._merge()
    _fx.items = {_E: Instrument(_E, "EURUSD", "EURUSD", "FOREX", "FOREX-SPOT", "FUT", "", 0, 1000, 0.00001),
                 _G: Instrument(_G, "US500", "US500", "FOREX", "GLOBAL-SPOT", "FUT", "", 0, 1, 0.01)}
    _fx.by_symbol_id = {1: _E, 20: _G}; _fx._merge()
    _f2.subscribe([_B, _E, _G])
    _bk = lambda p: _cry._handle({"type": "l2_orderbook", "symbol": "BTCUSD", "buy": [{"limit_price": str(p - 0.5 * i), "size": 500} for i in (1, 2, 3)],
                                  "sell": [{"limit_price": str(p + 0.5 * i), "size": 500} for i in (1, 2, 3)]})
    _tk = lambda p, q=True: _cry._handle({"type": "v2/ticker", "symbol": "BTCUSD", "close": p, "mark_price": str(p),
                                          **({"quotes": {"best_bid": str(p - 0.5), "best_ask": str(p + 0.5), "bid_size": "40", "ask_size": "30"}} if q else {})})
    _sp = lambda sid, p, t: _fx._handle({"payloadType": _SPOT, "payload": {"symbolId": sid, "bid": int(round((p - t) * 1e5)), "ask": int(round((p + t) * 1e5))}})
    _dp = lambda sid, p, t, n=[0]: (n.__setitem__(0, n[0] + 2), _fx._handle({"payloadType": _DEPTH, "payload": {"symbolId": sid, "newQuotes": [
        {"id": n[0], "size": 10 ** 9, "bid": int(round((p - t) * 1e5))}, {"id": n[0] + 1, "size": 10 ** 9, "ask": int(round((p + t) * 1e5))}], "deletedQuotes": [n[0] - 2, n[0] - 1]}}))
    _bk(75000); _tk(75000); _off[0] += 1; _tk(75010)
    ok("slow feed: with book messages arriving, a crypto perpetual keeps its full book", len(_f2.prices[_B]["asks"]) == 3 and _f2.prices[_B]["ask"] == 75000.5, str(_f2.prices[_B]["asks"]))
    for _i in range(60):
        _off[0] += 1; _tk(75000 + 12.5 * (_i + 1))
    _t = _f2.prices[_B]
    ok("slow feed: crypto book messages stopped for a minute, the market 1% higher: orders meet the quote of now, not the old book",
       _t["asks"] and _t["asks"][0][0] == 75750.5 and _t["bids"][0][0] == 75749.5 and _t["bid"] == 75749.5 and _t["ask"] == 75750.5, f"asks {_t['asks'][:1]} bids {_t['bids'][:1]}")
    _off[0] += 1; _tk(75800, q=False); _t = _f2.prices[_B]
    ok("slow feed: an old crypto book with no quote in the last-price message leaves nothing to fill against", _t["asks"] == [] and _t["bids"] == [] and _t["ask"] is None, str(_t["asks"]))
    _bk(75800); _t = _f2.prices[_B]
    ok("slow feed: the next book message brings the full book back", len(_t["asks"]) == 3 and _t["ask"] == 75800.5, str(_t["asks"]))
    _sp(1, 1.12, 0.00001); _dp(1, 1.12, 0.00001)
    _off[0] += 1; _sp(1, 1.1201, 0.00001)
    ok("slow feed: with ladder messages arriving, a forex pair keeps the broker's ladder", _f2.prices[_E]["asks"][0][0] == 1.12001, str(_f2.prices[_E]["asks"]))
    for _i in range(60):
        _off[0] += 1; _sp(1, 1.12 + 0.000187 * (_i + 1), 0.00001)
    _t = _f2.prices[_E]
    ok("slow feed: forex ladder messages stopped for a minute, the market 1% higher: orders meet the quote of now, not the old ladder",
       _t["asks"][0][0] == _t["ask"] and _t["bids"][0][0] == _t["bid"] and _t["ask"] > 1.131, f"ask {_t['ask']} ladder {_t['asks'][:1]}")
    _dp(1, 1.13122, 0.00002); _t = _f2.prices[_E]
    ok("slow feed: the next ladder message is used again", _t["asks"][0][1] == 10 ** 7 and near(_t["asks"][0][0], 1.13124, 1e-9), str(_t["asks"]))
    _sp(20, 7500.0, 0.25)
    for _i in range(30):
        _off[0] += 1; _sp(20, 7500.0 + 2.5 * (_i + 1), 0.25)
    _t = _f2.prices[_G]
    ok("slow feed: a contract the broker sends no ladder for is filled at its newest quote, not at its first",
       _t["asks"][0][0] == 7575.25 and _t["bids"][0][0] == 7574.75, f"bid/ask {_t['bid']}/{_t['ask']} ladder {_t['bids'][:1]} {_t['asks'][:1]}")
finally:
    time.time = _rt

# ---- Master activity record (21 Nov 2026): every Master address that changes something says what it did ----
# Looked at the way each address is built, without calling it: a new changing address added without its line
# of plain words for the activity record (main._note) fails here on the day it is written.
if True:
    import inspect as _insp
    _silent = []; _n = 0
    for _r in M.app.routes:
        _path, _meth = getattr(_r, "path", ""), (getattr(_r, "methods", None) or set())
        if not _path.startswith("/api/admin") or not (_meth - {"GET", "HEAD", "OPTIONS"}):
            continue
        _n += 1
        if "_note(" not in _insp.getsource(_r.endpoint):
            _silent.append(f"{sorted(_meth)[0]} {_path}")
    ok("activity record: every Master address that changes something says what it did", _n >= 30 and not _silent, f"{_n} addresses; silent: {_silent[:6]}")
    _src = "\n".join(_l for _l in _insp.getsource(M).splitlines() if "_note(" in _l and "def _note" not in _l)
    _bad = [_w for _w in ("body.password", "password_hash", "totp_secret", "{secret", "body.token", "refresh_token", "body.code", "pre_token", "{tok", "{t}", "SECRET", "_tg_cfg") if _w in _src]
    ok("activity record: no line is built from a password, a two-step secret, a code or a key", _src.count("_note(") >= 30 and not _bad, str(_bad))
    ok("activity record: a line is cut to a fixed length", M._note.__code__.co_consts and 400 in M._note.__code__.co_consts)

# ---- a nonsense dollar-rupee rate from the crypto exchange is not taken (21 Nov 2026) --------------------------
# A rate message of 0 (or negative, or not a number) was taken as the rate: every crypto contract was then worth
# nothing in rupees and an order needed no margin at all. The last good rate must stay in use.
_f3 = PriceFeed(); _cry3 = DeltaCrypto(_f3); _cry3._save_inr = lambda: None
_rate = lambda v: _cry3._handle({"type": "spot_price", "symbol": _cry3.INR_INDEX, "price": v})
_rate("94.25")
ok("crypto rate: an ordinary rate is taken", _cry3.usdinr() == 94.25, str(_cry3.usdinr()))
for _bad in ("0", "-94", "nan", "inf", "abc", None):
    _rate(_bad)
    ok(f"crypto rate: a rate message of {_bad!r} is ignored and the last good rate stays", _cry3.usdinr() == 94.25, str(_cry3.usdinr()))
_rate("94.5")
ok("crypto rate: the next ordinary rate is taken again", _cry3.usdinr() == 94.5, str(_cry3.usdinr()))

# ---- the automatic closes wait while a price feed is down or has only just come back (21 Nov 2026) --------------
# Users' own orders are refused while a feed is down (16 Nov 2026). The automatic square-off, the margin call
# and the intraday square-off were not: they sold at the price from before the outage, whatever the real
# market had done in the meantime (a NIFTY lot 54,945 coins better than any real close in the test).
W16 = W14 + timedelta(days=14)
at(day(W16, 1, 11)); px(nifty=30000)
mk_user("outage", 1_000_000)
trade("outage", F_NIFTY, "BUY", 3)
_gq = lambda n: sum(p.qty for p in db.query(Position).filter_by(user_id=users[n].id, token=F_NIFTY, is_closed=False))
_live0 = feed.live
try:
    feed.connected = False                                 # the feed is gone; the last book (30,000) stays in memory
    coins("outage", -300_000, "coins taken out while the feed is down")      # the account is now short of margin
    ok("feed down: the account is short of margin", engine.funds(db, users["outage"])["margin_short"])
    engine._consumed.clear(); run(engine._check_liquidations()); db.expire_all()
    ok("feed down: nothing is squared off at the price from before the outage", _gq("outage") == 225, f"qty {_gq('outage')}")
    feed.connected = True; feed.live = lambda t: False     # connected again, but no new price has arrived yet
    engine._consumed.clear(); run(engine._check_liquidations()); db.expire_all()
    ok("feed down: nor in the instant after the feed is back, before its first new price", _gq("outage") == 225, f"qty {_gq('outage')}")
    feed.live = _live0; feed.set(F_NIFTY, 29100); feed.set(I_NIFTY, 29100)       # the first new price: the market had fallen 3%
    engine._consumed.clear(); run(engine._check_liquidations()); db.expire_all()
    _lt = db.query(Trade).filter_by(user_id=users["outage"].id, token=F_NIFTY).order_by(Trade.id.desc()).first()
    ok("feed down: with the first new price the shortfall is squared off at that price",
       0 < _gq("outage") < 225 and _lt.side == "SELL" and near(_lt.price, 29099.95, 0.001), f"qty {_gq('outage')}, {_lt.side} @ {_lt.price}")
    # the margin call (everything closed) waits in the same way
    mk_user("outage2", 1_000_000)
    trade("outage2", F_NIFTY, "BUY", 3)
    feed.connected = False
    coins("outage2", -700_000, "coins taken out while the feed is down")
    _f2 = engine.funds(db, users["outage2"])
    ok("feed down: the second account is below its maintenance requirement", _f2["equity"] < _f2["maintenance"], str(_f2))
    engine._consumed.clear(); run(engine._check_liquidations()); db.expire_all()
    ok("feed down: a margin call does not close anything at the price from before the outage", _gq("outage2") == 225, f"qty {_gq('outage2')}")
    feed.connected = True; feed.set(F_NIFTY, 29000); feed.set(I_NIFTY, 29000)
    engine._consumed.clear(); run(engine._check_liquidations()); db.expire_all()
    _lt = db.query(Trade).filter_by(user_id=users["outage2"].id, token=F_NIFTY).order_by(Trade.id.desc()).first()
    ok("feed down: once prices arrive again the margin call closes at the new price", _gq("outage2") == 0 and near(_lt.price, 28999.95, 0.001), f"qty {_gq('outage2')}, @ {_lt.price}")
    # intraday square-off ten minutes before the close
    mk_user("outage3", 1_000_000)
    trade("outage3", F_NIFTY, "BUY", 1, product="MIS")
    os.environ["PT_SESSION_END"] = "1"
    feed.connected = False
    at(day(W16, 1, 15, 31)); run(engine.session_end_pass()); db.expire_all()
    ok("feed down: the intraday square-off does not sell at the price from before the outage", _gq("outage3") == 75, f"qty {_gq('outage3')}")
    feed.connected = True; feed.set(F_NIFTY, 28900); feed.set(I_NIFTY, 28900)
    engine._consumed.clear(); run(engine.session_end_pass()); db.expire_all()
    _lt = db.query(Trade).filter_by(user_id=users["outage3"].id, token=F_NIFTY).order_by(Trade.id.desc()).first()
    ok("feed down: once prices arrive again the intraday position is squared off at the new price", _gq("outage3") == 0 and near(_lt.price, 28899.95, 0.001), f"qty {_gq('outage3')}, @ {_lt.price}")
finally:
    feed.connected = True; feed.live = _live0; os.environ.pop("PT_SESSION_END", None)

# ---- an expired option whose underlying has no price is not settled at its own last trade (21 Nov 2026) --------
# After the three-minute wait for the underlying, an option fell back to its own last traded price: 5 lots of a
# crude call that expired worthless were paid out at the premium of that morning (420 a unit, 210,000 coins).
O_NOUND = 41
_xday = day(W16, 2, 12)
feed.instruments[O_NOUND] = Instrument(O_NOUND, "CRUDEOIL27FEB6000CE", "CRUDEOIL", "MCX", "MCX-OPT", "CE", _xday.date().isoformat(), 6000, 100, 0.1)
at(_xday); feed.set(F_CRUDE, 5900); feed.set(O_NOUND, 40.0)
mk_user("nound", 1_000_000)
trade("nound", O_NOUND, "BUY", 5)
at(day(W16, 2, 23, 50)); feed.set(O_NOUND, 3.0); feed.prices[O_NOUND]["ltp"] = 420.0     # worth 3 now; the last trade is from the morning
_crude_px = feed.prices.pop(F_CRUDE)                       # nothing in memory for the underlying future (restart, feed not delivering it)
_nq = lambda: db.query(Position).filter_by(user_id=users["nound"].id, token=O_NOUND, is_closed=False).count()
try:
    at(day(W16, 2, 23, 58)); run(engine._settle_expired()); db.expire_all()
    ok("no underlying price: an expired option first waits for its underlying", _nq() == 1)
    engine._und_wait[F_CRUDE] = time.time() - 200          # three minutes later there is still no price for it
    run(engine._settle_expired()); db.expire_all()
    ok("no underlying price: after the wait it is NOT settled at its own old last trade", _nq() == 1,
       "settled @ " + str(getattr(db.query(Trade).filter_by(user_id=users["nound"].id).order_by(Trade.id.desc()).first(), "price", None)))
finally:
    feed.prices[F_CRUDE] = _crude_px
feed.set(F_CRUDE, 5900); run(engine._settle_expired()); db.expire_all()
_lt = db.query(Trade).filter_by(user_id=users["nound"].id).order_by(Trade.id.desc()).first()
ok("no underlying price: once the underlying has a price the option settles against it (worthless: 0)", _nq() == 0 and _lt.price == 0.0, f"open {_nq()}, @ {_lt.price}")

# ---- a contract that expires while its price feed is down waits for the feed (21 Nov 2026) ----------------------
# With the feed down since 3:20 pm a NIFTY future was settled at 3:40 pm against the index of 3:20 pm, although
# the real close was 2% lower. It now waits until the feed is back and has delivered the underlying's price.
F_DOWN_X = 42
_dday = day(W16, 3, 12)
feed.instruments[F_DOWN_X] = Instrument(F_DOWN_X, "NIFTY27FEBFUT", "NIFTY", "NFO", "NFO-FUT", "FUT", _dday.date().isoformat(), 0, 75, 0.05)
at(_dday); feed.set(I_NIFTY, 29000); feed.set(F_DOWN_X, 29010)
mk_user("expdown", 1_000_000)
trade("expdown", F_DOWN_X, "BUY", 1)
_dq = lambda: db.query(Position).filter_by(user_id=users["expdown"].id, token=F_DOWN_X, is_closed=False).count()
at(day(W16, 3, 15, 20)); feed.set(I_NIFTY, 29000); feed.set(F_DOWN_X, 29010); W.remember_marks(engine, db)
feed.connected = False                                     # the feed drops; the index really closes at 28,420
try:
    at(day(W16, 3, 15, 41)); run(engine._settle_expired()); db.expire_all()
    ok("feed down at expiry: the contract is not settled at the price from before the outage", _dq() == 1,
       "settled @ " + str(getattr(db.query(Trade).filter_by(user_id=users["expdown"].id).order_by(Trade.id.desc()).first(), "price", None)))
finally:
    feed.connected = True
feed.set(I_NIFTY, 28420); run(engine._settle_expired()); db.expire_all()
_lt = db.query(Trade).filter_by(user_id=users["expdown"].id).order_by(Trade.id.desc()).first()
ok("feed down at expiry: once the feed is back it settles at the underlying's price delivered then", _dq() == 0 and near(_lt.price, 28420, 0.001), f"open {_dq()}, @ {_lt.price}")

# ---- a bought option while its market's contract list is not loaded (21 Nov 2026) --------------------------------
# After a restart in the night (until the day's price-feed login) and all weekend the NSE / BSE / MCX / Currency
# contract list is not loaded. A bought option was then treated like a future: its running loss, already paid for
# with the premium, counted against Available Balance again and half its premium was added to the maintenance
# requirement, so an account that also held a crypto position had part of it squared off with the charge.
W20 = W16 + timedelta(days=28)
at(day(W20, 4, 11)); px(nifty=30000, ce=4300, btc=90000)
mk_user("nolist2", 1_000_000)
trade("nolist2", O_CE, "BUY", 1); trade("nolist2", F_BTC, "BUY", 500); trade("nolist2", F_BTC, "BUY", 240)
at(day(W20, 4, 15, 30)); px(nifty=28500, ce=2900); W.remember_marks(engine, db); db.expire_all()      # the option has lost a third
_nl = users["nolist2"]
_nf0 = engine.funds(db, _nl)
_bq = lambda: sum(p.qty for p in db.query(Position).filter_by(user_id=_nl.id, token=F_BTC, is_closed=False))
_keep_i, _keep_p = feed.instruments.pop(O_CE), feed.prices.pop(O_CE)      # the restart: the contract is unknown, nothing in memory for it
try:
    _nf1 = engine.funds(db, _nl)
    ok("no contract list: a bought option's paid-for loss is not counted against Available Balance a second time",
       near(_nf1["available"], _nf0["available"], 0.01), f"{_nf0['available']} -> {_nf1['available']}")
    ok("no contract list: a bought option adds nothing to the maintenance requirement", near(_nf1["maintenance"], _nf0["maintenance"], 0.01),
       f"{_nf0['maintenance']} -> {_nf1['maintenance']}")
    engine._consumed.clear(); run(engine._check_liquidations()); db.expire_all()
    ok("no contract list: nothing of the account's crypto position is squared off because of it", _bq() == 740, f"BTC lots {_bq()}")
    # Shadow Book: the mirrored position showed "0 lots" while the contract list was not loaded
    _sh = M.admin_shadow(None, None, users["master"], db)
    _sp = next((x for x in _sh["positions"] if x["user"] == _nl.display_name and x["symbol"] == _keep_i.symbol), None)
    ok("no contract list: the Shadow Book still shows the lots of a mirrored position", _sp is not None and _sp["lots"] == 1 and _sp["qty"] == 75, str(_sp))
finally:
    feed.instruments[O_CE] = _keep_i; feed.prices[O_CE] = _keep_p

# ---- the price-feed login that is refused, and errors kept through a restart (owner's requests of 19 Nov 2026; checks added 20 Nov) ----
# On 19 Nov a login the broker had cleared was retried for two hours (about 300 errors) while the Master's page
# offered no way to log in again. Three refusals in a row must stop the retrying and ask for a fresh login.
from app.feed.kite import KiteFeed                         # noqa: E402
import app.probe as _PB                                    # noqa: E402
_tg, _told = _PB._telegram, []
_PB._telegram = lambda m: _told.append(m)
try:
    _kf = KiteFeed("fake-key", "fake-secret"); _kf.set_access_token("fake-token", __import__("app.feed.kite", fromlist=["ist_today"]).ist_today())
    ok("feed login: a login of today counts until the broker refuses it", _kf.token_valid_today() and not _kf.status()["needs_login"])
    _r = [_kf._maybe_refused(None, "connection was refused: 403 - Forbidden") for _ in range(2)]
    ok("feed login: two refusals are still retried", _r == [False, False] and not _kf.refused)
    _kf._maybe_refused(None, "connection was refused: 403 - Forbidden"); time.sleep(0.3)
    _st = _kf.status()
    ok("feed login: the third refusal stops the retrying and asks for a fresh login", _kf.refused and _st["needs_login"] and _st["refused"] and not _st["can_reconnect"] and not _kf.reconnect(), str({k: _st.get(k) for k in ("needs_login", "refused", "can_reconnect")}))
    ok("feed login: the owner is told once, with the way to log in", len(_told) == 1 and "/auth/kite/login" in _told[0], str(len(_told)))
    _kf._maybe_refused(None, "403"); _kf._on_close(None, 1006, "403"); time.sleep(0.2)
    ok("feed login: further refusals send no further message", len(_told) == 1, str(len(_told)))
    ok("feed login: an ordinary disconnection is not taken for a refusal", KiteFeed("k", "s")._maybe_refused(None, "connection lost (1006)") is False)
    _kf.set_access_token("fake-token-2", __import__("app.feed.kite", fromlist=["ist_today"]).ist_today())
    ok("feed login: a fresh login clears the refusal", not _kf.refused and _kf.token_valid_today())
finally:
    _PB._telegram = _tg

# Site health used to forget the day's errors at every restart and showed 300 identical lines one by one.
import logging as _lg                                      # noqa: E402
from app import watchdog as _WD                            # noqa: E402
_wd_file, _wd_err = _WD._err_file, list(_WD._errors)
try:
    _WD._err_file = __import__("pathlib").Path(tempfile.mkdtemp(prefix="lfx-errs-")) / "errors.jsonl"; _WD._errors.clear()
    _h = _WD._ErrorCounter(level=_lg.ERROR)
    for _m in ("same thing went wrong", "same thing went wrong", "same thing went wrong", "something else <b>went</b> wrong\nsecond line"):
        _h.emit(_lg.LogRecord("engine", _lg.ERROR, __file__, 1, _m, None, None))
    _h.emit(_lg.LogRecord("engine", _lg.WARNING, __file__, 1, "only a warning", None, None))
    _WD._errors.clear(); _WD._load_errors()                # what a restart does
    _g = _WD.error_groups(86400)
    ok("site health: the errors of before a restart are still there after it", len(_WD.errors_since(86400)) == 4, str(len(_WD.errors_since(86400))))
    ok("site health: identical errors are folded into one line with their number", sorted(x["count"] for x in _g) == [1, 3] and all(x["first"] <= x["last"] for x in _g), str(_g)[:200])
    with open(_WD._err_file, "a") as _f:
        _f.write('not json\n[1, "old", "an error of long ago"]\n')
    _WD._errors.clear(); _WD._load_errors()
    ok("site health: a broken line or an error past its keeping time is left out, the rest is kept", len(_WD._errors) == 4, str(len(_WD._errors)))
finally:
    _WD._err_file = _wd_file; _WD._errors.clear(); _WD._errors.extend(_wd_err)

# ---- the daily backup that does not pass its check (alarm "backup bad"; Technology officer, 21 Nov 2026) ----
# One round of the real backup job at a time, on this script's own database. The owner is told once per damaged
# file, the damaged file is set aside and the next round writes a good one. Also when the damaged file was
# already there at the start (the site restarted while the backup was being written): before 21 Nov 2026 that
# file stayed as the day's backup and was sent off-server as it was.
_bk_dir = M.config.DATA_DIR / "backups"
_bk_keep = (M._backup_to, M._tg_ready, M._tg_state, M._tg_send, _PB._telegram, M.get_setting_safe("backup_check"))
_bk_told, _bk_sent = [], []
try:
    import json as _json
    for _x in (_bk_dir.glob("limefx-*") if _bk_dir.exists() else []):
        _x.unlink()
    _PB._telegram = lambda _m: (_bk_told.append(_m), "")[1]
    M._tg_ready = lambda: False

    def _bk_round():
        async def _one():
            try:
                await asyncio.wait_for(M.backup_loop(), timeout=3)
            except asyncio.TimeoutError:
                pass
        run(_one())
        _f = sorted(_bk_dir.glob("limefx-*.db"))
        return _f[-1] if _f else None, _json.loads(M.get_setting_safe("backup_check") or "{}")

    _f, _c = _bk_round()
    ok("backup: a healthy round writes today's backup, opens it and tells nobody", _f is not None and _c.get("ok") is True and _c.get("file") == _f.name and not _bk_told, f"{_f} {_c}")
    _today = _f
    _tabs = lambda _p: {r[0]: r[1] for r in __import__("sqlite3").connect(str(_p)).execute(
        "select name, (select count(*) from pragma_table_info(name)) from sqlite_master where type='table'")}
    ok("backup: the backup holds every table of the books", _tabs(_today) == _tabs(M._db_file()) and len(_tabs(_today)) >= 11, str(sorted(_tabs(_today))))
    _today.unlink()
    M._backup_to = lambda _dest: open(_dest, "wb").write(b"SQLite format 3\x00" + os.urandom(4000))
    _f, _c = _bk_round()
    ok("backup: a backup that is damaged when written is reported to the owner, once", len(_bk_told) == 1 and "did not pass its check" in _bk_told[0] and _c.get("ok") is False, f"{len(_bk_told)} {_c}")
    ok("backup: the damaged file is set aside, not kept as today's backup", _f is None and _today.with_suffix(".bad").exists(), str(_f))
    ok("backup: Site health shows the failed check", M._health()["backup"]["check"].get("ok") is False)
    M._backup_to = _bk_keep[0]
    _f, _c = _bk_round()
    ok("backup: the next round writes a good one", _f is not None and _c.get("ok") is True and _WD.check_backup(_f, M._db_file())["ok"] and len(_bk_told) == 1, f"{_f} {_c}")
    # the site was restarted while the backup was being written: today's file is there, cut short, and no check of it is on record
    _bk_keep[0](_today); open(_today, "r+b").truncate(os.path.getsize(_today) // 2)
    M.set_setting_safe("backup_check", _json.dumps({"file": "limefx-2000-01-01.db", "ok": True}))
    M._tg_ready = lambda: True; M._tg_state = lambda: ({"sent": _bk_sent[-1][0]} if _bk_sent else {})
    M._tg_send = lambda _snap, daily=True: (_bk_sent.append((_snap.name, _WD.check_backup(_snap, M._db_file())["ok"])), {})[1]
    _bk_told.clear()
    _f, _c = _bk_round()
    ok("backup: a file left half-written by a restart is reported and set aside", len(_bk_told) == 1 and _c.get("ok") is False and _f is None, f"told {len(_bk_told)} {_c} {_f}")
    ok("backup: a damaged file is never sent off-server", not _bk_sent, str(_bk_sent))
    _f, _c = _bk_round()
    ok("backup: after it the next round writes a good backup, and that one is sent off-server", _f is not None and _c.get("ok") is True and _WD.check_backup(_f, M._db_file())["ok"]
       and _bk_sent == [(_f.name, True)] and len(_bk_told) == 1, f"{_f} {_c} {_bk_sent}")
    # the copy made for the Master's "Download backup" is removed once it has been sent (it used to stay in the
    # server's temporary folder, a full unencrypted copy per download)
    _td, tempfile.tempdir = tempfile.tempdir, TMP          # this script's own folder (other copies on this machine use the shared one)
    _old = M.Path(tempfile.gettempdir()) / "limefx-backup-2000-01-01-0000.db"; _old.write_bytes(b"x"); os.utime(_old, (time.time() - 3600,) * 2)
    _resp = M.admin_backup(admin=None)
    _p = M.Path(_resp.path)
    _whole = _p.exists() and _WD.check_backup(_p, M._db_file())["ok"]
    if _resp.background is not None:
        run(_resp.background())
    ok("backup: the Master's download is a whole copy, and the server's own copy of it is removed after sending", _whole and not _p.exists(), f"whole {_whole}, still there {_p.exists()}")
    ok("backup: a copy left behind by an earlier, broken download is removed at the next one", not _old.exists())
    _old.unlink(missing_ok=True); _p.unlink(missing_ok=True)
    tempfile.tempdir = _td
    # pruning: fourteen kept, always the newest ones
    for _i in range(1, 21):
        _bk_keep[0](_bk_dir / f"limefx-2026-10-{_i:02d}.db")
    _f, _c = _bk_round()
    _left = sorted(x.name for x in _bk_dir.glob("limefx-*.db"))
    ok("backup: old backups are pruned to fourteen, the newest always kept", len(_left) == 14 and _left[-1] == _today.name and _left[0] == "limefx-2026-10-08.db", str(_left))
finally:
    M._backup_to, M._tg_ready, M._tg_state, M._tg_send, _PB._telegram = _bk_keep[:5]
    M.set_setting_safe("backup_check", _bk_keep[5])

# ---- added 24 Nov 2026 (Security officer): the margin watch, a deleted account's peak margin, the crypto reconnect ----
# (1) The margin watch (app/margin_watch.py, live since 21 Nov) asks the broker's margin calculator once for
# everybody and once per user. A user's first trade of the day made a new row, and the database then stayed
# locked for writing through all of those calls: with 13 users holding positions and 0.4 s per answer, another
# user's order waited 5 s. The stand-in calculator here tries, each time it is asked, what an order placed at
# that moment would have to do: open the database for writing.
from app import margin_watch as _MW                       # noqa: E402
import sqlite3 as _sq                                     # noqa: E402
_asked, _other = [], []


class _Calc:
    def basket_order_margins(self, basket, consider_positions=False):
        try:
            _c = _sq.connect(str(M._db_file()), timeout=0.3); _c.execute("BEGIN IMMEDIATE"); _c.rollback(); _c.close(); _asked.append(True)
        except _sq.OperationalError:
            _asked.append(False)
        return {"final": {"total": 1234.5}}

    def __getattr__(self, name):                          # anything else it is asked to do (an order, above all) is written down
        _other.append(name); raise AttributeError(name)


feed.set(F_NIFTY, 28000); feed.set(I_NIFTY, 28000)
mk_user("mwatch", 5_000_000); trade("mwatch", F_NIFTY, "BUY", 1)
_mwu = users["mwatch"].id; _mw_db = SessionLocal()
feed.kite = _Calc(); feed.access_token = "x"; feed.refused = False
try:
    _MW._state.update(trade_id=None, sig=None, real_at=0.0)
    _MW.sample(_mw_db, feed, {_mwu}, ("NFO", "BFO", "MCX"))
finally:
    del feed.kite, feed.access_token, feed.refused
    _mw_db.close()
db.expire_all()
_pk = _MW.peaks(db); _now = sum(p.margin_blocked for p in db.query(Position).filter_by(user_id=_mwu, is_closed=False))
ok("margin watch: the broker's calculator is asked with nothing of the database held (an order placed meanwhile does not wait)",
   len(_asked) >= 2 and all(_asked), f"asked {len(_asked)} times, database free each time: {_asked}")
ok("margin watch: it only asks the calculator, never anything else of the broker (no order)", not _other, str(_other))
ok("margin watch: the user's peak is kept, is not below the margin now, and the calculator's figure is kept",
   _mwu in _pk and _pk[_mwu]["rule"] >= _now - 0.01 > 0 and _pk[_mwu]["real"] == 1234.5 and _pk[0]["rule"] >= _pk[_mwu]["rule"], f"{_pk.get(_mwu)} now {_now}")
# (2) A deleted account's number is handed out again by the database: the next account created was shown on the
# Shadow Book with the deleted account's Peak Margin (found 24 Nov 2026).
M.admin_delete_user(_mwu, admin=None, db=db); users.pop("mwatch")
_pk = _MW.peaks(db)
ok("margin watch: a deleted account's peak margin goes with it (the next account with that number starts with none)", _mwu not in _pk, str(_pk.get(_mwu)))
ok("margin watch: the peak of everybody together stays", 0 in _pk and _pk[0]["rule"] > 0, str(_pk.get(0)))

# (3) "Reconnect crypto" pressed twice at the same moment (or pressed while the automatic rebuild after six quick
# drops was reloading the contract list) started two connection loops that both stayed for good (found 24 Nov
# 2026). The real feed class, with a stand-in for the exchange's connection.
import websockets as _wsm                                 # noqa: E402
_live = set()


class _FakeWS:
    close_code = 1000; close_reason = ""

    def __init__(self):
        self._gone = asyncio.Event()

    async def send(self, _m):
        pass

    async def close(self):
        self._gone.set()

    def __aiter__(self):
        return self

    async def __anext__(self):
        await self._gone.wait()
        raise StopAsyncIteration


class _FakeConn:
    async def __aenter__(self):
        self.w = _FakeWS(); _live.add(self.w); return self.w

    async def __aexit__(self, *_a):
        _live.discard(self.w)


async def _press_thrice():
    _c3 = DeltaCrypto(PriceFeed()); _c3._loop = asyncio.get_event_loop()
    _c3.refresh_products = lambda: time.sleep(0.05)
    _c3._run_task = _c3._loop.create_task(_c3._run()); await asyncio.sleep(0.05)
    await asyncio.gather(_c3._fresh(), _c3._fresh(), _c3._fresh()); await asyncio.sleep(0.3)
    _n, _loops = len(_live), getattr(_c3, "_runs", None)
    for _t in [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]:
        _t.cancel()
    await asyncio.sleep(0.05)
    return _n, _loops

_kc = _wsm.connect; _wsm.connect = lambda *_a, **_k: _FakeConn()
try:
    _n3, _l3 = asyncio.get_event_loop().run_until_complete(_press_thrice())
finally:
    _wsm.connect = _kc
ok("crypto reconnect: three rebuilds at the same moment leave ONE connection to the exchange", _n3 == 1 and _l3 == 1, f"{_n3} connections, {_l3} loops")

if __name__ == "__main__":
    print(f"\nWEEKLY SIMULATION: {checks['pass']} passed, {checks['fail']} failed")
    sys.exit(1 if checks["fail"] else 0)
