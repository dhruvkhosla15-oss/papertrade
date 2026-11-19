"""Technical health of the site (not the trading books): are the background jobs alive, is there disk
space, did the server log errors, does today's backup open, is the broker feed logged in before the open.
Problems go to the owner's Telegram; the same facts are shown on the Master's Settings page and are part
of the daily check.

Every background job calls beat("name") on each round. A job that has not done so for longer than its
allowed gap has stopped or is stuck.
"""
import logging
import os
import shutil
import sqlite3
import time
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path

log = logging.getLogger("watchdog")
IST = timedelta(hours=5, minutes=30)
STARTED = time.time()

# name -> (plain name for the owner, longest allowed silence in seconds)
JOBS = {
    "prices":      ("Live price stream to the screens", 120),
    "squareoff":   ("Margin check and auto square-off", 180),
    "expiry":      ("Expiry settlement and end-of-session square-off", 600),
    "weekly":      ("Weekly settlement clock", 300),
    "feedwatch":   ("Price-feed alarm", 600),
    "daystart":    ("Day-start record", 600),
    "backup":      ("Daily backup", 3 * 3600),
    "dailycheck":  ("Daily safety check clock", 900),
}
_beats: dict = {}
ERRORS_MAX = 20000
_errors = deque(maxlen=ERRORS_MAX)   # (time, logger, message) of ERROR-level log records. Was 400, which hid most of a bad day from the health page and its counts
_alerted: dict = {}                  # problem key -> time the owner was last told


def beat(name: str):
    _beats[name] = time.time()


class _ErrorCounter(logging.Handler):
    def emit(self, record):
        try:
            if record.levelno >= logging.ERROR and record.name != "watchdog":
                _errors.append((time.time(), record.name, record.getMessage()[:500]))
        except Exception:
            pass


def install():
    logging.getLogger().addHandler(_ErrorCounter(level=logging.ERROR))


def errors_since(seconds: float) -> list:
    t = time.time() - seconds
    return [e for e in _errors if e[0] >= t]


def stopped_jobs() -> list:
    """Jobs that are silent for too long. Nothing counts during the first minutes after a restart."""
    now = time.time(); out = []
    if now - STARTED < 300:
        return out
    for name, (label, gap) in JOBS.items():
        last = _beats.get(name)
        if last is None:
            if now - STARTED > max(gap, 600):
                out.append((name, label, None))
        elif now - last > gap:
            out.append((name, label, int(now - last)))
    return out


def disk(data_dir: Path) -> dict:
    try:
        u = shutil.disk_usage(str(data_dir))
        return {"free_mb": round(u.free / 1e6), "total_mb": round(u.total / 1e6), "free_pct": round(u.free / u.total * 100, 1)}
    except Exception:
        return {}


def check_backup(path: Path, live_db: Path) -> dict:
    """Open a backup file and make sure it is a complete, readable copy: SQLite's own integrity check, the
    main tables present, at least as many accounts as... the live file had when it was taken (never more
    ledger lines than the live file has now)."""
    out = {"file": path.name, "ok": False, "why": ""}
    if not path.exists():
        out["why"] = "the backup file is missing"; return out
    try:
        out["kb"] = path.stat().st_size // 1024
        c = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30)
        try:
            if c.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                out["why"] = "the backup file is damaged"; return out
            tables = {r[0] for r in c.execute("select name from sqlite_master where type='table'")}
            need = {"users", "positions", "orders", "trades", "ledger", "settings"}
            if not need <= tables:
                out["why"] = "tables missing: " + ", ".join(sorted(need - tables)); return out
            out["users"] = c.execute("select count(*) from users").fetchone()[0]
            out["ledger"] = c.execute("select count(*) from ledger").fetchone()[0]
            out["coins"] = round(c.execute("select coalesce(sum(balance),0) from users where is_admin=0").fetchone()[0], 2)
        finally:
            c.close()
        if out["users"] < 1:
            out["why"] = "the backup has no accounts in it"; return out
        if live_db and live_db.exists():
            l = sqlite3.connect(f"file:{live_db}?mode=ro", uri=True, timeout=30)
            try:
                live_led = l.execute("select count(*) from ledger").fetchone()[0]
            finally:
                l.close()
            if out["ledger"] > live_led:
                out["why"] = "the backup has more ledger lines than the live books"; return out
        out["ok"] = True
    except Exception as e:
        out["why"] = f"could not open the backup ({type(e).__name__})"
    return out


def due(key: str, every: float) -> bool:
    """True if the owner has not been told about `key` within `every` seconds (and marks it as told now)."""
    now = time.time()
    if now - _alerted.get(key, 0) < every:
        return False
    _alerted[key] = now
    return True


def clear(key: str) -> bool:
    return _alerted.pop(key, None) is not None


def uptime() -> str:
    s = int(time.time() - STARTED); h, m = s // 3600, (s % 3600) // 60
    return f"{h} h {m} min" if h else f"{m} min"


def ist_now() -> datetime:
    return datetime.utcnow() + IST
