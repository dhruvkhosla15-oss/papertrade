"""Peak margin for the Shadow Book (owner's request, 21 Nov 2026).

The Shadow Book showed only the margin blocked right now; after a liquidation that understates what the
positions needed. This keeps, for every IST day, the HIGHEST margin in use: in total and per user, by
limefx's own rule ("rule") and, whenever the broker login is live, by the broker's own margin calculator
for the mirror positions ("real"). It only reads: nothing here changes how margin is charged to anyone, and
the broker connection is only asked a question (no order is ever sent).

  sample()   every few seconds: the rule margin now; the real margin when a trade has happened since the
             last look (so every trade is measured within seconds) and every 15 minutes besides.
  rebuild()  once: the days before this recorder existed, replayed from the trades (rough, marked rebuilt).
"""
import logging
import time
from datetime import datetime, timedelta

from .db import Base, Position, Trade
from sqlalchemy import Column, Integer, Float, String, Boolean, UniqueConstraint

log = logging.getLogger("margin_watch")
IST = timedelta(hours=5, minutes=30)
REAL_EVERY = 900          # seconds between calculator calls when nothing was traded


class MarginPeak(Base):
    __tablename__ = "margin_peaks"
    __table_args__ = (UniqueConstraint("day", "user_id", name="uq_mpeak_day_user"),)
    id = Column(Integer, primary_key=True)
    day = Column(String(10), index=True, nullable=False)       # IST day
    user_id = Column(Integer, index=True, nullable=False)      # 0 = everybody together
    rule_peak = Column(Float, default=0.0)
    rule_at = Column(String(20), default="")                   # UTC, ISO
    rule_rebuilt = Column(Boolean, default=False)              # True while the figure comes only from the replay of trades
    real_peak = Column(Float)                                  # None = never measured that day
    real_at = Column(String(20), default="")
    real_missed = Column(Integer, default=0)                   # trades that could not be measured (broker not logged in)


_state = {"trade_id": None, "sig": None, "real_at": 0.0}


def ist_day(dt: datetime = None) -> str:
    return ((dt or datetime.utcnow()) + IST).date().isoformat()


def _row(db, day, uid):
    r = db.query(MarginPeak).filter_by(day=day, user_id=uid).first()
    if r is None:
        r = MarginPeak(day=day, user_id=uid, rule_peak=0.0, real_missed=0)
        db.add(r); db.flush()
    return r


def _raise_rule(db, day, uid, value, at, rebuilt=False):
    r = _row(db, day, uid)
    if value > (r.rule_peak or 0.0) + 0.005 or (r.rule_rebuilt and not rebuilt and value >= (r.rule_peak or 0.0) - 0.005):
        if value > (r.rule_peak or 0.0) + 0.005:
            r.rule_peak = round(value, 2); r.rule_at = at
        r.rule_rebuilt = bool(rebuilt) if value >= (r.rule_peak or 0.0) - 0.005 else r.rule_rebuilt


def _basket(feed, positions):
    out = []
    for p in positions:
        ins = feed.instruments.get(p.token)
        if not ins or not p.qty:
            continue
        mirror_buy = p.qty < 0                      # the mirror is the opposite of the user
        n = abs(p.qty) // max(ins.lot_size, 1) if p.exchange == "MCX" else abs(p.qty)      # the broker counts MCX in lots
        out.append({"exchange": p.exchange, "tradingsymbol": p.symbol, "transaction_type": "BUY" if mirror_buy else "SELL",
                    "variety": "regular", "product": "NRML", "order_type": "MARKET", "quantity": int(n), "price": 0, "trigger_price": 0})
    return out


def _real(feed, basket):
    """The broker's margin calculator for a set of mirror positions, or None when it cannot be asked."""
    kite = getattr(feed, "kite", None)
    if kite is None or not getattr(feed, "access_token", None) or getattr(feed, "refused", False):
        return None
    if not basket:
        return 0.0
    try:
        r = kite.basket_order_margins(basket, consider_positions=False)
        return round(((r.get("final") or {}).get("total")) or 0.0, 2)
    except Exception as e:
        log.warning("margin calculator did not answer: %s", str(e)[:120])
        return None


def sample(db, feed, user_ids, exchanges) -> dict:
    """One look. Never raises into the caller's loop."""
    now = datetime.utcnow(); at = now.strftime("%Y-%m-%dT%H:%M:%S"); day = ist_day(now)
    pos = [p for p in db.query(Position).filter_by(is_closed=False).filter(Position.exchange.in_(exchanges)).all()
           if p.qty and p.user_id in user_ids]
    by = {}
    for p in pos:
        by.setdefault(p.user_id, []).append(p)
    total = 0.0
    for uid, ps in by.items():
        m = sum((p.margin_blocked or 0.0) for p in ps); total += m
        _raise_rule(db, day, uid, m, at)
    _raise_rule(db, day, 0, total, at)
    # has anything been traded since the last look?
    last = db.query(Trade.id).filter(Trade.exchange.in_(exchanges)).order_by(Trade.id.desc()).first()
    last = last[0] if last else 0
    traded = _state["trade_id"] is not None and last != _state["trade_id"]
    n_new = 0
    if traded:
        n_new = db.query(Trade).filter(Trade.exchange.in_(exchanges), Trade.id > _state["trade_id"], Trade.user_id.in_(list(user_ids) or [0])).count()
    _state["trade_id"] = last
    sig = tuple(sorted((p.user_id, p.token, p.qty) for p in pos))
    due = traded or sig != _state["sig"] or time.time() - _state["real_at"] >= REAL_EVERY
    out = {"rule": round(total, 2), "real": None}
    # The books must be free while the broker's calculator is asked: it can take seconds, and a line started for
    # a new day a moment ago would otherwise keep the database locked for writing all that time, so that every
    # order on the site waited for the calculator (found 25 Nov 2026: with six accounts and a calculator taking
    # 1.5 s a call, another account's order waited 8.7 s). So: write the rule figures and let go, ask, then write
    # the answers.
    all_basket = _basket(feed, pos) if due else []
    baskets = {uid: _basket(feed, ps) for uid, ps in by.items()} if due else {}
    db.commit()
    if due:
        tot = _real(feed, all_basket)
        per = {uid: _real(feed, b) for uid, b in baskets.items()} if tot is not None else {}
        if tot is None:
            if n_new:
                r = _row(db, day, 0); r.real_missed = (r.real_missed or 0) + n_new
        else:
            _state["sig"] = sig; _state["real_at"] = time.time(); out["real"] = tot
            r = _row(db, day, 0)
            if r.real_peak is None or tot > r.real_peak:
                r.real_peak = tot; r.real_at = at
            for uid, v in per.items():
                if v is not None:
                    ru = _row(db, day, uid)
                    if ru.real_peak is None or v > ru.real_peak:
                        ru.real_peak = v; ru.real_at = at
        db.commit()
    return out


def rebuild(db, engine, user_ids, exchanges) -> dict:
    """The days before the recorder existed, replayed from the trades with the margin rule of today.
    Rough: a carried position is counted at the price it was bought at, and a contract that is no longer in
    the list (expired) cannot be counted at all."""
    trades = db.query(Trade).filter(Trade.exchange.in_(exchanges), Trade.user_id.in_(list(user_ids) or [0])) \
               .order_by(Trade.created_at, Trade.id).all()
    if not trades:
        return {"days": 0, "skipped": 0}
    book, skipped = {}, 0          # (uid, token) -> [qty, margin]
    days = {}                      # day -> {uid: (peak, at)}

    def note(day, at):
        per = {}
        for (uid, _t), (q, m) in book.items():
            if q:
                per[uid] = per.get(uid, 0.0) + m
        per[0] = sum(per.values())
        d = days.setdefault(day, {})
        for uid, v in per.items():
            if v > d.get(uid, (0.0, ""))[0]:
                d[uid] = (v, at)

    first = (trades[0].created_at + IST).date(); today = (datetime.utcnow() + IST).date()
    i = 0; day = first
    while day <= today:
        dkey = day.isoformat()
        note(dkey, (datetime(day.year, day.month, day.day) - IST).strftime("%Y-%m-%dT%H:%M:%S"))      # what was held over into the day
        while i < len(trades) and (trades[i].created_at + IST).date() == day:
            t = trades[i]; i += 1
            ins = engine.feed.instruments.get(t.token)
            key = (t.user_id, t.token); q, m = book.get(key, [0, 0.0])
            dq = t.qty if t.side == "BUY" else -t.qty
            if q and (q > 0) != (dq > 0):                       # reducing (or flipping)
                cut = min(abs(q), abs(dq)); m -= m * cut / abs(q); q += cut if q < 0 else -cut
                dq = dq + cut if dq < 0 else dq - cut
            if dq:
                if ins is None:
                    skipped += 1
                else:
                    try:
                        m += engine.required_margin(db, ins, "BUY" if dq > 0 else "SELL", abs(dq), t.price)
                    except Exception:
                        skipped += 1
                q += dq
            book[key] = [q, max(m, 0.0)]
            note(dkey, t.created_at.strftime("%Y-%m-%dT%H:%M:%S"))
        day += timedelta(days=1)
    for dkey, per in days.items():
        for uid, (v, at) in per.items():
            _raise_rule(db, dkey, uid, v, at, rebuilt=True)
    db.commit()
    return {"days": len(days), "skipped": skipped}


def peaks(db, d_from: str = None, d_to: str = None) -> dict:
    """Highest figures of the period, per user (0 = everybody together)."""
    q = db.query(MarginPeak)
    if d_from:
        q = q.filter(MarginPeak.day >= d_from)
    if d_to:
        q = q.filter(MarginPeak.day <= d_to)
    out = {}
    for r in q.all():
        o = out.setdefault(r.user_id, {"rule": 0.0, "rule_at": "", "rule_rebuilt": False, "real": None, "real_at": "", "missed": 0})
        if (r.rule_peak or 0.0) > o["rule"]:
            o["rule"] = r.rule_peak; o["rule_at"] = r.rule_at; o["rule_rebuilt"] = bool(r.rule_rebuilt)
        if r.real_peak is not None and (o["real"] is None or r.real_peak > o["real"]):
            o["real"] = r.real_peak; o["real_at"] = r.real_at
        o["missed"] += r.real_missed or 0
    return out
