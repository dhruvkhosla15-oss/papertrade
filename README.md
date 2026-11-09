# LimeFX (paper trading F&O)

A paper-trading platform for NSE/BSE index F&O (Nifty, Bank Nifty, Sensex) and all MCX
contracts, with live Zerodha prices. A **master** account allocates virtual coins to
**trainees**; trainees buy and sell real contracts (real lot sizes, real live prices)
with those coins and see their profit/loss. No real money moves anywhere.

## What's inside

| Part | What it does |
|---|---|
| `app/main.py` | API + WebSocket server (FastAPI) |
| `app/engine.py` | Order engine — fills at the exact live LTP, lot sizes, margin, netting, P&L, expiry settlement |
| `app/feed/kite.py` | Live Zerodha Kite Connect feed (WebSocket ticks + daily instrument download) |
| `app/feed/mock.py` | Simulated feed for trying the app without a Zerodha login |
| `app/static/index.html` | Trainee app — option chain, order ticket, positions, orders, ledger (mobile-first) |
| `app/static/admin.html` | Master panel — create trainees, add/remove coins, watch every position, square off, freeze |

## Rules the engine follows

- **Market orders fill against the live order book** (Zerodha 5-level depth): buys pay the best ask,
  sells get the best bid, walking levels at average price if one level isn't enough — like a real exchange.
- **Real-market rule:** if there is an offer you can buy, if there is a bid you can sell — at *their* price.
  No counterparty → rejected. Not enough depth → partial fill for the lots available, rest cancelled
  (like a real market order). Optional extra guards in Settings: max spread % and "no trade for N minutes"
  (both off by default). Contracts with an empty book appear greyed out.
- **Shadow book:** quantity a paper fill consumes is treated as gone for every trainee until Zerodha's
  live book changes, so one 1-lot offer can't be "bought" twice.
- **Limit orders** rest until the opposite side of the book reaches the price (buy fills when best ask ≤ limit).
- **Stop-loss orders** trigger at the trigger price, then fill like a market order.
- Quantities are whole lots using the exchange lot size (Nifty 75, Bank Nifty 35, Sensex 20, MCX per contract).
- **Margin:** buying options blocks the full premium. Futures and short options block
  *margin % × underlying price × qty* (default 12 % NFO/BFO, 10 % MCX — change in Settings).
- Positions net per contract; realised P&L credits/debits the coin balance immediately.
- Orders are only accepted during exchange hours (NFO/BFO 09:15–15:30, MCX 09:00–23:55 IST).
- On expiry day after close, open positions are **auto-settled** at the last traded price.
- Coins are a ledger: every admin credit/debit and every P&L hit is recorded and visible to the trainee.

## Deploy on a server (recommended: any ₹500–1000/month Ubuntu VPS)

Needs: a VPS with Docker, and a domain/subdomain pointing at it (for HTTPS).

```bash
# 1. on the server
git clone <this repo>  (or upload the zip and unzip)
cd papertrade
cp .env.example .env
nano .env        # fill KITE_API_KEY, KITE_API_SECRET, a random PT_SECRET_KEY, DOMAIN=trade.yourdomain.in

# 2. start (Caddy fetches an HTTPS certificate automatically)
docker compose up -d --build

# 3. in developers.kite.trade -> your app -> set Redirect URL to:
#    https://trade.yourdomain.in/auth/kite/callback
```

Open `https://trade.yourdomain.in/admin`, log in with `PT_ADMIN_USER` / `PT_ADMIN_PASSWORD`,
**change the password** (Account tab), then click **Connect Zerodha**.

### Try it locally first (simulated prices)

```bash
./run_local.sh                       # http://localhost:8000  (login admin / admin123)
PT_FEED=kite ./run_local.sh          # live, with Redirect URL http://127.0.0.1:8000/auth/kite/callback
```

## Daily routine for the master

Zerodha invalidates the API session every morning (~6 AM) and requires a **manual login
once a day** — this is an exchange rule, not something the app can bypass.

1. Any time after 7:30 AM, open the master panel. The red bar says *Zerodha not connected*.
2. Click **Connect Zerodha**, log in with your Zerodha ID/password/TOTP. Takes ~10 seconds.
3. Bar turns green: *live Zerodha prices*. Trainees' screens update automatically.

If you forget, trainees see "Live prices not available" and orders are rejected until you log in.

## Managing trainees

- **Create:** username, display name, password, initial coins.
- **Add / remove coins:** type an amount in the row and press **+** or **−**; a note is optional. Shows up in the trainee's ledger instantly.
- **View:** click a row for live positions, orders, trades and coin ledger.
- **Square off all** closes every open position of that trainee at market.
- **Freeze** blocks login and trading without deleting history.
- **Net P&L** = equity − coins you've allocated, so adding coins never looks like "profit".

## Limits & notes

- Kite Connect is licensed for personal use. Running a small closed training group is how
  people use it in practice; if this becomes a large paid product, switch the feed to a
  licensed data vendor (TrueData / Global Datafeeds). Only `app/feed/kite.py` would change.
- One Kite WebSocket allows 3000 simultaneous instruments. The app subscribes only to what
  trainees are actually viewing or holding, so 50 trainees are fine.
- Margins are a flat percentage approximation, not SPAN+Exposure. Adjust in Settings to
  match what you want to teach.
- Option chain shows strikes for the chosen expiry; Greeks/OI columns are not shown (OI needs Kite "full" mode — easy to add).
- Data lives in `data/papertrade.db` (SQLite). Back it up by copying the folder.
- To change which NFO/BFO underlyings are allowed: `PT_UNDERLYINGS=NIFTY,BANKNIFTY,FINNIFTY,MIDCPNIFTY,SENSEX,BANKEX`. MCX always includes everything.

## Security checklist before going live

1. Change the admin password.
2. Put a long random `PT_SECRET_KEY` in `.env`.
3. Regenerate the Kite API secret in developers.kite.trade if it was ever shared in chat/email, and update `.env`.
4. Keep `.env` out of git (already in `.gitignore`).
