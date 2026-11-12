"""
Exchange calendar: trading hours, weekends and holidays for NSE/BSE F&O and MCX.

Sources (2026): NSE circular CMTR71775 (trading holidays), MCX holiday calendar (morning/evening
sessions), SEBI/NSE closing-auction framework effective 3 Aug 2026 (equity derivatives close 3:40 pm).
MCX's evening close follows US daylight saving: 11:30 pm while US DST is on, 11:55 pm otherwise.

Update HOLIDAYS each December when the exchanges publish the next year's list, or set
PT_HOLIDAYS_JSON='{"NSE": {"2027-01-26": "Republic Day"}, "MCX": {"2027-01-26": "full|Republic Day"}}'.
"""
import json
import os
from datetime import date, datetime, time, timedelta

IST = timedelta(hours=5, minutes=30)

# ---- hours -----------------------------------------------------------------------------------------
EQ_OPEN, EQ_CLOSE = time(9, 15), time(15, 40)          # NFO / BFO (since 3 Aug 2026)
CDS_OPEN, CDS_CLOSE = time(9, 0), time(17, 0)          # NSE currency derivatives
MCX_OPEN, MCX_EVENING = time(9, 0), time(17, 0)

# ---- holidays ---------------------------------------------------------------------------------------
# NSE/BSE: full-day closures (weekday holidays only; weekend ones are closed anyway)
NSE_HOLIDAYS = {
    "2026-01-26": "Republic Day", "2026-03-03": "Holi", "2026-03-26": "Shri Ram Navami",
    "2026-03-31": "Shri Mahavir Jayanti", "2026-04-03": "Good Friday", "2026-04-14": "Dr. Ambedkar Jayanti",
    "2026-05-01": "Maharashtra Day", "2026-05-28": "Bakri Id", "2026-06-26": "Muharram",
    "2026-09-14": "Ganesh Chaturthi", "2026-10-02": "Mahatma Gandhi Jayanti", "2026-10-20": "Dussehra",
    "2026-11-10": "Diwali-Balipratipada", "2026-11-24": "Guru Nanak Jayanti", "2026-12-25": "Christmas",
}
# MCX: "full" = closed all day; "morning" = morning closed, evening session (5 pm) open;
#      "evening" = morning open, evening closed
MCX_HOLIDAYS = {
    "2026-01-01": ("evening", "New Year"), "2026-01-26": ("full", "Republic Day"),
    "2026-03-03": ("morning", "Holi"), "2026-03-26": ("morning", "Shri Ram Navami"),
    "2026-03-31": ("morning", "Shri Mahavir Jayanti"), "2026-04-03": ("full", "Good Friday"),
    "2026-04-14": ("morning", "Dr. Ambedkar Jayanti"), "2026-05-01": ("morning", "Maharashtra Day"),
    "2026-05-28": ("morning", "Bakri Id"), "2026-06-26": ("morning", "Muharram"),
    "2026-09-14": ("morning", "Ganesh Chaturthi"), "2026-10-02": ("full", "Mahatma Gandhi Jayanti"),
    "2026-10-20": ("morning", "Dussehra"), "2026-11-10": ("morning", "Diwali-Balipratipada"),
    "2026-11-24": ("morning", "Guru Nanak Jayanti"), "2026-12-25": ("full", "Christmas"),
}

_extra = os.environ.get("PT_HOLIDAYS_JSON")
if _extra:
    try:
        _j = json.loads(_extra)
        NSE_HOLIDAYS.update(_j.get("NSE", {}))
        for d, v in _j.get("MCX", {}).items():
            kind, _, name = v.partition("|")
            MCX_HOLIDAYS[d] = (kind or "full", name or "Holiday")
    except Exception:
        pass


def ist_now() -> datetime:
    fake = os.environ.get("PT_FAKE_NOW")  # dev/test only
    if fake:
        return datetime.fromisoformat(fake)
    return datetime.utcnow() + IST


def us_dst(d: date) -> bool:
    """US daylight saving: 2nd Sunday of March to 1st Sunday of November."""
    def nth_sunday(y, m, n):
        first = date(y, m, 1)
        off = (6 - first.weekday()) % 7
        return first + timedelta(days=off + 7 * (n - 1))
    return nth_sunday(d.year, 3, 2) <= d < nth_sunday(d.year, 11, 1)


def mcx_close(d: date) -> time:
    return time(23, 30) if us_dst(d) else time(23, 55)


def _sessions(exchange: str, d: date):
    """List of (open_time, close_time) sessions on date d, or [] if closed. Also returns holiday name."""
    if exchange == "CRYPTO":
        return [(time(0, 0), time(23, 59, 59))], None       # 24x7
    if exchange == "FOREX":
        # 24x5: opens Monday 03:30 IST (Sunday 22:00 UTC), closes Saturday 03:30 IST (Friday 22:00 UTC)
        wd = d.weekday()
        if wd == 6:
            return [], "Weekend"
        if wd == 0:
            return [(time(3, 30), time(23, 59, 59))], None
        if wd == 5:
            return [(time(0, 0), time(3, 30))], None
        return [(time(0, 0), time(23, 59, 59))], None
    if d.weekday() >= 5:
        return [], "Weekend"
    ds = d.isoformat()
    if exchange in ("NFO", "BFO", "NSE", "BSE"):
        if ds in NSE_HOLIDAYS:
            return [], NSE_HOLIDAYS[ds]
        return [(EQ_OPEN, EQ_CLOSE)], None
    if exchange == "CDS":
        if ds in NSE_HOLIDAYS:
            return [], NSE_HOLIDAYS[ds]
        return [(CDS_OPEN, CDS_CLOSE)], None
    if exchange == "MCX":
        close = mcx_close(d)
        if ds in MCX_HOLIDAYS:
            kind, name = MCX_HOLIDAYS[ds]
            if kind == "full":
                return [], name
            if kind == "morning":
                return [(MCX_EVENING, close)], name
            if kind == "evening":
                return [(MCX_OPEN, MCX_EVENING)], name
        return [(MCX_OPEN, close)], None
    return [(EQ_OPEN, EQ_CLOSE)], None


def status(exchange: str, now: datetime | None = None) -> dict:
    """{open, holiday, opens_at, closes_at, label, today} — opens_at/closes_at are IST datetimes (ISO) or None."""
    now = now or ist_now()
    today = now.date()
    r = _status(exchange, now, today)
    r["today"] = today.isoformat()
    return r


def _status(exchange, now, today):
    sessions, hol = _sessions(exchange, today)
    for o, c in sessions:
        if o <= now.time() <= c:
            return {"open": True, "holiday": hol, "opens_at": None,
                    "closes_at": datetime.combine(today, c).isoformat(), "label": "open"}
    # next opening today?
    for o, c in sessions:
        if now.time() < o:
            return {"open": False, "holiday": hol, "opens_at": datetime.combine(today, o).isoformat(),
                    "closes_at": None, "label": "holiday" if hol else "pre"}
    # next trading day
    d = today
    for _ in range(14):
        d += timedelta(days=1)
        s2, h2 = _sessions(exchange, d)
        if s2:
            return {"open": False, "holiday": hol, "opens_at": datetime.combine(d, s2[0][0]).isoformat(),
                    "closes_at": None, "label": "holiday" if hol and hol != "Weekend" else ("weekend" if today.weekday() >= 5 else "closed")}
    return {"open": False, "holiday": hol, "opens_at": None, "closes_at": None, "label": "closed"}


def is_open(exchange: str) -> bool:
    return status(exchange)["open"]


def close_time_str(exchange: str, d: date | None = None) -> str:
    d = d or ist_now().date()
    s, _ = _sessions(exchange, d)
    if exchange == "CRYPTO":
        return "17:30"     # Delta India options expire at 5:30 pm IST (12:00 UTC) on their expiry date
    if exchange == "FOREX":
        return "23:59"
    return s[-1][1].strftime("%H:%M") if s else ("17:00" if exchange == "CDS" else "15:40" if exchange != "MCX" else mcx_close(d).strftime("%H:%M"))


def expiry_time_str(exchange: str, d: date | None = None) -> str:
    """When a contract stops trading and is settled on its expiry date. Everywhere this is the session
    close, except NSE currency derivatives: their last trading day ends at 12:30 pm (the contract is then
    settled at the RBI reference rate), although the segment itself stays open until 5 pm."""
    if exchange == "CDS":
        return "12:30"
    return close_time_str(exchange, d)
