"""Trading access: which segments an account may open new trades in.

Twelve switches. Futures are on by default in the four Indian segments, everything else is off until the
Master activates it (for everybody through the default table, or for one user). A switch that is off stops
NEW exposure only: prices and charts stay visible, and a position already held there can always be reduced
or closed (by the user, by the auto square-off, at expiry).
"""
import json
import os
from typing import Optional

from .db import get_setting, set_setting, Position
from .feed.base import INDEX_NAMES

KEYS = ["IDX_FUT", "IDX_OPT", "STK_FUT", "STK_OPT", "MCX_FUT", "MCX_OPT", "CDS_FUT", "CDS_OPT",
        "CRYPTO_FUT", "CRYPTO_OPT", "FOREX", "GLOBAL"]
LABEL = {"IDX_FUT": "Futures on Indices", "IDX_OPT": "Options on Indices", "STK_FUT": "Futures on Stocks",
         "STK_OPT": "Options on Stocks", "MCX_FUT": "Futures on MCX", "MCX_OPT": "Options on MCX",
         "CDS_FUT": "Futures on Currency", "CDS_OPT": "Options on Currency", "CRYPTO_FUT": "Crypto",
         "CRYPTO_OPT": "Options on Crypto", "FOREX": "Forex", "GLOBAL": "Global markets"}
ROWS = [("Indices", "IDX_FUT", "IDX_OPT"), ("Stocks", "STK_FUT", "STK_OPT"), ("MCX", "MCX_FUT", "MCX_OPT"),
        ("Currency", "CDS_FUT", "CDS_OPT"), ("Crypto", "CRYPTO_FUT", "CRYPTO_OPT"), ("Forex", "FOREX", None),
        ("Global", "GLOBAL", None)]
OPT_KEYS = [k for k in KEYS if k.endswith("_OPT")]
_ALL_ON = os.getenv("PT_ACCESS_ALL") == "1"          # private test copy: everything on unless a test says otherwise
BUILTIN = {k: (_ALL_ON or k in ("IDX_FUT", "STK_FUT", "MCX_FUT", "CDS_FUT")) for k in KEYS}
_PROBE = "zz-probe-"


def key_for(ins) -> Optional[str]:
    """The switch a contract belongs to."""
    if ins is None:
        return None
    opt = ins.instrument_type in ("CE", "PE")
    ex = ins.exchange
    if ex in ("NFO", "BFO"):
        return ("IDX_" if (ins.name or "").upper() in INDEX_NAMES else "STK_") + ("OPT" if opt else "FUT")
    if ex == "MCX":
        return "MCX_OPT" if opt else "MCX_FUT"
    if ex == "CDS":
        return "CDS_OPT" if opt else "CDS_FUT"
    if ex == "CRYPTO":
        return "CRYPTO_OPT" if opt else "CRYPTO_FUT"
    if ex == "FOREX":
        return "GLOBAL" if (ins.segment or "").startswith("GLOBAL") else "FOREX"
    return None


def _load(db, name) -> dict:
    try:
        d = json.loads(get_setting(db, name, "") or "{}")
        return {k: bool(v) for k, v in d.items() if k in KEYS} if isinstance(d, dict) else {}
    except Exception:
        return {}


def default(db) -> dict:
    d = dict(BUILTIN); d.update(_load(db, "access_default")); return d


def overrides(db, uid: int) -> dict:
    return _load(db, f"access_{uid}")


def effective(db, user) -> dict:
    if user.is_admin or (user.username or "").startswith(_PROBE):
        return {k: True for k in KEYS}               # the daily safety check trades every market on its own accounts
    d = default(db); d.update(overrides(db, user.id)); return d


def set_default(db, values: dict):
    d = default(db); d.update({k: bool(v) for k, v in (values or {}).items() if k in KEYS})
    set_setting(db, "access_default", json.dumps(d)); db.commit()


def set_user(db, uid: int, values: Optional[dict]):
    """values None/empty = back to the default. Only switches that differ from the default are kept, so a
    later change of the default still reaches this user for everything the Master did not set himself."""
    base = default(db)
    ov = {k: bool(v) for k, v in (values or {}).items() if k in KEYS and bool(v) != base[k]}
    set_setting(db, f"access_{uid}", json.dumps(ov) if ov else "")
    set_setting(db, f"access_optflat_{uid}", "")     # the Master has decided: no automatic switch-off any more
    db.commit()


def refusal(db, user, ins) -> Optional[str]:
    """None if the account may open new exposure in this contract, else the message to show."""
    k = key_for(ins)
    if k is None or effective(db, user).get(k, False):
        return None
    what = LABEL[k]
    verb = "are" if what.startswith(("Options", "Futures", "Global")) else "is"
    return f"{what} {verb} not activated on your account. You can view prices and charts. To trade, ask your admin to activate it."


def holds_options(engine, db, uid: int) -> bool:
    for p in db.query(Position).filter_by(user_id=uid, is_closed=False).all():
        if not p.qty:
            continue
        ins = engine.feed.instruments.get(p.token)
        if (ins is not None and ins.instrument_type in ("CE", "PE")) or (ins is None and (p.symbol or "").upper().endswith(("CE", "PE"))):
            return True
    return False


def keep_options_while_held(engine, db, user) -> bool:
    """One-time, for accounts that already hold options when the switches arrive: options stay on in the
    Indian segments so they can hedge, until they hold no option at all (see options_flat_check)."""
    if not holds_options(engine, db, user.id):
        return False
    base = default(db); ov = overrides(db, user.id)
    for k in ("IDX_OPT", "STK_OPT", "MCX_OPT", "CDS_OPT"):
        if not base[k]:
            ov[k] = True
    set_setting(db, f"access_{user.id}", json.dumps(ov))
    set_setting(db, f"access_optflat_{user.id}", "1"); db.commit()
    return True


def options_flat_check(engine, db, user) -> bool:
    """Called after a position closes: an account whose options were only kept on while it held some goes
    back to the default for options the moment it holds none. Quietly; returns True when it switched."""
    if (get_setting(db, f"access_optflat_{user.id}", "") or "") != "1" or holds_options(engine, db, user.id):
        return False
    ov = {k: v for k, v in overrides(db, user.id).items() if k not in OPT_KEYS}
    set_setting(db, f"access_{user.id}", json.dumps(ov) if ov else "")
    set_setting(db, f"access_optflat_{user.id}", ""); db.commit()
    return True


def cancel_resting(engine, db, user) -> int:
    """Resting orders that would open new exposure in a segment that is now off are cancelled."""
    from .db import Order
    n = 0
    for o in db.query(Order).filter_by(user_id=user.id, status="OPEN").all():
        ins = engine.feed.instruments.get(o.token)
        if ins is None or refusal(db, user, ins) is None:
            continue
        pos = engine._position(db, user.id, o.token)
        cur = pos.qty if pos else 0
        signed = o.qty if o.side == "BUY" else -o.qty
        if cur and (cur > 0) != (signed > 0) and abs(signed) <= abs(cur):
            continue                                  # an exit: stays
        o.status = "CANCELLED"; o.margin_blocked = 0.0; o.reason = "Cancelled — this segment is not activated on your account"
        n += 1
    if n:
        db.commit()
    return n
