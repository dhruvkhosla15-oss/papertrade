"""
Order / position engine.

Rules
- MARKET orders fill against the live order book: BUY walks the asks, SELL walks the bids (avg price
  across levels, like a real market order). Rejected when the book is empty, the spread is too wide,
  depth is insufficient for the quantity, or the contract hasn't traded recently.
- LIMIT orders rest; a BUY fills when the best ask <= limit, a SELL when the best bid >= limit, at the limit price.
- SL orders (stop-loss market): BUY triggers when LTP >= trigger, SELL when LTP <= trigger; then fills like a market order.
- Quantities are always whole lots using the exchange lot size.
- Margin: long options block full premium; futures and short options block
  margin_pct% of notional (underlying LTP x qty). Blocked margin is released when the position closes.
- Positions are netted per contract (long + short -> flat). Realised P&L credits/debits the coin balance.
- At expiry the position is squared off at the last traded price and the balance settled.
"""
import asyncio
import json
import logging
import time
from datetime import datetime, timedelta, date
from typing import Optional

from sqlalchemy.orm import Session

from .db import SessionLocal, User, Order, Position, Trade, Ledger, get_setting
from .feed.base import PriceFeed
from .config import DEFAULT_MARGIN_PCT, DEFAULT_COMMISSION_PCT, MARKET_HOURS, ENFORCE_MARKET_HOURS, IST_OFFSET_HOURS

log = logging.getLogger("engine")


class EngineError(Exception):
    pass


def ist_now() -> datetime:
    return datetime.utcnow() + timedelta(hours=IST_OFFSET_HOURS)


class Engine:
    def __init__(self, feed: PriceFeed):
        self.feed = feed
        self.events: list = []            # (user_id, dict) to push to websockets
        self._event_cb = None
        self._lock = asyncio.Lock()
        feed.on_tick(self._on_tick)
        self._pending_tokens = set()
        self._pending_scheduled = set()   # tokens with a pending-order pass already queued
        # shadow book: paper fills consume depth until the live book changes
        # token -> {"sig": depth signature, "bids": {price: consumed_qty}, "asks": {price: consumed_qty}}
        self._consumed = {}

    def set_event_callback(self, cb):
        self._event_cb = cb

    def _emit(self, user_id: int, event: dict):
        if self._event_cb:
            self._event_cb(user_id, event)

    # ---- helpers -------------------------------------------------------------
    def commission_pct(self, db: Session, exchange: str = None) -> float:
        if exchange == "FOREX":
            from .config import DEFAULT_COMMISSION_PCT_FOREX
            v = get_setting(db, "commission_pct_FOREX")
            return float(v) if v not in (None, "") else DEFAULT_COMMISSION_PCT_FOREX
        v = get_setting(db, "commission_pct")
        return float(v) if v not in (None, "") else DEFAULT_COMMISSION_PCT

    def margin_pct(self, db: Session, exchange: str, name: str = "") -> float:
        from .feed.base import kind_of
        key = "STK" if (name and kind_of(exchange, name) == "stock") else exchange
        v = get_setting(db, f"margin_pct_{key}")
        return float(v) if v else DEFAULT_MARGIN_PCT.get(key, 12.0)

    def vf(self, ins) -> float:
        """Rupee value of a 1.0 price move per unit qty (1.0 for NSE/BSE/MCX; contract size x USDINR for crypto)."""
        f = getattr(self.feed, "value_factor", None)
        return f(ins) if f else 1.0

    def market_open(self, exchange: str) -> bool:
        if not ENFORCE_MARKET_HOURS:
            return True
        from .market_calendar import is_open
        return is_open(exchange)

    # ---- liquidity / order book ------------------------------------------------
    def liquidity_settings(self, db: Session):
        on = (get_setting(db, "liquidity_check", "true") or "true").lower() == "true"
        self._mark_at_book = on
        spread = float(get_setting(db, "max_spread_pct", "0") or 0)   # 0 = no spread limit (real-market mode)
        stale = int(get_setting(db, "stale_minutes", "0") or 0)        # 0 = no staleness check
        return on, spread, stale

    def book_fill(self, db: Session, ins, side: str, qty: int, limit_price: float = None):
        """Price an order against the order book. Returns (avg_price, note, filled_qty) or raises EngineError.
        With limit_price, only book levels at or better than the limit are used (a LIMIT order that has
        become marketable), so a limit order is bounded by visible depth exactly like a market order."""
        tick = self.feed.prices.get(ins.token) or {}
        on, max_spread, stale_min = self.liquidity_settings(db)
        ltp = tick.get("ltp")
        if ltp is None:
            raise EngineError("No live price for this contract")
        if not on:
            return ltp, "", qty
        bids, asks = tick.get("bids") or [], tick.get("asks") or []
        if side == "BUY" and not asks:
            raise EngineError("Illiquid: no sellers in the order book for this contract")
        if side == "SELL" and not bids:
            raise EngineError("Illiquid: no buyers in the order book for this contract")
        if bids and asks:
            mid = (bids[0][0] + asks[0][0]) / 2
            spread_pct = (asks[0][0] - bids[0][0]) / mid * 100 if mid else 0
            if max_spread > 0 and spread_pct > max_spread:
                raise EngineError(f"Illiquid: bid {bids[0][0]} / ask {asks[0][0]} — spread {spread_pct:.1f}% exceeds {max_spread:g}% limit")
        ltt = tick.get("ltt")
        if stale_min > 0 and ltt and time.time() - ltt > stale_min * 60 and self.market_open(ins.exchange):
            raise EngineError(f"Illiquid: no trade in this contract for {int((time.time() - ltt) // 60)} minutes")
        # --- shadow book: subtract quantity already consumed by paper fills since this book snapshot ---
        sig = (tuple((x[0], x[1]) for x in bids), tuple((x[0], x[1]) for x in asks))
        sh = self._consumed.get(ins.token)
        if not sh or sh["sig"] != sig:
            # New snapshot. Levels that are *unchanged* (same price, same quantity) are the same resting
            # orders as before, so what paper fills already took from them stays taken — otherwise a thin
            # book that merely ticks at the top could be hit again and again at the same four 1-lot bids.
            old = sh or {"sig": ((), ()), "bids": {}, "asks": {}}
            keep = {}
            for key, old_side, new_side in (("bids", old["sig"][0], sig[0]), ("asks", old["sig"][1], sig[1])):
                new_set = set(new_side)
                keep[key] = {p: q for p, q in old[key].items()
                             if any(lvl[0] == p and lvl in new_set for lvl in old_side)}
            sh = {"sig": sig, "bids": keep["bids"], "asks": keep["asks"]}
            self._consumed[ins.token] = sh
        side_key = "asks" if side == "BUY" else "bids"
        raw_levels = asks if side == "BUY" else bids
        levels = []
        for lvl in raw_levels:
            if limit_price is not None and ((side == "BUY" and lvl[0] > limit_price + 1e-9) or
                                            (side == "SELL" and lvl[0] < limit_price - 1e-9)):
                continue
            left = lvl[1] - sh[side_key].get(lvl[0], 0)
            if left > 0:
                levels.append((lvl[0], left))
        if not levels and limit_price is not None:
            raise EngineError("limit not marketable")
        if not levels:
            raise EngineError("No remaining counterparty quantity at the moment — the visible "
                              f"{'offers' if side == 'BUY' else 'bids'} have already been taken; wait for the book to refresh")
        remaining, cost = qty, 0.0
        for lvl in levels:
            price, avail = lvl[0], lvl[1]
            take = min(remaining, avail)
            cost += take * price
            remaining -= take
            if remaining <= 0:
                break
        filled = qty - remaining
        # whole lots only (like the exchange)
        filled = (filled // ins.lot_size) * ins.lot_size
        if filled <= 0:
            raise EngineError(f"Not enough liquidity: less than one lot available in the order book")
        if filled < qty:
            # recompute cost for the lots we can actually fill
            remaining, cost = filled, 0.0
            for lvl in levels:
                take = min(remaining, lvl[1]); cost += take * lvl[0]; remaining -= take
                if remaining <= 0: break
        # record what this fill consumed so the next order (any trainee) can't take the same quantity again
        remaining = filled
        for price, avail in levels:
            take = min(remaining, avail)
            if take > 0:
                sh[side_key][price] = sh[side_key].get(price, 0) + take
            remaining -= take
            if remaining <= 0:
                break
        avg = round(cost / filled, 6)          # exact average of the levels hit (as on a real contract note)
        if limit_price is not None:
            avg = min(avg, limit_price) if side == "BUY" else max(avg, limit_price)
        if (side == "BUY" and avg < levels[0][0] - 1e-9) or (side == "SELL" and avg > levels[0][0] + 1e-9):
            log.error("FILL ANOMALY %s %s qty=%s filled=%s cost=%s avg=%s levels=%s raw=%s consumed=%s tick=%s",
                      ins.symbol, side, qty, filled, cost, avg, levels[:3], raw_levels[:3], sh[side_key], ins.tick_size)
        px_s = lambda v: (f"{v:.5f}".rstrip("0").rstrip(".") if v < 1000 else f"{v:.2f}")
        b = px_s(levels[0][0]) if side == "SELL" else (px_s(bids[0][0]) if bids else "—")
        a = px_s(levels[0][0]) if side == "BUY" else (px_s(asks[0][0]) if asks else "—")
        note = f"matched vs book: bid {b} / ask {a}"
        if abs(avg - levels[0][0]) > ins.tick_size / 2:
            note += ", filled across levels"
        if filled < qty:
            note += f"; partial: {filled // ins.lot_size}/{qty // ins.lot_size} lots filled, rest cancelled (no more depth)"
        return round(avg, 6), note, filled

    def required_margin(self, db: Session, ins, side: str, qty: int, price: float, leverage: float = None) -> float:
        vf = self.vf(ins)
        if ins.instrument_type in ("CE", "PE") and side == "BUY":
            return round(price * qty * vf, 2)
        if ins.instrument_type in ("CE", "PE"):
            und_tok = self.feed.index_token_for(ins.name)
            und = self.feed.ltp(und_tok) if und_tok else None
            if und is None:
                und = ins.strike
        else:
            und = price            # a future is margined on its own price (a far month trades at its own level)
        # Delta margins options like perpetuals: initial_margin % of the underlying notional (0.5% for
        # BTC/ETH = 200x) plus the option's mark price for sellers; liquidation is decided on the mark.
        pct = ins.init_margin_pct or self.margin_pct(db, ins.exchange, ins.name)
        if leverage and leverage > 0 and ins.leverage_options:
            pct = max(pct, 100.0 / leverage)      # trader chose less leverage than the contract allows
        m = und * qty * pct / 100.0
        if ins.instrument_type in ("CE", "PE"):
            m += price * qty  # short option: margin + premium received as collateral
        return round(m * vf, 2)

    def mark_price(self, token: int, qty: int) -> Optional[float]:
        """Liquidation value: longs marked at best bid, shorts at best ask. Falls back to LTP if
        liquidity checks are off or the book side is empty."""
        t = self.feed.prices.get(token)
        if not t:
            return None
        if getattr(self, "_mark_at_book", True):
            if qty > 0 and t.get("bid") is not None:
                return t["bid"]
            if qty < 0 and t.get("ask") is not None:
                return t["ask"]
        return t.get("ltp")

    def _position(self, db: Session, user_id: int, token: int) -> Optional[Position]:
        return (db.query(Position).filter_by(user_id=user_id, token=token, is_closed=False)
                .order_by(Position.id.desc()).first())

    def _ledger(self, db: Session, user: User, amount: float, kind: str, note: str = ""):
        user.balance = round(user.balance + amount, 2)
        db.add(Ledger(user_id=user.id, amount=round(amount, 2), balance_after=user.balance, kind=kind, note=note))

    def funds(self, db: Session, user: User) -> dict:
        used = sum(p.margin_blocked for p in db.query(Position).filter_by(user_id=user.id, is_closed=False))
        used += sum(o.margin_blocked for o in db.query(Order).filter_by(user_id=user.id, status="OPEN"))
        unreal = 0.0
        for p in db.query(Position).filter_by(user_id=user.id, is_closed=False):
            mk = self.mark_price(p.token, p.qty)
            if mk is not None:
                unreal += (mk - p.avg_price) * p.qty * self.vf(self.feed.instruments.get(p.token))
        # realised today (IST calendar day) net of commission, from the ledger
        from datetime import datetime, timedelta
        day_start = datetime.combine(ist_now().date(), datetime.min.time()) - timedelta(hours=5, minutes=30)
        realised_today = sum(l.amount for l in db.query(Ledger).filter(
            Ledger.user_id == user.id, Ledger.created_at >= day_start,
            Ledger.kind.in_(["REALISED_PNL", "COMMISSION", "EXPIRY_SETTLEMENT"])))
        maint = self.maintenance(db, user)
        return {"balance": round(user.balance, 2), "used_margin": round(used, 2),
                "available": round(user.balance + min(0.0, unreal) - used, 2), "unrealised": round(unreal, 2),
                "realised_today": round(realised_today, 2), "equity": round(user.balance + unreal, 2),
                "maintenance": round(maint, 2)}

    def maintenance(self, db: Session, user: User) -> float:
        """Maintenance requirement across open positions: exchange % of notional where published
        (Delta), otherwise MAINT_SHARE of the margin blocked. Long options need none (premium paid)."""
        from .config import MAINT_SHARE
        total = 0.0
        for p in db.query(Position).filter_by(user_id=user.id, is_closed=False):
            ins = self.feed.instruments.get(p.token)
            if ins and ins.instrument_type in ("CE", "PE") and p.qty > 0:
                continue
            if ins and ins.maint_margin_pct:
                und_tok = self.feed.index_token_for(ins.name)
                und = (self.feed.ltp(und_tok) if und_tok else None) or self.mark_price(p.token, p.qty) or p.avg_price
                m = abs(p.qty) * und * ins.maint_margin_pct / 100.0
                if ins.instrument_type in ("CE", "PE"):
                    # short option: Delta adds the current mark price of the option (buy-back cost)
                    mk = self.mark_price(p.token, p.qty) or self.feed.ltp(p.token) or p.avg_price
                    m += abs(p.qty) * mk
                total += m * self.vf(ins)
            else:
                total += p.margin_blocked * MAINT_SHARE
        return total

    # ---- orders ----------------------------------------------------------------
    def place_order(self, db: Session, user: User, token: int, side: str, lots: int,
                    order_type: str = "MARKET", limit_price: float = None, trigger_price: float = None,
                    leverage: float = None) -> Order:
        ins = self.feed.instruments.get(token)
        if not ins or ins.segment == "INDICES":
            raise EngineError("Unknown or non-tradable instrument")
        if not user.is_active:
            raise EngineError("Account is frozen")
        side = side.upper(); order_type = order_type.upper()
        if side not in ("BUY", "SELL"):
            raise EngineError("side must be BUY or SELL")
        if order_type not in ("MARKET", "LIMIT", "SL"):
            raise EngineError("order_type must be MARKET, LIMIT or SL")
        max_lots = max(500, ins.pos_limit // max(ins.lot_size, 1)) if ins.pos_limit else 500
        if lots < 1 or lots > max_lots:
            raise EngineError(f"lots must be 1..{max_lots}")
        if not self.market_open(ins.exchange):
            raise EngineError(f"{ins.exchange} market is closed")
        cry = getattr(self.feed, "crypto", None)
        if cry and token in cry.items and not cry.connected:
            raise EngineError("Crypto live prices are offline right now — trading is paused until the feed is back")
        if cry and token in cry.items and not cry.fx_ready():
            raise EngineError("Waiting for the ₹ conversion rate — crypto trading resumes in a moment")
        fx = getattr(self.feed, "forex", None)
        if fx and token in fx.items:
            if not fx.connected:
                raise EngineError("Forex prices are offline right now — trading is paused until the feed is back")
            if not fx.fx_ready(ins):
                raise EngineError("Waiting for the rupee conversion rate for this pair — try again in a moment")
        ltp = self.feed.ltp(token)
        if ltp is None or (self.feed.tick_age(token) or 0) > 300:
            # Not yet subscribed / stale. Subscribe and ask client to retry.
            self.feed.pin([token])
            if not self.feed.connected:
                raise EngineError("Live prices are offline right now — trading is paused until the feed is back")
            raise EngineError("No live price yet for this contract — try again in a second")
        if order_type == "LIMIT" and (limit_price is None or limit_price <= 0):
            raise EngineError("limit_price required")
        if order_type == "SL" and (trigger_price is None or trigger_price <= 0):
            raise EngineError("trigger_price required")
        if order_type == "SL" and ltp:
            # Like the exchange: a sell SL must trigger below the market, a buy SL above it. A trigger on
            # the wrong side would fire instantly as a market order — not what a stop is for.
            if side == "SELL" and trigger_price >= ltp:
                raise EngineError(f"Stop-loss SELL trigger ({trigger_price:g}) must be below the last price ({ltp:g})")
            if side == "BUY" and trigger_price <= ltp:
                raise EngineError(f"Stop-loss BUY trigger ({trigger_price:g}) must be above the last price ({ltp:g})")

        qty = lots * ins.lot_size
        from .config import FREEZE_QTY
        fz = FREEZE_QTY.get(ins.name) if ins.exchange in ("NFO", "BFO") else None
        if fz and qty > fz:
            raise EngineError(f"Exceeds the exchange freeze quantity for {ins.name} ({fz // ins.lot_size} lots per order) — split the order")
        if ins.pos_limit:
            pos = self._position(db, user.id, token)
            cur = pos.qty if pos else 0
            new = cur + (qty if side == "BUY" else -qty)
            if abs(new) > ins.pos_limit and abs(new) > abs(cur):
                raise EngineError(f"Exceeds the exchange position limit of {ins.pos_limit:,} contracts for {ins.symbol}")
        if ins.price_band_pct:
            # band measured from the touch (best bid/ask), never from a stale last trade
            ref = limit_price if order_type == "LIMIT" else trigger_price if order_type == "SL" else None
            tk = self.feed.prices.get(token) or {}
            anchor = (tk.get("ask") if side == "BUY" else tk.get("bid")) or ltp
            lo = min(tk.get("bid") or anchor, anchor) * (1 - ins.price_band_pct / 100)
            hi = max(tk.get("ask") or anchor, anchor) * (1 + ins.price_band_pct / 100)
            if ref and anchor and not (lo <= ref <= hi):
                raise EngineError(f"Price outside the exchange band (±{ins.price_band_pct:g}% around {anchor}) — the exchange would reject this order")
        if leverage is not None:
            if not ins.leverage_options:
                leverage = None
            else:
                mx = max(ins.leverage_options)
                if not (1 <= leverage <= mx):
                    raise EngineError(f"Leverage must be between 1x and {mx:g}x for this contract")
                leverage = round(float(leverage), 2)
        order = Order(user_id=user.id, token=token, symbol=ins.symbol, exchange=ins.exchange, side=side,
                      order_type=order_type, lots=lots, qty=qty, limit_price=limit_price,
                      trigger_price=trigger_price, status="OPEN", leverage=leverage)
        db.add(order)
        db.flush()

        if order_type == "MARKET":
            try:
                px, note, filled = self.book_fill(db, ins, side, qty)
            except EngineError as err:
                order.status = "REJECTED"; order.reason = str(err)
                db.commit()
                self._emit(user.id, {"type": "order", "order": self.order_dict(order)})
                raise
            if filled < qty:
                order.qty = filled; order.lots = filled // ins.lot_size
            self._fill(db, user, order, px)
            if note and order.status == "FILLED":
                order.reason = note
            if order.status == "FILLED":
                order.fill_price = px  # always the counterparty price, never LTP
        else:
            # reserve margin for the opening part so user can't over-commit
            ref_price = limit_price if order_type == "LIMIT" else ltp
            need = self._opening_margin(db, user, ins, side, qty, ref_price, leverage)
            f = self.funds(db, user)
            if need > f["available"] + 1e-6:
                order.status = "REJECTED"; order.reason = f"Insufficient coins: need ₹{need:,.2f}, available ₹{f['available']:,.2f}"
            else:
                order.margin_blocked = need
                self.feed.pin([token])
                self._pending_tokens.add(token)
        db.commit()
        self._emit(user.id, {"type": "order", "order": self.order_dict(order)})
        if order.status == "REJECTED":
            raise EngineError(order.reason)
        return order

    def _opening_margin(self, db, user, ins, side, qty, price, leverage=None) -> float:
        """Margin needed for the part of this order that opens new exposure (netting against existing)."""
        pos = self._position(db, user.id, ins.token)
        cur = pos.qty if pos else 0
        signed = qty if side == "BUY" else -qty
        new = cur + signed
        if cur == 0 or (cur > 0) == (signed > 0):
            opening = qty
        else:
            opening = max(0, abs(new)) if (new > 0) != (cur > 0) else 0
        if opening == 0:
            return 0.0
        return self.required_margin(db, ins, side, opening, price, leverage)

    def cancel_order(self, db: Session, user: User, order_id: int):
        o = db.query(Order).filter_by(id=order_id, user_id=user.id).first()
        if not o or o.status != "OPEN":
            raise EngineError("Order not open")
        o.status = "CANCELLED"; o.margin_blocked = 0.0
        db.commit()
        self._emit(user.id, {"type": "order", "order": self.order_dict(o)})

    def cancel_pending_for(self, db: Session, user: User, token: int) -> int:
        """Cancel resting LIMIT/SL orders on a contract (used when a position is exited from the
        Positions screen, so a leftover stop-loss can't silently open a fresh position)."""
        n = 0
        for o in db.query(Order).filter_by(user_id=user.id, token=token, status="OPEN").all():
            o.status = "CANCELLED"; o.margin_blocked = 0.0; o.reason = "Cancelled — position exited"
            n += 1
            self._emit(user.id, {"type": "order", "order": self.order_dict(o)})
        if n:
            db.commit()
        return n

    def _fill(self, db: Session, user: User, order: Order, price: float):
        ins = self.feed.instruments[order.token]
        qty = order.qty
        signed = qty if order.side == "BUY" else -qty
        pos = self._position(db, user.id, order.token)
        reserved = order.margin_blocked or 0.0  # pending reservation, replaced by position margin below
        order.margin_blocked = 0.0

        cur = pos.qty if pos else 0
        new = cur + signed
        realised = 0.0

        # margin check on the opening part
        if cur == 0 or (cur > 0) == (signed > 0):
            opening_qty = qty
        else:
            opening_qty = abs(new) if (new != 0 and (new > 0) != (cur > 0)) else 0
        need = self.required_margin(db, ins, order.side, opening_qty, price, order.leverage) if opening_qty else 0.0
        vf = self.vf(ins)
        comm = round(price * qty * vf * self.commission_pct(db, ins.exchange) / 100.0, 2)
        db.flush()
        f = self.funds(db, user)  # reservation already zeroed above, so not double counted
        avail = f["available"]
        # a trade that only reduces exposure is always allowed (commission is still charged; the
        # balance may go negative, like a broker's debit balance after a square-off)
        if opening_qty and need + comm > avail + 1e-6:
            order.status = "REJECTED"
            order.reason = f"Insufficient coins: need ₹{need + comm:,.2f} (incl. ₹{comm:,.2f} commission), available ₹{avail:,.2f}"
            return

        if pos is None:
            pos = Position(user_id=user.id, token=order.token, symbol=ins.symbol, exchange=ins.exchange,
                           lot_size=ins.lot_size, qty=0, avg_price=0.0, expiry=ins.expiry)
            db.add(pos); db.flush()

        if cur == 0 or (cur > 0) == (signed > 0):
            # adding to position
            total = abs(cur) + qty
            pos.avg_price = (pos.avg_price * abs(cur) + price * qty) / total
            pos.qty = new
            pos.margin_blocked = round(pos.margin_blocked + need, 2)
        else:
            # reducing / closing / flipping
            closing = min(abs(cur), qty)
            realised = (price - pos.avg_price) * closing * (1 if cur > 0 else -1) * vf
            pos.realised_pnl = round(pos.realised_pnl + realised, 2)
            # release margin proportionally
            released = pos.margin_blocked * closing / abs(cur)
            pos.margin_blocked = round(pos.margin_blocked - released, 2)
            if new == 0:
                pos.qty = 0; pos.margin_blocked = 0.0; pos.is_closed = True
                # position is flat: a leftover stop/limit on this contract would silently open a new one
                for o2 in db.query(Order).filter_by(user_id=user.id, token=order.token, status="OPEN").all():
                    if o2.id != order.id:
                        o2.status = "CANCELLED"; o2.margin_blocked = 0.0; o2.reason = "Cancelled — position closed"
                        self._emit(user.id, {"type": "order", "order": self.order_dict(o2)})
            elif (new > 0) != (cur > 0):
                # flipped: remaining qty opens new position at fill price
                pos.is_closed = True; pos.qty = 0; pos.margin_blocked = 0.0
                npos = Position(user_id=user.id, token=order.token, symbol=ins.symbol, exchange=ins.exchange,
                                lot_size=ins.lot_size, qty=new, avg_price=price, expiry=ins.expiry,
                                margin_blocked=need)
                db.add(npos)
            else:
                pos.qty = new
            if realised:
                self._ledger(db, user, realised, "REALISED_PNL", f"{order.side} {closing} {ins.symbol} @ {price}")

        if comm > 0:
            self._ledger(db, user, -comm, "COMMISSION",
                         f"{self.commission_pct(db, ins.exchange):g}% on {order.side} {qty} {ins.symbol} @ {price} (₹{price * qty * vf:,.0f})")
        order.status = "FILLED"; order.fill_price = price
        db.add(Trade(user_id=user.id, order_id=order.id, token=order.token, symbol=ins.symbol,
                     exchange=ins.exchange, side=order.side, qty=qty, price=price, realised_pnl=round(realised, 2),
                     commission=comm))
        self.feed.pin([order.token])

    # ---- tick handling: pending orders ------------------------------------------
    def _on_tick(self, tick: dict):
        tok = tick["token"]
        if tok not in self._pending_tokens or tok in self._pending_scheduled:
            return
        self._pending_scheduled.add(tok)
        asyncio.get_event_loop().create_task(self._process_pending(tok, tick["ltp"]))

    async def _process_pending(self, token: int, ltp: float):
        async with self._lock:
            self._pending_scheduled.discard(token)
            ltp = self.feed.ltp(token) or ltp   # use the freshest price by the time we run
            db = SessionLocal()
            try:
                orders = db.query(Order).filter_by(token=token, status="OPEN").all()
                if not orders:
                    self._pending_tokens.discard(token)
                    return
                ins = self.feed.instruments.get(token)
                tick = self.feed.prices.get(token) or {}
                on, _, _ = self.liquidity_settings(db)
                bid, ask = tick.get("bid"), tick.get("ask")
                for o in orders:
                    if not self.market_open(ins.exchange):
                        continue
                    fill_at = None; note = ""
                    if o.order_type == "LIMIT":
                        if on:
                            # real matching: a buy fills only when someone is offering at/below our price,
                            # and only for the quantity actually offered there (rest stays open)
                            if o.side == "BUY" and ask is not None and ask <= o.limit_price or \
                               o.side == "SELL" and bid is not None and bid >= o.limit_price:
                                try:
                                    fill_at, note, _f = self.book_fill(db, ins, o.side, o.qty, limit_price=o.limit_price)
                                    note = note.split("; partial:")[0]
                                except EngineError:
                                    continue       # depth at our price already taken — keep waiting
                                if _f < o.qty:
                                    rest = o.qty - _f
                                    # remainder keeps resting as its own order with its share of the reservation
                                    db.add(Order(user_id=o.user_id, token=o.token, symbol=o.symbol, exchange=o.exchange,
                                                 side=o.side, order_type="LIMIT", lots=rest // ins.lot_size, qty=rest,
                                                 limit_price=o.limit_price, status="OPEN", leverage=o.leverage,
                                                 margin_blocked=round((o.margin_blocked or 0) * rest / o.qty, 2),
                                                 reason=f"remainder of order #{o.id}"))
                                    o.margin_blocked = round((o.margin_blocked or 0) * _f / o.qty, 2)
                                    o.qty = _f; o.lots = _f // ins.lot_size
                                    note += f"; partial: {_f // ins.lot_size} lots filled, {rest // ins.lot_size} still open"
                        elif (o.side == "BUY" and ltp <= o.limit_price) or (o.side == "SELL" and ltp >= o.limit_price):
                            fill_at = o.limit_price
                    elif o.order_type == "SL":
                        if (o.side == "BUY" and ltp >= o.trigger_price) or (o.side == "SELL" and ltp <= o.trigger_price):
                            try:
                                fill_at, _n, _f = self.book_fill(db, ins, o.side, o.qty)
                                if _f < o.qty:
                                    o.qty = _f; o.lots = _f // ins.lot_size
                            except EngineError as err:
                                o.status = "REJECTED"; o.reason = f"Stop-loss triggered but {err}"; o.margin_blocked = 0.0
                                db.commit()
                                self._emit(o.user_id, {"type": "order", "order": self.order_dict(o)})
                                continue
                    if fill_at is None:
                        continue
                    user = db.get(User, o.user_id)
                    self._fill(db, user, o, fill_at)
                    if note and o.status == "FILLED":
                        o.reason = note
                    db.commit()
                    self._emit(user.id, {"type": "order", "order": self.order_dict(o)})
                    self._emit(user.id, {"type": "refresh"})
            except Exception:
                log.exception("pending order processing failed")
                db.rollback()
            finally:
                db.close()

    def load_pending(self):
        db = SessionLocal()
        try:
            # Legacy positions opened before MCX lot multipliers were applied can't be netted against the
            # corrected lot size; settle them at the current exit price with a note (one-time cleanup).
            for p in db.query(Position).filter_by(is_closed=False).all():
                ins = self.feed.instruments.get(p.token)
                if ins and ins.lot_size != p.lot_size:
                    mk = self.mark_price(p.token, p.qty) or self.feed.ltp(p.token) or p.avg_price
                    user = db.get(User, p.user_id)
                    realised = (mk - p.avg_price) * p.qty
                    p.realised_pnl = round(p.realised_pnl + realised, 2)
                    db.add(Trade(user_id=user.id, token=p.token, symbol=p.symbol, exchange=p.exchange,
                                 side="SELL" if p.qty > 0 else "BUY", qty=abs(p.qty), price=mk, realised_pnl=round(realised, 2)))
                    self._ledger(db, user, realised, "LOT_SIZE_CORRECTION", f"{p.symbol} settled @ {mk} (lot size corrected {p.lot_size}->{ins.lot_size})")
                    p.qty = 0; p.margin_blocked = 0.0; p.is_closed = True
                    log.warning("settled legacy position %s for user %s due to lot size change", p.symbol, user.username)
            db.commit()
            toks = {o.token for o in db.query(Order).filter_by(status="OPEN")}
            toks |= {p.token for p in db.query(Position).filter_by(is_closed=False)}
            # underlying reference prices for margin / maintenance of open positions
            for p in db.query(Position).filter_by(is_closed=False):
                ins = self.feed.instruments.get(p.token)
                ut = self.feed.index_token_for(ins.name) if ins else None
                if ut:
                    toks.add(ut)
            self._pending_tokens |= {o.token for o in db.query(Order).filter_by(status="OPEN")}
            from .feed.base import INDEX_NAMES
            idx = [i.token for i in self.feed.instruments.values() if i.segment == "INDICES" and i.name in INDEX_NAMES]
            self.feed.pin(list(toks) + idx)
        finally:
            db.close()

    # ---- liquidation (margin call) --------------------------------------------------
    async def liquidation_loop(self):
        while True:
            try:
                await self._check_liquidations()
            except Exception:
                log.exception("liquidation check failed")
            await asyncio.sleep(3)

    async def _check_liquidations(self):
        async with self._lock:
            db = SessionLocal()
            try:
                uids = {p.user_id for p in db.query(Position).filter_by(is_closed=False).all()}
                for uid in uids:
                    user = db.get(User, uid)
                    if not user:
                        continue
                    f = self.funds(db, user)
                    if f["maintenance"] > 0 and f["equity"] < f["maintenance"]:
                        self._liquidate(db, user, f)
            finally:
                db.close()

    def _liquidate(self, db: Session, user: User, f: dict):
        """Force-close every open position at the book (what the exchange/broker RMS does), cancel
        resting orders. Positions with no counterparty depth are retried on the next pass."""
        note = f"Liquidated — equity ₹{f['equity']:,.0f} fell below maintenance ₹{f['maintenance']:,.0f}"
        for o in db.query(Order).filter_by(user_id=user.id, status="OPEN").all():
            o.status = "CANCELLED"; o.margin_blocked = 0.0; o.reason = "Cancelled — margin call"
        closed = 0
        for p in db.query(Position).filter_by(user_id=user.id, is_closed=False).all():
            ins = self.feed.instruments.get(p.token)
            if not ins or not self.market_open(ins.exchange):
                continue
            side = "SELL" if p.qty > 0 else "BUY"
            try:
                px, bnote, filled = self.book_fill(db, ins, side, abs(p.qty))
            except EngineError as e:
                log.warning("liquidation %s %s: %s", user.username, p.symbol, e)
                continue
            order = Order(user_id=user.id, token=p.token, symbol=p.symbol, exchange=p.exchange, side=side,
                          order_type="MARKET", lots=filled // ins.lot_size, qty=filled, status="OPEN")
            db.add(order); db.flush()
            self._fill(db, user, order, px)
            if order.status == "FILLED":
                order.reason = f"{note} · {bnote}"; order.fill_price = px; closed += 1
            self._emit(user.id, {"type": "order", "order": self.order_dict(order)})
        if closed:
            self._ledger(db, user, 0.0, "LIQUIDATION", note)
            db.commit()
            log.warning("LIQUIDATION user=%s positions=%d %s", user.username, closed, note)
            self._emit(user.id, {"type": "refresh", "message": "Margin call: your positions were liquidated at market"})
        else:
            db.commit()

    # ---- expiry settlement ------------------------------------------------------
    async def expiry_loop(self):
        while True:
            try:
                await self._settle_expired()
            except Exception:
                log.exception("expiry settlement failed")
            await asyncio.sleep(60)

    async def _settle_expired(self):
        n = ist_now()
        today = n.date().isoformat()
        hm = n.strftime("%H:%M")
        async with self._lock:
            db = SessionLocal()
            try:
                for p in db.query(Position).filter_by(is_closed=False).all():
                    if not p.expiry:
                        continue
                    from .market_calendar import close_time_str
                    close_time = close_time_str(p.exchange)
                    if p.expiry < today or (p.expiry == today and hm >= close_time):
                        ins = self.feed.instruments.get(p.token)
                        ltp = None
                        if ins and ins.instrument_type in ("CE", "PE"):
                            # options settle at intrinsic value vs the underlying (exchange rule), never at a stale LTP
                            und = self.feed.ltp(self.feed.index_token_for(ins.name) or -1)
                            if und is not None:
                                ltp = max(0.0, (und - ins.strike) if ins.instrument_type == "CE" else (ins.strike - und))
                        if ltp is None:
                            ltp = self.feed.ltp(p.token)
                        if ltp is None:
                            if ins and ins.instrument_type in ("CE", "PE"):
                                continue  # wait until the underlying price is available
                            ltp = p.avg_price
                        user = db.get(User, p.user_id)
                        realised = (ltp - p.avg_price) * p.qty * self.vf(ins)
                        p.realised_pnl = round(p.realised_pnl + realised, 2)
                        db.add(Trade(user_id=user.id, token=p.token, symbol=p.symbol, exchange=p.exchange,
                                     side="SELL" if p.qty > 0 else "BUY", qty=abs(p.qty), price=ltp,
                                     realised_pnl=round(realised, 2)))
                        self._ledger(db, user, realised, "EXPIRY_SETTLEMENT", f"{p.symbol} settled @ {ltp}")
                        p.qty = 0; p.margin_blocked = 0.0; p.is_closed = True
                        db.commit()
                        self._emit(user.id, {"type": "refresh", "message": f"{p.symbol} expired and settled at {ltp}"})
                # cancel open orders on expired contracts
                for o in db.query(Order).filter_by(status="OPEN").all():
                    ins = self.feed.instruments.get(o.token)
                    if ins and ins.expiry and ins.expiry < today:
                        o.status = "CANCELLED"; o.reason = "contract expired"; o.margin_blocked = 0.0
                db.commit()
            finally:
                db.close()

    # ---- serialisers ----------------------------------------------------------------
    @staticmethod
    def order_dict(o: Order) -> dict:
        return {"id": o.id, "token": o.token, "symbol": o.symbol, "exchange": o.exchange, "side": o.side, "leverage": o.leverage,
                "order_type": o.order_type, "lots": o.lots, "qty": o.qty, "limit_price": o.limit_price,
                "trigger_price": o.trigger_price, "status": o.status, "fill_price": o.fill_price,
                "reason": o.reason, "created_at": o.created_at.isoformat() + "Z"}

    def position_dict(self, p: Position) -> dict:
        ltp = self.feed.ltp(p.token)
        mk = self.mark_price(p.token, p.qty)
        vf = self.vf(self.feed.instruments.get(p.token))
        unreal = round((mk - p.avg_price) * p.qty * vf, 2) if (mk is not None and p.qty) else 0.0
        lev = None
        if p.exchange in ("CRYPTO", "FOREX") and p.margin_blocked and mk:
            lev = round(abs(p.qty) * mk * vf / p.margin_blocked)      # effective leverage of the position
        return {"id": p.id, "token": p.token, "symbol": p.symbol, "exchange": p.exchange, "lot_size": p.lot_size, "value_factor": vf, "leverage": lev,
                "qty": p.qty, "lots": p.qty // p.lot_size if p.lot_size else 0, "avg_price": round(p.avg_price, 5),
                "ltp": ltp, "mark": mk, "unrealised": unreal, "realised": round(p.realised_pnl, 2),
                "margin": round(p.margin_blocked, 2), "expiry": p.expiry, "is_closed": p.is_closed}
