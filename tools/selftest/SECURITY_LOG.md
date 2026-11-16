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
Nothing open. (`security-fix/2026-11-16`, a carried bought option's loss beyond its blocked premium counts against
Available Balance, is on main since 16 Nov 2026 together with the owner's rule that a carried bought option blocks its
whole carried value; `security-fix/2026-11-14` was put live on 14 Nov 2026, `security-fix/2026-11-12` on 12 Nov 2026.)

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

## Normal-working checks added to `site_check.py` (private copy, real browser)
- 17 Nov 2026: no screen shows "-₹0" (nothing, with a minus sign); the Master summary Excel has whole paise only; with
  the simulated prices paused, the Master's user panel shows the same Unrealised / Realised / Net P&L as the user's
  row on All Time and on Daily; All Time "Realised" is closed trades only (equal to the server's closed-trade figure).

## Findings

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
