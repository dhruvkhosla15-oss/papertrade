#!/bin/bash
# Private copy of the whole site on this machine (simulated prices, throw-away database), then the
# daily safety check is run against it. Nothing here touches the live site.
#   tools/selftest/run.sh            -> run the safety check, print every line, exit 1 if any check fails
#   tools/selftest/run.sh keep       -> same, but leave the copy running on http://localhost:8001 (admin / admin123)
# Extra env for the fake forex/global feed: FAKE_CLOSED=US500 (contract shut), FAKE_MULT=US500:0.99 (price shifted),
# FAKE_OPEN=1 (every Global contract open all week, so Global can be attacked on a weekend too)
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"; ROOT="$(cd "$HERE/../.." && pwd)"; cd "$ROOT"
DATA="${PT_SELFTEST_DIR:-/tmp/lfx-selftest}"; [ "${PT_SELFTEST_FRESH:-1}" = "1" ] && rm -rf "$DATA"; mkdir -p "$DATA"
pkill -f "uvicorn app.main:app --port 8001" 2>/dev/null; pkill -f fake_crypto_feed.py 2>/dev/null; pkill -f fake_forex_feed.py 2>/dev/null; sleep 1
(python3 "$HERE/fake_crypto_feed.py" >/dev/null 2>&1 &)
(python3 "$HERE/fake_forex_feed.py" >/dev/null 2>&1 &)
(PT_FEED=mock PT_DATA_DIR="$DATA" PT_CANONICAL_HOST=www.limefx.in PT_PROBE_AT=99:99 PT_WEEK_TEST=1 PT_ACCESS_ALL=1 PT_STRICT_LIQ_GRACE_MIN=0 \
 PT_DELTA_REST=http://localhost:8765 PT_DELTA_WS=ws://localhost:8765 PT_CTRADER_WS=ws://localhost:8766 \
 PT_CTRADER_CLIENT_ID=cid PT_CTRADER_CLIENT_SECRET=csec PT_CTRADER_ACCOUNT=10135462 PT_CTRADER_TOKEN=tok-ok \
 python3 -m uvicorn app.main:app --port 8001 >"$DATA/server.log" 2>&1 &)
for i in $(seq 1 60); do sleep 1; curl -s localhost:8001/ >/dev/null 2>&1 && break; done
sleep 40   # the simulated forex/global feed needs about half a minute to list its contracts
python3 - <<'PY'
import httpx, sys
c = httpx.Client(base_url="http://localhost:8001", timeout=600)
assert c.post("/api/login", json={"username": "admin", "password": "admin123"}).status_code == 200
r = c.post("/api/admin/probe/run"); j = r.json()
if r.status_code != 200:
    print("could not run:", r.status_code, j); sys.exit(2)
for x in j["rows"]:
    print({True: "PASS", False: "FAIL", None: " .. "}[x["ok"]], x["area"], "|", x["check"], "|", x["info"])
print(f"\nRESULT {j['passed']} passed, {j['failed']} failed, {j['secs']}s")
sys.exit(1 if j["failed"] else 0)
PY
RC=$?
# Normal-working check in a real browser: every screen, tab and Excel file (tools/selftest/site_check.py).
# PT_SITE_CHECK=0 skips it; "full" prints every line instead of only the failures and the total.
if [ "${PT_SITE_CHECK:-1}" != "0" ] && python3 -c "import playwright, pyotp" 2>/dev/null; then
  if [ "${PT_SITE_CHECK:-1}" = "full" ]; then timeout 600 python3 "$HERE/site_check.py"; else timeout 600 python3 "$HERE/site_check.py" 2>&1 | grep -E "^FAIL|^SITE|Traceback|Error"; fi
  SRC=${PIPESTATUS[0]}; [ "$SRC" != "0" ] && { [ "$SRC" = "124" ] && echo "SITE check timed out"; RC=1; }
fi
# Masters under the owner: the walls between the books, the stock of coins, the weekly share (25 Nov 2026).
if [ "${PT_MASTERS_CHECK:-1}" != "0" ]; then
  # The browser check above turns the Master's two-step login on, and this check logs in with the password alone:
  # run after it, it stopped at its first line ("Not logged in") and tested nothing (found 26 Nov 2026). Two-step
  # login is switched off again here, in the private copy's throw-away database only.
  python3 -c "import sqlite3, sys; c = sqlite3.connect(sys.argv[1], timeout=30); c.execute(\"update users set totp_enabled = 0, totp_secret = '' where username = 'admin'\"); c.commit()" "$DATA/papertrade.db"
  timeout 300 python3 "$HERE/masters_check.py" 2>&1 | grep -E "^FAIL|^MASTERS|Traceback|Error"
  [ "${PIPESTATUS[0]}" != "0" ] && RC=1
fi
grep -c "Traceback" "$DATA/server.log" | sed 's/^/server tracebacks: /'
if [ "${1:-}" != "keep" ]; then pkill -f "uvicorn app.main:app --port 8001"; pkill -f fake_crypto_feed.py; pkill -f fake_forex_feed.py; fi
exit $RC
