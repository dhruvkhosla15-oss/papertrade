# limefx security log

The daily safety check (`app/probe.py`) attacks the live site every day at 10:05 am and 9:35 pm IST with two
hidden test accounts. This file is the memory of the nightly review that keeps adding to it: what has been
tried, what was found, what is waiting for the owner. Newest entry first. Read it before thinking of new
attacks so the same idea is not tried twice.

Rule since 12 Nov 2026 (owner's decision): a fix that is proven on the private copy goes live the same night
(attack refused after the fix, full self-test passes twice with no server errors, nothing in any existing
account is rewritten, honest trading unchanged). Only a fix that cannot meet those conditions waits on a
branch `security-fix/YYYY-MM-DD` for the owner.

## Waiting for the owner
No branch is waiting. Decisions and wishes put to the owner (do not build without his word; do not repeat in the
report once he has answered; what he decided on 19 Nov is under "Owner's decisions" at the end and is not here):
- (20 Nov) Positions opened before the 50x rule keep 200x / 500x until closed: leave them, or ask their owners to
  close by a date? (the daily check notes how many are still open)
- (20 Nov) The time until Monday noon after the weekly settlement also covers Crypto, which trades all weekend; an
  account can hold far more than 50 times its coins in that time (86 times in the test). Shorter time for Crypto?
- (20 Nov) Currency (3% margin, 33x) is now the most leveraged market: below zero on a gap above about 3.5%.
- (20 Nov) A silence rule per crypto contract (one contract silent while the rest of its feed delivers), once the
  daily check's new note has shown the real longest wait; nothing checks whether the NSE / BSE / MCX / Currency
  prices arrive late.
- (20 Nov) The Master page file can be opened by anyone at /admin (no data without login) and its text names the
  price providers; hiding it needs a small login page of its own.
- (20 Nov) Order Book on a phone: Status, the refusal reason and Cancel are off the right edge (needs a layout
  decision); crypto option chain in rupees (Greeks) is wider than a phone; the leverage row shows on a bought option
  although it changes nothing; small tap areas on the Master page on a phone (arrows, coins + / -); Master Users
  table at 1440: Coins column and row buttons beyond the card's edge.
- (20 Nov) User P&L tab: the "This Week" pill is closed trades only while the Overview's "Net P&L (This Week)"
  includes open positions. The user's Excel "Value" column is in the contract's own currency for Crypto / Forex.
- (20 Nov) Activity record: no line when the Master changes his own password, for the daily price-feed login, or
  for a refused action; the errors list can keep a deleted user's login name for up to 7 days.
- (20 Nov) No limit on the number of visitor price connections per address.
- On an expiry day the price-feed login must be done before 12:30 pm (Currency), 3:30 pm (NSE / BSE) and the MCX close.
- Activity record: say WHAT changed (amount, setting old / new, which switch, freeze vs password reset); lines for
  backup / Excel downloads and Master logins; keep a deleted user's coin history. The Master's two-step secret is
  stored readable in the database and on-server backups.
- The app does not state plainly that trading is in coins (amounts carry the rupee sign).
- The items of "What confuses a new user"; bigger tap areas for the Excel links, period pills, "+ Watchlist";
  dashboard cards show our side while the tables show the users' side, unlabelled; more decimals in the weekly
  ledger note for forex pairs; Indian commas in coins messages.
- Whether the login should take the same time for unknown names; a limit on orders per second per account; whether
  the hosting overwrites the visitor's address header.
- Whether Site health should count requests that crash.
(`security-fix/2026-11-16` is on main since 16 Nov 2026; `security-fix/2026-11-14` was put live on 14 Nov 2026,
`security-fix/2026-11-12` on 12 Nov 2026.)

## Ideas already covered by the daily check
- Nonsense numbers: zero / negative / fractional / NaN / Infinity lots, prices, triggers, leverage; junk side and order type
- Leverage outside the contract's range; intraday product on 24-hour markets; stop-loss on the wrong side
- Order with no login; user calling Master endpoints; cancelling / closing another account's order or position
- Market order larger than the account can carry; tiny-limit-price "cheap margin" order; 12 orders at the same instant
- 3 instant round trips (must not gain; trades must equal balance change; ledger must equal balance)
- Limit far above / below the market must fill at the market price
- Exit sent 6 times at once (must not flip the position); Cancel sent 5 times at once (margin freed once)
- Thin option book: buy more than is offered, take the same sellers twice, dump (must lose money)
- Selling into a book with no buyers; closed market / closed Global contract refuses orders
- Prices: stale, zero, negative, bid above ask, last far from bid/ask, rupee conversion rates, live mark for every open position
- Books: balance vs last ledger line on every real account; resting orders / positions with a broken price or margin
- Books: every open position is on a contract the site still lists; no position left unsettled past its expiry day (12 Nov 2026)
- Crypto options stop trading and settle at the exchange's own expiry time (12 Nov 2026); widened 13 Nov 2026 to
  Currency: contracts stop at 12:30 pm on their last day
- Margin shortfall in every market: new order refused, automatic square-off, only the needed lots (12 Nov 2026)
- Frozen price, in every market (13 Nov 2026): an order on a contract nobody is streaming must wait for a live price.
  The check plants a recognisable (worse) price in the frozen book of an unstreamed contract and sends an order;
  a fill at the planted price is the failure. Forex / Global: every contract is always streamed, so only a note.
- Logins (13 Nov 2026): a login made before the password was changed stops working
- Books (13 Nov 2026): the underlying of every open option position is being streamed (so it settles at a live price)
- Books (14 Nov 2026): no open position is valued for the weekly cut-off above the best offer (long) / below the best bid (short)
- Double limit exit, in every market (14 Nov 2026): one lot bought, the same SELL LIMIT placed twice at the same instant
  below the market; the position must end flat, never short
- Price socket (14 Nov 2026): 40 junk orders (zero lots) on 40 unwatched far-month options from one test account; at most
  25 may start streaming, and all are dropped again after half a minute
- Rules at the moment of the fill, in every market (15 Nov 2026): on a test account whose segment is switched off for a
  moment, a 2-lot limit exit rests, one lot is sold at market, the exit fills: the account must end flat, never short.
  (The test accounts trade every market, but the check can switch one segment off on them: `access.effective`.)
- Frozen account, in every market (15 Nov 2026): a buy limit rests, the test account is frozen, the order must be
  cancelled and open nothing
- Books (15 Nov 2026): every future that expired in the last three days had its closing price taken in the last 45
  seconds before it stopped trading (real accounts; needs the position to have been settled within 150 s of the stop).
  With it, as a note only: expired futures settled more than 0.1% away from their own closing price

- Prices offline, in every market (16 Nov 2026): the test account opens one lot; for the length of one function call
  (nothing else on the site can run in between) that market's feed is marked as down and the exit is sent the way the
  Exit button sends it: it must be refused. Crypto and Forex / Global also with the feed marked as silent.
  (`_offline`; restores the mark in the same call; never disconnects anything.)
- Order right after a reconnect, in every market with a contract nobody is streaming (16 Nov 2026): the contract is
  streamed, told what every contract is told when its feed reconnects (`feed.restart_live`), a recognisable worse
  price is planted as the price from before the outage, and an order is sent: refused or filled at a new price, never
  at the planted one. Forex / Global: only a note (every contract is streamed all the time). `_unwatched` now falls
  back to near-the-money options when every future of a small market is being streamed (BSE on the private copy).

- First instant of a session, in every market (17 Nov 2026): the test account opens one lot; for the length of one
  function call (nothing else on the site can run in between) the engine is told that this contract's session opened
  this very moment (`engine.session_opened`), so every price in memory is from before the opening, and the exit is
  sent the way the Exit button sends it: it must be refused ("the market has just opened"). `_session_open`.
- Turns (17 Nov 2026): one test account sends 40 light requests at the same instant; the turnstile reports how many
  of them it worked on at once: never more than its limit for one login (8). `_one_login`, area "Capacity".

- Streams of cancelled orders (18 Nov 2026): at the start of the run a test account rests one far limit order on one
  option nobody is watching and cancels it at once; a minute and a half later the engine must not be keeping that
  contract on the price socket any more. `_leak_start` / `_leak_end`, area "Price socket".
- Master doors (18 Nov 2026): every address under /api/admin is looked at the way it is built (it must depend on
  `current_admin`; a new address added without the lock fails on the day it goes live, without being called), and
  every Master page of figures (GET only) is read as a test user and as a visitor: refused. `_doors`.
- Screens (18 Nov 2026, normal working): what the search box and the futures lists offer for seven underlyings holds
  no contract that has already expired. `_offered`. (At 9:35 pm on an expiry day the day's contracts are still in
  the contract list, so the check bites on the live site.)

- Logins (19 Nov 2026, widened): a login dated before the test account was created is refused (a deleted account's
  login on the next account); a logged-out login stops working while the account's other login goes on. `_dead_logins`.
- Oversized input (19 Nov 2026), as a visitor: a 1.5 MB request with and without its length declared, a login with a
  5,000-letter name (refused and not remembered), the price socket's size rule. `_oversize`, area "Capacity".
- Pending orders (19 Nov 2026): the test account's own limit is lowered to three for a moment; three far limit orders
  rest on the crypto perpetual, the fourth must be refused. `_resting_cap`, `engine.resting_cap_for`.
- Books (19 Nov 2026): every open crypto / forex position older than four minutes (and the site up five minutes) has
  its rupee value per point kept and within 5% of the live one; a note lists positions whose contract is not listed.
- `weekly_sim.py` (19 Nov 2026): "missing contract: …" (7 checks) and "late list: …" (2 checks).

- Logins (20 Nov 2026, widened): 45 more log-outs of the test account do not bring its first logged-out login back
  to life. `_dead_logins`.
- Slow request bodies and socket pace (20 Nov 2026), as a visitor, in-process: 80 requests that announce a body and
  send nothing do not delay the public home data and each gets 408; a socket over its allowance is read slowly.
  `_oversize`, `_slow_bodies`, area "Capacity".
- Master doors (20 Nov 2026, widened): the price-feed login and its return address are built with a login and
  refuse a visitor and a test user without logging an error (skipped with a note for ten minutes after the Master
  started a login); /docs, /redoc, /openapi.json answer 404. `_doors`.
- Prices (20 Nov 2026, read only): no crypto / forex / Global contract with a fresh price is filled against an old
  order book. Notes: positions still above 50x; the longest wait between two prices of a crypto perpetual.
- `weekly_sim.py` (20 Nov 2026): "opening second: …" (5), "slow feed: …" (8), "no conversion rate: …" (2), "position
  limit: …" (2), "Exit closes a position of 800 lots" (1), "feed login: …" (7), "site health: …" (3).

## Normal-working checks added to `site_check.py` (private copy, real browser)
- 20 Nov 2026 (sixteen; each belongs to a fix of that night): Pulse lists; plain refusals; a badly written date;
  square-off message in dollars; pop-up on opening; shortfall shown once; the red bar agrees with the pop-up;
  messages not covering each other; My P&L rounding and line break; Pulse on a 360 phone; option chain on a 360
  phone; a frozen account is told; Master card labels; the crypto margin note (two checks); the user page source
  names no price provider. That block opens its pages with service workers blocked (the app's self-update
  reloaded a page in the middle of a check once).
- 19 Nov 2026 (ten; each belongs to a fix of that night): text typed by the Master is shown as text; Master user
  panel on a phone keeps every button on the screen; a message arriving while a pop-up is open stays; watchlist names
  on a 360-wide phone; an empty search says so; light-theme price flash; the index message; a long error text in
  Site health; the Ledger Statement's top line adds up; after deleting the account that made the newest trade the
  next order goes through. The "all-time Excel Net" comparison reads the Master's figure before and after.
- 18 Nov 2026: search and the futures lists offer no expired contract (Indian date); the Master deletes an account
  that has been through a weekly cut-off; the next account created (same number) has no pop-up, no finished week, no
  position and no switch of the deleted one; the Site health rows show name and value apart. The NIFTY option the
  check trades now comes from the option chain (which options the search lists first depends on the weekday).
- 17 Nov 2026: no screen shows "-₹0" (nothing, with a minus sign); the Master summary Excel has whole paise only; with
  the simulated prices paused, the Master's user panel shows the same Unrealised / Realised / Net P&L as the user's
  row on All Time and on Daily; All Time "Realised" is closed trades only (equal to the server's closed-trade figure).

## Sweep matrix (started 19 Nov 2026)
One row per family (market × order type × account state × market state) and the date it was last really attacked.
Each night: the 5 fresh ideas, plus the 10 rows that have waited longest. Add a row when a feature appears.

| # | Market | Order type | Account state | Market state | Last attacked |
|---|---|---|---|---|---|
| 1 | NSE future | market / exit | normal | open | 20 Nov |
| 2 | NSE future | limit (marketable, far, double exit) | normal | open | 19 Nov |
| 3 | NSE future | stop-loss | normal | open | 18 Nov |
| 4 | NSE option (thin) | market, book depth | normal | open | 18 Nov |
| 5 | NSE option | stop-loss opening a short | normal | open | 19 Nov |
| 6 | NSE option | limit, remainder | normal | open | 18 Nov |
| 7 | NSE any | any | normal | shut / first instant of session | 17 Nov |
| 8 | NSE any | exit / new | normal | feed down / just back | 16 Nov |
| 9 | NSE any | any | normal | expiry minute | 15 Nov |
| 10 | NSE future | market | normal | weekly cut-off in the same instant | 19 Nov |
| 11 | NSE option | resting limit | at the 200-contract limit | open | 19 Nov |
| 12 | BSE future | market / exit / limit | normal | open | 20 Nov |
| 13 | BSE future | stop-loss + entry resting | frozen | open | 19 Nov |
| 14 | BSE option (thin) | market / limit | normal | open | 18 Nov |
| 15 | BSE any | any | segment switched off | open | 20 Nov |
| 16 | BSE any | any | normal | shut / first instant / feed down | 17 Nov |
| 17 | MCX future | market / exit / limit | normal | open | 20 Nov |
| 18 | MCX future | intraday, stop-loss, flip | normal | open | 19 Nov |
| 19 | MCX option (thin) | market / limit / stop-loss | normal | open | 18 Nov |
| 20 | MCX future | any | normal | expiry (closing price) | 15 Nov |
| 21 | MCX any | intraday | normal | square-off time / session end | 20 Nov |
| 22 | MCX any | any | margin shortfall | open | daily check |
| 23 | Currency future | market / exit / limit | normal | open | 20 Nov |
| 24 | Currency future | market | normal | weekly cut-off in the same instant | 19 Nov |
| 25 | Currency option (thin) | limit, remainder | normal | open | 18 Nov |
| 26 | Currency any | any | normal | last day after 12:30 | 20 Nov |
| 27 | Currency any | any | segment switched off | open | 20 Nov |
| 28 | Crypto perpetual | market / exit / limit | normal | open | 20 Nov |
| 29 | Crypto perpetual | thousands of resting limits | normal | open | 19 Nov |
| 30 | Crypto perpetual | resting stop + limit | normal | feed silent, then a gap | 19 Nov |
| 31 | Crypto perpetual | leverage 1x then highest | normal | open | 20 Nov |
| 32 | Crypto option | market / limit | normal | expiry time, delisting | 20 Nov |
| 33 | Crypto any | market | normal | weekly cut-off in the same instant | 19 Nov |
| 34 | Crypto any | any | carried position after a cut-off | open | 20 Nov |
| 35 | Forex | market / exit / limit | normal | open | 20 Nov |
| 36 | Forex | resting stop + limit | normal | feed silent, then a gap | 19 Nov |
| 37 | Forex | leverage mix | normal | open | 18 Nov |
| 38 | Forex | any | normal | weekend / Monday opening | 20 Nov |
| 39 | Forex | any | conversion rate missing | open | 20 Nov |
| 40 | Global | market / exit / limit | normal | open | 20 Nov |
| 41 | Global | resting stop + limit | normal | feed silent, then a gap | 19 Nov |
| 42 | Global | resting orders | normal | daily break / holiday of one contract | 20 Nov |
| 43 | Global | stop-loss + position | account deleted | open | 19 Nov |
| 44 | Global | any | first login, password not yet changed | open | 19 Nov |
| 45 | any | any | short of margin in the weekly grace time | Monday before noon | 14 Nov |
| 46 | any | bought option | carried over a cut-off at a profit | open | 16 Nov |
| 47 | any | exit bigger than the position | segment switched off | open | 20 Nov |
| 48 | any | any | options-only-until-flat account | open | 20 Nov |
| 49 | any | order above the exchange position limit, several resting | normal | open | 20 Nov |
| 50 | any | intraday and overnight mixed at the fill | normal | open | 19 Nov |
| 51 | any | automatic square-off | normal | first seconds of a session / feed silent | 20 Nov |
| 52 | any | two logins of one account at once | normal | open | 18 Nov |
| 53 | Crypto / Forex | any | normal | contract list missing after a restart | 19 Nov (Price) |
| 54 | Crypto / Forex / Global | market | normal | book messages stalled, price messages flowing | 20 Nov |
| 55 | any (visitor) | request with a slow body | no login | open | 20 Nov |
| 56 | any (visitor) | price-socket message flood | no login | open | 20 Nov |
| 57 | Currency / stock / MCX | Exit and Master square-off of more than 500 lots | normal | open | 20 Nov |
| 58 | Crypto / Forex / Global | add / reduce / flip | position opened above 50x before the cap | open | 20 Nov |

Next in line (oldest): 9, 20 (15 Nov), 8 (16 Nov), 45, 46 (14 / 16 Nov), 7, 16 (17 Nov), then 3, 4, 6, 14, 19, 25, 37, 52
(18 Nov). Rows 15, 27, 47, 48 need a copy started with the trading-access switches enforced (`PT_ACCESS_ALL=0`).

## Nightly rotations (so the next night knows where to go on)
- Technology alarm: job stopped (19 Nov), disk low (20 Nov) → next: backup bad → domain renewal → job stopped.
- Price feed state (P6): disconnected, reconnecting, silent (16 Nov), contract list not loaded (19 Nov), slow (20 Nov) → next: disconnected again.
- UX pop-ups (U3): Master's message, access switch, install banner (19 Nov); weekly settlement, shortfall, liquidation (20 Nov) → next: the Monday 9:15 reminder, the Master's maintenance notice, then from the start.
- Load figures (100 users, 60 s, fresh copy): 19 Nov: screens 31 ms, orders 57–69 ms median (yesterday's code the
  same night: 30–51 / 43–84).
  20 Nov: screens 13 ms, orders 24 ms median (95% under 194 / 164 ms), 55 requests a second, no server error.
- UI screens studied closely: 20 Nov: Master Shadow Book, Performance and dashboard filters on a phone; user Market
  tab, option chain, ticket in every market, Order Book, P&L, Account, Pulse.

## What confuses a new user (started 19 Nov 2026; work down it)
1. No Stop-loss or Target button on a position (the way is Add → SELL → Stop-loss), and the position card does not
   show that a stop or target is resting.
2. Exit bursts six small messages ("OPEN", "Order placed", "CANCELLED" twice, "FILLED", "filled").
3. The index and stock "spot" rows come first in Market search although they cannot be traded (explained since 19 Nov).
4. The ticket of a shut market looks ready to trade; "closed" is only in the pill at the top until BUY is pressed.
5. Opening the chart from the ticket closes the ticket; closing the chart does not bring it back.
6. Nothing tells a user when the Master switches a segment on or off.
7. "Margin required ₹0 (netting)" on an exit.
8. Coins messages use 219,252.46 while the screens use 2,19,252.
9. The ticket shows "exp" with no date for an index.
10. (20 Nov) Order Book on a phone hides Status, the refusal reason and Cancel off the right edge.
11. (20 Nov) The leverage row on a bought option changes nothing.
12. (20 Nov) A first BUY gives two messages saying the same; they now stack instead of overlapping.
13. (20 Nov) The Positions summary writes "+₹0".
14. (20 Nov) "This Week" on the P&L tab is closed trades only; the Overview's weekly figure includes open positions.
All of these are layout or feature changes: under "Waiting for the owner".

## Findings

### 2026-11-20 (officers' nightly audit) — two no-login loopholes that stopped the site, one free-coins loophole (old order book), five other loopholes / rule gaps and seventeen faults, all live tonight
Self-test at the start: safety check 289 / 0, browser check 227 / 0, weekly simulation 6653 / 0, no server error.
On tonight's code: safety check 296 / 0, browser check 243 / 0, weekly simulation 6681 / 0, no server error
(run again before the push; see Release). The officers worked side by side, each on its own private copy.

#### Technology
- Fresh copy starts with no server error; `/healthz` 200; Site health: all eight jobs running, backup opened and
  passed its check. Alarm of the night: **disk low** forced in-process (1.2% free): one Telegram line in twenty
  rounds, none while there is room, told again when low again.
- Forced restart in the middle of trading (six accounts ordering without pause, `kill -9`): 927 answered orders all
  in the books, each with exactly one trade, none doubled, ledger = balance for every account, integrity check and
  foreign keys clean, a user's login still works. An error written before the restart is on the health page after it.
- Load, 100 users for 60 s on a fresh copy: LOAD RESULT OK, no server error; screens 13 ms, orders 24 ms median
  (last night 31 / 57–69: not slower). Safety check after the load 296 / 0.
- Data: backup holds all 11 tables and all 115 accounts with the same row counts and passes the integrity check; 20
  planted old backups pruned to 14, the newest kept; the encrypted copy opens with its password and with no other
  (wrong case / empty refused), nothing readable in it; passwords are hashes. Largest tables: ledger, orders /
  trades, shadow_fills, positions. Nothing is pruned (unchanged).
- Deploy risk: no new package, no new environment variable, no database change. The stored list of logged-out
  logins changes its form (`logout_<number>`): proven by starting tonight's code on a database made by
  yesterday's code: starts clean, balances identical, a logged-out login stays dead, a login made under yesterday's
  code still works and can be logged out, a carried position is kept exactly. (A roll-back to older code would not
  read the new form: logged-out logins would work again until the next release.)
- First job of the night (a past fix without its own check): the refused price-feed login and the errors kept
  through a restart (both 19 Nov) had none: ten checks added to `weekly_sim.py` ("feed login: …", "site health: …").
- Known weaknesses (`pip-audit`): the same three reports as last night in the one library the price-feed client
  pins (server side only, not used that way); nothing new. Repository and its 276 commits: no real secret.
- Seen, not changed: errors from the ten minutes before a restart are read back, so the "5 errors in 10 minutes"
  alarm can be sent once more after a restart.

#### Security
- **LOOPHOLE (no login needed, stops the site), FIXED, live: slow request bodies.** 80 requests from "different
  addresses" that announce a body and send nothing took every shared turn: no visitor or user was answered for as
  long as they were held (65 s measured). *Fix (main.py `_Turnstile._read_body`):* the body is read first, on the
  sender's own turn, and has 10 s to arrive (then 408). After: visitor 17–25 ms, user 6–8 ms.
- **LOOPHOLE (no login needed, stops the site), FIXED, live: price-socket floods.** Four visitor connections sending
  pings without pause froze the site (single waits of 8 to 23 s). *Fix (main.py `_WsPace`):* a connection has an
  allowance (120 messages, 10 a second more; long contract lists count for more); beyond it only its own messages
  wait. After: worst 100 ms.
- **LOOPHOLE (no login needed, changes stored data), FIXED, live: the price-feed login return address answered
  anybody.** Each visitor call was sent on to the broker under the site's key and written as a server error (30
  calls = 30 errors and the owner's alarm); a code the broker accepts would have replaced the site's stored
  price-feed login (not provable here). *Fix (main.py `kite_callback`, `kite_login`):* it lets through a browser
  with the Master's login, or the return of a login a Master started with the button in the last ten minutes
  (added after the release review: the return may arrive on another host name and then carries no login).
  Anyone else is sent to the Master page with a message; nothing is sent on, nothing logged.
- **LOOPHOLE, FIXED, live: the 41st log-out brought the first one back.** *Fix (auth.py `_ended_state`):* each
  logged-out login is kept until it would have run out anyway (up to 2,000 per account).
- **RULE BYPASS, FIXED, live: the exchange position limit with resting orders** (sweep row 49): four resting buys of
  200 on a contract with a limit of 250 left a position of 800 (full margin, no coins gained). *Fix (engine.py
  `_still_allowed`):* checked again at the fill; what fits is filled, the rest dropped.
- **FAULT, FIXED, live: a position of more than 500 lots could not be closed** by Exit or the Master's square-off
  ("Enter a number of lots between 1 and 500"); the Master's square-off also failed on an index position above the
  freeze quantity. Now sent in slices (`engine.max_lots`, `close_position`, `admin_squareoff`). With a flat fee per
  order each slice pays it, as when splitting by hand.
- **FIXED, live: `/docs`, `/redoc`, `/openapi.json` answered a visitor** with every address of the site. Now 404.
- **Latent, FIXED, live (row 39): fills while the rupee conversion rate is missing** booked a loss of 0.00 and
  opened positions with no margin (in-process, rate taken away by hand). `engine.rupee_known`: resting orders and
  automatic closes wait for the rate.
- No hole: the 50x cap (16 leverage values on six contracts, flips, adds, sold crypto option, every way a contract
  is built: lowest margin 1.9998%); the errors file (junk input writes no error line; 24,000 errors from four
  threads across the rewrite: no broken line; planted markup shown as text); 640 limit orders at once: exactly 500
  rest; a user's text never reaches a reason on the Master's screen.
- Sweep rows run (13): 21 MCX intraday at square-off time and the close; 26 Currency last day after 12:30; 31
  leverage 1x then 50x; 32 crypto options delisted before expiry (three buys still filled at the old top of book
  for 3–20 s: only if the exchange stops quoting early; open idea); 34 crypto carried over a cut-off (difference
  0.00); 39; 42 Global resting orders across a shut contract; 48 options-only-until-flat; 49; 51 (see Price);
  15, 27, 47 switched-off segments. Every market by hand (NSE, BSE, MCX, Currency, Crypto, Forex, Global):
  nonsense lots, limit far above the market, Exit x6, 12 buys at once, three full-size limit exits at once, buying
  past the book: all held, ledger = coins.
- No-login sweep: 93 addresses, five methods, as visitor and as user: only public pages, login, logout, `/healthz`
  and the public home / pulse / maintenance / underlyings / futures data answer (plus the three pages above, now
  shut). Wrong passwords lock a name after 5 tries and an address after 20; same message for unknown user and wrong
  password; cookie HttpOnly, SameSite, Secure over https; no framing; two-step cannot be skipped; dead logins stay
  dead; a visitor's socket gets futures prices only.

#### Accounts
- Twelve accounts (all seven markets, 11 carried positions, sold options, no trades, brand new, frozen, segment off,
  two auto-squared-off, old-leverage, two real deletes), prices standing still: database, Master row, dashboard in
  four periods, Weekly Settlement, Performance, Shadow Book, the user's own figures and every Excel file: about
  18,400 comparisons in nine states (before / after the cut-off, markets shut, feeds off, weekend clock, with
  expiry settlements): no real mismatch. Real browser: Master page 218 / 0, user app 78 / 0.
- The 50x cap on a database made by the code before it: 51 checks, 0 differences: old 200x / 500x positions keep
  their margin to the paisa, new lots take 2%, a partial exit releases in proportion, a flip opens at 2%, a limit
  order resting since before fills at 2%, labels equal value / margin everywhere.
- Commission by hand (futures 0.041%, options 0.13%, flat 9, crypto 0.052%, forex 0.0073%, auto square-off 37 /
  0.08%): 42 fills in all markets agree with trade, ledger and estimate. Coins added / removed: one line each. After
  the cut-off coins back to Allocated (10 of 10). A deleted account leaves 19 totals by exactly its figures.
- **FAULT, FIXED, live: Master Settings still said "0.5% = 200x" beside the crypto margin.** Now says 2% / 50x; Save
  leaves the stored figure unchanged (`min_margin_pct` is display only).
- Seen, not a fault: on the private copy a test cut-off in mid-week makes the dashboard "Weekly" leave out the
  week-close valuation (cannot happen with the real Sunday cut-off unless it runs late into Monday).

#### Price
- P1 (all seven markets, in-process, hours enforced): market orders at the exit side with a last trade planted 3%
  away; limits never better than the book; refused at the weekend, at night, on the 24 Nov holiday, in the opening
  second. P3, P4 re-proved, and **stock futures exercised**: RELIANCE settled at the cash price 1,287.35 (stale last
  trade 1,340); a cash print 9% away is ignored. P5: one rupee factor per contract on every screen, kept through 10 s
  of silence. Last night's fixes re-proved after a restart with the forex broker unreachable. P2 only in-process.
- P6, state of the night: **slow**. Every feed stamps the arrival time, so a late but steady feed looks fresh.
- **LOOPHOLE (free coins), FIXED, live: an order book that stops arriving kept filling orders under a fresh price**
  (crypto perpetuals, Forex, Global: book and price come in separate messages). 60 s without book messages, market
  1% higher: BTC +143,914 coins, EURUSD +313,618. *Fix (feed/delta.py, feed/ctrader.py `_handle`):* a book not
  renewed for 8 s is replaced by the quote the price message carries (or dropped) until the next book message.
  After: −6,266 / −1,677. A user cannot cause it. Watch on live: if the crypto exchange sends an unchanged book
  less often than every 8 s for a quiet perpetual, big orders there meet only the top quote; raise the 8 s then.
- **FAULT, FIXED, live: a Forex / Global contract the broker sends no ladder for was filled at its first quote for
  good.** Same change.
- **LOOPHOLE / FAULT, FIXED, live (row 51, open idea): in the opening second the automatic closes and resting
  orders acted on the last session's book.** A short account had a NIFTY lot sold on Monday 9:15:00 at Friday's
  price (49,211 coins worse than the real opening); a margin call closed 315 Currency lots at Friday's price
  (263,541 coins taken); a resting buy was filled against an old book (+26,993). *Fix (`engine.session_price` in
  `_process_pending`, `_force_close`, `_square_off_shortfall`, `_liquidate`):* they wait for the first price of the
  session, as users' orders do. Side effect: a contract with no price yet today is not auto-closed until its
  first tick; another position is closed first. Sign on live: system orders in the first 2 s after an opening.
- Wording: Exit with the contract list missing; "Forex" / "Crypto" instead of FOREX / CRYPTO in the shut message.
- Known left-over, unchanged: a whole-feed silence under 8 s (3–7 s with a 1% jump: +0.9–1.0% of position value).
  New open: ONE contract silent while its feed delivers (BTC alone 240 s: +143,914): limit is the 5-minute rule.

#### UI
- N2: the 50x ticket (buttons, Custom box, margin line, labels) at 360 / 412 / 820 / 1440; Site health error groups
  with none / one / 308 / very long / markup errors, kept through three restarts; the price-feed card in seven
  stubbed states (login button visible in all 21 renders): all do what they say.
- About 330 screenshots, 150 read closely (tonight: Master Shadow Book, Performance, dashboard filters on a phone;
  user Market, option chain, tickets, Order Book, P&L, Account, Pulse), light and dark; buttons pressed.
- FAULTS FIXED, live: Pulse showed risers under "Top losers" and the reverse when fewer than ten of a kind (seen
  daily in Indices, Crypto, Forex); My P&L "Realised −188 / P&L −187" with nothing open; Pulse figures overlapping
  on a phone; option chain (Greeks) cut off at 360; Master card labels cut with "…"; two messages on top of each
  other.

#### User experience
- U1: brand-new user on a phone, 27 steps from first login to logging in again: 0.06–0.93 s each.
- U3 (weekly settlement, shortfall, liquidation, made to happen for real): each once, closable, right user only.
- FAULTS FIXED, live: the liquidation pop-up gave a dollar price with the rupee sign ("BTCUSD at ₹73,909.50");
  the shortfall after the weekly settlement was told twice with two figures and the red bar contradicted the
  pop-up; a waiting pop-up appeared 5.5 s after opening (now 0.4 s); a user frozen while using the app landed on
  the login screen without a word; a badly written date crashed the report addresses (now a plain 400).
- Reworded (wording only): fractional lots; "Unknown or non-tradable instrument"; exit with prices offline.

#### Compliance (housekeeping, not a legal opinion)
- C1 (two-step enforced, in-process): 28 checks held; 55 Master addresses refused to a user and a visitor; no
  password, login or secret in the server log, the backup or the new errors file (message only, never the
  exception text). The errors file is Master only, not in any backup; it can hold a login name for 7 days.
- C2: 26 Master actions each leave a line. None for: the Master's own password change, the daily price-feed login,
  a refused action (Waiting).
- C3: off-server copy opens with its password only; one user's socket and files hold nothing of another; deleted
  accounts are in no table or file.
- C4: charges match the settings; **FIXED, live: three comments in the user page's source named a price provider.**
  No provider name on 39 user / visitor addresses. The Master page file (readable without login, no data) names
  them in its text (Waiting).

#### Risk (all with the 50x cap; 1,000,000 coins, 80% used)
- R1: warning → shortfall message → square-off on a slide; only the lots needed, worst loser first, one charge
  per system order. Net Balance after a 10% gap (last night in brackets): NSE +451,756; BSE +359,116; MCX +357,326;
  Currency −1,676,652; **Crypto −3,033,760 (−15,134,681); Forex −2,995,395 (−39,024,556); Global −2,997,462
  (−16,848,881)**. Below zero now only on a gap above about 2.5% (Crypto / Forex / Global) or 3.7% (Currency).
- R2: old 200x / 500x positions keep their margin and last night's risk until closed; adding is at 50x. After the
  weekly cut-off a crypto account that re-used a realised profit held 86 times its coins inside the grace time.
- R3: largest position for 5,000,000 coins: NIFTY 22 lots (40 M), USDINR 1,953 lots (165 M), BTC 33,046 lots (247 M;
  was 937 M), EURUSD 2,360 lots (249 M; was 2.5 billion), US500 250 lots. All coins gone at a move of 12% (NSE /
  BSE), 8–12% (MCX), 3% (Currency), 2% (Crypto, Forex; was 0.5% / 0.2%).

#### Release
- Independent reviewer (fresh, saw only the diff, the rules and D): 18 of 19 items approved; **one held**: the
  price-feed login return address needing the Master's login could have broken tomorrow morning's login if the
  return arrives on another host name than the one the Master is logged in on. *Answered the same night:* the
  return of a login started with the button is let through for ten minutes without the cookie (tested in-process:
  visitor refused, Master-started return accepted once, refused after ten minutes); full self-test run again.
- Remarks kept for later: the top-quote stand-in for a quiet crypto book (see Price); in the opening seconds the
  shortfall is judged partly on last session's marks; a trimmed order (position limit) carries no reason text;
  `_doors` compares the global error count (a stray error in that instant would fail it); new sentences reach
  users (red bar in the grace time, "Nothing is up / down here right now", the longer refusals).


### 2026-11-19 (officers' nightly audit, first night in this form) — one account-takeover loophole, four other loopholes and eleven faults, all live tonight
Self-test at the start: safety check 279 / 0, browser check 217 / 0, weekly simulation 6644 / 0, no server error.
On tonight's code, twice: safety check 286 / 0, browser check 227 / 0, weekly simulation 6653 / 0, no server error.
(The officers worked side by side, each on its own private copy; the results were merged and tested together.)

#### Technology
- Fresh copy starts with no server error; `/healthz` 200; Site health: all eight jobs running, backup opened and
  passed its check. Alarm of the night (rotation: job stopped → disk low → backup bad → domain renewal): **job
  stopped** forced in-process (square-off job silent for 500 s): Telegram line sent once, `/healthz` 503.
- Forced restart in the middle of trading (six accounts ordering without pause, `kill -9`): back in 11 s; 437 answered
  orders all in the books, none doubled (439 filled orders, each with exactly one trade), ledger = balance for every
  account, integrity check and foreign keys clean.
- Load, 100 users for 60 s on a fresh copy: LOAD RESULT OK, no server error. Yesterday's code: screens 30–51 ms
  median, orders 43–84 ms. Tonight's code: screens 31–32 ms, orders 57–69 ms (one run of 154 / 224 ms was the
  machine, not the code: repeated three times alternating with yesterday's code). The median on this machine swings
  by a factor of two from run to run; compare several runs before calling it slower.
- Data: a backup taken in the middle of trading holds every table and all 109 accounts and passes the integrity
  check; 20 planted old backups pruned to 14, the newest kept; the encrypted copy opens with its password and with
  no other (wrong / empty: refused); passwords are hashes in the database and the backup. Fastest-growing tables:
  ledger, then orders / trades, shadow_fills; day_snaps grows by one row per account per day. Nothing is pruned.
- Deploy risk: no new package, no new environment variable. One database change tonight (`positions.last_vf`,
  nullable, added at start-up): proven by starting tonight's code on a database made by yesterday's code (109
  accounts, 560 positions): starts clean, column added, a login made under yesterday's code still works.
- Known weaknesses (`pip-audit`): three reports, all in one library that the price-feed client pins to an old
  version; all three concern its use as a web-socket SERVER (redirect header; message size limit), which the site
  never does. It cannot be upgraded on its own (the client pins it). Not a finding; re-check when the client moves.
- Repository and history searched for real passwords, tokens, keys: none.
- Seen by the UI officer, not changed: Site health "Server errors" and the "5 errors in 10 minutes" alarm do not
  count a request that crashes (only lines the site's own code logs). Counting them would make the known
  junk-input "500"s raise alarms; listed under Waiting.

#### Security
- **LOOPHOLE (account takeover), FIXED, live: a deleted account's login worked on the next account created.** A login
  is a signed account number, and the database hands a deleted account's number out again. Proven over the API (the
  deleted user's login answered as the newcomer) and in-process with two-step login enforced: a deleted trainee's
  old login became the second Master login created next, set up its own two-step code and created an account with
  99,999,999 coins. *Fix (auth.py `session_current`, `make_token`):* a login older than its account is refused. It
  needed the Master to delete the newest account and create another while the old login was under 30 days old.
  Whether it was used cannot be told from the books; a sign would be a Master login nobody recognises.
- **WEAKNESS, FIXED, live: "Log out" did not end the login** (a copy worked for 30 days). Now recorded as ended
  (`logout_<number>`, last 40) and refused, on the price socket too.
- **LOOPHOLE (no login needed, breaks the site), FIXED, live: oversized input.** One 200 MB request took 560 MB of
  memory; megabyte-long login names stayed in memory; four visitor sockets sending 9 MB messages slowed everyone.
  Now: requests over 1 MB refused, a login name over 64 letters that belongs to no account is not counted, a socket
  message over 64 KB ends that connection.
- **LOOPHOLE (breaks the site for others), FIXED, live: no limit on pending orders** (open idea of 18 Nov, measured):
  one account with 4,650 resting orders that kept sending more made other users' clicks take 0.4–2.7 s. Now 500
  pending orders per account (`engine.MAX_RESTING_ORDERS`); market orders and Exit are not counted. After: 30–170 ms.
- **FAULT, FIXED, live: text typed by the Master ran as script** (display name on four Master tables, coin note on
  the user's Ledger). Now shown as text.
- Tried, no hole: 80 orders at once at the 200-contract limit; a weekly cut-off in the middle of 96 market orders
  (NSE, Currency, Crypto); resting stop and limit across a silent feed and a 1% gap (Crypto, Forex, Global); deleting
  an account with positions and resting orders; a first-login account before its password change; frozen account on
  BSE; three stop-loss sells opening short NIFTY options; intraday on MCX with an oversized stop and a flip.
- Old attacks by hand in all seven markets (NSE, BSE, MCX, Currency, Crypto, Forex, Global): zero / negative / huge
  lots, order bigger than the book, Exit x6, buy limit above the market: all held.
- No-login sweep: 98 addresses, five methods each, as visitor and as user: only public pages, login, logout,
  `/healthz` and the public home / pulse / maintenance / underlyings data answer a visitor. Wrong passwords lock a
  name after 5 tries; same message for unknown user and wrong password; cookie HttpOnly, SameSite, Secure over
  https; no framing; two-step cannot be skipped; a password change kills older logins; a visitor's socket gets
  public prices only.
- Sweep matrix started (below): 13 rows run tonight.

#### Accounts
- Eight accounts (seven markets with 8 carried positions and trades after the cut-off; sold option; no trades; brand
  new; frozen; segment off; two auto-squared-off) plus three deleted ones, prices standing still: Master row,
  dashboard in four periods, Weekly Settlement running and final, Performance, Shadow Book, the user's own figures
  and every Excel file (user and Master; this week, last week, all time), and the database: 844 comparisons, 0
  mismatches after the fix below; again with NSE / BSE / MCX / Currency shut: 844 / 0.
- Commission by hand after setting unusual rates (futures 0.037%, options 0.11%, flat fee 7, crypto 0.045%, forex
  0.0061%, auto square-off 33 flat / 0.07% crypto): nine trades in all markets agree with trade record, ledger and
  the estimate before the order. Coins added / removed: one ledger line each, Allocated follows everywhere; after
  the cut-off coins went back to Allocated. Frozen account stays in totals, marked; a deleted account leaves every
  total by exactly its figures.
- **FAULT, FIXED, live: after the Master deleted the account that made the newest trade, every NSE / BSE / MCX order
  of every user failed ("500")** until a crypto / forex / currency trade used the number up: the deleted account's
  Shadow Book line stayed behind and collided with the next trade's number. Reachable since 18 Nov (Delete works
  again). *Fix:* the lines go with the account; a leftover line is replaced. Nothing was half-booked.
- **FAULT, FIXED, live: the line above the Ledger Statement (Excel) did not add up after a cut-off with carried
  positions** (weekly valuation counted under Realised and again under Unrealised). Realised there = closed trades.
- The existing check "all-time Excel Net = the Master's figure" could fail when prices moved between its two
  readings; it now reads the Master's figure before and after.

#### Price
- P1 fills in all seven markets: market orders at the live exit side, a limit never better than the book, refused
  while shut, on a holiday (24 Nov), at a weekend, in a Global contract's break and in the opening second. P2: with
  hours enforced and two restarts, every shut position sits on its closing price on every screen and in Excel, P&L
  identical 25 s apart and after a restart. P3: carried at the week-close price, original average kept. P4
  (in-process, stale last trades planted): currency at the spot rate, NIFTY / SENSEX futures at the index, crude
  future at the exit side of the book, crude option against the middle of the future's book, BTC option at its own
  time; expired contracts refuse orders. P5: one rupee factor per contract on ticket, user and Master screens;
  remembered through 12 s of silence.
- P6, state of the night (rotation: disconnected → silent → reconnecting → **contract list not loaded**): two faults.
- **FAULT (takes coins), FIXED, live: a crypto or forex position whose contract is missing from the list was valued
  as if one point were one rupee.** After a restart while the crypto exchange could not be reached, a BTC loss of
  26,938 showed as 237,481, Available Balance went below zero and the account's NIFTY future was squared off with
  the charge; the weekly cut-off would have booked it. *Fix:* `positions.last_vf` (kept once a minute),
  `engine.pvf(p)`; unknown = not valued, left unpriced at the cut-off; the crypto list is retried every minute while
  empty. With the contract listed every figure is worked out exactly as before.
- **FAULT (wrong payout), FIXED, live: a contract reaching expiry while its exchange's contract list is not loaded
  (no price-feed login yet that day) was settled at the previous day's close.** Now it waits for the list (one error
  line in Site health). If the login only happens the next day it still settles at the last price seen.
- Not exercised: stock futures at the cash price (simulation only).

#### UI
- N2: the new Master Settings list of waiting pop-ups and the error list (c8978fd) used for real at 1440, 820, 412
  and 360 wide with none / one / many / day-old pop-ups and long texts: does what it says.
- Every Master tab and user screen at 1440 and 412, prices live and markets shut; closely: Master Settings, Users
  table and user panel on a phone, Weekly Settlement on a phone; user Positions (carried), Ledger, Watchlist,
  search, pop-ups, sheets, install banner; 360 and 820; light and dark; every button on them pressed.
- FAULTS FIXED, live: Master user panel on a phone hid "Delete" and the close button off the right edge; a long
  error text ran off the Site health card; on a 360-wide phone a watchlist name ran under its price; in the light
  theme a changing price flashed white on pale; three close buttons enlarged to 36 px.
- Seen, not changed (design): see "Waiting for the owner".

#### User experience
- U1: brand-new user on a phone, every step from first login to logging in again: 0.1–2.1 s each, none over 3 s.
- U2 refusals reworded (wording only): "NFO market is closed" → "The NSE market is closed right now — it opens again
  today at 9:15 am"; "lots must be 1..500" → "Enter a number of lots between 1 and 500"; "limit_price required" /
  "trigger_price required" → "Enter a limit price for a Limit order" / "Enter a trigger price for a Stop-loss
  order"; "Order not open" → "This order is no longer open — it was already filled or cancelled"; "No remaining
  counterparty quantity…" → "Nothing left to buy at the moment — the offers on the screen have already been taken;
  wait a moment for new ones". Clear as they are: feed down, not enough coins, segment not activated, freeze
  quantity, too many orders, leverage, price band, frozen account.
- Dead ends closed: tapping BUY on an index itself now explains it cannot be traded and where to go; a search with
  no match says so.
- **FAULT, FIXED, live: a message that arrived while a pop-up was open was cleared unseen** by OK (a square-off
  notice could be lost so). OK now clears only what that pop-up showed.
- U3: Master's message pop-up once, right user only; install banner wording for both phones reads well; there is no
  pop-up when the Master changes trading access (listed under Waiting).

#### Compliance (housekeeping, not a legal opinion)
- C1: a user never reaches a Master address; the two-step login cannot be skipped (password alone gives a 5-minute
  pre-login refused everywhere); a second Master login behaves the same and his actions are recorded under his name;
  no password or two-step secret in the server log or activity record. The two-step secret is stored readable in
  the database and on-server backups (the off-server copy is encrypted).
- C2: every changing Master action leaves a line (who, when, from where, which address). None for: backup download,
  Excel downloads, looking at a user, Master logins. The line never says WHAT changed (amount, setting and old / new
  value, which switch; freeze and password reset read the same). A deleted account's coin history goes with it.
- **FAULT, FIXED, live: the activity list named the wrong user** for lines about a deleted account whose number was
  given out again. Now "account since deleted".
- C3: held: username, display name, password hash, two-step secret, balance, orders, trades, positions, ledger,
  watchlist, weekly / day-start records, pop-up texts, access switches, Master name and address in the activity
  record. No e-mail, phone or address. One user's data never in another's screens, files or socket. A deleted user
  is gone from every table keyed by account.
- **FAULT, FIXED, live: the full price-feed status (provider name, broker account number, diagnostics) went to every
  user's browser and to visitors without login.** No screen showed it. Now Master only.
- C4: charges before the order and in P&L match the Master's settings; no provider name on a user screen; nothing
  promises profit. The app shows amounts with the rupee sign and does not state plainly that trading is in coins;
  no terms, risk note or privacy note exist (Waiting).

#### Risk
- R1 (in-process, 1,000,000 coins, 80% used): on a slide the order is warning → shortfall message → square-off; on
  a gap the warning is skipped; only the lots needed (NIFTY 10% gap: 1 of 3), worst loser first, one charge per
  system order (a slide makes several orders). Bought options never go below zero.
- Net Balance after a 10% gap against the position (10 lakh coins): NSE +450,628; BSE +356,707; MCX +357,326;
  Currency −1,672,882; Crypto (200x) −15,134,681; Global (500x) −16,848,881; Forex (500x) −39,024,556. Smaller gaps:
  Forex 0.5% → −1,034,629; Crypto 1% → −744,986; Global 1% → −796,593; Currency 5% → −342,573.
- R2: thin book: one lot per pass, one charge each; stop-loss in a gap fills at the new bid; a market that opens 10%
  lower closes 1 of 3 lots at the first price; shortfall after the cut-off (Sunday warning, Monday 9:15, noon) holds.
- R3: largest position for 5,000,000 coins: NIFTY 22 lots (40M), crude 71 lots, USDINR 1,965 lots (166M), BTC 125,000
  lots (937M, position limit), EURUSD 23,654 lots (2.5 billion), US500 250 lots (limit). All coins gone at a move of
  12% (NSE / BSE), 8–16% (MCX), 3% (Currency), 0.5% (Crypto), 0.2% (Forex / Global). Many accounts on one side change
  nothing for others except sharing the visible quantity of a thin book.
- Also seen (Accounts): an account squared off far below zero is back at its Allocated coins after the weekly
  cut-off (by design).

#### Release
- Independent reviewer (fresh, saw only the diff, the rules and D): **approved, nothing held.** Three points:
  (1) the two price fixes change figures only when a contract list is missing, and the 500-pending-orders limit is
  a new limit: the owner is told in the report; (2) an account with a login name over 64 letters would have been
  locked out by the oversized-name rule: changed so that only names belonging to no account are turned away;
  (3) the new "kept factor" books check could have failed in the first minute after a restart: it now waits five
  minutes. Remarks kept for later: order reasons on the user's own Order Book are not escaped (server text only);
  "Log out" remembers the last 40 per account; an expired position on an exchange whose list never loads waits.
- More than five normal-working checks were added tonight (ten browser checks, one books check) because the owner's
  rule of 18 Nov (every fix keeps its own check) outranks the nightly cap; each passed in three full runs.


### 2026-11-18 (nightly review) — one loophole fix (price socket) and four normal-working faults, all live tonight
PART 1, normal working
- Self-test at the start: safety check 275 / 0, weekly simulation 6644 / 0, no server error, but the browser check
  7 FAILED: every order on the first NIFTY future the search offered was refused "This contract has expired". That
  was fault 1 below (it shows on the private copy on a night when the server's calendar day is still Tuesday).
- FAULT 1, FIXED, live: **an expired contract stayed at the top of the search and of the futures list.** Both lists
  go by the server's own calendar day and keep a contract through its whole expiry day: from 3:30 pm on its last day
  (and until 5:30 am the next morning, when the server's day turns) the expired contract headed the list with a
  price that stood still, and every order on it was refused. *Fix (base.py `search(skip=)`, main.py `/api/search`,
  `/api/futures`):* a contract that `engine.expired` is not offered. Option-chain dates already did this.
- FAULT 2, FIXED, live: **the Master's "Delete" did nothing for any account that had been through a weekly cut-off.**
  The weekly record (week_settlements, since 13 Nov) blocked the delete in the database: the server answered "500",
  nothing was deleted, and the Master's screen showed no message at all. Since the first cut-off (15 Nov) that was
  every existing account. *Fix (main.py `admin_delete_user`, admin.html):* the account's weekly record goes with
  its trades and ledger, as the confirmation text says ("and all their history"); a delete that fails now says so.
  Other accounts' records are not touched (checked: the kept user's weeks, balance and positions identical).
- FAULT 3 (also a leak), FIXED, live: **a new account received a deleted account's leftovers.** The database hands the
  number of a deleted account out again when it was the newest one. Proven: user deleted, new user created: same
  number, and the newcomer was shown the pop-up message the Master had written to the deleted user; the deleted
  user's trading-access switches and day-start records were also still filed under the number. *Fix
  (`_forget_number`):* pop-ups, switches, grace flag and day-start records are dropped when an account is deleted
  AND when a new one is created (so leftovers of accounts deleted earlier cannot be inherited either). Never run for
  an account that exists. If an account was created right after deleting the newest one since 14 Nov, look at its
  trading-access switches once.
- FAULT 4, FIXED, live: **Site health card unreadable.** Name and value of each row ran together ("Databaseanswering",
  "Domain name limefx.invalid until 2027-11-09"): the row style existed only on the user page. Added to admin.html.
- Recent changes used for real: yesterday's fixes (user panel = row in all four periods for three users, checked in
  the browser with prices standing still; All Time Realised = closed trades; no "-₹0" on any screen; one login's 8
  turns and the first price of a session through the daily check); orders, Exit and Cancel in all seven markets;
  the Site health card; a carried position's exit note; a frozen account (screen logged out, order "Account
  inactive") and a switched-off segment (three segments, the right message each, the rest still trades).
- Screens: every Master tab and user screen at 1440 and 412 wide, with prices live and with every feed paused ("Price
  feed down" bar, figures standing still), for a user trading in all seven markets, a brand-new user and a frozen
  one. Studied most closely tonight: Performance, Shadow Book, Settings (site health, trading access, costs), the
  user panel's trading access; user Pulse, Watchlist, Market, order ticket, Order Book, P&L, Account, the weekly pop-up.
- Figures compared for three users with every feed paused (to the paisa): Master row, dashboard in four periods, user
  panel, Weekly Settlement running and final, Performance, Shadow Book totals, the user's own report / weekly /
  ledger / positions, and the Excel files (user and Master: all statements, P&L, ledger, order book; this week, last
  week, all time; Master summary and all-users file). They agree. (Weekly on the dashboard holds two weeks on the
  private copy, as noted on 17 Nov.)
- Seen, NOT changed, for the owner to decide: on **All Time** (dashboard, Performance, Excel) "Unrealised" is Net
  P&L + Commission − closed trades. After a carried position has been closed it still holds what that position was
  valued at when the earlier week closed, so it is not the P&L of what is open now (user with open positions worth
  −1,134 since entry: All Time Unrealised −872). Net P&L is right everywhere. Showing that part under Realised would
  change the meaning of Realised on Performance and in the Excel files, so it was left alone.
- Seen, not changed: the user's header "P&L today" is today's closed trades and commission plus the WHOLE open P&L,
  while the Master's Daily shows the day's move only; the Performance ranking table needs sideways scrolling on a
  1440 screen; a watchlist row without any price shows a lone "/" under the dash.

PART 2, the hunt
- LOOPHOLE (breaks the site for others), FIXED, live: **cancelled orders and closed positions kept their contracts on
  the price socket for good.** Every fill and every resting order added a stream for its contract that was never
  given back (until the next restart). The limits of 14 Nov covered refused orders only. Proven on the private copy:
  one account looked at 1,200 options over the live socket, rested a limit order far below the market on each and
  cancelled it (24 seconds, no coins used), did the same twice more: 2,655 contracts left streaming a minute and a
  half later with no order and no position on the account (the copy lists no more options). The broker's socket holds
  3,000; from 2,900 no screen gets prices for a contract that is not already streaming, from 2,980 orders on such
  contracts are refused, and it stays so until a restart. Honest trading leaked the same way, slowly.
  *Fix (engine.py `_pin` / `release_pins`):* the engine keeps a contract streaming once, and once a minute gives
  back every contract that no open position and no resting order needs (as its own price or as the underlying of
  an option). Same attack afterwards: 1,229 streams while the attacker looks, 29 a minute and a half after.
  *Second half (engine.py `MAX_OPEN_CONTRACTS`):* orders left resting need their streams, so the same could be done
  for a few coins of margin (and hundreds of resting orders slowed every order on the copy). One account may now
  hold positions or resting orders on at most 200 different contracts; the next one is refused with a plain message.
  Afterwards: 200 rest, 1,000 refused, 229 streams. Exits and orders on a contract already held are never counted.
  Nobody could gain coins from this. A sign that it was used would be "No live price" complaints from many users
  at once on a day with thousands of cancelled orders from one account.
- Checked by hand in all seven markets (NSE, BSE, MCX, Currency, Crypto, Forex, Global): zero / negative / huge lots,
  buy limit far above the market, a market order bigger than the visible book, Exit x6 (old attacks); a stop-loss
  bigger than the position followed by an exit and by a flip; ledger = balance and nothing left blocked after each.
  Thin options in NSE, BSE, MCX and Currency: a limit order for more lots than are offered at its price fills in
  parts (remainder order), never above the limit, reservation freed on cancel. Crypto, Forex, Global: 1x then the
  highest leverage, then selling one lot. All 58 Master addresses with every method as a user and as a visitor.
- Nothing in any account was changed. Self-test twice on tonight's code: 279 / 0, browser check 217 / 0, weekly
  simulation 0 failures, no server error.
- Daily check: three new checks (two attacks, one normal-working). Browser check: four new checks.


### 2026-11-17 (nightly review) — two loophole fixes and three display faults, all live tonight
PART 1, normal working
- Self-test at the start: 267 / 0, browser check 209 / 0, weekly simulation 0 failures, no server error.
- Recent changes used for real on the private copy: orders, Exit and Cancel after the capacity change of 16 Nov (they
  hand the database connection back while waiting): every proven attack by hand in all seven markets, Exit x6 with
  two market sales at the same instant, 300 requests at once (which is how the turnstile fault below was found);
  `/healthz` and the Site health card (every job running, backup opened and checked, domain line shows); period
  results of an account created today (Daily = Monthly = All Time, to the paisa); the carried bought option after
  a cut-off (margin = carried value, exit note in the Order Book); a frozen account and a switched-off segment
  (order refused with the right message, both show on the Master's screens); Excel files of three users (all
  statements, P&L, ledger, order book; this week, last week, all time) and the Master's files.
- Screens: every Master tab and user screen opened at 1440 and 412 wide, twice: with all markets open and with NSE /
  BSE / MCX / Currency shut (the copy started with exchange hours enforced at 1 am: closing price everywhere, "opens
  9:15 am" pills, figures standing still). Studied most closely tonight: Master dashboard with each filter, the user
  panel, Weekly Settlement, Settings / Site health; user Positions with carried positions, P&L, Ledger, order ticket.
- Figures compared for three users (one trading in six markets, one in three with a short option, one brand new):
  Master row, the four dashboard filters, Weekly Settlement running and final, Performance, Shadow Book, the user's
  own P&L / weekly / ledger, and every Excel file. They agree, apart from the three faults below. (On the private
  copy the test cut-off closes the week that is still running, so "this week" holds a finished and a running week;
  that cannot happen on the live site.)
- FAULT, FIXED, live: **the Master's user panel disagreed with the user's own row.** On Daily, Monthly and an earlier
  week the panel worked Unrealised and Net P&L out its own way (always the whole open P&L of the running week, or
  nothing for a finished week) while the row showed the result of the period. Proven with prices standing still:
  same user, same moment, Daily: row Net P&L +458, panel +175. *Fix (admin.html `refreshDetail`):* the panel takes
  its figures from the same calculation as the row (`pdRow`).
- FAULT, FIXED, live: **Master dashboard, All Time: "Realised" was not closed trades.** It also held what open
  positions were valued at when earlier weeks closed, so it disagreed with the Performance tab and every Excel file
  (user with one closed trade of +3.75: dashboard Realised +286, Performance and Excel +4). *Fix:* `/api/admin/users`
  also gives the closed trades since the beginning (`realised_closed`); All Time shows that as Realised and counts
  the week-close valuations with Unrealised, like Performance and Excel do. Net P&L is unchanged; the note under the
  dashboard says so. Nothing stored is touched.
- FAULT, FIXED, live: **"-₹0" in red.** A user with no closed trade this week saw "Realised -₹0" on his P&L tab (a
  stray 0.00000000001 from the arithmetic), and the Master summary Excel showed -0.00 in the same place. *Fix:* an
  amount that rounds to ₹0 carries no minus sign (both pages); the two figures are rounded to the paisa.
- Seen, not changed: a 500x forex position can read "501x" after the price has moved (the label is worked out from
  the current price); times on the user's screens follow the clock of his own device.

PART 2, the hunt
- LOOPHOLE (free coins), FIXED, live: **the first instant of a session was filled at the last session's book.**
  An order needs a price that is live and under five minutes old. But "old" was counted from when the price reached
  us, and the feed hands the last book out again to whoever starts looking at a contract (and to everybody after a
  reconnect), so shortly before the opening yesterday's closing book can look seconds old. Proven in-process (prices
  and clock set by hand; the closing book handed out ten seconds before the opening; the new session 1% higher): a
  buy at the opening second was filled at yesterday's closing offer and sold five seconds later at the new price:
  NSE +174,923 (ten NIFTY lots), BSE +152,584, MCX +54,668, Currency +19,179, Forex on Monday morning +125,982,
  a Global contract after its daily break +280,434. Crypto never closes. *Fix (engine.py `session_opened`, checked in
  `place_order`; ctrader.py `opened_at` for a Global contract's own timetable and holidays):* a price that reached us
  before the session opened (or in its first two seconds) is not a price of this session; the order is refused with
  "the market has just opened, try again in a second" until the session's first price has arrived. Same attacks
  afterwards: refused; the round trip costs commission only. What an honest user notices: an order in the first two
  seconds of a session, or on a contract that has not had a single price yet today, is asked to try again.
  Could not be checked from here: whether the real NSE feed really hands out a book with offers in it before the
  opening (it may hand out an empty one, and then nothing could be filled anyway). Nothing in the books can show
  whether anyone used it; a sign would be fills in the first second or two of a session far from the next prices.
- LOOPHOLE (breaks the site for others), FIXED, live: **one login could take every turn.** Since 16 Nov requests take
  turns, 80 at a time, first come first served. Proven on the private copy: one small account sent 300 Excel
  downloads at once; another user's next click was answered after 32 seconds (300 orders on contracts nobody watches:
  2 seconds on the copy, longer where a price takes longer to arrive). Kept up, that shuts the site for everybody.
  *Fix (main.py `_Turnstile`):* one login (a visitor: one address) is worked on 8 requests at a time; its other
  requests wait behind its own, not in everybody's queue; beyond 200 waiting it is told "too many requests" at once.
  Same flood afterwards: the other user is answered in 0.03 to 0.25 seconds.
- Checked by hand in all seven markets (NSE, BSE, MCX, Currency, Crypto, Forex, Global): zero / negative / huge lots,
  buy limit above the market, an order bigger than the visible book, Exit x6 together with two market sales, the same
  limit exit twice at the same instant, intraday / overnight mixing: all refused or filled at the market, nothing
  left blocked. Junk numbers and text into the watchlist, margin, chart, option chain, search, weekly, report and
  Excel addresses, and the Master's addresses as a user: refused; one of them (deleting a watchlist entry with an
  absurd number) answers "500" to the sender only.
- Nothing in any account was changed. Self-test twice on tonight's code: 275 / 0, browser check 213 / 0, weekly
  simulation 0 failures, no server error.
- Daily check: two new checks (see "Ideas already covered"). Browser check: four new checks.


### 2026-11-16 (nightly review) — three fixes live tonight (all about price-feed outages), one waiting on a branch
- LOOPHOLE (loss dodged at an old price), FIXED, live: **Exit worked while the NSE / BSE / MCX / Currency feed was
  down.** The order screen refuses while that feed is down ("Orders will be rejected until the feed is back up"), but
  the Exit button went straight to the engine, which only checked the crypto and forex feeds. A position was closed at
  the frozen book from before the outage (for up to five minutes). A user who sees elsewhere that the market has moved
  against him gets out at the old price; if it moved his way he waits. Proven over the API in all four markets (new
  order 400, Exit 200 FILLED at a price 4 s old). *Fix (engine.py `place_order`):* no order of any kind on a contract
  of the main feed while it is not connected. Same test afterwards: Exit refused in all four.
- LOOPHOLE (free coins), FIXED, live: **the instant a feed came back, orders were filled at the price from before the
  outage.** On a reconnect the feed is marked connected at once, but the prices in memory are as old as the outage until
  each contract's next tick (up to a second; up to five for crypto options). Proven on the private copy (feed switched
  off, simulated market moved 1%, feed switched on, order sent at once): Crypto +7,000, Forex +20,860, Global +35,832
  coins; NSE / BSE / MCX / Currency filled at a price 4 s old (the simulated NSE feed cannot move while it is off).
  *Fix:* `PriceFeed.restart_live` — on every (re)connect the feed's contracts stop counting as live until a new price
  arrives (Zerodha `_on_connect`, the simulated feed, Delta `_resync`, cTrader `_resync`); orders wait for it like on a
  contract nobody streams. A crypto perpetual gets its book and its last price in separate messages: the last-price
  message is not taken until the new book is in (`_stale_book`). Forex: the old ladder and the old quote ids are
  dropped, and nothing is published until both sides are new. Same attacks afterwards: −207 to −614 (costs only); a
  resting stop-loss across an outage fills at the new bid.
- LOOPHOLE (free coins), FIXED, live: **a crypto or forex feed that was connected but silent kept filling orders.**
  A stalled stream is noticed late (crypto: after 20–40 s; forex: never, there is no ping) and until then every order
  fills at the last price received. Proven (the pretend exchanges can now go mute: `/debug/mute`, `/debug/shift`):
  9.5 s of silence with the market 1% higher: Crypto +14,566, Forex +40,933, Global +70,786 coins.
  *Fix:* `quiet()` in both feeds: after 8 s without anything from the exchange (crypto) or without any price from the
  broker (forex / Global) orders are refused like on a feed that is down, and the first message after such a silence
  counts as a reconnect (prices wait for a new tick). `PT_FEED_QUIET_SECS` changes the 8 s. Afterwards: refused.
  What is left: a silence shorter than 8 s (3 s of silence with a 1% jump still filled at the old price in the test).
- A user cannot cause any of these three; he can only pounce when an outage happens (the feed status is on his
  screen). Whether somebody did cannot be told from the books: the fills look ordinary. A sign would be fills within
  seconds of a "prices are back" message, or an Exit during a "prices are DOWN" spell.
- RULE GAP, fix waiting on `security-fix/2026-11-16`: a bought option carried over the weekly cut-off at a profit can
  lose far more than the account holds without being stopped (see "Waiting for the owner").
- Checked by hand in all seven markets (NSE, BSE, MCX, Currency, Crypto, Forex, Global; Global opened with
  `FAKE_OPEN=1`): zero / negative / huge lots, buy limit far above the market, Exit x6, an order bigger than the visible
  book, 12 orders at once with coins for 3: all refused or filled at the market. Exit while the crypto / forex feed is
  down: refused (was already so).
- Nothing in any account was changed. Self-test 229 / 0 twice on main, weekly simulation 0 failures.
- Daily check: two new checks (see "Ideas already covered"); on yesterday's code they fail 11 times (exit in NSE, BSE,
  MCX, Currency; silent feed in Crypto and Forex; reconnect in five markets), on tonight's they pass twice.

### 2026-11-15 (nightly review) — three fixes, all live tonight
- RULE BYPASS, FIXED, live: **a switched-off segment could be traded through an exit that outgrew its position.**
  Trading access (14 Nov) is checked when an order is placed: in a segment that is off, only an order no bigger than
  the position (an exit) is accepted. A resting exit is not looked at again when it fills. Holding 3 lots: rest a limit
  exit of 2 lots and one of 3 lots (each is "no bigger than the position"); the first leaves 1 lot, the second then
  sells 3 and the account is 2 lots SHORT in a segment it may not trade. The same with a stop-loss of 3 lots followed
  by a market sale of 2. Proven over the API on NSE, BSE and Crypto (limit exits) and MCX (stop-loss): long 3 -> short 2;
  on MCX futures, Currency and Forex the bigger exit happened to fill first in the hand test, and Global was shut, but
  the new daily check fails on yesterday's code in NSE, BSE, MCX, Currency, Crypto and Forex alike (same code path).
  No coins gained (margin and commission are charged), but the Master's switch was bypassed, again and again if wanted.
  *Fix (engine.py, `_still_allowed`, called just before a resting LIMIT / SL order fills):* an order that would open new
  exposure is checked again; in a segment that is off an oversized exit is cut down to the position (it closes it and
  no more), any other opening order is cancelled. Orders in an activated segment and plain exits are not touched.
- RULE BYPASS, FIXED, live (same place): **a frozen account's resting order still filled and opened a position.**
  Proven: buy limit resting, Master freezes the account, two seconds later the order fills (1 lot BANKNIFTY). Now such
  an order is cancelled ("Cancelled — account frozen"); a frozen account's stop-loss / target still closes its position.
- LOOPHOLE (free coins), FIXED, live: **a commodity future was settled at a closing price up to a minute old.** Since
  14 Nov a future that settles at its order book (every MCX future; index / stock / currency futures when their
  underlying has no usable price) is settled at the "closing price" kept for the position, and that was refreshed only
  once a minute. A user who holds 1 lot and sees the market drop in the contract's last seconds adds at the new price
  and is settled at the old one. Proven in-process (prices and clock set by hand): crude 5999/6001, mark stored, price
  falls to 5959/5961 twenty seconds before the stop, 9 lots added at 5961, all settled at 5999: +32,927 coins; the same
  purchase by an account with no earlier position: −3,192. A short who simply held was settled 40 points too high.
  *Fix (weekly.py `closing_positions` / `remember_marks(only=…)`, main.py `weekly_loop`):* positions on a contract in its
  last three minutes get their closing price refreshed every second. Same attack afterwards: −7,073. Checked on a
  running copy (clock set to two minutes before an MCX expiry): the mark of the expiring contract is under a second
  old, other positions keep the once-a-minute pass. What is left: a closing price up to about one second old.
  No future has expired since the closing price was introduced (14 Nov, a Saturday), so nobody can have used this.
- Observation for the owner (design of 14 Nov, not changed): index, stock and currency futures are settled at the
  underlying, not at the contract's own book. If in the last seconds the underlying stands more than the commission
  (0.02%) above the contract's offer, buying the contract then is free money for the gap (in-process: 0.1% gap = +1,796
  on one NIFTY lot, 1% = +22,046; 0.02% = −4). On real prices the two meet at expiry, so this cannot be judged on
  simulated prices. The daily check now lists every expired future that was settled more than 0.1% away from its own
  closing price (a note, not an alarm); if that list ever fills up, settle at the contract's own book instead.
- Checked by hand in all seven markets (NSE, BSE, MCX, Currency, Crypto, Forex, Global): zero / negative / huge lots,
  buy limit far above the market, add / flip (market and limit) in a switched-off segment, Exit x6: all refused or
  filled at the market. Global is shut on the private copy at the weekend; the fake feed now takes `FAKE_OPEN=1`
  (every Global contract open all week) so it can be attacked on any night.
- Nothing in any account was changed. Nobody could gain coins from the two rule bypasses. A user in a switched-off
  segment may since 14 Nov (afternoon) hold a position opened by a limit or stop-loss exit bigger than what he held;
  only crypto and (for a few hours) forex were open in that time.
- Daily check: three new checks (see "Ideas already covered"); the two trading ones fail on yesterday's code in all
  six open markets and pass twice on tonight's. `weekly_sim.py` has all three as well (5103 checks, 0 failures).

### 2026-11-14 (nightly review) — two fixes live tonight, one waiting on a branch
- LOOPHOLE (breaks the site for others), FIXED, live: **one account could fill the price socket.** Since the frozen-price
  fix an order on a contract nobody streams starts streaming it; that happened before the order was even looked at, so
  nonsense orders (zero lots) did it too, and when the contract had no price in memory yet it was pinned for good. The
  per-account limit of 1,200 streams only applied to the live socket. Proven: one account sent 1,600 refused orders on
  1,600 different options in 15 s; streams went from 29 to 1,629 and were still there 40 s later. The live socket holds
  3,000; beyond that nobody gets prices for a new contract (orders refused "No live price yet") until a restart.
  *Fix (main.py):* a stream started for an order or a contract look-up is temporary (30 s) and counted per account, at
  most 25 at a time (`ORDER_STREAM_LIMIT`); none is started when the socket is nearly full (2,980); a refused order no
  longer leaves the engine's "retry" stream behind. The 26th order on an unwatched contract gets "Too many orders on
  contracts you are not viewing" (HTTP 429). The app always streams the contract on the order screen, so an honest
  order never needs one of these. After the fix: 1,573 of 1,600 refused, streams 35 -> 60 -> 35.
  (This also closes the open idea "looking up a contract subscribes it for good".)
- BUG / RULE BYPASS, FIXED, live: **a cancelled exit order filled anyway and flipped the position.** Two exit orders
  on the same position that become fillable on the same price tick (the same limit exit placed twice, or stop-loss and
  target together): the first closes the position and cancels the other, but the pass over the resting orders did not
  look at the status again and filled the cancelled one too, opening a position the other way round. Proven in all
  seven markets (long 1 lot -> short 1 lot). No coins gained (margin is checked, commission paid), but the rule "an exit
  never opens a new position" was bypassed and an honest user with stop-loss and target could be left short.
  *Fix (engine.py, `_process_pending`):* an order that is no longer OPEN is skipped.
- LOOPHOLE, FIXED, live since 14 Nov (owner's go-ahead): **weekly valuation at an old last trade.** With nobody quoting
  on the exit side at the cut-off (always so when the exchange is shut) a position was valued at the last trade, however
  old: a thin option bought at 3 with a last trade of 15 showed 30,000 spent as +119,994 for the week (in-process test,
  prices set by hand). *Fix:* `weekly.close_price` uses the last exit-side quote seen (`positions.last_mark`, no longer
  overwritten by a bare last trade unless the contract has traded since) and never values a long above the best offer
  or a short below the best bid. Same attack afterwards: −10,006. New `_books` check on it.
- 14 Nov, owner's request: no "prices are DOWN" alarm for a feed whose markets are all shut (weekend, holiday, night);
  it starts again one hour before the first of them opens, so the daily-login reminder still comes in time.
- Checked, no hole: weekly cut-off on the private copy (MCX, Currency, NSE option, BSE resting order, Forex, Global,
  Crypto positions carried; partial exit, add, flip afterwards; own-price P&L of all trades = week result + change since,
  to the paisa); an account short of margin after the cut-off cannot open, add, flip or rest anything during the grace
  time and is not squared off; junk `week_end` values; crypto leverage mixing when adding (1x then 200x, then partial
  exit); by hand in Forex / Global / Currency: round trips, limit far above the market, junk numbers, Exit x6.
- Nothing in any account was changed. Nobody could gain coins from the two fixed items. A user who had two exits
  resting may have been left with an opposite position he did not ask for (two exits of the same contract filled in the
  same second, followed by an open position the other way).
- Daily check: two new checks (see "Ideas already covered"); both fail on yesterday's code, pass twice on tonight's.

### 2026-11-13 (nightly review) — four fixes, all live tonight
- LOOPHOLE, FIXED, live: **trading at a frozen price (free coins, every market except Forex / Global).** Prices arrive
  only for contracts somebody is looking at. When the last viewer leaves, the last price stays in memory and an order
  was still filled against it for up to five minutes. A user looks at a contract over the live socket, stops looking,
  watches the index (always live), and buys whichever frozen contracts the move has already made cheap. Proven: eight
  in-the-money NIFTY puts bought at prices 200 s old after the index fell, sold at once: +24,564 coins on 5,000,000;
  the same on SENSEX: +14,831. Also shown on MCX, Currency and crypto options (orders accepted at prices 105–116 s
  old). Forex and Global were not open to it: every contract there is streamed all the time.
  *Fix:* the feed knows whether a price is live (contract streamed now, and a price received since that streaming
  began). An order on a contract nobody streams first starts the stream and waits (up to 6 s) for a new price; without
  one it is refused ("No live price yet"). The app always streams the contract on the order screen, so an honest order
  is not delayed. After the fix the same attack loses the spread (−365 to −1,350).
- LOOPHOLE, FIXED, live: **options settled against a frozen underlying price.** At expiry an option is paid out against
  its underlying. For commodity and currency options (nearest future) and stock options (the stock) nobody kept that
  price streaming, so the settlement could use one that was minutes, hours or days old; a user can choose the moment it
  freezes. Proven on NATURALGAS: settled against a price frozen 150 s earlier while the live one had moved; the payout
  on 10 lots was wrong by a few thousand coins. Index options (index always streamed) and crypto options were safe.
  *Fix:* the underlying of every open option position is kept streaming (at the fill, and re-checked every minute); a
  settlement that still finds the underlying frozen starts the stream and waits up to three minutes for a live price.
- RULE BYPASS, FIXED, live: **currency contracts traded after 12:30 pm on their last day** (open idea of 12 Nov). The real
  exchange stops them at 12:30 pm and settles at the RBI rate; the site kept them open until 5 pm. No gain could be shown
  on simulated prices. *Fix:* on its expiry date a currency contract expires (no orders, settled) at 12:30 pm.
- SECURITY, FIXED, live: **a login survived a new password** (open idea of 12 Nov). After the Master reset a user's
  password, or the user changed it, every earlier login kept working for up to 30 days. Proven: an old login placed
  orders after the reset. *Fix:* a login made before the last password change is refused (HTTP and live socket); the
  device that changes the password stays logged in; logins from before this update keep working until the next
  password change (nobody was logged out by the update). New column users.pw_changed_at.
- Nothing in any account was changed. Whether somebody already used the frozen-price trick cannot be told from the
  books (the fills look like ordinary fills); a sign would be a user with many quick, small, almost always winning
  round trips on contracts nobody else trades.
- Checked, no hole: Forex and Global against the frozen-price attack; the full daily check by hand on the private copy
  in all seven markets (NSE, BSE, MCX, Currency, Crypto, Forex, Global): 198 checks pass.
- CHANGED 13 Nov (owner's decision): a BOUGHT option's running loss no longer counts against Available Balance (its
  premium is already blocked), so bought options are not squared off for a dip; they are also the last positions the
  shortfall square-off closes. Daily check "Bought option" covers it. The observation below is therefore resolved.
- Observation for the owner (not a cheat, not changed): the new "Available Balance below zero" square-off also counts
  the running loss of a BOUGHT option, although its whole premium is already blocked. Someone who puts nearly all
  their coins into bought options is squared off (with the ₹50 charge) after a dip of a few percent in the premium.
- Daily check: three new checks and one widened (see "Ideas already covered").


### 2026-11-12 (nightly review)
- LOOPHOLE, fix waiting on branch security-fix/2026-11-12: crypto options settled four hours late and, once the
  exchange delists the expired contract, at about ten times the real value; orders accepted on the expired contract.
- LOOPHOLE (nuisance), same branch: login lock-out of any username, the Master included, by a stranger.
- Small, same branch: a password-only (pre-2FA) login was a full user on the live socket; logged-in accounts had no
  limit on live-price subscriptions.
- Checked, no hole: the new trading costs (flat fee per order, options rate, crypto rate) — the estimate shown, the
  amount charged, the trade record and the balance change all agree; forged login tokens (old default key, unsigned);
  one user's socket never receives another user's order updates; frozen account's session is refused at once.
- Daily check: two new checks on main (see above). One existing check ("fills at the sellers' prices") gave a false
  alarm about once in four runs on the private copy because it compared the fill with a book read a moment earlier;
  it now compares with the book right before and right after the order.
- The private copy's pretend crypto exchange expires options at 12:00 UTC like the real one and can delist them on
  demand (on the branch).

### 2026-11-11 (first manual review)
- FIXED, live: LIMIT/SL order with a NaN price was accepted and saved with no price and no margin; the account,
  its order list and the margin-call loop for everyone then failed. All request bodies now refuse NaN/Infinity.
- FIXED, live: resting orders, stop-losses, forced closes and margin calls ignored a Global contract's own
  timetable (daily break / holiday) and could fill at a stale quote.
- FIXED, live: Exit cancelled the position's stop-loss even when the exit itself was refused.
- FIXED, live: an order rejected with an infinite price was still saved and made the order list unreadable.
- FIXED, live: Exit on a position above the exchange freeze quantity was refused; it now goes out in slices.
- Checked, no hole: rupee conversion on all 14 Global contracts, margin = value / 500, 40 simultaneous orders,
  25 round trips, cross-account access.

## Ideas tried that led nowhere
- Getting under 2% margin in Crypto / Forex / Global (20 Nov 2026): leverage as fractions, huge, strings, on options,
  flips, adds, resting orders from before the cap, every way a contract object is built: never under 1.9998%.
- Old 200x / 500x positions through add, partial exit, flip, weekly cut-off (20 Nov 2026): margin kept, books exact.
- Making the server write error lines at will with junk input (20 Nov 2026): 18 "500"s, no error line.
- Races at the 500-pending-orders limit and with partial-fill remainders (20 Nov 2026): exactly 500.
- The errors file as a leak of secrets (20 Nov 2026): message only, never the exception text.
- Out-of-order prices and a one-sided forex quote (20 Nov 2026): cannot arise on one ordered connection; only that
  side changes.
- MCX intraday around the square-off time and the close (20 Nov 2026): same margin as overnight, nothing gained.
- Orders at the same instant at the edge of the 200-contract limit (19 Nov 2026): exactly 200 held.
- A weekly cut-off in the middle of a burst of market orders (19 Nov 2026): the books stay exact.
- Resting stop / limit across a silent feed and a gap in Crypto, Forex, Global (19 Nov 2026): filled at the new prices.
- Deleting an account that has resting orders and positions (19 Nov 2026): nothing left, no server error.
- A stop-loss that opens a short option, several at once (19 Nov 2026): each reserves full margin.
- A half-finished two-step login used as a session (19 Nov 2026): refused everywhere.
- The "nearest future" as the underlying of MCX / Currency options after that future expired (19 Nov 2026, open idea
  of 18 Nov): only Currency, 12:30–5 pm on the monthly expiry day; margin for a sold option 4,242 instead of 4,298
  after a 2% move; no coins move on it.
- A limit order bigger than what is offered at its price (18 Nov 2026): fills in parts, the rest keeps resting with
  its share of the reservation, never above the limit; cancelling the rest frees it. Nothing gained.
- A stop-loss bigger than the position, then exit or flip (18 Nov 2026): after the exit the stop is cancelled; after a
  flip it stays with the reservation for one lot only, but a fill is checked against Available Balance again.
- 1x then the highest leverage in Forex and Global (18 Nov 2026): like crypto on 14 Nov, margin is released in
  proportion and never drops below what the highest leverage needs.
- Every Master address with every method as a user and as a visitor (18 Nov 2026): refused, except the page shell
  /admin (no data without login), a user's own two-factor set-up under the Master's name for it, and the broker
  login return address (already listed under open ideas).
- Trading the stock or index "spot" rows (18 Nov 2026, read only): they are loaded as indices and refused.
- Many logins of one account to get more turns (18 Nov 2026, read only): the turns are counted per account.
- Mixing intraday and overnight on one contract (17 Nov 2026): a sale bigger than an overnight position, sent as
  intraday, leaves an intraday position with its full margin; adding the other kind is refused. Nothing gained.
- Exit racing with market sales after the capacity change (17 Nov 2026): one Exit goes through, the others find no
  position; the sales open an ordinary short with margin. Never an unpaid position.
- Junk into the watchlist / margin / chart / chain / search addresses (17 Nov 2026): an error for the sender only;
  the watchlist stays at its 50 entries.
- Switching two-factor on again while it is on, to replace the code without knowing it (17 Nov 2026, read only): refused.
- Tiny lots to round losses away (16 Nov 2026): the smallest price step on one lot is worth ₹0.001 (XAUT) to ₹0.006
  (JP225); a loss only rounds to zero when the price has moved less than a few steps, far inside the spread.
- A frozen account's (or a reset password's) open live-price connection (16 Nov 2026): it keeps receiving prices until
  it is closed, nothing else: no orders, no other account's data. Not changed.
- 2FA switched on by someone inside an account survives a password reset by the Master (16 Nov 2026): the owner then
  needs the Master's "reset 2FA" as well. Nobody gets in with it; wrong codes are locked after five tries.
- The "grace until Monday noon" flag after a weekly settlement (16 Nov 2026, read only): it is cleared on the first
  margin pass that finds the account no longer short, and never lasts past Monday noon.
- Mixing leverage when adding to a crypto position (14 Nov 2026): margin is released in proportion, the average never
  drops below the highest leverage the contract allows.
- Opening more during the weekly-settlement grace time (14 Nov 2026): every opening, adding, flipping or resting order
  is refused while Available Balance is below zero; only reducing is allowed.
- Carried-position accounting after a cut-off (14 Nov 2026): partial exit, add and flip all keep the books exact.
- Frozen-price attack on Forex and Global (13 Nov 2026): every contract there is streamed permanently, fills were
  always at the live price.
- Using the new margin-shortfall square-off and its charge to gain (13 Nov 2026): it only ever costs the user.
- Junk in dates, sizes and ids on the read / report / export endpoints (12 Nov 2026): only an error page for the sender
  (a few answer "500" instead of "400"); nothing leaks, nothing sticks, the site keeps answering.
- Export file name / sheet name tricks to smuggle text into the download header: refused before the name is built.
- Forged login tokens signed with the old built-in key or with no signature: refused.
- Reading another user's order updates over one's own live socket: nothing arrives.
- Hunting for a gap in the new flat-fee / options-rate costs (round trips, estimate vs charge): none.

## Open ideas for a later night (noted, not yet tested or not provable on the private copy)
- (20 Nov 2026) ONE crypto / forex contract silent while the rest of its feed delivers: fills at its old price for
  up to five minutes. Needs the real longest wait between two prices (the daily check's new note) before a rule.
- (20 Nov 2026) Every feed stamps the arrival time: a late but steady feed is invisible (NSE / BSE / MCX / Currency
  have no silence or lateness rule at all).
- (20 Nov 2026) A streamed crypto option that stops ticking counts as live for five minutes (row 32).
- (20 Nov 2026) While a feed is silent the automatic square-off still acts on the old price (the user's own Exit is
  refused): 39 BTC lots closed 1.5% better than the market in the test. A user cannot cause the silence.
- (20 Nov 2026) At 9:15:00 screens and Available Balance switch from the closing price to whatever is in memory
  until the first price (valuation only; nothing fills now).
- (20 Nov 2026) Only about the last 5,000 errors are read back after a restart; a full error store makes the health
  answer about 8 MB; 80 stuck bodies from ONE address delay that address's own requests (10 s per 8).
- (20 Nov 2026) Code notes: an automatic close or a resting-order fill must go through `engine.session_price(ins)`
  and `engine.rupee_known(ins)`; a feed that gets book and price in separate messages must stamp the book
  (`_book_ts`, `_depth_ts`). Done 20 Nov: "automatic closes in the first seconds of a session" (below).
- (19 Nov 2026) The login answers in about 16 ms for a name that does not exist and about 330 ms for one that does.
- (19 Nov 2026) A visitor who sets the forwarded-address header himself gets a fresh address each time on the private
  copy, so the per-address login limit and turns do not hold him (the 5-tries-per-name lock does).
- (19 Nov 2026) One login sending orders without pause (all refused) costs every other user about 50 ms per click.
- (19 Nov 2026) Logins from before 19 Nov have no id: logging one out ends every login of that account made in the
  same second. "Log out" remembers the last 40 per account.
- (19 Nov 2026) Order reasons / carry notes on the user's own Order Book are not escaped (server-written text only).
- (19 Nov 2026) With a contract unlisted, a bought crypto option's loss counts in full against Available Balance (the
  instrument type is not known then); a new position with no kept factor is not valued until the list returns.
- (19 Nov 2026) An option whose underlying has no price after the three-minute wait falls back to its own last
  trade; a position whose expiry day passed with no feed login settles the next day at the last price seen; an
  expired position on an exchange whose list never loads waits (one error line).
- (19 Nov 2026) A new position value that depends on the contract must go through `engine.pvf(p)`, not `engine.vf`.
- (Done 19 Nov 2026: resting orders on one contract, now 500 per account; the "nearest future" idea, see above.)
- (18 Nov 2026) 200 contracts per account: fifteen accounts acting together could still hold 3,000 streams with real
  positions or resting orders. Accounts are created by the Master, so not pursued.
- (18 Nov 2026) Resting orders on ONE contract are not limited in number; every price tick walks all of them. A few
  thousand far limit orders on one busy contract might slow fills for everybody. Not measured.
- (18 Nov 2026) The "nearest future" used as the underlying of MCX / Currency options (`index_token_for`) is picked by
  date only: between a future's expiry and the next refresh of the contract list it is the expired one, whose price
  stands still (short-option margin, option settlement). The markets are shut for most of that time; not provable on
  the simulated contract list tonight.
- (18 Nov 2026) All Time "Unrealised" after a carried position is closed, and "P&L today" in the user's header: see
  Findings; waiting for the owner's wish, no branch.
- The automatic closes (margin call, shortfall square-off) in the first seconds of a session still act on the last
  session's book until the first price arrives; a user cannot choose to be squared off, so no gain was found.
- A flood of requests from many addresses without a login (public pages) is limited per address only; the address is
  read from a header (see the login-throttling item below).
- Exit of a position that another request closed a moment earlier while the engine was busy could answer "500"
  (close_position reads the position before its turn); not reachable in tests, the engine is never busy that long.
- Charts: `/api/candles` fetches from the broker for any contract and keeps the answer in memory with no limit per
  account; one account asking for thousands of contracts could use up the broker's request allowance (charts fail for
  everybody) and memory. Not reproducible on simulated prices (no broker, no cache there).
- The closing price at an ordinary daily close (not an expiry) is still up to a minute old. Valuation only: screens,
  Available Balance overnight, the weekly valuation of a shut market. No coins move on it.
- Settlement of index / stock / currency futures at the underlying (see 15 Nov 2026): watch the daily check's note.
- Other rules checked only when an order is placed, not when it fills: the exchange position limit (already listed
  below) and the intraday / overnight mix. Since 15 Nov the fill re-checks trading access and frozen accounts only.
- The Zerodha login return address (/auth/kite/callback) needs no Master login. It only works with a one-time code
  from Zerodha for this app, so probably harmless; cannot be tried on the private copy (simulated prices).
- (Done 16 Nov 2026: the moment after a feed is back, and a silent feed. Left open:) the automatic closes (margin
  call, shortfall square-off, intraday square-off) still act on the prices in memory while a feed is down or silent;
  a user cannot trigger them at will. Zerodha's own feed is trusted to notice a dead connection within seconds (its
  library does); it has no "silent" rule here because an evening with one quiet MCX contract is silent by nature.
- A carried FUTURE also keeps the margin blocked at its original price; its running loss counts against Available
  Balance, so it is covered. Only bought options were not (branch of 16 Nov 2026).
- Rupee conversion for Forex cross pairs uses the USD legs; those are always streamed. A cross pair that is not a
  USD pair (if the broker ever lists one) would be open to the frozen-price idea only through the daily check's note.
- Short-option margin before the first fill uses the underlying's price in memory (may be frozen) or the strike.
  Margin only, no money; not attacked.
- An order on a contract that IS streamed but has had no tick for five minutes still makes the engine start one more
  permanent stream; since 14 Nov a refused order gives it back, so it no longer adds up. Not reproducible on simulated
  prices (every streamed contract ticks twice a second).
- The position screen and the margin call still value a long with no bid at the last trade (`engine.mark_price`); only
  the weekly valuation is changed on the branch. A stale high last trade overstates equity there (never Available
  Balance, which ignores running profit).
- 2FA "turn off" and "confirm" are not throttled; they need a full login first, so only someone already inside an
  account could guess codes there.
- The address used for login throttling is taken from a header the visitor may be able to set; whether the live
  hosting overwrites it could not be checked from here.
- Exchange position limit is checked per order against the current position only; several resting orders together
  could exceed it (margin is still required in full, so no free money expected).
- A Forex / Global position force-closed while its rupee conversion rate is missing would book zero profit or loss.
- Positions on a perpetual the crypto exchange suspends: now kept listed by the branch fix; re-check after it is live.

## 13 Nov 2026 — weekly settlement (Sunday 23:59:59 IST)
- New: `app/weekly.py`. Open positions are valued at the week-close price and carried forward at it (not squared off); the week's result is settled and coins go back to Allocated. Fills are held from 23:59:57 until the cut-off has run.
- Month simulation `tools/selftest/weekly_sim.py` (16 accounts, 6 cut-offs, late cut-off with and without trades in between, missed week, unpriced position, liquidation, expiry): every week, screen figure and Excel total is checked against an independent own-price P&L. Must stay at 0 failures.
- Daily live check (`_books`): finished weeks match the ledger; every finished week adds up; carried positions keep their original average; the cut-off has run for every finished week; every open position has a price for the valuation.
- `POST /api/admin/weekly/test-close` exists only when `PT_WEEK_TEST=1` (private copy). Never set it on the live site.
- The nightly hunt must not change `WEEKLY_VALUATION` / `WEEKLY_SETTLEMENT` ledger lines, `week_settlements` rows or a position's `entry_avg` / `carried_week`.
- Shortfall left by the weekly settlement (booked profit leaves the coins): warning pop-up Sunday night, reminder Monday 9:15 am, time until Monday 12 noon; only then the usual auto square-off (`engine.week_grace`). The margin call on a deep loss is not delayed. Simulated with three users (did nothing / reduced himself / never opened the app).

## 14 Nov 2026 (morning) — weekend restart: wrong screens
- After a restart with the exchange shut the feed has no price in memory: open positions showed 0 unrealised (Master and user). Now valued at the last price seen (`engine.value_price`, `Position.last_mark`) until a live price arrives.
- Forex/global rupee conversion rates are remembered across restarts (`fx_inr_rates`); before, a weekend restart left them unknown (daily check "dollar–rupee rate is sensible — None") and a forex position would have been worth 0 in rupees. The weekly cut-off now leaves a position alone when its conversion rate is unknown instead of booking 0.
- Screens: a market that is shut shows "closed / opens …", never "feed down"; the red "Price feed down" bar only lists markets that should be open.
- One closing price: while a contract's market is shut, a position is valued at the price it had when the market closed (`engine.at_close_price`, `Position.last_mark`) on every screen, in Available Balance, in the reports and in the weekly settlement. Stray quotes after the close and restarts do not move it. Simulated (Friday close → stray quote → Saturday restart → Sunday settlement → Monday live).
- Daily live check additions (10:05 and 21:35, every day incl. weekends and holidays): shut-market positions sit on the closing price; no open position without a price; open-position P&L identical on user screen, Master table and weekly report; Master row / user P&L / weekly report agree and add up; open/closed status matches the calendar. Keep these when changing `_books`.
- Master dashboard Daily / Monthly: the result of a period is measured from where it started (`day_snaps`, one row per account at every IST midnight = the last closing price): closed trades + the move in open positions − commission. A period without its day-start record shows closed trades only and says so; it is never guessed. Record begins 14 Nov 2026.

## 14 Nov 2026 (afternoon) — expiry of a thin future
- Loophole: a future was settled at its own last traded price. On a thin contract that can be hours old and far from the book: buy at the ask below it (or sell at the bid above it), hold to expiry, be settled at the old trade for a free profit.
- Fix: a future settles at the exit side of the order book at the close (bid for a long, ask for a short) = the closing price the screens show (`engine.value_price`). Options unchanged (intrinsic value against the underlying). Simulated both directions in `weekly_sim.py`.
- Expiry now follows the exchange method (`engine._settle_underlying`): index and stock futures settle at the underlying's closing price (index value / NSE cash price), currency futures and options at the spot rate (ignored if it is more than 3% from the contract; then the book), commodity futures at the exit side of the book, commodity options against the MIDDLE of the underlying future's book (not its last trade). A spot print more than 5% from the future is treated as a bad tick and the book is used. All simulated in `weekly_sim.py`.

## 14 Nov 2026 — trading access switches (`app/access.py`)
- Twelve switches (futures/options × Indices, Stocks, MCX, Currency, Crypto; Forex; Global). Default: futures on in the four Indian segments, everything else off. Master sets the default table (Settings) and per-user switches (user panel).
- Enforced in `engine.place_order` for anything that opens NEW exposure (also a flip). Reducing/closing, the auto square-off and expiry are never blocked. Switching off cancels resting orders that would open a position there.
- Accounts that held options on the day this went live keep options on until they hold none (`access_optflat_<uid>`), then go back to the default by themselves; the Master gets a Telegram line.
- The daily check's own accounts (`zz-probe-`) and the private copy (`PT_ACCESS_ALL=1` in run.sh) are not restricted. Never set PT_ACCESS_ALL on the live site. The nightly hunt must keep the checks in `weekly_sim.py` ("access: …") passing and should try to get round the switches (flip orders, resting orders, SL orders, exits larger than the position). Done 15 Nov 2026: resting exits (limit and stop-loss) that outgrow the position got round them; fixed, see Findings.

## 16 Nov 2026 — bought option carried over the weekly cut-off (owner's rule)
- At the cut-off a carried BOUGHT option's margin is set to its carried value (week-close price × qty), up or down. Its whole remaining loss is then blocked, so it cannot take the account below zero after a profitable week has been paid out. An account that cannot cover the carried value is short at once: warned at the settlement, auto square-off Monday 12 noon (`week_grace`). The 16 Nov branch rule (loss beyond the blocked premium counts against Available Balance) stays as a second net. Simulated in `weekly_sim.py` ("carried option: …").

## 16 Nov 2026 — normal-working checks (owner's request: not only attacks)
- `tools/selftest/site_check.py` (run by run.sh after the safety check, prints "SITE n passed, m failed"): in a real browser on the private copy, Master page and user app on a computer and a phone screen, every tab and panel, dashboard filters, user panel, order ticket, pop-ups; no script/server error, nothing wider than the screen, no "undefined"/"NaN"; a weekly cut-off in the middle (carried positions, final week, pop-up, order-book note); every Excel file downloads, opens, has its sheets, adds up and matches the server's figures; two-factor set-up and login.
- Daily live check (books section) additions: every user's Excel builds, its Net P&L (Settlement) equals the weekly report, ledger balances run on; the days of the running week add up to the week; the Master's all-users Excel builds; both pages are in place and complete.
- The nightly task now has two parts: PART 1 normal working (recent changes verified by use, screens looked at, numbers compared across screens and Excel, new checks added to site_check.py), PART 2 the loophole hunt.

## 16 Nov 2026 — technical health (`app/watchdog.py`)
- Every background job calls `_wd.beat(name)` each round (prices, squareoff, expiry, weekly, feedwatch, daystart, backup, dailycheck). `watchdog_loop` sends Telegram when a job is silent beyond its allowed gap (and when it is back), when the disk is nearly full, and when 5+ errors are logged in 10 minutes. A NEW background job must get a beat and an entry in `watchdog.JOBS`.
- The daily backup is opened right after it is written (integrity check, tables, accounts, ledger lines); a bad one is renamed .bad, reported, and redone.
- `/healthz` (no login, no data): 200 only when the database answers and the two core jobs run. For an outside uptime monitor and the hosting's check of a new version.
- `/api/admin/health` + "Site health" card on Master → Settings. Daily live check: jobs running, disk, errors in the last hour, recent backup, backup opened and complete.
- The broker-login reminder already exists (feed alarm counts the hour before an opening as open).

## 16 Nov 2026 — owner's rule on WHEN changes go live
- Anything that is NOT urgent goes live after 11:55 pm IST or on a weekend (the nightly task at 12:40 am already fits). Anything URGENT (a loophole someone can use now, wrong money figures, the site or a market not working) goes live then and there, at any hour. When in doubt whether it is urgent: it is urgent if a user or the owner is being harmed or misled right now.
- New tools on the private copy: `tools/selftest/load_test.py` (N users trading at once; never against the live site) and `tools/selftest/restore_drill.py` (backup → encrypt → decrypt → brand-new site → everything compared → safety check on the restored site).
- The off-server copy is decrypted again on the server before it is sent, to prove it opens with the password.

## 16 Nov 2026 (night) — capacity: orders no longer hold a database connection while they wait
Load test found the private copy locking up at about 300 simultaneous users: every order waiting for a price
or for its turn kept one of the 120 database connections. place_order, cancel_order, close_position and
admin_squareoff now hand the connection back (db.rollback()) before they wait; everything is re-read under
the lock as before (db.expire_all()). iPhone install hint reworded (Share button is in the bottom bar).

## 17 Nov 2026 — turns per login, and the first price of a session
- `main._Turnstile`: 80 requests at a time for the site, of which at most 8 for one login (visitor: one address);
  the rest of that login's requests wait behind its own. `_Turnstile.last.watch` lets the daily check count them.
- `engine.session_opened(ins)`: when the session a contract trades in began (None for crypto, mid-week forex, or when
  exchange hours are not enforced, as on the private copy). `place_order` refuses until a price newer than that
  (plus `OPEN_SETTLE_SECS`, 2 s) is in memory. A new kind of market with its own opening must be added there.

## 18 Nov 2026 — streams are given back, and what goes with a deleted account
- `engine._pin(tokens)`: the only way the engine keeps a contract streaming for a position, a resting order or an
  option's underlying (once per contract). `engine.release_pins(db)`: called at the end of every expiry pass (once a
  minute, under the engine lock); gives back what no open position / OPEN order needs. New code that needs a price
  kept alive for a position or an order must use `_pin`, never `feed.pin` (which is for the permanent ones: indices,
  and the feeds' own always-on contracts). `place_order`'s "no price yet" stream is still a plain `feed.pin` that the
  order endpoint gives back itself.
- `engine.MAX_OPEN_CONTRACTS` (200): positions + resting orders on different contracts per account.
- `main._forget_number(db, uid)`: everything filed under an account number that is not a row of the account itself.
  A NEW per-account setting (`something_<uid>`) or table keyed by user must be added there, and a table with a
  foreign key to users must be deleted in `admin_delete_user` (or the delete fails again).


## Owner's decisions, 18 Nov 2026 (do not raise again, do not change)
- All Time "Unrealised" keeps the week-close result of a carried position even after that position is later
  closed. The owner's reason: a position carried from Friday to Monday is not closed at the week-end, so the
  week-close result is a valuation, not a realised trade; that is why the two are kept apart. This is DECIDED:
  it is not a fault, do not move it under Realised, and do not list it under "Waiting for you" again.
- Every loophole or fault that was ever fixed must keep its own check in the daily safety check (app/probe.py)
  or the browser check (site_check.py), and those run in full every night and twice a day on the live site.
  If you find a past fix in this log that has no check of its own, adding one is tonight's first job.

## Owner's decisions, 19 Nov 2026 (do not raise again, do not change)
- At most 50x in Crypto, Forex and Global (at least 2% margin on NEW exposure). Open positions keep the margin
  they were filled at. Set in one place: feed/base.py MAX_LEVERAGE, applied when a contract is built.
- No cap on the number of fixes per night.
- Terms / risk / privacy note: NOT wanted. Do not build, do not list under "Waiting for you".
- Auto square-off charge 0.05% on crypto and Rs 50 flat elsewhere: intended.
- The "Log in to Zerodha" button on the Master's Zerodha card is ALWAYS visible, in every state.

## 19 Nov 2026 (night, owner's requests) — Zerodha login that was refused
On 19 Nov the owner did the daily Zerodha login at 6 am; Zerodha clears every login at about 7 am, so the price
stream was refused (403) from 7:06. The site believed "today's login is done", hid the login button, offered
only Reconnect (which reuses the dead login) and retried for two hours (about 300 errors). Now: three refusals
in a row stop the retrying, the card says "Zerodha refused the login", needs_login becomes true, one Telegram
message with the login link is sent, and the login button is always shown. The login's day is the Indian day
(the server clock is UTC). Tested directly on the feed class (the private copy runs on simulated prices).

## 19 Nov 2026 (night, owner request) — errors kept through a restart
The health page lost the day's errors at every restart. Errors are now also written to errors.jsonl beside the database
(kept 7 days) and read back at start; the health answer gains "error_groups" (identical errors folded: count, first, last).
