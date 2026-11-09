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
from .config import DEFAULT_MARGIN_PCT, MARKET_HOURS, ENFORCE_MARKET_HOURS, IST_OFFSET_HOURS

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
    def margin_pct(self, db: Session, exchange: str, name: str = "") -> float:
        from .feed.base import kind_of
        key = "STK" if (name and kind_of(exchange, name) == "stock") else exchange
        v = get_setting(db, f"margin_pct_{key}")
        return float(v) if v else DEFAULT_MARGIN_PCT.get(key, 12.0)

    def market_open(self, exchange: str) -> bool:
        if not ENFORCE_MARKET_HOURS:
            return True
        n = ist_now()
        if n.weekday() >= 5:
            return False
        o, c = MARKET_HOURS.get(exchange, ("09:15", "15:30"))
        hm = n.strftime("%H:%M")
        return o <= hm <= c

    # ---- liquidity / order book ------------------------------------------------
    def liquidity_settings(self, db: Session):
        on = (get_setting(db, "liquidity_check", "true") or "true").lower() == "true"
        self._mark_at_book = on
        spread = float(get_setting(db, "max_spread_pct", "0") or 0)   # 0 = no spread limit (real-market mode)
        stale = int(get_setting(db, "stale_minutes", "0") or 0)        # 0 = no staleness check
        return on, spread, stale

    def book_fill(self, db: Session, ins, side: str, qty: int):
        """Price a market order against the order book. Returns (avg_price, note, filled_qty) or raises EngineError."""
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
            sh = {"sig": sig, "bids": {}, "asks": {}}
            self._consumed[ins.token] = sh
        side_key = "asks" if side == "BUY" else "bids"
        raw_levels = asks if side == "BUY" else bids
        levels = []
        for lvl in raw_levels:
            left = lvl[1] - sh[side_key].get(lvl[0], 0)
            if left > 0:
                levels.append((lvl[0], left))
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
        avg = round(cost / filled / ins.tick_size) * ins.tick_size
        if (side == "BUY" and avg < levels[0][0] - 1e-9) or (side == "SELL" and avg > levels[0][0] + 1e-9):
            log.error("FILL ANOMALY %s %s qty=%s filled=%s cost=%s avg=%s levels=%s raw=%s consumed=%s tick=%s",
                      ins.symbol, side, qty, filled, cost, avg, levels[:3], raw_levels[:3], sh[side_key], ins.tick_size)
        px_s = lambda v: f"{v:.2f}".rstrip("0").rstrip(".")
        b = px_s(levels[0][0]) if side == "SELL" else (px_s(bids[0][0]) if bids else "—")
        a = px_s(levels[0][0]) if side == "BUY" else (px_s(asks[0][0]) if asks else "—")
        note = f"matched vs book: bid {b} / ask {a}"
        if abs(avg - levels[0][0]) > 1e-9:
            note += ", filled across levels"
        if filled < qty:
            note += f"; partial: {filled // ins.lot_size}/{qty // ins.lot_size} lots filled, rest cancelled (no more depth)"
        return round(avg, 2), note, filled

    def required_margin(self, db: Session, ins, side: str, qty: int, price: float) -> float:
        if ins.instrument_type in ("CE", "PE") and side == "BUY":
            return round(price * qty, 2)
        und_tok = self.feed.index_token_for(ins.name)
        und = self.feed.ltp(und_tok) if und_tok else None
        if und is None:
            und = ins.strike if ins.instrument_type in ("CE", "PE") else price
        pct = self.margin_pct(db, ins.exchange, ins.name)
        m = und * qty * pct / 100.0
        if ins.instrument_type in ("CE", "PE"):
            m += price * qty  # short option: margin + premium received as collateral
        return round(m, 2)

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
                unreal += (mk - p.avg_price) * p.qty
        return {"balance": round(user.balance, 2), "used_margin": round(used, 2),
                "available": round(user.balance - used, 2), "unrealised": round(unreal, 2),
                "equity": round(user.balance + unreal, 2)}

    # ---- orders ----------------------------------------------------------------
    def place_order(self, db: Session, user: User, token: int, side: str, lots: int,
                    order_type: str = "MARKET", limit_price: float = None, trigger_price: float = None) -> Order:
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
        if lots < 1 or lots > 500:
            raise EngineError("lots must be 1..500")
        if not self.market_open(ins.exchange):
            raise EngineError(f"{ins.exchange} market is closed")
        ltp = self.feed.ltp(token)
        if ltp is None or (self.feed.tick_age(token) or 0) > 300:
            # Not yet subscribed / stale. Subscribe and ask client to retry.
            self.feed.pin([token])
            raise EngineError("No live price yet for this contract — try again in a second")
        if order_type == "LIMIT" and (limit_price is None or limit_price <= 0):
            raise EngineError("limit_price required")
        if order_type == "SL" and (trigger_price is None or trigger_price <= 0):
            raise EngineError("trigger_price required")

        qty = lots * ins.lot_size
        order = Order(user_id=user.id, token=token, symbol=ins.symbol, exchange=ins.exchange, side=side,
                      order_type=order_type, lots=lots, qty=qty, limit_price=limit_price,
                      trigger_price=trigger_price, status="OPEN")
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
            need = self._opening_margin(db, user, ins, side, qty, ref_price)
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

    def _opening_margin(self, db, user, ins, side, qty, price) -> float:
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
        return self.required_margin(db, ins, side, opening, price)

    def cancel_order(self, db: Session, user: User, order_id: int):
        o = db.query(Order).filter_by(id=order_id, user_id=user.id).first()
        if not o or o.status != "OPEN":
            raise EngineError("Order not open")
        o.status = "CANCELLED"; o.margin_blocked = 0.0
        db.commit()
        self._emit(user.id, {"type": "order", "order": self.order_dict(o)})

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
        need = self.required_margin(db, ins, order.side, opening_qty, price) if opening_qty else 0.0
        db.flush()
        f = self.funds(db, user)  # reservation already zeroed above, so not double counted
        avail = f["available"]
        if need > avail + 1e-6:
            order.status = "REJECTED"
            order.reason = f"Insufficient coins: need ₹{need:,.2f}, available ₹{avail:,.2f}"
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
            realised = (price - pos.avg_price) * closing * (1 if cur > 0 else -1)
            pos.realised_pnl = round(pos.realised_pnl + realised, 2)
            # release margin proportionally
            released = pos.margin_blocked * closing / abs(cur)
            pos.margin_blocked = round(pos.margin_blocked - released, 2)
            if new == 0:
                pos.qty = 0; pos.margin_blocked = 0.0; pos.is_closed = True
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

        order.status = "FILLED"; order.fill_price = price
        db.add(Trade(user_id=user.id, order_id=order.id, token=order.token, symbol=ins.symbol,
                     exchange=ins.exchange, side=order.side, qty=qty, price=price, realised_pnl=round(realised, 2)))
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
                    fill_at = None
                    if o.order_type == "LIMIT":
                        if on:
                            # real matching: a buy fills only when someone is offering at/below our price
                            if o.side == "BUY" and ask is not None and ask <= o.limit_price:
                                fill_at = o.limit_price
                            elif o.side == "SELL" and bid is not None and bid >= o.limit_price:
                                fill_at = o.limit_price
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
            self._pending_tokens |= {o.token for o in db.query(Order).filter_by(status="OPEN")}
            from .feed.base import INDEX_NAMES
            idx = [i.token for i in self.feed.instruments.values() if i.segment == "INDICES" and i.name in INDEX_NAMES]
            self.feed.pin(list(toks) + idx)
        finally:
            db.close()

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
                    close_time = MARKET_HOURS.get(p.exchange, ("09:15", "15:30"))[1]
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
                        realised = (ltp - p.avg_price) * p.qty
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
        return {"id": o.id, "token": o.token, "symbol": o.symbol, "exchange": o.exchange, "side": o.side,
                "order_type": o.order_type, "lots": o.lots, "qty": o.qty, "limit_price": o.limit_price,
                "trigger_price": o.trigger_price, "status": o.status, "fill_price": o.fill_price,
                "reason": o.reason, "created_at": o.created_at.isoformat() + "Z"}

    def position_dict(self, p: Position) -> dict:
        ltp = self.feed.ltp(p.token)
        mk = self.mark_price(p.token, p.qty)
        unreal = round((mk - p.avg_price) * p.qty, 2) if (mk is not None and p.qty) else 0.0
        return {"id": p.id, "token": p.token, "symbol": p.symbol, "exchange": p.exchange, "lot_size": p.lot_size,
                "qty": p.qty, "lots": p.qty // p.lot_size if p.lot_size else 0, "avg_price": round(p.avg_price, 2),
                "ltp": ltp, "mark": mk, "unrealised": unreal, "realised": round(p.realised_pnl, 2),
                "margin": round(p.margin_blocked, 2), "expiry": p.expiry, "is_closed": p.is_closed}
