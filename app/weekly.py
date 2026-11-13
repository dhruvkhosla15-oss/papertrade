"""Weekly settlement.

A week runs Monday 00:00 to Sunday 23:59:59 IST. At the cut-off, for every account:

1. Every open position is VALUED at the week-close price. The running profit or loss up to that price is
   booked (ledger line WEEKLY_VALUATION), and the position is carried forward at that price: avg_price
   becomes the week-close price, entry_avg keeps the user's own average. Nothing is bought or sold, no
   commission is charged, margin stays blocked.
2. The week's result (everything that moved the coins since the previous cut-off, apart from coins the
   Master added or removed) is settled: one ledger line WEEKLY_SETTLEMENT brings the coins back to the
   allocated amount. A loss is put back, a profit is taken out.
3. One WeekSettlement row per account records the week for good.

So each week stands on its own, and for a carried position
    settled in earlier weeks + this week's P&L  =  P&L since the user's own entry price
always holds: settled earlier is (avg_price - entry_avg) x qty, this week is (price - avg_price) x qty.
"""
import logging
import math
from datetime import datetime, date, time as dtime, timedelta
from typing import Optional

from .db import User, Position, Trade, Ledger, WeekSettlement, get_setting, set_setting

log = logging.getLogger("weekly")

IST = timedelta(hours=5, minutes=30)
PROBE = "zz-probe-"
ALLOC_KINDS = ("ADMIN_CREDIT", "ADMIN_DEBIT")
VALUATION, SETTLEMENT = "WEEKLY_VALUATION", "WEEKLY_SETTLEMENT"
WEEK_KINDS = (VALUATION, SETTLEMENT)
CRYPTO = ("CRYPTO",)


# ---- calendar ---------------------------------------------------------------------------------------
def week_end_of(d: date) -> date:
    """The Sunday that closes the week containing d."""
    return d + timedelta(days=6 - d.weekday())


def last_finished_week_end(now_ist: datetime) -> date:
    """The most recent Sunday whose 23:59:59 has already passed."""
    d = now_ist.date()
    back = (d.weekday() + 1) % 7 or 7          # Monday -> 1 day back, Sunday -> the Sunday a week ago
    return d - timedelta(days=back)


def cutoff_utc(week_end: date) -> datetime:
    """Sunday 23:59:59 IST, as the naive UTC the database stores."""
    return datetime.combine(week_end, dtime(23, 59, 59)) - IST


def week_start_utc(week_end: date) -> datetime:
    return datetime.combine(week_end - timedelta(days=6), dtime(0, 0, 0)) - IST


def week_label(week_end: date) -> str:
    a = week_end - timedelta(days=6)
    if a.month == week_end.month:
        return f"{a.day}–{week_end.day} {week_end.strftime('%b %Y')}"
    return f"{a.day} {a.strftime('%b')} – {week_end.day} {week_end.strftime('%b %Y')}"


# ---- small helpers ------------------------------------------------------------------------------------
def accounts(db):
    """Every account the weekly settlement applies to (the hidden safety-check accounts are left out)."""
    return [u for u in db.query(User).order_by(User.id).all() if not (u.username or "").startswith(PROBE)]


def allocated(db, user) -> float:
    return round(sum(l.amount for l in db.query(Ledger).filter(Ledger.user_id == user.id, Ledger.kind.in_(ALLOC_KINDS))), 2)


def settled_total(db, user) -> float:
    """Sum of all finished weeks' results for this account (a loss is negative)."""
    return round(-sum(l.amount for l in db.query(Ledger).filter(Ledger.user_id == user.id, Ledger.kind == SETTLEMENT)), 2)


def last_cutoff(db, user) -> Optional[datetime]:
    row = (db.query(Ledger).filter(Ledger.user_id == user.id, Ledger.kind == SETTLEMENT)
           .order_by(Ledger.created_at.desc(), Ledger.id.desc()).first())
    return row.created_at if row else None


def _exit_quote(engine, p: Position) -> Optional[float]:
    """The price on the side of the book this position would be closed at (bid for a long, ask for a short),
    or None when nobody is quoting there right now."""
    if not getattr(engine, "_mark_at_book", True):
        return None
    t = engine.feed.prices.get(p.token) or {}
    q = t.get("bid") if p.qty > 0 else t.get("ask")
    return q if isinstance(q, (int, float)) and math.isfinite(q) and q >= 0 else None


def _trade_after_mark(engine, p: Position) -> bool:
    """True when the contract has traded since the price kept in last_mark was seen."""
    ltt = (engine.feed.prices.get(p.token) or {}).get("ltt")
    if not ltt or not p.last_mark_at:
        return False
    return ltt > (p.last_mark_at - datetime(1970, 1, 1)).total_seconds()


def close_price(engine, p: Position) -> Optional[float]:
    """Price an open position is valued at: what it could be closed at now (bid for a long, ask for a
    short). When nobody is quoting on that side (a thin contract, or the exchange is shut at the cut-off)
    the last such quote seen is used, unless the contract has traded since: then the last trade. A last
    trade that is days old says nothing about today's value: a thin option bought at today's offer of 3
    whose last trade was 15 would otherwise show five times its cost as the week's profit. For the same
    reason a long is never valued above the best offer in the book, nor a short below the best bid.
    The last price seen is also what is used if the feed has nothing (site restarted over the weekend
    with the exchange shut)."""
    mk = _exit_quote(engine, p)
    if mk is None:
        mk = engine.mark_price(p.token, p.qty)
        if mk is None:
            mk = engine.feed.ltp(p.token)
        if p.last_mark is not None and (mk is None or not _trade_after_mark(engine, p)):
            mk = p.last_mark
        if mk is not None and getattr(engine, "_mark_at_book", True):
            t = engine.feed.prices.get(p.token) or {}
            other = t.get("ask") if p.qty > 0 else t.get("bid")
            if isinstance(other, (int, float)) and math.isfinite(other) and other >= 0:
                mk = min(mk, other) if p.qty > 0 else max(mk, other)
    if mk is None or not isinstance(mk, (int, float)) or not math.isfinite(mk) or mk < 0:
        return None
    return float(mk)


def remember_marks(engine, db) -> int:
    """Keep the last exit-side price of every open position in the database, so a weekly valuation can still
    be done after a restart while that exchange is shut (the feed then has no price in memory), and so that
    a position nobody is quoting at the cut-off is valued at the last quote, not at an old last trade.
    While nobody is quoting, the kept quote stays; it gives way to the last trade only if the contract has
    traded since."""
    n = 0
    for p in db.query(Position).filter_by(is_closed=False).all():
        if not p.qty:
            continue
        mk = _exit_quote(engine, p)
        if mk is None:
            if p.last_mark is not None and not _trade_after_mark(engine, p):
                continue
            mk = engine.mark_price(p.token, p.qty)
            if mk is None:
                mk = engine.feed.ltp(p.token)
        if mk is None or not math.isfinite(mk) or mk < 0:
            continue
        if p.last_mark != mk:
            p.last_mark = float(mk); p.last_mark_at = datetime.utcnow(); n += 1
    if n:
        db.commit()
    return n


def _split(db, user, start: Optional[datetime]) -> dict:
    """Closed-trade P&L and commission of one account since `start` (its last cut-off), split crypto /
    everything else."""
    q = db.query(Trade).filter(Trade.user_id == user.id)
    if start is not None:
        q = q.filter(Trade.created_at > start)
    out = {"closed": 0.0, "commission": 0.0, "closed_crypto": 0.0, "commission_crypto": 0.0, "trades": 0}
    for t in q.all():
        out["closed"] += t.realised_pnl or 0.0; out["commission"] += t.commission or 0.0; out["trades"] += 1
        if t.exchange in CRYPTO:
            out["closed_crypto"] += t.realised_pnl or 0.0; out["commission_crypto"] += t.commission or 0.0
    return out


# ---- the cut-off --------------------------------------------------------------------------------------
def close_week(engine, db, week_end: date, exact: bool = True, stamp: Optional[datetime] = None) -> dict:
    """Run the weekly cut-off for the week ending on `week_end`. Call with the engine lock held.
    Idempotent: an account that already has a row for this week is skipped.
    `stamp` is the real time of a late run; see below for when it is used."""
    nominal = cutoff_utc(week_end)
    # Fills are held from the cut-off until it has run, so normally nothing is traded in between and the
    # books are cut at Sunday 23:59:59 even when the cut-off runs late. Only if something did trade after
    # that moment (the hold was released after repeated failures) is the real time used.
    traded_after = stamp is not None and stamp > nominal and db.query(Trade).filter(Trade.created_at > nominal).first() is not None
    stamp = stamp if traded_after else nominal
    we = week_end.isoformat()
    done = {r.user_id for r in db.query(WeekSettlement).filter_by(week_end=we).all()}
    summary = {"week_end": we, "accounts": 0, "carried": 0, "unpriced": 0, "result_total": 0.0}
    for user in accounts(db):
        if user.id in done:
            continue
        start = last_cutoff(db, user)
        alloc = allocated(db, user)
        sp = _split(db, user, start)
        valuation = valuation_crypto = 0.0
        carried = unpriced = 0
        lines = []
        for p in db.query(Position).filter_by(user_id=user.id, is_closed=False).order_by(Position.id).all():
            if not p.qty:
                continue
            ins = engine.feed.instruments.get(p.token)
            vf = engine.vf(ins) if ins else 1.0
            px = close_price(engine, p)
            if px is None:
                unpriced += 1
                log.warning("weekly close %s: no price for %s of %s, left as it is", we, p.symbol, user.username)
                continue
            val = round((px - p.avg_price) * p.qty * vf, 2)
            if p.entry_avg is None:
                p.entry_avg = p.avg_price
            note = f"{p.symbol} valued at {px:,.2f} (carried from {p.avg_price:,.2f}, original avg {p.entry_avg:,.2f})"
            user.balance = round(user.balance + val, 2)
            db.add(Ledger(user_id=user.id, amount=val, balance_after=user.balance, kind=VALUATION, note=note[:250], created_at=stamp))
            p.realised_pnl = round((p.realised_pnl or 0.0) + val, 2)
            p.avg_price = px; p.carried_week = we
            valuation += val; carried += 1
            if p.exchange in CRYPTO:
                valuation_crypto += val
            lines.append((p.symbol, px, val))
        before = user.balance
        result = round(before - alloc, 2)
        other = round(result - (sp["closed"] + valuation - sp["commission"]), 2)
        if abs(other) < 0.05:           # rounding of individual ledger lines
            other = 0.0
        user.balance = alloc
        db.add(Ledger(user_id=user.id, amount=round(alloc - before, 2), balance_after=user.balance, kind=SETTLEMENT,
                      note=f"Week {week_label(week_end)} closed at {result:+,.2f}; coins back to the allocated amount", created_at=stamp))
        db.add(WeekSettlement(week_end=we, user_id=user.id, closed=round(sp["closed"], 2), valuation=round(valuation, 2),
                              commission=round(sp["commission"], 2), other=other, result=result,
                              closed_crypto=round(sp["closed_crypto"], 2), valuation_crypto=round(valuation_crypto, 2),
                              commission_crypto=round(sp["commission_crypto"], 2), allocated=alloc, coins_before=before,
                              carried=carried, unpriced=unpriced, exact=exact, created_at=stamp))
        db.flush()
        summary["accounts"] += 1; summary["carried"] += carried; summary["unpriced"] += unpriced
        if not user.is_admin:
            summary["result_total"] = round(summary["result_total"] + result, 2)
        if sp["trades"] or carried or abs(result) >= 0.01:
            try:
                text = (f"Closed trades: {sp['closed']:+,.2f}\nOpen positions valued at week close: {valuation:+,.2f}\n"
                        f"Commission: {-sp['commission']:+,.2f}\nWeek result: {result:+,.2f}\n\n")
                if carried:
                    text += (f"Your {carried} open position{'s are' if carried != 1 else ' is'} still open. "
                             f"{'They are' if carried != 1 else 'It is'} now carried at the week-close price and your P&L starts again from zero. ")
                text += f"Your coins are back to {alloc:,.0f}."
                engine._user_alert(db, user, f"Weekly settlement · {week_label(week_end)}", text)
            except Exception:
                log.exception("weekly alert failed")
    # The week's profit has left the coins. Anyone now holding more than the allocated coins cover is warned
    # first and has until Monday 9:15 am to reduce; only then does the usual auto square-off apply.
    import json as _json
    until = datetime.combine(week_end + timedelta(days=1), dtime(9, 15))
    if stamp > nominal:
        until = max(until, stamp + IST + timedelta(hours=9))
    hard = until + timedelta(hours=2, minutes=45)          # Monday noon
    for user in accounts(db):
        if user.id in done:
            continue
        try:
            f = engine.funds(db, user)
            if f.get("margin_short"):
                set_setting(db, f"week_grace_{user.id}", _json.dumps({"monday": until.isoformat(), "hard": hard.isoformat(), "warned2": False, "seen": ""}))
                summary["short"] = summary.get("short", 0) + 1
                engine._user_alert(db, user, "Margin shortfall after weekly settlement",
                                   f"Your coins are back to {allocated(db, user):,.0f} and your open positions need more margin than that: "
                                   f"Available Balance is {f['available']:,.0f}.\n\nNothing is squared off tonight. Please reduce your positions. You have until {hard.strftime('%A %I:%M %p').replace(' 0', ' ')} to do it yourself "
                                   f"(a reminder comes at {until.strftime('%I:%M %p').lstrip('0')}). If Available Balance is still below zero then, "
                                   "positions are squared off automatically until it is back above zero.")
            elif get_setting(db, f"week_grace_{user.id}", ""):
                set_setting(db, f"week_grace_{user.id}", "")
        except Exception:
            log.exception("weekly shortfall warning failed for %s", user.username)
    set_setting(db, "week_closed", we)       # commits
    return summary


# ---- reports ------------------------------------------------------------------------------------------
def row_dict(db, r: WeekSettlement, user: User) -> dict:
    return {"user_id": user.id, "username": user.username, "display_name": user.display_name or user.username,
            "is_admin": bool(user.is_admin), "week_end": r.week_end, "final": True, "exact": bool(r.exact),
            "closed": r.closed, "valuation": r.valuation, "commission": r.commission, "other": r.other, "result": r.result,
            "closed_crypto": r.closed_crypto, "valuation_crypto": r.valuation_crypto, "commission_crypto": r.commission_crypto,
            "allocated": r.allocated, "coins_after": r.allocated, "carried": r.carried, "unpriced": r.unpriced}


def running_row(engine, db, user: User) -> dict:
    """The week in progress for one account: what the cut-off would book if it ran right now."""
    start = last_cutoff(db, user)
    alloc = allocated(db, user)
    sp = _split(db, user, start)
    valuation = valuation_crypto = 0.0
    carried = unpriced = 0
    for p in db.query(Position).filter_by(user_id=user.id, is_closed=False).all():
        if not p.qty:
            continue
        ins = engine.feed.instruments.get(p.token)
        px = close_price(engine, p)
        if px is None:
            unpriced += 1; continue
        val = (px - p.avg_price) * p.qty * (engine.vf(ins) if ins else 1.0)
        valuation += val; carried += 1
        if p.exchange in CRYPTO:
            valuation_crypto += val
    result = round(user.balance + valuation - alloc, 2)
    other = round(result - (sp["closed"] + valuation - sp["commission"]), 2)
    if abs(other) < 0.05:
        other = 0.0
    we = week_end_of((datetime.utcnow() + IST).date())
    return {"user_id": user.id, "username": user.username, "display_name": user.display_name or user.username,
            "is_admin": bool(user.is_admin), "week_end": we.isoformat(), "final": False, "exact": True,
            "closed": round(sp["closed"], 2), "valuation": round(valuation, 2), "commission": round(sp["commission"], 2),
            "other": other, "result": result,
            "closed_crypto": round(sp["closed_crypto"], 2), "valuation_crypto": round(valuation_crypto, 2),
            "commission_crypto": round(sp["commission_crypto"], 2),
            "allocated": alloc, "coins_after": alloc, "carried": carried, "unpriced": unpriced}


def weeks_available(db) -> list:
    return [w for (w,) in db.query(WeekSettlement.week_end).distinct().order_by(WeekSettlement.week_end.desc()).all()]


def report(engine, db, week_end: Optional[str] = None, user_ids: Optional[list] = None, include_admin: bool = False) -> dict:
    """Weekly settlement table. week_end=None -> the running week (provisional)."""
    us = [u for u in accounts(db) if (include_admin or not u.is_admin) and (user_ids is None or u.id in user_ids)]
    if week_end:
        d = date.fromisoformat(week_end)
        byu = {r.user_id: r for r in db.query(WeekSettlement).filter_by(week_end=week_end).all()}
        rows = [row_dict(db, byu[u.id], u) for u in us if u.id in byu]
        final = True
    else:
        d = week_end_of((datetime.utcnow() + IST).date())
        rows = [running_row(engine, db, u) for u in us]
        final = False
    keys = ("closed", "valuation", "commission", "other", "result", "closed_crypto", "valuation_crypto", "commission_crypto", "allocated", "carried", "unpriced")
    tot = {k: round(sum(r[k] for r in rows), 2) for k in keys}
    return {"week_end": d.isoformat(), "week_start": (d - timedelta(days=6)).isoformat(), "label": week_label(d), "final": final,
            "exact": all(r["exact"] for r in rows), "cutoff": f"{d.strftime('%a %d %b %Y')}, 11:59 pm",
            "rows": sorted(rows, key=lambda r: r["result"]), "total": tot, "weeks": weeks_available(db)}
