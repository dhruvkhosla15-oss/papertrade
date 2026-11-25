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
Branch `security-fix/2026-11-26` is waiting (three separate commits, each with its check; "put security-fix/2026-11-26
live", or name the ones wanted). Weekly simulation on the branch: 6883 passed, 0 failed.
1. (26 Nov) A stop-loss AND a target on one position, and one of them closes only part of it (too few buyers): the
   other is cut down to the lots that are left (now the target later sells too many and the account ends short: 2
   lots in the test, 7 once the rest of the stop also fills). New sentence on the order: "Reduced to N lots — part
   of the position was closed by your other exit order". Changes a user's own order.
2. (26 Nov) Square off pressed by the owner or a master cancels the user's waiting orders on a contract only once
   its position is really closed, as the user's own Exit does (now they are cancelled first, so a position that
   could not be closed, or only in part, is left without its stop-loss). Changes what happens to a user's order.
3. (26 Nov) The owner's panel for a master's user or a deleted account is look-only: Square off, Freeze, Reset
   password, Delete and the access switches are hidden (the server refuses them all) and one line says why. Held by
   the release reviewer: new look and two new sentences on the owner's page. (Live since 26 Nov: those buttons at
   least SAY why they are refused; Freeze and Reset password said nothing.)
(`security-fix/2026-11-25`: items 2 to 6 were put live by the owner on 25 Nov 08:48, item 1 was REFUSED: a trade or a
cut-off never books at the closing price. Do not offer item 1 again. Nothing of that branch is waiting.)
Not ready, sketch only (`tools/selftest/held/crypto_price_before_book.patch`): a crypto stop (or a forex order) filled
against the order book from the moment before a jump when the price message arrives before the book. Since 26 Nov
the daily check prints, as a note, how often the real exchange's book is behind its price message and how far:
READ THAT NOTE on the live site first; the figure decides whether the rule is needed (26 Nov test: 5,500 BTC lots
sold 0.8% above the market, about 328,600 coins; a EURUSD buy 2% under the quote).
Decisions and wishes put to the owner (do not build without his word; do not repeat in the report once he has
answered; what he decided is under "Owner's decisions" at the end and is not here):
- (26 Nov, Masters) Nothing ties what a master's users hold to the coins that master was given (test: three users on
  3,000,000 coins won or lost 12.1 million on a 10% step). Suggested, not built: his users' margin in use together
  not above the coins given to him, and / or a largest position value per master and market. With it: when his
  users lose more than their coins, the owner's percentage is worked out on the whole loss (3.64 of 4.84 million
  had no coins behind it): count only up to the users' coins? A master whose users win owes his side whether or
  not he holds that many coins: a warning line on the Masters page?
- (26 Nov, Masters) Removing a master deletes his account and his stock lines (one line stays in the activity
  record) and his number can go to the next account: keep them, as for users? A master's login / log-out and own
  password change leave no line. A master has no Excel download of his own. The owner has no list of pop-ups
  waiting for a master's users. A minus typed in the master's deposit box is deposited as a plus (-5 → 5).
  Master's page on a phone: tables scroll sideways, "Your Share" is the last column. Weekly Record: Book P&L,
  Commission and Book Total are each rounded to whole coins (-336 + 377 can read +40).
- (26 Nov) ROLL-BACK RULE (for whoever maintains the site, proven): once a master exists, never deploy a version from
  before 25 Nov (4b843fc): that code treats every master, even a paused one, as an owner.
- (26 Nov) A one-off, read-only look at the live ledgers for a line whose balance does not follow from the line before
  would show whether "coins added at the very instant of that user's fill" (fixed 26 Nov) ever hit a real account.
- (26 Nov) Deleted users' data is now kept without a time limit (decision of 25 Nov): how long it may be kept is for
  the owner and his lawyer (said once). The row of a deleted account keeps its password hash: wipe it at deletion?
  The database now only grows (about 200 MB a year at 1,000 fills a day): a yearly archive, some day?
- (26 Nov) Stop-loss sheet: the trigger starts at the current price; pressed as it is, it was accepted once in six
  presses and closed the position at once. Start it EMPTY? (extends the item of 21 Nov.)
- (26 Nov) The owner's Reset password takes a password of any length (3 letters worked); every other password box
  asks for 6. A second square-off notice arriving while the first pop-up is open only shows at the next opening of
  the app. The liquidation pop-up writes "₹-15,055", the screens "-₹15,055". "+ Watchlist" still reads "+ Watchlist"
  after adding. A user frozen while in the app just sees the public page with "Log in". Positions tab: "No open
  positions" beside a Used Margin that is a waiting order's. Watchlist at 360 breaks a long name inside the word.
- (26 Nov) Square-off on a thin market charges the auto square-off charge once per order, and a thin market means
  several small orders (4 charges of 50 where a deep market takes 1). One charge per shortfall instead? The
  Master's Square off now says "N lots are still open (too few buyers right now). Press Square off again in a
  moment": other words?
- (26 Nov) In the first 30 s after an opening an account that also holds crypto is not judged at all while one of its
  Indian contracts has no price yet (read in the code, not run). Is 30 s still right for such accounts?
- (26 Nov) A currency future on its last day is settled at once at its own closing price if the spot-rate connection
  is not up at 12:30 (an index future waits up to three minutes for its index): wait for the spot rate too? A
  cut-off while a crypto / forex contract list is missing books nothing for that position although the Weekly tab
  shows it valued: keep? The refusal in that state says "it may have expired or been taken off the list".
- (25 Nov) A position opened in the last minute before a market shuts gets its closing price from whatever quote is
  in memory just after the close (a stray quote moved one week's result by 201,314 in the test and back the next
  week). Keep the closing price at the moment of the fill?
- (25 Nov) A stop whose price is reached when no buyer at all is visible is refused and deleted (seen for a
  bystander while twenty accounts were squared off on a thin book). Should it wait and try again?
- (25 Nov) The margin recorder asks the broker's calculator once for everybody plus once per account with a position
  after every trade (30 accounts: 31 calls). Per account only every few minutes? A position opened and closed within
  the 20 s between two looks never shows in Peak Margin: record at every fill? The Peak Margin card keeps the peak
  of accounts deleted since: keep or drop?
- (25 Nov) Night of 23 Nov: please have that night's server log looked at for lines "websocket dropped: 5000…" (a
  bare contract number). If they are there, the cause was the fault fixed on 25 Nov (a contract that left the
  crypto list while still open on a screen) and reading crypto prices another way is probably not needed.
- (25 Nov) Activity record: the Reconnect crypto line says "reconnected from scratch" also when the answer was "Not
  connected yet". Domain reminder: silent on days 6, 5, 4 and after the last day; the date in the site (9 Nov
  2027) must be updated by hand after each renewal. Where the live server's output is kept and whether it is cut
  at a size (a crashing request writes about 20,000 characters).
- (25 Nov) User app: the "No options" box says "Only futures are listed … trade the future above" also for Forex,
  Global and crypto perpetuals; "Options ›" is the full-colour button also on accounts with options switched off
  (every new user) and on names that never have options; Market → Options → Crypto lists names without options;
  P&L "1 Closed Trades", "Worst ₹0" when the only trade was a win; a coins entry that rounds to nothing (0.004)
  writes a 0.00 line; the Master's Live Positions tooltip says "Market is shut" also in the opening moments.
  Master page on a phone: the forex card's title is squeezed beside its two buttons; Shadow Book "By User" on a
  tablet needs a sideways scroll for the three margin columns; Performance chart's "-6K" label under the value tag.
- (25 Nov) New sentence on the user's option chain since 25 Nov: "No options are listed for X right now. Tap Back to
  choose another name." (it was an empty table). Other words?
- (21 Nov) A contract whose feed only returns the day after its expiry, and an MCX future expiring during an outage,
  settle at the last price seen; use the exchange's published settlement price (needs a source)?
- (21 Nov) The Shadow Book's open P&L steps by one spread per position when a market shuts (our exit side while
  open, the user's closing price once shut). One price for both, and which?
- (21 Nov) The "known device" mark (400 days) survives a password reset by the Master: its holder cannot guess
  faster, but can keep the real owner locked out of his usual device by guessing wrong. End it with a reset?
- (21 Nov) Activity record: still no line for a Master login / log-out, backup / Excel downloads, the Master's own
  password change, the daily price-feed login, a refused action. A deleted user's name, coins lines and balance at
  deletion stay in the record for good (the coin history he wished kept): a keeping time?
- (21 Nov) Position card: show that a stop-loss or target is resting. The Stop-loss sheet opens with the trigger at
  the current price, which is always refused if left unchanged: leave it empty, or start it a little away?
- (21 Nov) The same person is called "trainer", "admin" and "master" in the app. Trade History on a phone is a table
  cut at the right (cards like the Order Book?). Master tables on a phone / tablet scroll sideways; the Order Book
  table between 641 and 710 px. Pulse top cards on a phone cut the price with "…". A maintenance time earlier than
  now is taken as tomorrow while the pop-up says "today". A Global order at the weekend is refused as "The Forex
  market is closed … 3:30 am" although that contract opens at 4:30 am.
- (20 Nov) Currency (3% margin, 33x) is the most leveraged Indian market: below zero on a gap above about 3.8%.
- (20 Nov) A silence rule per crypto contract (one contract silent while the rest of its feed delivers); nothing
  checks whether the NSE / BSE / MCX / Currency prices arrive late. (21 Nov: the automatic closes now wait while a
  whole feed is down or silent.)
- (20 Nov) Crypto option chain in rupees (Greeks) is wider than a phone; the leverage row shows on a bought option
  although it changes nothing; small tap areas on the Master page on a phone (arrows, coins + / -).
- (20 Nov) User P&L tab: the "This Week" pill is closed trades only while the Overview's "Net P&L (This Week)"
  includes open positions. The user's Excel "Value" column is in the contract's own currency for Crypto / Forex.
- (20 Nov) The errors list can keep a deleted user's login name for up to 7 days.
- (20 Nov) No limit on the number of visitor price connections per address.
- On an expiry day the price-feed login must be done before 12:30 pm (Currency), 3:30 pm (NSE / BSE) and the MCX close.
- The Master's two-step secret is stored readable in the database and on-server backups.
- The app does not state plainly that trading is in coins (amounts carry the rupee sign).
- The items of "What confuses a new user"; bigger tap areas for the Excel links, period pills, "+ Watchlist";
  dashboard cards show our side while the tables show the users' side, unlabelled; more decimals in the weekly
  ledger note for forex pairs; Indian commas in coins messages.
- Whether the login should take the same time for unknown names; a limit on calls / orders per second per account
  (21 Nov: one login calling search or the option chain without pause costs others about 70 ms a click); whether
  the hosting overwrites the visitor's address header.
- Whether Site health should count requests that crash.
(Answered and taken off on 21 Nov: positions above 50x (none left), the crypto grace time (not to be raised), the
Master page behind the login, the Order Book on a phone, the Master Users table at 1440, "say WHAT changed" in the
activity record. `security-fix/2026-11-16` is on main since 16 Nov 2026; `security-fix/2026-11-14` was put live on
14 Nov 2026, `security-fix/2026-11-12` on 12 Nov 2026.)

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

- Master doors (21 Nov 2026, widened): /admin gives a visitor and a test user only the small login page (no Master
  address, no provider name, not kept by the browser), /static/admin.html and nine other spellings give nothing; a
  user's call under a Master address leaves no line in the activity record. `_doors`.
- Expiry (21 Nov 2026): a future with nobody quoting on its exit side is not valued beyond the other side of the
  book (a one-sided book planted for one function call on an unstreamed future). `_one_sided`, area "Expiry".
- Logins (21 Nov 2026): seven wrong tries at the current password in the change-password box: five refused, then
  locked; the counter is cleared. `_old_login`.
- Capacity (21 Nov 2026): six reports of the test account at the same instant are worked out one at a time. `_one_login`.
- Margin shortfall, in every market (21 Nov 2026): a stop-loss that only closes the position is still accepted. `_shortfall`.
- Prices offline, in every market (21 Nov 2026): with that market's feed marked down (crypto / forex also silent)
  for one function call, the engine asked to close the test account's lot the way a square-off does must decline.
  `_offline_auto`.
- All accounts (21 Nov 2026, read only): every listed contract and open position gives the same "bought option"
  answer from its symbol alone as from the contract. `_option_symbols`.
- Books (21 Nov 2026): last week's Net P&L (Settlement) on the Performance report equals the Weekly Settlement on
  every account (weeks closed on time; an account whose first settlement holds more than that week is skipped);
  no trading line booked in the finished week is dated after its cut-off (newest cut-off).
- Thin book (21 Nov 2026, hardened): "the same sellers cannot be taken twice" needs the book unchanged before and
  after the second order.
- `weekly_sim.py` (21 Nov 2026): "expiry …: with nobody quoting on the exit side …" (3), "feed down: …" (8), "feed
  down at expiry: …" (2), "no underlying price: …" (3), "no contract list: …" (4), "crypto rate: …" (8), "daily …:
  Monday is measured from the weekly cut-off" and "finished week …" (37), "activity record: …" (3), "backup: …" (14).

- First instant of a session (25 Nov 2026, widened), in every market: the test position is valued at its closing
  price, not at the old book in memory (a recognisable closing price is put on it in memory only). `_session_open`.
  Books, widened: a position waiting for the first price of a session sits on its closing price and says so.
- Capacity (25 Nov 2026): a date at the edge of the calendar (0001-01-01, 9999-12-31) in the test account's own
  report, Excel, lists and weekly figure is refused plainly, never a server error. `_edge_dates`.
- Price socket (25 Nov 2026, read only): crypto prices come over one connection, never two (`_one_feed_loop`; not
  judged in the minute of a rebuild). With it a note: crypto option price messages with one side of the quotes
  missing / with no quotes (for the fix waiting on `security-fix/2026-11-25`).
- `weekly_sim.py` (25 Nov 2026): "margin watch: …" (about 20: asks the calculator with nothing held, never an order,
  peak >= now, peak survives a square-off, a deleted account's lines go, the recorder is a watched job), "site
  health: every job started with the site is one the watchdog knows", "domain: …" (7), "opening valuation: …" (19),
  "reconnect: …" (crypto drop and return, a contract that left the list, rebuilds at once), "crypto reconnect: …",
  "expiry: the ledger line of a settled option …". (On the branch with their fixes: "square-off and a resting
  stop: …", the one-sided crypto option book.)

- Masters (26 Nov 2026; `tools/selftest/masters_check.py`, run by run.sh on the private copy: the two test accounts of
  the daily check are ordinary users and cannot act as a master): two movements of coins at the same instant (two
  gifts from one stock, a double click, two new users each given the whole stock, the owner taking the stock back
  while the master hands it out, twenty owner's gifts at once, twelve deposits at once): one at a time, stock +
  coins with users = coins given; a movement of coins at the instant of that user's own fill (owner's and
  master's, 120 each): neither is lost; a delete at the instant of that user's fill never leaves a shut account
  with a position; a deleted account with a name of 57 to 64 letters; deleted accounts listed by ONE rule on every
  list and Excel file; no provider word anywhere in the page a master is sent. 71 → 92 checks.
- Daily check (26 Nov 2026, notes only, never a failure): per feed, how often the order book in memory is wholly on
  the wrong side of a newer price message since the restart, and how far (for the "price before book" decision).
- `weekly_sim.py` (26 Nov 2026): "stop on a thin book: …" (15: the rest of a stop keeps resting, fills at a live
  price, goes with its position), "opening, …" (10: the 30 s wait of a hedged account, judged at the second first
  price or after 30 s, one contract judged at once), "price band: …" (2), "Master's square-off, buyers for 4 of 10
  lots: …" (3). 6842 → 6872 checks. `restore_drill.py`: masters, stock, users, deleted users, weeks (42 → 59).
- run.sh (26 Nov 2026): the Masters check really runs in the full run (it stopped at "Not logged in" since 25 Nov:
  the browser check left the two-step login on).

## Normal-working checks added to `site_check.py` (private copy, real browser)
- 26 Nov 2026 (four, `ui_block_26nov`): the Master's user panel coin ledger at 1440 shows every "Balance after" with
  a 120-letter note and the week-close lines; Settings: the MCX futures commission field shows the server's figure
  and Save stores what is typed; user Pulse at 412 and at 360: the Top gainer / Top loser figures in full.
  `masters_screens_check.py` (25 → 28; needs a FRESH copy, not part of run.sh): Freeze pressed by the owner on a
  master's user says why it is refused; the owner's and the master's coin ledger show every balance in full.
  The browser check has 322 checks.
- 25 Nov 2026 (seventeen): `ui_block_25nov` (11): resting stop / target line on the position card; a Pulse row opens
  the future; the order sheet's Back | Options | Other expiries; Options and Back from the chain; a name without
  options; Market tab opens on Futures; Shadow Book margin cards and columns; Reconnect buttons always shown; Pulse
  list arriving late; a message does not swallow a tap; an empty option chain says so. `accounts_block_25nov` (4):
  coins in whole paise; Shadow Book peak not below now right after a trade; the peak survives a square-off; a new
  account does not start with a deleted account's peak. `tech_block` (2): Reconnect crypto says within 20 s that
  prices arrive; a second Reconnect during a slow rebuild leaves ONE connection. The Stop-loss / Target comparison
  now waits for what it compares (it failed once on 24 Nov on fixed waits). NOTE for check writers: both pages
  refuse text run as script, so `page.wait_for_function` needs a function ("() => …"), never a bare expression.
  The browser check has 318 checks and takes about 7 minutes (limit in run.sh 600 s: little room left).
- 21 Nov 2026 (58 new, in four blocks): UI / user experience block (21): Stop-loss / Target button and sheet, a stop
  and a target rest, position figures beside their labels at 360, "+-0.00", Watchlist line at 360, Order Book cards
  at 360 / 412 and Cancel on a card, Order Book table at 768 / 1440, too-many-lots wording, the Master login page
  (no login, user refused, wrong code + Back, two-step login, log out, dark), Master tables at 1280 / 1440 / 1728,
  panel Status and forex decimals. "Master activity record" block (32): each Master action leaves its line in plain
  words, a user's call leaves none, no line holds a password or secret. `accounts_block` (4): coins lines agree
  with the ledger; the Stop-loss / Target sheet sends the same order as the ordinary ticket; a shut market's card
  keeps the closing-price figure; never "-₹0". Security (1): names and notes with markup in the activity record
  are shown as text. The browser check now takes about 330 s (limit in run.sh 600 s).
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
| 1 | NSE future | market / exit | normal | open | 25 Nov |
| 2 | NSE future | limit (marketable, far, double exit) | normal | open | 25 Nov |
| 3 | NSE future | stop-loss | normal | open | 25 Nov |
| 4 | NSE option (thin) | market, book depth | normal | open | 25 Nov (depth race; no thin strike listed) |
| 5 | NSE option | stop-loss opening a short | normal | open | 25 Nov |
| 6 | NSE option | limit, remainder | normal | open | 25 Nov |
| 7 | NSE any | any | normal | shut / first instant of session | 26 Nov |
| 8 | NSE any | exit / new | normal | feed down / just back | 21 Nov |
| 9 | NSE any | any | normal | expiry minute | 26 Nov |
| 10 | NSE future | market | normal | weekly cut-off in the same instant | 25 Nov |
| 11 | NSE option | resting limit | at the 200-contract limit | open | 25 Nov |
| 12 | BSE future | market / exit / limit | normal | open | 25 Nov |
| 13 | BSE future | stop-loss + entry resting | frozen | open | 25 Nov |
| 14 | BSE option (thin) | market / limit | normal | open | 25 Nov (depth race; no thin strike listed) |
| 15 | BSE any | any | segment switched off | open | 26 Nov |
| 16 | BSE any | any | normal | shut / first instant / feed down | 25 Nov |
| 17 | MCX future | market / exit / limit | normal | open | 25 Nov |
| 18 | MCX future | intraday, stop-loss, flip | normal | open | 26 Nov |
| 19 | MCX option (thin) | market / limit / stop-loss | normal | open | 25 Nov (in-process: the copy lists no MCX option) |
| 20 | MCX future | any | normal | expiry (closing price) | 25 Nov |
| 21 | MCX any | intraday | normal | square-off time / session end | 26 Nov |
| 22 | MCX any | any | margin shortfall | open | 25 Nov |
| 23 | Currency future | market / exit / limit | normal | open | 25 Nov |
| 24 | Currency future | market | normal | weekly cut-off in the same instant | 25 Nov |
| 25 | Currency option (thin) | limit, remainder | normal | open | 25 Nov |
| 26 | Currency any | any | normal | last day after 12:30 | 26 Nov |
| 27 | Currency any | any | segment switched off | open | 26 Nov |
| 28 | Crypto perpetual | market / exit / limit | normal | open | 25 Nov |
| 29 | Crypto perpetual | thousands of resting limits | normal | open | 26 Nov (by the daily check's own attack only) |
| 30 | Crypto perpetual | resting stop + limit | normal | feed silent, then a gap | 25 Nov |
| 31 | Crypto perpetual | leverage 1x then highest | normal | open | 26 Nov |
| 32 | Crypto option | market / limit | normal | expiry time, delisting | 25 Nov |
| 33 | Crypto any | market | normal | weekly cut-off in the same instant | 21 Nov |
| 34 | Crypto any | any | carried position after a cut-off | open | 25 Nov |
| 35 | Forex | market / exit / limit | normal | open | 25 Nov |
| 36 | Forex | resting stop + limit | normal | feed silent, then a gap | 25 Nov |
| 37 | Forex | leverage mix | normal | open | 21 Nov |
| 38 | Forex | any | normal | weekend / Monday opening | 25 Nov |
| 39 | Forex | any | conversion rate missing | open | 26 Nov (rate remembered; a rate never seen: not attacked) |
| 40 | Global | market / exit / limit | normal | open | 25 Nov |
| 41 | Global | resting stop + limit | normal | feed silent, then a gap | 25 Nov |
| 42 | Global | resting orders | normal | daily break / holiday of one contract | 25 Nov |
| 43 | Global | stop-loss + position | account deleted | open | 26 Nov |
| 44 | Global | any | first login, password not yet changed | open | 26 Nov |
| 45 | any | any | short of margin in the weekly grace time | Monday before noon | 25 Nov |
| 46 | any | bought option | carried over a cut-off at a profit | open | 21 Nov |
| 47 | any | exit bigger than the position | segment switched off | open | 26 Nov |
| 48 | any | any | options-only-until-flat account | open | 26 Nov |
| 49 | any | order above the exchange position limit, several resting | normal | open | 26 Nov (by the daily check's own attack only) |
| 50 | any | intraday and overnight mixed at the fill | normal | open | 26 Nov |
| 51 | any | automatic square-off | normal | first seconds of a session / feed silent | 25 Nov |
| 52 | any | two logins of one account at once | normal | open | 21 Nov |
| 53 | Crypto / Forex | any | normal | contract list missing after a restart | 26 Nov |
| 54 | Crypto / Forex / Global | market | normal | book messages stalled, price messages flowing | 26 Nov |
| 55 | any (visitor) | request with a slow body | no login | open | 26 Nov (by the daily check's own attack only) |
| 56 | any (visitor) | price-socket message flood | no login | open | 26 Nov (by the daily check's own attack only) |
| 57 | Currency / stock / MCX | Exit and Master square-off of more than 500 lots | normal | open | 26 Nov |
| 58 | Crypto / Forex / Global | add / reduce / flip | position opened above 50x before the cap | open | 26 Nov |
| 59 | Master page | any address / spelling | visitor, user, dead Master logins | any | 21 Nov |
| 60 | any | stop + target + Exit at the same instant (Stop-loss / Target sheet) | normal | open | 21 Nov |
| 61 | MCX / NSE future (thin) | market, held to expiry | normal | one side of the book empty at expiry | 21 Nov |
| 62 | any | stop / target that only closes | Available Balance below zero (also weekly grace) | open | 25 Nov |
| 63 | any (user) | own Excel / report several at once | normal, thousands of trades | open | 21 Nov |
| 64 | any (user) | wrong current password in the change-password box | logged in | any | 21 Nov |
| 65 | Crypto | market | normal | Sunday 23:59:57 to the cut-off run (fills held) | 21 Nov |
| 66 | any | automatic square-off / margin call / intraday square-off | normal | feed down, silent, just back | 21 Nov |
| 67 | bought option (NSE / BSE / MCX / Currency) + Crypto | automatic square-off | normal | restart, contract list not loaded | 21 Nov |
| 68 | any expiring | settlement | normal | feed down at the expiry moment / underlying without a price | 21 Nov |
| 69 | any | position held over a close | normal | first seconds of a session: closing price until the first price (value, Available, square-off, weekly figure) | 25 Nov |
| 70 | NSE / BSE / MCX | any trade | first trade of the day | margin recorder asking the calculator | 25 Nov |
| 71 | Crypto | Master's Reconnect twice / during the automatic rebuild | - | connection dropping | 25 Nov |
| 72 | any (visitor, user) | Pulse row opening the future, Other expiries, Options | visitor / normal | any | 25 Nov |
| 73 | any | position opened in the last minute before a close | normal | shut market, stray quote, weekly cut-off | 25 Nov |
| 74 | any (user) | report / Excel / lists with edge dates and other accounts' numbers | normal | any | 25 Nov |
| 75 | Master page | account deleted, its number given to the next (Shadow Book peak margin) | deleted | any | 25 Nov |
| 76 | Crypto option | market | normal | one side of the book empty; right after a reconnect | 25 Nov |
| 77 | Crypto any | any | normal | contract left the list while still subscribed, then a reconnect | 25 Nov |
| 78 | any | resting stop / target for the whole position | auto square-off takes part of it | open | 25 Nov |
| 79 | any | stop-loss bigger than the visible book | normal | thin book | 25 Nov |
| 80 | any | hedged account (two contracts) | normal | first seconds of a session, one leg priced | 25 Nov |
| 81 | Crypto perpetual | resting stop | normal | price message before book message | 25 Nov |
| 82 | Masters | deposit / withdraw / new user / stock change fired at the same instant | master, owner | any | 26 Nov |
| 83 | Masters / owner | coins moved at the instant of that user's own fill | normal | open | 26 Nov |
| 84 | Masters / owner | delete a user as his order fills | normal | open | 26 Nov |
| 85 | any (thin) | stop-loss AND target on one position, one of them filled in part | normal | open | 26 Nov |
| 86 | any (thin) | Master's / master's Square off: part or nothing can be closed, user has a stop | normal | open | 26 Nov |
| 87 | NSE / MCX two contracts | none (the margin pass) | hedged, or two losers | first 30 s of a session | 26 Nov |
| 88 | Masters | a master's users all on one side, 10% step | master's stock 0 | open | 26 Nov |
| 89 | any | master's user deleted in the running week | deleted | real Sunday cut-off | 26 Nov |
| 90 | Currency future | expiry | normal | spot-rate connection not up at 12:30 | 26 Nov |
| 91 | Masters pages | names / notes with markup; another book's user by number on every master address | master, owner, user, visitor | any | 26 Nov |

Next in line (oldest), written 26 Nov: 8, 33, 37, 46, 52, 59, 60, 61, 63 to 68 (all 21 Nov), then 20 Nov's 29, 49, 55, 56
(only by the daily check since). Rows 15, 27, 47, 48 need `PT_ACCESS_ALL=0`.

## Nightly rotations (so the next night knows where to go on)
- Technology alarm: job stopped (19 Nov), disk low (20 Nov), backup bad (21 Nov), domain renewal (25 Nov) → next: job stopped → disk low → backup bad. 26 Nov: job stopped → next: disk low → backup bad → domain renewal.
- Price feed state (P6): disconnected, reconnecting, silent (16 Nov), contract list not loaded (19 Nov), slow (20 Nov), disconnected (21 Nov), reconnecting (25 Nov), silent (26 Nov: crypto and forex; the simulated NSE / MCX feed cannot be silenced) → next: contract list not loaded.
- UX pop-ups (U3): Master's message, access switch, install banner (19 Nov); weekly settlement, shortfall, liquidation (20 Nov); the Monday 9:15 reminder, the Master's maintenance notice (21 Nov); Master's message, access switch, install banner (25 Nov); weekly settlement, shortfall, liquidation (26 Nov) → next: the Monday 9:15 reminder, the Master's maintenance notice.
- Load figures (100 users, 60 s, fresh copy): 19 Nov: screens 31 ms, orders 57–69 ms median (yesterday's code the
  same night: 30–51 / 43–84).
  20 Nov: screens 13 ms, orders 24 ms median (95% under 194 / 164 ms), 55 requests a second, no server error.
  21 Nov: screens 15 ms, orders 24 ms median (95% under 308 / 300 ms), 57 requests a second, no server error.
  25 Nov: screens 28 ms, orders 50 ms median (95% under 463 / 381 ms), 55 requests a second, no server error. This
  machine (2 processors) is slower: the code of 21 Nov measured on it the same night gave 25 / 60 ms, 53 a second.
  Compare with 28 / 50 next night only if the machine is the same (run the old code beside it when in doubt).
- UI screens studied closely: 20 Nov: Master Shadow Book, Performance and dashboard filters on a phone; user Market
  tab, option chain, ticket in every market, Order Book, P&L, Account, Pulse.
  21 Nov: Master Users + user panel, Weekly Settlement, Settings (trading access, Site health, activity record);
  user Watchlist, Positions (carried), Ledger, pop-ups, install banner, Order Book cards, Stop-loss / Target sheet
  25 Nov: Master Shadow Book, Performance, dashboard filters; user Market, option chain, tickets in every market,
  P&L, Account, Pulse; 1440 / 412 / 360 / 820, dark and light
  → next: Master Users + user panel, Weekly Settlement, Settings (trading access, Site health, activity record);
  user Watchlist, Positions (carried), Ledger, pop-ups, install banner, Order Book cards, Stop-loss / Target sheet.
  26 Nov: that list, plus the new Masters section and the master's own page (1440 / 412 / 360 / 820, dark and light)
  → next: Master Shadow Book, Performance, dashboard filters, and the Masters section and master's page once more
  (they are new); user Market, option chain, tickets in every market, P&L, Account, Pulse. Method note: a full-page
  screenshot of the user app paints the fixed tab bar in the middle; take viewport screenshots while scrolling.
- Security deep area: 20 Nov capacity without login and the price socket; 21 Nov the Master page behind the login,
  expiry with a broken book, capacity of one logged-in account → next: currency conversion for Crypto / Forex /
  Global and the weekly cut-off of a shut market; export / report inputs.
- Security deep area 25 Nov: currency conversion, weekly cut-off of a shut market, export / report inputs, the code
  since 21 Nov → next: trading-access switches on a copy with PT_ACCESS_ALL=0 (rows 15, 27, 47, 48) and the order
  races around expiry and intraday square-off.
- Security deep area 26 Nov: the Masters feature (coins at the same instant, walls between the books, delete against
  a fill), the access switches with PT_ACCESS_ALL=0 → next: order races around expiry and the intraday square-off
  (rows 20, 21, 51, 73); a master's withdrawal from a user with a LOSING open position and a deposit in the weekly
  grace time (guarded in the code, not driven by hand); what a second owner login can do to a master.
- Risk, next night: the hard moves with TWO losing positions per account (worst loser first was seen with one pair
  only) and with a master's users; the intraday square-off on a thin book with the rest of a stop; rows 66 and 8.
- Accounts commission settings used: 26 Nov: 0.043 / 0.13 / 17 / 0.052 / 0.0077 / 37 / 0.08, MCX futures unset (0.01),
  then 0.023 (method: three copies; PT_FAKE_NOW restarts for the weekend, and the copy on its own clock across the
  REAL Sunday cut-off: a wrapper that patches time.time / datetime before the app is imported; import sqlalchemy,
  pydantic and openpyxl BEFORE patching. PT_FAKE_NOW does not move the weekly loop or the Global timetable.)
  25 Nov: 0.037 / 0.17 / 11 / 0.063 / 0.0058 / 29 / 0.09 (method: one database
  through five server starts with PT_FAKE_NOW and PT_ENFORCE_MARKET_HOURS=true: a weekend, and the clock frozen at
  Monday 9:15:00 for the opening). 21 Nov: 0.029 / 0.21 / 13 / 0.047 / 0.0091 / 43 / 0.11, then 0.055 / 0.09 / 6 /
  0.071 / 0.0044 / 61 / 0.06. Take others next night. (21 Nov method: the copy on its own clock, a real week and a
  real Sunday cut-off; the wrapper lived in the scratch folder: worth keeping in tools/selftest.)
- Running several private copies at once: `PT_SELFTEST_DIR=/tmp/lfx-x bash tools/selftest/isolated.sh <command>`
  (since 25 Nov; own localhost and process list, no internet inside). The full run.sh now takes about 11 minutes:
  longer than one command may run here, so start it detached (setsid nohup) and read its output file.
- Load figures 26 Nov: screens 73 ms, orders 152 ms median, 50 requests a second, no server error; the code of 25 Nov on the
  same machine the same hour: 114 / 127 ms, 49 a second (a slow machine again).
- The 300-user load test has not been run since 15 Nov's week: run it on the next Sunday night without fail.
- No nightly audit ran on 22, 23 and 24 Nov (no entry, no commit): the Sunday restore drill was run on 25 Nov
  instead; the 300-user load test was not run that week.

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
15. (21 Nov) The Stop-loss sheet's trigger starts at the current price, which is always refused if left as it is.
16. (21 Nov) "trainer", "admin" and "master" for the same person.
17. (21 Nov) A position does not show its resting stop or target (rest of item 1).
18. (21 Nov) Pressing Exit and then at once the stop or target already filled in on the sheet opens a new short with
    full margin (the Exit closed the long first). Nothing is gained; it may surprise.
19. (21 Nov) A Global order at the weekend is refused as "The Forex market is closed … 3:30 am".
20. (25 Nov) A stop-loss that meets a thin book shows FILLED for fewer lots with no word, and the rest has no stop.
21. (25 Nov) The "No options" box says "Only futures are listed … trade the future above" also for Forex, Global
    and crypto perpetuals.
22. (25 Nov) On a futures-only account (every new user) the full-colour "Options ›" button leads to a chain where
    every price ends in "Not activated".
23. (25 Nov) Market → Options → Crypto lists names that have no options (explained on the chain since 25 Nov).
24. (25 Nov) P&L line "1 Closed Trades · 100% Winners · Best ₹68 · Worst ₹0".
25. (26 Nov) "+ Watchlist" on the order sheet still reads "+ Watchlist" after it said "Added to watchlist".
26. (26 Nov) Item 15 is worse than written: when the price ticks up in the second of the press, the stop at the
    current price is ACCEPTED and fills at once: the position the user wanted to protect is closed (1 in 6 presses).
27. (26 Nov) An account frozen while its user has the app open: he just sees the public price page with "Log in".
28. (26 Nov) After Exit, "No open positions" beside "USED MARGIN ₹1,10,006" (a waiting limit order's margin).
29. (26 Nov) A master's user is told "ask your admin" / "contact your trainer"; his master is neither word.
30. (26 Nov) Master's page: a minus typed in the amount box and "Deposit" pressed deposits the amount; "You hold
    1,000,000.00 coins" beside "10,00,000" on the card above it (item 8 again).
Answered 25 Nov: items 1 and 17 (the card shows the resting stop and target); item 2 in part (four messages, and
they no longer block the buttons under them).
Answered: item 1 first half (button, 20 Nov) and item 10 (Order Book cards on a phone, 20 Nov); "a stop-loss for
one's own position refused with 'need ₹0.00' while short of margin" was fixed on 21 Nov.
All of these are layout or feature changes: under "Waiting for the owner".

## Findings

### 2026-11-26 (officers' nightly audit, night of 25 → 26 Nov) — one coins-from-nothing loophole in the new Masters feature (two coin movements at the same instant) closed and live with seven faults; three changes wait on `security-fix/2026-11-26`
Self-test at the start (main 98ace60): safety check 325 / 0, browser check 318 / 0, weekly simulation 6842 / 0, no
server error; the Masters check inside the full run FAILED at its first line ("Not logged in"): a fault of the
self-test itself since 25 Nov, see Technology. On tonight's code: see Release. Five officers' agents worked side by
side, each in its own worktree and isolated private copy; the coordinator merged, ran the gates and had the result
reviewed. Everything since be2ebd9 counted as "recent": the held items 2 to 6 put live on 25 Nov, the Masters
feature, "records always remain", the MCX futures commission. The log's "Waiting for the owner" was corrected
(items 2 to 6 of `security-fix/2026-11-25` are live, item 1 was refused).

#### Technology
- **LOOPHOLE (coins from nothing, a master) and FAULT (a fill left off the balance, the owner's path too), FIXED,
  live: movements of coins did not wait their turn.** Every call that moves coins (owner's Add / Remove coins, the
  owner giving or taking a master's stock, a master's deposit or withdrawal, a new user's first coins, a delete that
  returns coins) read the coins, worked out the new figure and wrote it back with nothing held, while orders fill
  under the order lock. Found independently by Technology and Security. *Before:* a master with a stock of 100,000
  gave 100,000 to each of two users at the same instant: both accepted, and taking them back left him 200,000;
  twelve deposits of 90,000 at once from 1,000,000 all went through (630,000 coins from nothing); the OWNER gave
  one coin 300 times while that user's orders filled: 20 ledger lines no longer followed from the line before (a
  fill's result or a gift never reached the balance; 49 of 300 for a master's gifts). The second is as old as the
  Add coins button. *Fix (`app/main.py`: admin_coins, masters_stock, master_create_user, master_coins,
  admin_delete_user, master_delete_user):* each waits for its turn exactly as an order does (order lock, database
  handed back while waiting, everything re-read inside; a new user's password is worked out before the turn is
  taken). Amounts, wording and ledger lines unchanged; nothing booked is touched. *After:* 40 rounds: one accepted,
  one refused, books 100,000 / 0 / 100,000; 300 + 300 gifts during 339 / 405 fills: 0 lines out of step; another
  user's order while a master moves coins without pause: median 30 ms against 28 ms alone. Security's own fix (a
  separate lock) did not cover a fill or the owner's Add coins (measured): Technology's version was kept, both
  officers' checks kept. *Checks:* masters_check "coins at once: …" (8), "deposits firing together …".
  *Real users:* no master existed on live on 25 Nov 17:45; for the owner's Add coins a real user may at some time
  have had one fill or one gift left off his coins if the button was pressed within the same few hundredths of a
  second as his fill: cannot be told from here (a read of the live ledgers would tell: Waiting list).
- **FAULT, FIXED, live (small): a deleted account with a name of 57 letters or more** was not freed (64 letters), or
  the next account of that name answered an error on delete for good (the mark "~deleted<number>" was cut off).
  The mark is kept whole. Checks: masters_check "delete: a name of 64 / 60 / 57 letters …" (4).
- **FAULT in the self-test, FIXED: the full run never ran the Masters check** (the browser check before it turns the
  Master's two-step login on; the Masters check then stopped at "Not logged in"). run.sh switches it off again in
  the throw-away database, and the browser check turns it off when it ends.
- Restore drill extended to the Masters (tool only) and run although it is not Sunday: a master with stock and a
  percentage, his user who trades, a user he deleted, his finished week, an owner's deleted user: **RESTORE 59
  passed, 0 failed** from the encrypted copy alone.
- T1: fresh copy 0 tracebacks, /healthz 200, nine jobs beating, today's backup passes. Alarm of the night JOB
  STOPPED (in-process, the real watchdog loop with the clock moved): margin check silent 181 s → ONE message in
  plain words, /healthz 503, one reminder after 30 minutes, ONE "running again"; a job that never beat and a
  silent backup: one message each; 100 s after a restart: none. Forced restart in mid-trading (8 accounts, 4 of
  them two masters' users, 7 contracts, a test cut-off with 48 carried positions before; `kill -9` after 1,562
  answered orders): answering after 3.4 s; 2,351 answered orders all in the books, none lost, none doubled,
  positions = sums of trades, ledger = coins for all 13 accounts, both masters' books add up, integrity clean.
- T2 (coordinator, quiet machine): 100 users 60 s on a fresh copy: LOAD RESULT OK, no server error, 607
  orders filled, none refused, safety check after the load 325 / 0; screens 73 ms, orders 152 ms median (95% under
  896 / 905 ms), 50 requests a second. More than double the 25 Nov figures (28 / 50), but YESTERDAY'S code (98ace60)
  measured on this machine the same hour gave 114 / 127 ms, 49 a second: the machine tonight, not the code. Compare
  next night only against the old code run beside it.
- T3: not a Sunday night; the restore drill was run all the same (above). The 300-user load test was NOT run.
- T4: no new package, no new environment variable; four new columns on users (is_sub, master_id, share_pct,
  deleted_at) and one index, added at start-up when missing. **Proven on a database made by the code of be2ebd9**
  (6 users, 30 orders in 5 contracts, a test cut-off with 30 carried positions, two accounts deleted the OLD way):
  tonight's code starts on it in 2.1 s, 0 tracebacks, every old row identical, old logins work, every old user is
  the owner's own, Masters list empty. Going back also starts clean, BUT the old code treats a master as an OWNER
  (a paused master logged in and read and changed the owner's users): **never roll back past 4b843fc once a master
  exists** (Waiting list). Account numbers: an account deleted the new way keeps its number; a REMOVED master's
  number (and an old-way deleted newest account's) can go to the next account, with nothing left under it.
- T5: backup after the heavy run: all 12 tables, same row counts, every account incl. masters, their users and
  deleted accounts; integrity and foreign keys clean (also after the kill); pruning keeps exactly the 14 newest;
  a damaged file is set aside with ONE message; the encrypted copy opens with its password and with nothing else.
  Growth: orders fastest (about 200 bytes a row), about 0.55 KB per filled order all told (1,000 fills a day ≈ 200
  MB a year). Deleted accounts now stay for good, so the file only grows (Waiting list; no limit is near).
- No new background job came with the Masters; no Masters call holds the order lock or a write through slow work.
- kite_reactor_check: KITE-REACTOR OK. pip-audit: the same three reports in the one library the price-feed client
  pins, nothing new. Secrets: 377 commits of every branch scanned: none (fake local values and placeholders only).

#### Security
- **No loophole lets anyone reach or damage ANOTHER account, and nothing lets a visitor change data.** The two holes
  found need a logged-in master (or the owner) and requests at the very same instant:
- **LOOPHOLE, FIXED, live: a master's stock spent twice** (see Technology: the same fault, found by both).
- **LOOPHOLE, FIXED, live: deleting a user at the instant his order fills left a SHUT account holding a position**
  (5 of 10 tries: both calls answered 200; a dead login with a live position, its coins already back with the
  master). The delete (a master's and the owner's) now takes its turn with fills: either the fill goes first
  (delete refused: open position) or the delete goes first (order refused). After: 0 of 10 (and 0 of 15). Check:
  masters_check "deleting a user as his order fills never shuts the account with a position still open".
- Masters, attacked and clean: all 117 addresses listed from the code; every /api/master address refuses a visitor
  (401), a user (403) and the owner (403); every /api/admin address and price-feed button refuses a master; /admin
  gives a visitor or user only the small login page; a master cannot trade; a withdrawal from a user with margin in
  use is capped at his free balance (193,951.72 of 200,000); wrong passwords: the same words for an unknown name, a
  master's name and a deleted account's name, throttled after 4 tries; cookie HttpOnly, SameSite, Secure on HTTPS;
  no framing. Coordinator: a master's name, his user's name and a deposit note
  holding markup, opened in a real browser on the owner's Masters section (table, master's tab, the user's panel
  and coin ledger) and on the master's own page (list, panel, ledger): shown as text, nothing ran, no script error.
- Access switches on a copy with PT_ACCESS_ALL=0 (rows 15, 27, 47, 48): a new order, an add, a flip and an exit
  bigger than the position in a switched-off segment are refused, the position stays intact.
- Sweep rows: 6 by Security (15, 27, 47, 48, 43, 44), 6 by Risk (18, 21, 31, 50, 57, 58), 6 by Price / Accounts (26,
  39 in part, 53, 54, 9, 7); rows 29, 49, 55, 56 only through the daily check's own attacks (not by hand: still
  owed). All seven markets traded by hand (buy and exit filled in NSE, BSE, MCX, Currency, Crypto, Forex, Global)
  and attacked by the daily check's proven attacks (325 / 0).
- No new attack check in the daily check tonight: the Masters rules cannot be exercised through its two test
  accounts (ordinary users); they went into masters_check (71 → 92). Seen by the UI officer and left for the next
  night: 140 limit orders in 6 seconds from one account were all accepted on the copy (a per-account pace is
  already on the Waiting list).

#### Accounts
- Three copies: 11 accounts in three books (two masters at 40% / 12.5%, five users of theirs, six of the owner: one
  without trades, one frozen, one deleted after trading, one deleted before trading), seven markets, deposits,
  withdrawals, a user squared off and deleted in the running week, a test cut-off, the percentage changed 40 → 55;
  a weekend with hours enforced; and, for the first time, the REAL Sunday 23:59:59 cut-off with masters on the
  copy's own clock (78 lines, 0 failed).
- **Masters hold, by the officer's own arithmetic:** stock + coins with users = coins given at four moments (e.g.
  4,126,543.22 + 5,123,456.78 = 9,250,000); book P&L + commission = book total = owner's share + master's share to
  the paisa (master 1: 4,510.79 + 7,030.43 = 11,541.22 = 4,616.49 + 6,924.73); a finished week unchanged after the
  percentage change, a delete and new trades; the owner's Users, Positions, Weekly, Performance and Leaderboard
  held none of the masters' users while the Shadow Book listed all; coins returned once per delete.
- Commission by hand on 60+ fills with settings 0.043 / 0.13 / 17 / 0.052 / 0.0077 / 37 / 0.08: all equal to the
  paisa. MCX futures with nothing set: 0.01% + the flat fee (crude 582,000 × 0.01% + 17 = 75.20); after 0.023 was
  set no earlier trade or ledger line of 11 accounts changed and the next fill used it; charge shown before the
  order = charge taken; auto square-off charge once per system order. MCX OPTIONS could not be traded on the copy
  (it lists none): simulation lines only.
- All Time = finished weeks + running week for all ten accounts, with deleted accounts in the book; every ledger
  runs on without a gap; weekend: one closing price on five screens and the Excel, P&L identical a minute later.
- **FAULT (display / Excel), FIXED, live: a deleted account was not treated the same everywhere.** Performance, the
  Leaderboard and both Excel files listed an account deleted before it ever traded (the Users list leaves it out)
  under its internal name; the summary Excel called deleted accounts "frozen"; the Excel weekly sheets gave them
  lines of zeros the Weekly tab leaves out. No total was wrong. Now one rule everywhere, "deleted", the plain name.
  Check: masters_check (6 lines; they fail on the code before). At most one day of such files on live.
- Not done by own arithmetic tonight: dashboard Daily / Monthly and the Shadow Book totals (existing browser checks
  only).

#### Price
- P4 expiry end to end on the running copy: NIFTY future settled at the index 24,313.98 (own book 24,336.90),
  SENSEX at 79,852.63, RELIANCE at the cash price, the 24200 call at 113.98 (= index − strike), the put at 0, crude
  at the exit side of its book; all within 33 s; an expired contract refused in plain words, gone from lists and
  search, a resting order on it cancelled. Row 26 (Currency after 12:30): refused, delisted, settled; found: with
  the spot-rate connection not up in those seconds USDINR was settled at its own closing price (Waiting list).
- P6 SILENT (crypto, forex): after 8 s every order is refused in plain words, positions keep the last price, a
  resting stop is not touched and fills at the real price when prices return. The simulated NSE / MCX feed cannot
  be silenced.
- P1 with the newly live behaviours: the rest of a stop fills only at the book of the moment it triggers again; a
  crypto option with no bid shows ONE value on seven screens / files and cannot be sold ("Nobody is buying this
  contract right now …"). P2 / P3 through the real cut-off: carried at exactly the weekend's closing price,
  original average kept, Monday's figures start from it. P5 / rows 53, 39: after a restart with the crypto and
  forex sources unreachable the positions keep their last price and their rupee factor, orders are refused.
- Row 54 and the waiting "price before book" item re-proved with figures (a stop for 6,000 BTC lots sold 5,500 at
  the book from before a 0.8% fall: about 328,600 coins better than the market). **Added, counting only:** both
  feeds count price messages that find the book in memory wholly on the wrong side; the daily check prints it as a
  note. No fill, price or figure changes.

#### UI
- N2, used for real in the browser at 412 and 1440: owner creates a master, the master's first login (own
  password, two-step set-up), his page, create user, deposit, withdraw, weekly record, square off, delete (refused
  while not flat), the deleted user greyed with his records; the owner sees a master's users only under the
  master's tab; "Commission" everywhere; the owner's own delete keeps the records; the MCX commission field; the
  reworded far-limit refusal. About 330 screenshots at 1440 / 412 / 360 / 820, 212 measured by script (0 script
  errors after the fix below), about 45 read by eye.
- **FAULT, FIXED, live: on the owner's panel for a master's user, Freeze and Reset password said NOTHING when the
  server refused them** (an uncaught script error; the owner would believe it had worked). They now show the
  server's sentence. Hiding those buttons altogether was held by the release reviewer (branch item 3).
- **FAULT, FIXED, live: in the user panel's coin ledger at 1440 a long note pushed "Balance after" off the edge**
  ("6,00,00" for 6,00,000). The note wraps, on the owner's page and the master's.
- **FAULT, FIXED, live: Pulse on a phone cut the Top gainer / Top loser price** ("52,3…"); it takes a second line.
- Checks: site_check `ui_block_26nov` (4), masters_screens_check 25 → 28.

#### Risk (50x cap; 1,000,000 coins, 80% used; 25 Nov in brackets)
- First job: of the five items put live on 25 Nov, items 2, 3 and 6 had no check. 27 written in weekly_sim (they
  fail when the fix is taken out).
- 144 hard moves in seven markets: charge once per system order, nobody left short after the pass, a bought option
  never squared off, only the lots needed, warning → shortfall → square-off in order. Net Balance after a 10% gap,
  future: NSE +413,056, BSE +488,618, MCX +336,496 (sizes differ from 25 Nov), Currency −1,675,653 (−1,676,652),
  Crypto −3,033,422 (−3,033,760), Forex −3,001,229 (−2,995,395), Global −2,980,812 (−2,997,462). Unchanged.
- Masters (new): three users of one master on 3,000,000 coins, all long BTC, a 10% step: users' result −12.1
  million; the owner's 40% share figure 4.84 million, of which 3.64 million has no coins behind it; the other way
  the master's side is −7.18 million. Nothing ties the users' exposure to the master's coins (Waiting list).
- **FAULT, FIXED, live: the Master's Square off answered "1 position closed" with 6 of 10 lots still open** (thin
  book). It now says how many lots are left; no order, price or coin differs. Check: weekly_sim (3).
- **FAULT, fix WAITING (branch item 1): stop-loss and target on one position, the stop fills in part → the target
  later sells too many (2 lots short), the rest of the stop 5 more (7 short).** Possible on live since 25 Nov
  08:48 only with both orders on a book too thin for the stop; the orders table would show it.
- **Fix WAITING (branch item 2): Square off cancels the user's stop before trying to close.**
- The 30 s hedged wait: nobody truly short escapes (judged at the second first price or at 30 s).

#### User experience
- A new user, a new master and a master's user on a 412 phone, first login to logging in again: every step under 2
  s, no dead end. Every refusal reached was plain (lots, coins, band, unknown contract, not activated, feed down,
  frozen; the master's: not enough stock, not his user, not flat). Not reached: market shut, illiquid, expired by
  the real path, too many orders. Pop-ups (weekly settlement, shortfall, liquidation): once, to the right user
  only, across three books. New confusion items 25 to 30 (the gravest: item 26, the Stop-loss sheet).

#### Compliance (housekeeping, not a legal opinion)
- C1: 61 owner and 13 master addresses, 461 calls: visitor 401, user 403, master 403 on the owner's, owner 403 on
  the master's; a master gets 404 for seven kinds of account that are not his; two-step cannot be skipped by the
  owner, a second owner login or a master; a paused master is out at once; ten passwords and three secrets
  readable nowhere (answers, log, activity record, backup); the two-step secret readable in the database (known
  item, now also a master's).
- **FAULT, FIXED, live: the page a master is sent held six unused style rules named after a price provider's
  product.** Removed; nothing on the screen changes. Check: masters_check.
- C2: every action of the owner on a master and of a master on his users leaves a line (who, when, from → to); only
  the owner reads the record. No line: a master's login / log-out, own password change (as for the owner's).
  Removing a master deletes his stock lines (Waiting list).
- C3 / C4: nothing of another book in any answer or socket; a shut account cannot log in, its name is free, its
  records open only to its master and the owner; charge shown = charged (incl. MCX); no provider name to a user or
  master. Whether the business is within the law is for the owner's lawyer and accountant.

#### Release
- Independent reviewer (fresh agent; saw only the diff against live, the rules, D and the list of claims):
  **approved except two points**: (3) the "deleted account" change had made the Master table's rows carry the
  plain name, and the daily check on the LIVE site looks accounts up by that name: a freed name given to a new
  account would have made it fail for no fault. Corrected (rows keep the stored name; only the Excel cell is
  plain) and re-tested. (5) hiding the buttons on the owner's panel with two new sentences is new look and
  wording: moved to the branch (item 3); the spoken refusals and the wrapped note stay.
- Reviewer's remarks for later: more calls now commit on the event loop under the order lock (as orders do);
  removing a master is still outside the lock; "Press Square off again in a moment" is advice beyond the bare
  correction (shown to the owner); an account deleted BEFORE tonight with a 57+ letter name keeps its cut mark.
- Held by the officers before the review: branch items 1 and 2.
- Gates: on the merged code before the review's two corrections: safety check 325 / 0, browser check 322 /
  0, Masters check 92 / 0, no server error, weekly simulation 6872 / 0. On exactly what was pushed, twice in a row:
  see the last line of this entry. Masters click-through on a fresh copy 28 / 0. The branch
  `security-fix/2026-11-26`: weekly simulation 6883 / 0; its safety and browser checks were not run.
- Not tested: the 300-user load test; MCX options over the API; a silent NSE / MCX feed; real exchange messages;
  whether any real account already met the stop-and-target fault or the coins-at-a-fill coincidence (needs live
  data); rows 29, 49, 55, 56 by hand; market-shut and too-many-orders refusals through the screens.

### 2026-11-25 (officers' nightly audit, night of 24 → 25 Nov; the first since 21 Nov) — no free-coins loophole on main; eleven faults in the code released since 21 Nov fixed and live; six changes wait on `security-fix/2026-11-25`
Self-test at the start (main 034f88b): safety check 316 / 0, browser check 301 / 0, weekly simulation 6762 / 0, no
server error. On tonight's code: safety check 325 / 0, browser check 318 / 0, weekly simulation 6824 / 0, no server
error (see Release). Five officers' agents worked side by side, each in its own worktree and isolated private copy
(`tools/selftest/isolated.sh`, new); the coordinator merged, ran the gates, and had the result reviewed. No audit
ran on 22, 23 or 24 Nov, so everything since cfeac56 counted as "recent".

#### Technology
- **FAULT, FIXED, live: the Shadow Book's margin recorder (new 21 Nov) kept the database locked for writing while it
  asked the broker's margin calculator.** Whenever a look had just started a day's line for an account (its first
  position of the day, or the first look after midnight / a restart) the lock was held through one calculator call
  for everybody and one per account with a position: every order on the site waited. Found independently by three
  officers with stand-in calculators (6 accounts, 1.5 s a call: another account's order took 8.67 s; 6.5 s a call:
  refused after 30 s, "database is locked"; 13 accounts, 0.4 s: 5.05 s). Not visible on the private copy as
  shipped (no calculator there). *Fix (`margin_watch.sample`):* what is known is committed first, the calculator is
  asked with nothing held, the answers are written afterwards; same figures. After: 0.01 s. Real users may have had
  all orders stall for seconds at an account's first trade of the day since 21 Nov (no coins involved; cannot be
  told from here). Checks: weekly_sim "margin watch: …".
- **FAULT, FIXED, live: the recorder was the one background job the watchdog did not know** (no beat, no line in
  Site health). Now the ninth job, "Shadow Book peak-margin record" (allowed silence 15 min). Checks: weekly_sim
  "margin watch: the recorder is a job the watchdog knows …", "site health: every job started with the site is one
  the watchdog knows".
- **FAULT, FIXED, live: "Reconnect crypto" asked for again while the first rebuild was still loading the contract
  list (a second press, a second Master, or the automatic rebuild after six quick drops) left a second price
  connection that nothing stopped any more**, not even Disconnect (prices went on arriving on a "paused" feed; each
  later Reconnect left two again; in the 23 Nov situation it doubled the knocking at the exchange). Found by three
  officers. *Fix (`feed/delta.py _fresh`, `_stop_run`, `_runs`):* one rebuild at a time, and whatever is connecting
  is stopped before the new connection starts. Checks: site_check `tech_block` (2), weekly_sim "crypto reconnect: …",
  "reconnect: rebuilding the crypto connection three times at once …", daily check `_one_feed_loop`.
- **FAULT, FIXED, live (small): a hosting setting PT_DOMAIN_EXPIRY that is not a date broke the Site health card**
  (500, an error a minute). Now the built-in date is used. Checks: weekly_sim "domain: …" (7).
- The crypto Reconnect of 23 Nov used for real (simulated exchange killed and restarted): button always shown; waits
  5, 10, 20, 40, 80 s after quick drops, rebuilt itself at 156 s; every drop on record with its reason; ONE "DOWN"
  message per outage and ONE "back and steady"; with the exchange away Reconnect answers after 20.0 s "Not connected
  yet …", with it back after 4.0 s "Connected: crypto prices are arriving again."; a user's order meanwhile refused
  in plain words; no drop reason reaches a user.
- T1: fresh copy 0 tracebacks, /healthz 200, all jobs running, today's backup passes, off-server copy opens. Alarm of
  the night DOMAIN RENEWAL, forced in-process: 30, 14, 7, 3, 2, 1, 0 days: one message each, after 10 am IST, not
  twice a day, not again after a restart; nothing on other days (really 9 Nov 2027, 349 days). Forced restart in
  mid-trading (6 accounts, 6 markets, `kill -9` after 1,717 answered orders): answering after 1.1 s; 2,919 answered
  orders all in the books, none lost, none doubled, 2,438 filled orders with exactly one trade, positions = sums of
  trades, ledger = balance, integrity clean, nine jobs running.
- T2 (coordinator, quiet machine): 100 users 60 s: LOAD RESULT OK, no server error; screens 28 ms, orders 50 ms
  median (95% under 463 / 381 ms), 55 requests a second. More than double the 21 Nov figures (15 / 24), but the
  21 Nov code measured on this machine the same night gave 25 / 60 ms, 53 a second: the machine, not the code.
- T3 (the Sunday run was missed): the restore drill itself was broken (it took its option from the search, which
  listed no NIFTY call first; fixed in the tool: option chain). Then RESTORE 42 passed, 0 failed. The 300-user load
  test was NOT run (shared machine).
- T4: no new package; one new environment variable with a default (PT_FEED_STEADY_SECS); one new table
  (margin_peaks, created at start-up). Proven on a database made by the code of cfeac56 (6 accounts, 14 trades in
  five markets, a test cut-off with 9 carried positions): tonight's code starts in 1.1 s, only margin_peaks added,
  every old row identical, old logins work, the recorder rebuilt the earlier days; going back also starts clean.
- T5: backup holds all 12 tables and every account, integrity and foreign keys clean (also after the kill);
  pruning 20 → 14 with the newest kept; the encrypted copy opens with its password and with no other; passwords are
  hashes. Growth after 2,923 orders (1.6 MB): orders 508 KB (fastest, about 174 bytes a row), ledger 393, trades
  221, positions 139 (closed positions stay), shadow_fills 94; margin_peaks one line per account per day (under
  2 MB a year at 50 accounts, never pruned); crypto drops: memory only, last 30.
- kite_reactor_check: KITE-REACTOR OK. pip-audit: the same three reports in the one library the price-feed client
  pins, nothing new. Secrets: 364 commits of every branch scanned: none (placeholders and the fake local values only).

#### Security
- No loophole that gives coins, takes over an account or lets a visitor change anything was found on main.
- **FAULT, FIXED, live: a deleted account's Peak Margin was shown on the next account created** (margin_peaks is
  filed by account number and was not in `_forget_number`; found by three officers: pk1 bought 2 NIFTY lots, was
  deleted, pk2 got the number and stood on the Shadow Book with Peak Margin 438,102.90 and no order). *Fix:* the
  per-account lines go with the account and when a number is handed out; "everybody together" stays. Checks:
  weekly_sim "margin watch: a deleted account's peak margin goes with it …", site_check "Shadow Book: a new account
  does not start with the Peak Margin of a deleted account that had its number".
- **FAULT, FIXED, live: the first or last day of the calendar (0001-01-01, 9999-12-31) crashed six addresses**
  (report, Excel, trades, orders, ledger, weekly: "500", about 20,000 characters to the server's output each; one
  login could repeat it without end). Now refused like any badly written date. Check: daily check `_edge_dates`.
- Closing price until a session's first price (a8075ed), attacked in-process with clock and prices set by hand: no
  gain (orders on that contract refused, nothing squared off, Available the closing-price figure). Found there: the
  weekly figure of those seconds (branch item 1) and the closing price of a position opened in the last minute
  before a close (Waiting list). New daily check: `_session_open` widened in every market.
- Deep area: currency conversion in Crypto / Forex / Global exact to the paisa (round trips −55.06 / −714.04 /
  −469.82 = prices × factor; 14 Global contracts through their own currency; margin exactly 2.0% at 50x); export /
  report as another account: own data only; nothing injected through file names; weekly cut-off of a shut market
  valued at the closing price.
- Sweep rows run: 11 by Security (2, 4, 5, 6, 10, 11, 13, 14, 19 in-process, 24, 25), 13 by Risk, 14 by Accounts /
  Price (dates in the matrix). All seven markets attacked by hand (junk numbers, buying past the visible book, Exit
  six times at once, limit above the offer, round trips losing money, ledger = coins).
- No-login sweep: 88 addresses, five methods, as visitor and as user (870 calls): only the public pages, the small
  login page, login, logout, /healthz and the public home data answer a visitor; a user is refused on every Master
  address; wrong passwords 5 then locked, same words for known and unknown names; cookie HttpOnly, SameSite, Secure;
  logged-out and password-changed logins dead; two-step cannot be skipped; no framing; visitor's socket gets prices
  only. New text places since 21 Nov (resting line, "no options", drop reasons, Shadow Book columns): all escaped.

#### Accounts
- Nine accounts (two in all seven markets; one without trades, one frozen, one deleted after the cut-off, one with a
  segment switched off, two auto-squared-off, one brand new), one database through five server starts (ordinary
  day, a pretend Saturday with hours enforced, a pretend Monday 9:15:00 on old and new code). Truth rebuilt from
  the tables and compared with the Master row, dashboard formulas, Weekly Settlement, Performance, Shadow Book, the
  user's own screens and every Excel file: about 6,500 comparisons; the ones not equal were the two faults below
  or the script's own. Identities hold; commission by hand on 40 fills with settings 0.037 / 0.17 / 11 / 0.063 /
  0.0058 / 29 / 0.09: all agree; one charge per system order. Coins with fractions of a paisa (eight entries and a
  first allocation): whole paise, ledger line = balance step, once each. Deleted account: 24 totals dropped by
  exactly its figures. Master dashboard formulas were re-done in script, not read off the browser.
- **FAULT (display), FIXED, live: in the first moments of a session the position card, the running week and the
  Shadow Book did not stand on the closing price** although the server valued Available Balance at it (decision of
  21 Nov): the screen was told to re-price the card itself, and the running week and Shadow Book used the old book
  or a stray quote (NIFTY long, stray quote 11% lower: +59,985 on the rows, −450,015 on the running week; lasts
  until the contract's first price, on a thin contract hours). *Fix:* `engine.position_dict` "at_close" also while
  awaiting the first price; `weekly.running_price` for the running row only; `main.admin_shadow`. The cut-off
  itself is unchanged (branch item 1). Checks: weekly_sim "opening valuation: …" (19), daily books check widened.
- **FAULT (display), FIXED, live: the Shadow Book showed Peak Margin below Margin Now right after a trade** (the
  recorder looks every 20 s: 1,461,628 beside 801,099). The peak shown is never below the margin of the moment;
  nothing stored. Check: site_check "Shadow Book: right after a trade Peak Margin is not below Margin Now …".
- First jobs done: opening valuation, coins in whole paise, Shadow Book peak (checks in site_check and weekly_sim).

#### Price
- P1, in-process with hours enforced, 13 kinds of contract in seven markets, 200 checks: fills only at the live
  offer / bid; nothing on a holiday, at night, at the weekend, in a Global break or in the opening instant; limits
  never better than the book. P2: after a pretend Saturday restart 18 positions at the closing price, P&L equal to
  the close, none at zero, no "feed down" for the shut Indian markets (Forex / Global not judged: the pretend feed
  keeps the real clock). P3: 25 carried positions at the week-close price, average kept. P5: one rupee factor per
  contract on every screen, rates known after five restarts. P4 only by the existing simulation checks and 5 scratch
  checks. P6 RECONNECTING (crypto): 88 sell orders during a real reconnect with the market 2% lower: 87 filled at
  the new prices, 1 refused; none at a pre-drop price.
- **FAULT, FIXED, live: a contract that left the crypto list while still open on somebody's screen (an option the
  night after its expiry) broke every later connection** ("KeyError" on its number before anything was subscribed:
  no crypto prices until a restart, whatever Reconnect was pressed). Matches the night of 23 Nov but NOT proven
  (needs that night's server log). *Fix (`delta._channels`, `_unsubscribe`).* Checks: weekly_sim "reconnect: a
  contract that left the crypto list …" (2).
- **WRONG-PRICE LOOPHOLE, fix WAITING (branch item 4): a crypto option keeps an old bid or offer when one side of
  its book goes empty** (sold 10 lots at an old bid of 395 with the option worth 250; proven with messages fed by
  hand only). Held by the coordinator: the fix changes how a held option with no bid is valued, and whether the
  real exchange sends an empty side as "nothing" could not be seen offline (if it sometimes sends no quotes at all,
  the fix would empty option books). Main only counts such messages; the daily check prints the note.

#### UI
- N2: everything asked for between 21 and 24 Nov used for real at 412 and 1440 and works as its commit says:
  resting line on the position card; Shadow Book cards and columns; Reconnect buttons; a Pulse row opens the
  nearest future in all eight views; Back | Options › | Other expiries as three equal buttons (122 / 120 / 122 px
  at 412; also 360, 820, 1440, light and dark), each doing what it says, incl. "No options trade on X" and "Only
  one contract is listed"; Back from the chain; Market tab opens on Futures. Each has its check (`ui_block_25nov`).
- About 620 screenshots at 1440 / 412 / 360 / 820, measured by script (off-screen, undefined / NaN, cut text, small
  tap areas, script errors: none); about 30 read by eye.
- **FAULTS (display), FIXED, live:** (1) Pulse showed the list of the market or period chosen a moment earlier
  under the new choice (a late answer replaced the list; 29 rows of other markets under "Indices"); (2) the little
  messages after an Exit covered Back | Options | Other expiries and swallowed the taps (the message now lets taps
  through; nothing looks different); (3) an option chain with nothing listed was a bare table head: it now says
  "No options are listed for X right now. Tap Back to choose another name." (new sentence: shown to the owner in
  the report).
- The Stop-loss / Target comparison check waited fixed times (the failure of 24 Nov): it now waits for what it reads.

#### Risk (50x cap; 1,000,000 coins, 80% used; 21 Nov in brackets)
- About 230 hard moves. R1 (102): warning first on a slide, shortfall and square-off of only the lots needed, a deep
  loss closes everything, one charge per system order, a bought option never squared off, in all runs.
- Net Balance after a 10% gap, future: NSE +451,756 (+448,719); BSE +359,116 (+355,904); MCX +357,326 (+354,013);
  Currency −1,676,652 (−1,655,858); Crypto −3,033,760 (−2,993,117); Forex −2,995,395 (−2,994,958); Global
  −2,997,462 (−2,982,856). Below zero from a one-step gap of 2.4% (Crypto), 2.5% (Forex, Global), 3.7% (Currency),
  15.6% (BSE, MCX), 18.3% (NSE). Unchanged rules; nothing new proposed. Largest position for 1,000,000 coins: NIFTY 4
  lots, SENSEX 5, crude 14, gold 1, USDINR 391, BTC 6,613, EURUSD 472, US500 69 (same multiples as before).
- a8075ed at the opening, 40 runs in six markets: a stray quote while shut changes nothing; a real gap is judged at
  the first real price; nobody escapes. Found: branch items 1 and 3.
- **FAULT, fix WAITING (branch item 5; held by the release reviewer): after the auto square-off closed PART of a
  position, the user's stop-loss still asked for all the lots**: refused when its price was reached ("Insufficient
  coins") and the remaining lots had no stop (all 9 slide cases in 7 markets); a target in the same situation was
  filled in full and left the account SHORT (NSE −1 lot, Crypto −341 lots …). The fix cuts such an order down to the
  lots that are left. Held: nobody gains, and it is new behaviour for a user's own order with a new sentence.
- Thin book: branch item 2 (the rest of a stop is dropped); a bystander's stop refused and deleted when the visible
  buyers were taken by twenty square-offs (Waiting list). Crypto price message before book message: a stop filled
  563,062 coins better than the market on the feed class fed by hand (sketch only; needs a live measurement).
- **FAULT (text), FIXED, live:** the ledger note of a settled option read "settled @ 2430.0000000000036"; now
  "2430.0". The amount booked is unchanged. Check: weekly_sim "expiry: the ledger line of a settled option …".
- Weekly cut-off with hours enforced (14 runs): Sunday warning, one reminder at Monday 9:15:00, at 12:00:30 only the
  lots needed, one charge.

#### User experience
- U1, brand-new futures-only user on a 412 phone, about 55 real taps from first login to logging in again: 0.05 to
  0.83 s each, nothing stuck. U2: every refusal hit and read (coins, lots, bad numbers, shut contract, inactive
  segment, feed off, thin trading, expired, 501st pending order, frozen): all plain, no provider name. One
  rewording (limit price outside the exchange band) was HELD by the reviewer (branch item 6). U3: Master's message
  (once, as text, right user), access switch (lock on the open ticket at once), install banner (Android and iPhone
  wording, ✕ keeps it away). U4: items 1 and 17 answered; new items 20 to 24.

#### Compliance (housekeeping, not a legal opinion)
- C1: 55 Master addresses refuse a user and a visitor; two-step: password alone gives no session, the 5-minute pass
  is refused everywhere, a second Master needs his own code; no password, hash or secret in 20 Master answers,
  Excel files, the activity record, the server log or the errors file; backup holds hashes only.
- C2: every coins entry, setting, access switch, freeze, square-off, notice and the new Reconnect / Disconnect
  buttons leave a line saying what. Still none for downloads, Master login / log-out, own password change, the
  daily price-feed login, a refused action (already waiting). The Reconnect crypto line reads "reconnected from
  scratch" also when it did not connect (Waiting list).
- C3: data held as before plus per account and day the peak-margin figures; the deleted account's line was the fault
  above; one user's marks appear on nobody else's screens, files or socket.
- C4: charge shown before the order = charged (675.51 at 0.037%); no provider name or drop reason in 40-odd user
  answers; nothing promises profit. Whether the business is within the law is for the owner's lawyer and accountant.

#### Release
- Independent reviewer (fresh agent; saw only the diff against the live code, the rules, D and the list of claims):
  **approved except two items, which were taken off main**: (10) cutting a resting stop / target down after a
  partial auto square-off: the fault is real and the code sound, but it is new behaviour for a user's own order
  with a new sentence, so the owner's yes is needed; (12) the reworded "exchange band" refusal: no proved fault.
  Both are on the branch (items 5 and 6). Held by the coordinator before the review: the crypto option fix (item 4).
- The reviewer's remarks for later: the Master's tooltip "Market is shut" now also shows in the opening moments; the
  recorder's 15-minute silence could false-alarm if the calculator answers very slowly for many accounts; a
  Reconnect pressed during a rebuild is dropped silently (the answer still tells the true state); `_channels` with
  every wanted contract gone would send an empty subscribe; dates one day inside the calendar's edges were not
  tried; the three margin-recorder blocks in weekly_sim overlap and "every job … the watchdog knows" breaks when a
  task is added that is not a watchdog job; if item 5 is released: lot size from the contract, a try / except round
  the call, a sentence in the square-off alert.
- Coordinator's own changes after the merge: three officers had fixed the recorder, the reconnect and the deleted
  account's peak each in their own way: one version kept (Technology's), every officer's checks kept; two test
  blocks used the same account name and the same day's line; the browser check "Master Shadow Book: …" assumed the
  Peak card equals the sum of the users' peaks (it is the peak of everybody together and keeps deleted accounts):
  corrected in the check. Gates: full run on the merged code 325 / 0 and 318 / 0, no server error; on exactly what was
  pushed, twice in a row: safety check 292 / 0 and browser check 318 / 0, no server error (between 3:30 and 4:30 am
  IST the simulated Global contracts are in their daily break by the real clock, so the plain run has 292 checks);
  the safety check again with Global open (`FAKE_OPEN=1`): 325 / 0; weekly simulation 6824 / 0. The branch
  `security-fix/2026-11-25`: weekly simulation 6837 / 0; its safety and browser checks were not run.
- Not tested: the 300-user load test; the recorder against the real calculator; real exchange messages; MCX options
  over the API (the copy lists none); light theme by eye at every size; real phones.

### 2026-11-21 (officers' nightly audit) — one free-coins loophole (expiry of a one-sided book), four wrong-price / wrong-margin faults that give or take coins, four other loopholes and about twenty-five faults, all live tonight; two fixes held as patches
Self-test at the start: safety check 292 / 0, browser check 243 / 0, weekly simulation 6681 / 0, no server error.
On tonight's code: safety check 316 / 0 (284 / 0 once Global had shut for the weekend), browser check 301 / 0, weekly
simulation 6762 / 0, no server error. The officers worked side by side, each on its own private copy (own network
and process space: `unshare -n -p`, so the fixed ports do not collide), merged by the coordinator.

#### Technology
- Fresh copy starts with no server error; `/healthz` 200; Site health: all eight jobs running (prices, square-off,
  expiry, weekly, feed alarm, day-start, backup, daily check), today's backup opened and passed its check, the
  off-server copy sent to a pretend chat and opened again. Alarm of the night: **backup bad**, forced in-process four
  ways (rubbish written, empty file, a database without the tables, a copy cut in half): each time one Telegram line
  ("did not pass its check: …"), the file set aside as `.bad`, Site health shows the failed check, the next round
  writes a good one.
- **FAULT, FIXED, live: a backup found damaged at the start stayed as the day's backup and was sent
  off-server.** When today's file is already there and no check of it is on record (the site was restarted while the
  backup was being written), the job checked it and told the owner, but did not set it aside: no fresh backup that
  day, and the damaged file went out as the day's encrypted copy. Proven in-process (file cut in half). *Fix
  (main.py `backup_loop`, second branch):* renamed `.bad` exactly as the first branch does; the next round writes
  and sends a good one. Touches no account. Checks: `weekly_sim.py` "backup: …" (12, also the alarm, every table in
  the backup, pruning to fourteen with the newest kept).
- **FAULT, FIXED, live: every "Download backup" left a full, unencrypted copy of the books in the server's
  temporary folder** (never removed until the next deploy; one per minute of use). *Fix (main.py `admin_backup`):*
  the copy is removed once sent; one left by a broken download goes with the next download. Proven over HTTP
  (file there before, none after) and in `weekly_sim.py` ("backup: the Master's download …", 2 checks).
- Forced restart in the middle of trading (six accounts ordering without pause in six markets, limit orders rested
  and cancelled in between, `kill -9`), twice (before and after tonight's changes): answering again after 2 s;
  2,344 / 2,633 answered orders all in the books, none lost, none doubled, every filled order with exactly one
  trade, no trade of an unfilled order, no margin left blocked by an order that is not resting, every open position
  equal to the sum of its trades, last ledger line = balance for every account, integrity check and foreign keys
  clean, a login made before the kill still works and trades. (That is also "stopped in the middle of a write".)
- Data: the Master's backup file holds all 11 tables with the same row counts and all accounts with the same
  balances as the books, and passes the integrity and foreign-key checks; the encrypted copy opens with its password
  (11 tables, all accounts) and not with an empty, a wrong-case, a one-letter-short or another password; nothing
  readable in it; passwords in the backup are hashes. Growth after 2,400 orders: orders 430 KB (about 177 bytes a
  row), ledger 356 KB, trades 200 KB, shadow_fills 86 KB: about half a kilobyte per filled order, nothing pruned
  (unchanged). `admin_log` with the new detail column: about 150 bytes a line (text 65–85 bytes; longest line 179;
  a line is cut at 1,500): a Master doing 100 actions a day adds about 5 MB a year. See Compliance for what made it
  grow without limit until tonight.
- Deploy risk (`git diff e0eddb9..HEAD`, `git log --since="2 days ago"`): no new package (`requirements.txt`
  untouched), no new environment variable, one database change (`admin_log.detail`, added at start-up). **Proven on
  an old database**: a database made by the code of e0eddb9 (7 accounts, 56 trades in four markets, a cut-off with
  carried positions, 12 activity lines), then tonight's code started on it: starts with no error, column added,
  every table's rows identical (users, ledger, positions, trades, orders, week_settlements compared by hash), the 12
  old lines still listed (empty detail, shown the old way), balances on the Master page identical, logins made
  under the old code (Master and user) still work, a new action writes its detail, all jobs running. Going back to
  the older code would also work (the extra column is ignored).
- The Master page's move to `app/pages/`: the Dockerfile copies the whole `app` folder, there is no `.dockerignore`,
  `.gitignore` does not hide it, the file is in git; the service worker never touches `/admin` and its cache list
  does not name the page; README and the daily check already point to the new place; nothing else refers to the
  old path. The backup does not hold pages. `/static/admin.html` and nine other spellings give 404.
- Known weaknesses (`pip-audit`): the same three reports in the one library the price-feed client pins; nothing new.
- Seen, not changed (for the Accounts officer): the sum of a ledger's amounts can differ from the balance by one or
  two paise after some hundreds of trades (each amount is rounded on its own; the running balance column and the
  balance agree to the paisa).
- Not run by me: the load test (coordinator).
- Load, 100 users for 60 s on a fresh copy of tonight's code (machine quiet): LOAD RESULT OK, no server error; screens
  15 ms, orders 24 ms median (95% under 308 / 300 ms), 57 requests a second (last night 13 / 24 ms, 55 a second: not
  slower). Safety check after the load 0 failed.

#### Security
- **First job, done: daily check for the Master page behind the login** (`probe._doors`). As a visitor and as a test
  user, /admin answers the small login page (under 12,000 characters, the login button, no "api/admin", none of the
  price-provider names, not to be kept by the browser), /static/admin.html answers 404, and nine other spellings of
  the address (/pages/…, /static/..%2fpages/…, /static/%2e%2e/…, /admin.html, /admin/ …) hand out nothing that holds
  a Master address.
  Attacked by hand (raw connections, GET and HEAD): 31 spellings under /static, /pages, /app, doubled slashes,
  encoded dots and backslashes, a zero byte, also for main.py / config.py / .env / the nightly report; a range
  request; a conditional request with the Master file's own tag; a user's login as cookie, as Bearer header, the
  Master's login in the address; a half-finished two-step login as cookie and as Bearer; a logged-out Master login;
  a Master login from before a password change; a removed Master's login, also after the number was given to the
  next account. None gets the Master page or a Master address. HEAD is 405. The service worker's list holds "/" and
  two icons only and never touches /admin. The login-only page names nothing behind the site (4,151 characters).
  Not a hole, noted: a Master login marked "frozen" (through the users address) still logs in and works; freezing
  is a rule for users only, and only a Master can do it to a Master.
- **LOOPHOLE, FIXED (a user damages the Master's record): a user could write into the Master's activity record.**
  The two-step set-up answers an ordinary user under /api/admin/2fa/… too, and the recorder wrote a line for every
  successful call under /api/admin/, whoever made it. 230 calls by one user (2.6 s) left 200 lines under the user's
  name on the activity screen and not one of the Master's own actions. The name of whoever acted was also put into
  the page unescaped: with a login name that holds markup, the line ran as script in the Master's browser (shown in
  Chromium; a user cannot choose his login name, so this needed a name typed by a Master).
  *Fix (main.py `_admin_audit`):* only a Master's action is recorded. *(pages/admin.html `#auLoad`):* the name is
  shown as text. *Checks:* `probe._doors` (the test account asks for a two-step set-up under the Master address, the
  set-up is taken back, no line may appear); `site_check` "Master activity record: names and notes with markup are
  shown as text, and no line holds a password". After: 0 lines by users, no script run.
- Review of the other recent change (Stop-loss / Target button, `admin_log.detail`, `main._note`): every detail line
  is shown through `esc()`; the text in it comes from the Master (login names, display names, the note on coins)
  and from numbers; a user controls none of it. After creating users and Masters, resetting passwords, a two-step
  set-up and password changes, no line held any of the eight passwords or the two-step secret used. The
  Stop-loss / Target button sends an ordinary order (see below for the attack on it).
- **LOOPHOLE (free coins), FIXED: a future settled at an old last trade when nobody quoted on its exit side**
  (sweep rows 20 and 9; in-process, prices and clock under control). A thin future in its last hours with sellers
  only at 1,000 and a last trade of 1,100 from the morning: buy 5 lots at 1,000, do nothing, be settled at 1,100:
  +180,000 coins. The same the other way round (buyers only at 5,500, old trade 5,000, sell, +250,000), and for an
  NSE future when the index price is missing or more than 5% away (+75,000). The fix of 14 Nov ("the exit side of
  the book, not the last trade") fell back to the last trade when that side was empty; only the weekly valuation
  capped it at the other side.
  *Fix (weekly.py `inside_book`, used in `remember_marks`; engine.py `_settle_expired`):* the closing price kept for
  a position, and the price a book-settled future is settled at, is never above the best offer for a long nor
  below the best bid for a short. A two-sided book is untouched (bid is below offer). *Checks:* `probe._one_sided`
  (area "Expiry": a one-sided book is put in memory for an unstreamed future for the length of one function call,
  the closing price is worked out for a position that is never stored); `weekly_sim` "expiry …: with nobody quoting
  on the exit side a future is not settled beyond the other side of the book" (3: sellers only, buyers only,
  sellers gone before the close). Before: 3 failed (+10,000 / +5,000 / +8,000); after: 0 failed, settled at the
  price dealt. This changes a settlement price in exactly that situation: coordinator / release review to decide
  live or held. Whether a real account has already gained cannot be seen from the private copy: look for a future
  bought (sold) on its last day and settled above (below) the price dealt with no trade in between.
  Left open: while such a contract is still trading, the position screen values it at the last trade (old item).
- **LOOPHOLE, FIXED: the current password could be guessed without limit in the change-password box**, and each
  guess is slow on purpose: 24 at a time from one login made another user's screens 9 → 42 ms and orders 16 → 84 ms
  (median; machine busy). *Fix (main.py `change_password`):* five wrong tries, then five minutes' wait, the same
  rule and words as at the login. *Check:* `probe._old_login` (seven wrong tries on the test account: 400 ×5, then
  429 ×2; the counter is cleared). After: 0 of 40 guesses looked at. The flood of refused calls itself still costs
  others about 30 ms a click: the known "no limit on calls per second" item, already with the owner.
- **LOOPHOLE (one account slows everybody), FIXED: eight Excel downloads / reports at a time from one login.** An
  account with 2,400 trades downloading its own Excel without pause: other users' screens 95% 1.26 s, worst 1.4 s;
  orders 95% 1.5 s, worst 3.9 s (quiet: 16 ms / 33 ms). The report address: median 230 ms for everybody else.
  *Fix (main.py `_Turnstile.HEAVY`):* /api/export.xlsx and /api/report are worked out one at a time for one login;
  the next one waits behind it (nothing is refused). After: screens 95% 221 ms, worst 334 ms; orders 95% 188 ms;
  report flood: median 27 ms. *Check:* `probe._one_login` (six reports of the test account at the same instant:
  one worked on at a time, all answered).
- **FAULT, FIXED: a stop-loss or target for one's own position was refused while Available Balance was below
  zero** ("Insufficient coins: need ₹0.00, available ₹-42,005.85"), found in the weekly grace time (row 45): just
  when a position most needs its stop, the new Stop-loss / Target button gave this. *Fix (engine.py `place_order`):*
  a resting order that only closes what is held (needs nothing) is taken; one lot more than held is refused as
  before, and the fill still checks margin. *Check:* `probe._shortfall` in every market ("short of margin: a
  stop-loss that only closes the position is still accepted"; only the "need ₹0.00" refusal counts as a failure).
- No hole (fresh ideas): stop + target + stop + target + Exit ×2 at the same instant in all seven markets (when
  Exit wins the race the later sales open an ordinary short with its full margin: 875,669 held vs 875,885 for a
  fresh short; with stop and target resting first, Exit ×3 leaves nothing held and nothing resting, in all seven);
  the "known device" mark at the login (a former holder still gets 5 tries per 5 minutes and no more, see open
  ideas); huge numbers in addresses and bodies; the price socket with contract numbers that do not exist (not
  streamed, count only against the sender).
- Sweep rows run (10 in full, 4 in part): 9 NSE expiry minute (orders at 15:39:58 fill, at 15:40:00 are refused,
  resting GTT limit / stop do not fill on a price through them at 15:40:00, are cancelled and their margin freed,
  future settles at the index, option at its intrinsic value); 20 MCX expiry (hole above); 8 NSE feed down (exit,
  buy, limit all refused); 45 short of margin in the weekly grace time (buy, other market, buy stop, far limit,
  flip, option: all refused; own reduction ends the grace and buying back is refused; nothing squared off before
  12:00; fault above); 46 bought option carried at a profit (margin = carried value 299,962.50, account short at
  once, nothing can be opened with the paid-out profit, half sold frees half, square-off of 2 lots at 12:01, weeks
  + coins = own-price P&L 135,042.95); 7 and 16 NSE / BSE shut and first instant (refused when shut; resting GTT
  orders untouched by a stray quote 1,000 lower; at 9:15:00 with the old book in memory buy and exit refused,
  resting orders wait); 3 NSE stop-loss (wrong side, 0, negative, huge, without the coins: refused; ten stops
  opening a short at once: one rests, nine refused); 37 Forex 1x then 50x then sell (margin kept 83,811 vs 6,325
  needed at the top leverage; 0.5x / 51x / 1e9 / −3 refused); 52 two logins of one account (12 buys of 60% of the
  coins at once: Available never below zero; Exit ×8 and a log-out at once: one fills, flat, the other login
  works, the logged-out one is dead). In part: 4, 6, 14 (NSE / BSE options: one order cannot be bigger than the
  exchange allows, which is less than the pretend book offers; limit at the best offer never filled above it), 25
  (Currency: asked 115 with 112 offered, got 94, then "nothing left" twice). 19 (MCX option) not reached by hand:
  the private copy listed no MCX option for the names tried; the daily check's thin-contract attack on MCX passed.
- Every market by hand (NSE, BSE, MCX, Currency, Crypto, Forex, Global): the stop / target / Exit race above,
  nonsense lots (0, −1, 10^12, 1.5, NaN: refused), a limit 5% above the offer (filled at the offer), 12 buys at once
  (Available never below zero), ledger = coins every time. Thin options also Crypto (offered 2, asked 5, got 2,
  then "nothing left"; reservation of the resting rest freed on cancel).
- No-login sweep: 87 addresses, five methods, as visitor and as user (850 calls): only the public pages, /admin
  (login page), login, logout, /healthz and the public home / pulse / maintenance / underlyings data answer a
  visitor; the price-feed return address sends a visitor to the Master page with a message; a user is refused on
  every Master address. Wrong passwords: locked after 5 for a name (existing or not, same two messages), after 20
  for an address; right password refused while locked; cookie HttpOnly, SameSite, Secure over https; a logged-out
  and a password-changed login are dead (cookie and Bearer); three forged logins refused; the two-step cannot be
  skipped (wrong code, empty code, a full login in place of the half one, the half one as a session); no framing,
  no sniffing, no answer to another site's pre-flight, an order posted as plain text from another site is
  refused; a visitor's socket: asked for 30 contracts with 10 options, got 10 futures / indices and no option, no
  event of a trading user; an oversized message ends it; a logged-out login on the socket is a visitor.
- Known weaknesses in the software: pip-audit ran: 3 reports, all in the one library the price-feed client pins
  (autobahn 19.11.2: PYSEC-2020-25 twice, PYSEC-2026-4027), server side of that library only, which the site does
  not use; the same as the last nights, nothing new. Repository and its whole history (314 commits) searched for
  passwords, tokens and keys: only the made-up test passwords of the self-test and the placeholders of .env.example.

#### Accounts
- **Method new tonight: the private copy on its own clock.** A whole week was played with the copy's clock moved
  (a small wrapper in the scratch folder sets `time.time` / `datetime` before the app is imported; nothing in the
  repository): Mon 30 Nov → Tue 8 Dec 2026, the same database through twelve restarts, market hours enforced, the
  trading-access switches enforced (`PT_ACCESS_ALL=0`), the site up across every midnight (so every day has its
  day-start record) and across the REAL Sunday 23:59:59 cut-off (not the test button). The earlier nights compared
  on one calendar day with the test button; three of tonight's four fixed faults only show with real days and a
  real Sunday.
- Nine accounts: two trading all seven markets (NSE index and stock futures, bought and sold options; BSE; MCX
  futures and options; Currency futures and options; Crypto perpetuals and options bought and sold; Forex; Global),
  one with no trades, one frozen mid-week, one with MCX futures switched off while holding one (adding refused,
  reducing allowed), one auto-squared-off (Master took coins back), one deleted after the cut-off, one brand new,
  one new with a single trade. 35 positions carried over the real cut-off; exits of carried futures, a carried
  bought and a carried sold option, a flip and an add after it; a second cut-off in mid-week with the test button
  and trades after that.
- **Comparisons made, honestly counted.** Truth was rebuilt from the tables alone (trades, ledger, positions,
  week records) and compared with: Master row, dashboard figures of every day / week / month since the start and
  All Time, Weekly Settlement running and final, Performance, Shadow Book (mirror realised, turnover, slippage
  rebuilt from the recorded mirror prices), the user's own funds / positions / weekly / report, and every Excel file
  (user: all statements, P&L, ledger, order book; Master: all users, each user, the three single statements,
  summary; all time, this week, last week). Before the fixes: 72,370 comparisons, of which 61,642 on the server's
  answers in thirteen states (new day and month with Indian markets shut; after three midnights; all markets open
  with the feeds disconnected; night with Indian markets shut and their prices still ticking; mid-week with a
  frozen account, a segment off and new commission settings; Saturday; Sunday 00:02 with crypto and forex feeds
  disconnected; the minute after the real cut-off with a trade after it; Monday mid-morning; after a delete; right
  after the test-button cut-off; trades after it; Tuesday 00:02) and 10,728 read off the real browser (Master page:
  every dashboard period with its cards and both user panels, Weekly Settlement running and final, Performance in
  five ranges, Shadow Book; user app: Positions cards, P&L tab, weekly list) in four states (after the cut-off,
  Monday mid-morning, after the second cut-off, Tuesday 00:02). The browser part did NOT run in the four states
  before the cut-off (my driver: the Master page asks a Master without two-step login to set it up; then the
  browser driver was restarted wrongly); the server-side comparison ran in all of them. After the fixes, on a copy
  of the books as they stood one minute after the cut-off: 5,174 + 2,405 (browser) comparisons, 0 mismatches.
- What the mismatches were: 205 + 12 + 1 belong to the three display faults below, 23 + 9 to the coins fault
  below, 49 to the Saturday run where the pretend forex feed went on ticking the rupee rate (the real one is silent
  on a weekend; with it disconnected, 3,699 comparisons, 0 mismatches), 140 to my own script (it asked the ticket's
  commission estimate before the contract had a price: the answer is then the flat fee alone), 1 to an order of
  mine between the provisional and the final reading.
- Commission by hand from the Master's settings, two different sets in one week (futures 0.029% then 0.055%,
  options 0.21% / 0.09% of premium, flat fee 13 / 6, crypto 0.047% / 0.071%, forex 0.0091% / 0.0044%, auto
  square-off 43 / 61 flat and 0.11% / 0.06% on crypto): 104 fills at the fullest count, in every market and
  kind, each against its trade and its own ledger line (rupee value of crypto / forex fills cross-checked with
  price × quantity × the rupee factor read before the order): all agree; both auto square-off charges agree; no
  commission line without its trade; a trade keeps the charge of the day it was made after the settings changed.
- Coins: 16 additions and removals (also 0.004, 0.01, 33.333333, 10,000,000.1): one ledger line and one activity
  line each; Allocated follows everywhere; after the real cut-off every account's coins = Allocated (9 of 9), the
  cut-off lines are stamped Sunday 23:59:59, nothing unpriced, the weekly message to every account that traded.
  One amount of the 16 showed the fault below.
- Deleted account: 56 totals (Master rows, Weekly running and final, Performance all time and last week, Shadow
  Book) dropped by exactly its own figures; no line of it left in any table. Frozen account: stays in every total,
  marked frozen; its own login refused.
- N2, changes of the last two days. Stop-loss / Target sheet against the ordinary ticket in the real browser (phone
  size), on a bought future and on a sold option: the request sent is identical, the stored order identical
  (side, type, lots, price, product, validity), margin shown and reserved identical, and one lot filled through
  each way was charged the hand-computed commission: 88 comparisons, 0 differences. Activity record: every
  "coins … balance from → to" line against the ledger to the paisa (15 of 16 agree, the 16th is the fault below);
  settings lines say old → new for all seven commission figures, freeze, segment switch, user created / deleted,
  default access; no detail line holds a password (17 checks).
- **FAULT, FIXED, live: a finished week and a Monday were measured from the Monday day-start record,
  which is written up to 45 seconds after midnight.** For every account holding Crypto over Sunday midnight, last
  week's Net P&L (Settlement) on the Performance tab and in the "last week" Excel (user and Master) differed from
  the Weekly Settlement tab's final result by what Crypto did in those seconds (−2,685.70 against −2,640.50 on one
  test account; four of seven accounts differed); on a Monday the dashboard's Daily Net P&L differed from "Today"
  on the Performance tab; the days of a week did not add up to the week. Not seen before because the test button
  cuts in the middle of a day. *Fix:* `main._period_pnl` takes the start of a Monday and the end of a Sunday from
  the cut-off itself, where the P&L since the beginning is exactly the sum of the finished weeks
  (`main._cut_overall`; only for a cut-off that ran on time, otherwise the record as before). Nothing stored
  changes. *Checks:* daily check, books: "last week's Net P&L (Settlement) on the Performance tab and in Excel
  equals the Weekly Settlement, on every account"; `weekly_sim.py`: "daily …: Monday is measured from the weekly
  cut-off" and "finished week …: the Performance report's Net P&L (Settlement) is the Weekly Settlement's result"
  (37 checks; the old "a day with no day-start record is reported as unknown" now uses a mid-week day, because a
  Monday no longer needs a record of its own). The existing daily check "the daily figures of this week add up"
  would have failed on the live site on a Monday for any account holding Crypto.
- **FAULT, FIXED, live: an order could fill between Sunday 23:59:59 and the moment the cut-off ran, and
  was then counted in two weeks.** Fills are meant to be held from 23:59:57; the weekly job slept five seconds at
  a time and could sleep right through those three seconds (two of four tries on the private copy). The fills of
  the next one to three seconds (Crypto is the only market open) were settled with the old week but dated in the
  new one: the new week's Weekly Settlement counted their result and commission again and showed "other +28" on
  the Master's tab; the coins themselves were right. *Fix:* `main.weekly_loop` wakes up for the last three seconds
  (first version still missed one try in three when it woke a millisecond early; second version: held in five
  tries of five). *Check:* daily check, books: "nothing was booked in the finished week while dated after its
  cut-off (no trade counted in two weeks)", for the newest cut-off. Whether it has happened on the live site: the
  new check will say on its first run; it needs a Crypto fill in those seconds.
- **FAULT, FIXED, live: the card of a position whose market is shut did not show the closing price.**
  The user's Positions tab re-priced every card, and the Unrealised figure above them, from whatever quote
  arrived, also after the close, while Available Balance, the Master's screen and Excel stood on the closing
  price (private copy, where the simulated prices never stop: ten of ten cards, −₹19,690 against −₹31; on the
  live site only as far as quotes arrive after the close). *Fix:* `index.html`, the live P&L loop leaves a
  position marked `at_close` on the server's figure; `shutPoll` reads the list again every 5 s while one is
  held, so it goes live when its market reopens. *Check:* site_check "the card of a position whose market is shut
  keeps the closing-price figure while quotes still arrive, and follows the quotes again when the market reopens".
- **FAULT, FIXED, live: "-₹0".** A commission or a loss under 50 paise (one lot of a crypto option costs
  about 7 paise of commission) read "-₹0" on the user's P&L tab and weekly list, on the Master's user row, and in
  the split lines of his Weekly Settlement tab (there for every zero). *Fix:* those cells use `inr(-x)`, which
  writes no sign for an amount that rounds to zero. *Check:* site_check "A commission or a loss of less than 50
  paise is written ₹0, never '-₹0'".
- **FAULT, HELD (patch kept in the log below, not on main) (it changes what is stored): coins typed with more than two decimals.** 250000.335
  added to 20,000,000 coins was booked in the ledger as 250,000.33 while the coins moved by 250,000.34: Allocated
  is then a paisa less than the coins, the Ledger Statement's balance jumps a paisa more than its amount, the
  activity line's "from → to" does not match its own amount, and the week's result holds a paisa no trade explains.
  Only when the Master types a fraction of a paisa (the amount box allows it). Patch
  `held_coins_whole_paise.patch` (`main.admin_coins` brings the amount to whole paise once) with its site_check.
- Two checks that belong to no fix (my two): site_check "Master activity record: coins added and removed read
  'balance from → to' and agree with the ledger to the paisa" and "the Stop-loss / Target button opens the order
  sheet on the exit side for the whole position, and its order is the same order, with the same reservation, as
  from the ordinary ticket". All my site_check additions are one function, `accounts_block`, called once.
- Seen, not changed: Crypto and Forex refuse orders during the last second of every day (23:59:59, "market is
  closed"); the ticket's commission estimate is the flat fee alone until the contract's first price arrives; on
  the private copy the simulated contract numbers change with the calendar date (weekly expiries), so positions
  carried over a restart must be on the far-month contracts.

#### Price
- How it was run: in-process with exchange hours ENFORCED, the clock and every price set by hand, the real crypto
  and forex feed classes fed message by message, 30 contracts in all seven markets (index, stock and index
  futures, options, a currency pair quoted in yen, a Global contract with its own timetable); and a real restart
  of the private copy over a "weekend" (clock set to Friday 3 pm, kill, Saturday noon, kill, Saturday with the
  broker feed class and NO login, kill, Sunday cut-off, kill, Monday 9:20), comparing every API answer and Excel
  file with the figures of Friday's close.
- P1 (223 checks, NSE future / option / stock future, BSE future / option, MCX future / option, Currency future /
  option, Crypto perpetual / option, Forex, Global): market orders at the exit side of the book of that moment with
  a last trade planted 3% away; a limit never better than the book in both directions; refused on Thursday
  evening, in the Global daily break, on Saturday, on the 24 Nov holiday (MCX until 5 pm), in the opening instant
  of Monday 3:30 am (Forex), 4:30 am (Global), 9:00 (MCX, Currency), 9:15 (NSE, BSE), also when the old book looks
  one second old; GTT limits and stops do not fill on quotes that arrive while shut and fill at the first price of
  the new session (at the new offer / bid, not at the limit, not at Friday's price).
- P2 on the screens (real restarts, run three times): right after the Saturday restart the user's funds,
  positions, weekly figure, report and Excel, the Master's row, live positions, user panel, weekly row, report,
  summary Excel and user Excel show Friday's closing price and Friday's P&L for every NSE, BSE, MCX and Currency
  position to the paisa (Forex / Global: the same closing price, the rupee value moving only with the dollar
  rate, see "Seen"), again 75 s later with simulated quotes still arriving, and with the feeds disconnected as
  well; after tonight's fix also after the restart with no login; every position marked "at close", none at zero; orders and Exit refused with the
  "closed … opens Monday" text; on a 412-wide phone no "Price feed down" bar and no "feed down" chip (with the
  Global contracts really shut; a first try showed the bar only because the real clock was still Friday in
  Chicago). Sunday's cut-off booked the Friday-close figure (exactly in two runs). Three differences, see below.
- P3 on the screens: after the cut-off every position is carried at Friday's closing price, the original average
  kept, running P&L 0, total-since-entry = what was settled, coins back to Allocated; on Monday the week figure
  starts from the carried price.
- P4 (58 checks, stale last trades planted everywhere, long and short): Currency future at the spot rate 84.92
  (book 84.79 / 84.81, last trade 86.90), Currency call / put against it; NIFTY and SENSEX futures at the index
  close, RELIANCE future at the cash price, index options at intrinsic value; crude future at bid (long) / offer
  (short), crude options against the MIDDLE of the future's book; BTC options at 5:30 pm against the middle of the
  perpetual's book. Expired contracts refuse orders and are gone from search, the futures lists and the chain's
  expiry list; the next month stays.
- P5 (21 checks): one rupee factor per contract on ticket, user position, Master position and in the engine (BTC,
  BTC option, EURUSD, USDJPY, US500, gold); remembered through 10 minutes of silence and read back by a brand-new
  feed object after a restart; one fault (below).
- P6, state of the night: **disconnected**, in every market's feed (87 checks in-process, 48 on the running copy):
  market, limit and stop-loss orders and Exit refused with "… prices are offline right now …" / "Price feed for
  this market is down …"; no resting order fills; Available Balance, every position's value, the weekly figure and
  the Master row stand where the last price left them; conversion rates stay known; the phone shows the red bar
  naming all six markets; after the reconnect nothing fills before the first new price, then at the new bid. Two
  faults in this state (the automatic closes, an expiry), below.
- **LOOPHOLE / FAULT (wrong price, gives or takes coins), FIXED, live: while a feed was down the automatic
  closes still acted on the price from before the outage** (open idea of 16 / 20 Nov, now tested). NSE feed down,
  real market 3% lower, the account ran short on its crypto position: one NIFTY lot "squared off" at 24,419.95
  (real bid 23,687.35): 54,945 coins better than any real close; an intraday position was squared off at 3:30 pm at
  the frozen price; the same in the instant after a reconnect and with a silent crypto feed (margin call). A user
  cannot cause the outage, but with the feed down he can see elsewhere where the market is and let a small loss
  in an open market push him over. *Fix (engine.py `feed_delivering` in `_force_close`, `_square_off_shortfall`,
  `_liquidate`):* they wait until that feed is connected, not silent and has delivered a price since it came
  back; another position is closed first. After: nothing sold during the outage, 2 lots sold at 23,687.35 once the
  feed was back. Side effect: during an outage a short account is not squared off in that market.
- **FAULT (wrong payout), FIXED, live: a contract that expired while its feed was down was settled against
  the price from before the outage.** Feed down from 3:20 pm, index really 2% lower at the close: NIFTY future
  settled 72,900 coins too high, a put 145,800 too low. *Fix (engine.py `feed_up` in `_settle_expired`):* it waits
  (one error line) until the feed is back and the underlying has delivered a new price. Left: an MCX future is
  settled at its closing price in memory, which after such an outage is still the price from before it; a feed
  that only returns the next day settles at the last price seen (both as before).
- **FAULT (wrong payout), FIXED, live: an expired option whose underlying has no price was settled at its
  own old last trade** (open idea of 19 Nov, now tested): 5 lots of a crude call worth nothing settled at 420:
  210,000 coins. *Fix (`_settle_expired`):* an option waits for its underlying (one error line). An option whose
  underlying is not listed at all now waits too instead of settling at its last trade.
- **FAULT (takes coins; real users may ALREADY have been affected), FIXED, live: after a restart with no
  price-feed login a bought option was treated like a future.** The NSE / BSE / MCX / Currency contract list is
  not loaded from every night's restart until the morning login and all weekend. A bought option's running loss
  (already paid with the premium) was then counted against Available Balance again and half its premium added to
  the maintenance requirement. Seen first on the restarted copy (Available +75.00 after the restart, maintenance
  537,708 → 578,945); in-process: bought NIFTY calls at a loss plus a crypto position, Available +115,019 →
  −113,101 at the restart, 843 BTC lots squared off, charge 2,971.57. Sign on live: a system square-off in Crypto
  or Forex in the hours after a night restart on an account that holds bought options. *Fix (engine.py
  `_bought_option`, used by `funds` and `maintenance`):* without the contract it is told from the position's own
  symbol, as the weekly cut-off already does. Nothing changes while the list is loaded.
- **FAULT (display), FIXED, live: Shadow Book "0 lots"** for every mirrored position while the contract
  list is not loaded (main.py `admin_shadow`: the lot size the position keeps).
- **LATENT, FIXED, live: a dollar-rupee rate of 0, negative or not-a-number from the crypto exchange was
  taken as the rate** (message fed by hand): every crypto contract worth nothing in rupees, an account with 1,000
  coins bought 500 BTC lots with no margin. *Fix (feed/delta.py `_handle`, `_load_inr`):* only an ordinary
  positive number is a rate; the last good one stays.
- **FAULT (takes coins), fix HELD (patch kept in the log below, not on main) (it changes how positions are valued in the opening seconds):
  `held_opening_valuation.patch`.** Open idea of 20 Nov, now tested: at 9:15:00 the valuation switches from the
  closing price to whatever is in memory. With a low quote planted on Saturday, Available went 226,311 → −254,889
  at 9:15:00 and 2 crude lots (MCX open since 9:00) were squared off with the charge before any NSE / BSE price
  of the day. On the live feed it needs a quote after the close that differs from the closing price, or a thin
  contract with no quote, and a position in a market that is already open. The patch keeps the closing price until
  the session's first price (`engine.value_price`, `weekly.remember_marks`) with its check ("opening valuation: …").
- Last night's fixes, side effects: (1) the top quote standing in for a crypto book not renewed for 8 s carries only
  the quote's own size (tens of contracts): a user's 500-lot order filled 30 lots, and the automatic square-off
  closed 40 lots a pass: in a 5% slide in one minute an 80%-used account ended at −891,264 instead of +65,957. Only
  if the exchange really resends a quiet perpetual's book less often than every 8 s (not knowable here). (2) Forex
  stand-in (100 lots a side): no difference in the same slide. (3) First price of a session: a contract that gets no
  price all morning stays on Friday's price, is not squared off and cannot be exited (as designed).
- Seen, not changed: the rupee value of a shut Forex / Global position still moves with the dollar-rupee rate
  (−252.68 → −252.71 on the copy, where the simulated broker quotes at the weekend; in one run the weekly
  valuation booked −1,097.37 against −1,097.56 at Friday's close for that reason; the rate kept with the closing
  price, `last_vf`, is not used for it); the maintenance figure moves
  with quotes arriving while shut (537,708.10 → 537,706.07); the Shadow Book values a mirrored position at its own
  exit side while the market is open and at the user's closing price once it is shut, so its open P&L steps by one
  spread per position at the close (331 → 771); the Master's Live Positions rows have an empty name / segment
  while the contract list is not loaded.

#### UI
- N2, used for real in the browser (commits e4c506e, aa167d3), all do what they say: **Stop-loss / Target button** on every
  position (412 and 360 wide; sheet on the exit side, whole position, on Stop-loss, hint shown, hint gone on an ordinary
  sheet; a stop and a target placed through it rest and are cancelled by the app when the position is exited);
  **Order Book cards** at 360 / 412 / 640 (no pill, reason or Cancel off the screen; Cancel on a card cancels; table from
  641 up); **Master page behind the login** (no login → the small page, 4 KB, no Master code; a user's login refused
  with its message, no session left; wrong password / wrong code messages; two-step login lands on the Master page;
  Log out ends on the login page; a user's session opening /admin gets the login page and stays logged in on the
  main site; light and dark; 412 and 1440).
- STILL-OPEN item of 19 Nov closed: Master **Users, Live Positions and Performance tables were wider than their box**
  at 1280 / 1440 / 1728 (1403, 1240 and 1400 px in a box of 1162: Coins and View off the edge). Fix (`app/pages/admin.html`,
  CSS only for those three tables from 701 px up, plus the coin box 110 → 78 px): a long column title or a long name
  may take two lines, cells 4 px apart, figures 13 px. Every column kept. Limit, said plainly: with an account of five
  crore AND a name of two 15-letter words the Users table is still 42–54 px too wide (it then scrolls as before).
- N3: about 330 screenshots at 1440 / 412 / 360 / 820, dark and light; about 40 read with my own eyes (the rest went
  through a script that measures every element: off the screen, "undefined / NaN", cut text, small tap areas, script
  errors). Studied closely tonight: Master Users + user panel (all four tabs), Weekly Settlement (running and final),
  Settings incl. trading access, Site health and the activity record; user Watchlist, Positions with carried
  positions, Ledger, pop-ups, install banner (Android and iPhone wording), Order Book cards, Stop-loss / Target sheet.
  Buttons pressed for real: coins + / −, View, Freeze / Unfreeze, panel tabs, close, week picker, maintenance
  Announce / Clear, Show last 200, card Cancel, sheet Cancel, banner ✕.
- FAULTS FIXED (live; display only, each with its browser check):
  1. Order Book as a table (tablet and computer): one long note under the status (a refusal reason, "matched vs
     book …") made the table 1098 px wide in a card of 790 / 870, so Status and Cancel were off the right edge on
     every tablet and, with a refused order in the list, on a computer too. The note now wraps (`index.html`, CSS).
     Between 641 and about 710 px wide the table is still some 60 px too wide (cards start at 640 by the owner's decision).
  2. Master user panel, Orders tab: the whole Status column was off the right edge at 1440 (table 1403 in 962). The
     status cell wraps now.
  3. Master user panel: forex prices were shown with two decimals ("Avg 1.12 · orig 1.12 · Exit px 1.12"); positions,
     orders and trades in the panel now use the Live Positions price format (1.1229).
  4. Positions: an amount of minus nothing read "+-0.00" (EURUSD, seen on the card and in "This week so far"); the
     Master panel could read "-0.00". Neither is shown with a minus any more (`fmt2` / Master `fmt`).
  5. Watchlist on a phone: the line under a name was cut with "…" ("MCX · Lot 10…" for a lot of 100, "Exp 1…"); it
     takes a second line now.
  6. Position card on a phone: with the third button the last line broke labels from their figures ("Exit" / "px
     123.40"); each figure now stays beside its label and, when both do not fit, the buttons go under the figures.
  7. Login (user app, Master page, Master login page): after a wrong code, Back showed the password step with "Wrong
     authenticator code" still under it; Back clears it.
- Not faults of the site (private copy only): "Every day at 3:99 pm" on the safety-check card (the copy's switched-off
  clock); MCX "Nov" contracts with Exp 11-20 in the default watchlist and stock prices with five decimals (simulated feed).

#### Risk (50x cap; 1,000,000 coins, 80% used; last night's figure in brackets)
- R1 (102 runs: future, sold call, bought put × 3 / 5 / 10% × gap / slide × seven markets): on a slide the
  low-margin warning comes first, then the shortfall message and the square-off in the same pass; on a gap the
  warning is skipped. A shortfall closes only the lots needed (Available back above zero by less than two lots'
  margin, part of the position left), worst loser first (crude −210,680 before SENSEX −80,202 before NIFTY
  −54,953; the bought put untouched); a deep loss (equity under maintenance) closes everything. One charge per
  system order in all 102 runs (a slide makes many orders: Currency 10% slide 37 orders, 1,850 coins; Crypto 38
  orders, 19,228). A bought option never goes below zero (10%: 200,000 to 213,000 left).
- Net Balance after a 10% gap, future: NSE +448,719 (+451,756); BSE +355,904 (+359,116); MCX +354,013
  (+357,326); Currency −1,655,858 (−1,676,652); Crypto −2,993,117 (−3,033,760); Forex −2,994,958 (−2,995,395);
  Global −2,982,856 (−2,997,462). Sold call, 10% gap: NSE +522,877; BSE +575,101; MCX +569,685; Currency
  −1,276,099; Crypto −382,773. 5% gap: Currency −334,022; Crypto −1,014,510; Forex −999,434; Global −992,898.
  3% gap: Crypto −223,068; Forex −200,869; Global −196,915; Currency +194,712. Below zero from a one-step gap of
  2.5% (Crypto, Forex), 2.6% (Global), 3.8% (Currency), 16% (BSE, MCX), 18.5% (NSE). Why: at 50x / 33x the whole
  margin is 2% / 3% of the position; a gap beyond that is lost before anything can be closed.
- R2: a market that opens 10% lower: nothing in the opening second, then the square-off at the first price (NSE 2
  of 3 lots; BSE, MCX, Currency, Forex, Global margin call, same figures as the gap). Stop-loss in a 10% gap: fills
  at the new bid, the whole position, no square-off on top, never short. Thin book (2 lots visible): one or two
  lots a pass, 6 orders, 6 charges (300 coins), stops when Available is back above zero. Expiry: 30 s before, only
  the lots needed are sold; the rest settles at the index close with no second charge. Weekly cut-off with hours
  enforced: Sunday warning, nothing at Monday 9:15:00, one reminder with the first price, nothing at 11:59, at
  12:00:30 only the lots needed (6 → 3), one charge. Inside the grace time an NSE account held 1,620,000 of margin
  on 1,000,000 coins (13.5 times its coins); a Monday opening 5% lower closed all of it by margin call, Net
  Balance +322,385 (below zero from about 7.5%).
- R3: largest position: 1,000,000 coins: NIFTY 4 lots (7.3 M), SENSEX 5 (8.0 M), crude 14 (8.2 M), gold 1 (7.7 M),
  RELIANCE 7 (4.5 M), USDINR 389 (33 M), BTC 7,019 (49.5 M), ETH 21,044 (49.5 M), EURUSD 524 (49.8 M), US500 77
  (49.4 M). 5,000,000 coins: NIFTY 22 (40 M), SENSEX 25 (40 M), crude 71 (41 M), gold 8 (61 M, 12 times: 8% margin),
  USDINR 1,949 (165 M), BTC 35,098 (247 M), EURUSD 2,623 (249 M), US500 388 (249 M; 250 lots where the broker's
  limit applies). Twenty accounts on one side: on a deep book nothing changes for anybody (same price, same
  margin, all treated alike in a 10% gap). On a thin book they share what is visible: 20 accounts with 11 crude
  lots each took 24 passes (72 s); the last in line ended at 303,789 against 344,123 for the first.

#### User experience
- U1, brand-new user on a 412 phone with the access a real new user has (futures only), 31 steps by real taps from
  opening the site to logging in again: 0.01–0.66 s each, nothing stuck, no script error. Forced password change
  explains itself; short / different / same-as-old passwords each get their own message.
- U2, every refusal hit on purpose through the order sheet and read: not enough coins, too many lots for one order,
  0 / negative / 1.5 / 99999 lots, limit price 0 or negative, stop on the wrong side, empty trigger, segment not
  activated (options, crypto, forex, global: pop-up; the server says the same), shut Global contract, expired
  contract, too little trading (allowed gap set tiny by the Master), 500 pending orders, price feed down, account
  frozen with the sheet open. REWORDED (wording only, `engine.py`, no test reads these texts): "Exceeds the exchange
  freeze quantity for NIFTY (24 lots per order) — split the order" → "Too many lots for one order: NIFTY takes at most
  24 lots per order — split it into smaller orders"; the five "Illiquid: …" / "Not enough liquidity" texts (e.g.
  "Illiquid: bid X / ask Y — spread 3.1% exceeds 2% limit") → "Nobody is selling this contract right now — …",
  "Too little trading in this contract right now: the gap between the buying price X and the selling price Y is …";
  the expired-contract text now also says to choose a later one in the Market tab. Not reachable on the private copy
  (market hours are not enforced there): the NSE / MCX "market is closed" text, read in the code instead (plain).
- U3 rotation: **Monday 9:15 reminder** (the real reminder code, started by planting the waiting record of a short
  account in the private database with the reminder time 25 s ahead): the standing warning before, the reminder once
  25 s later while the app was open, closed with one tap, not again in the next 8 s, on re-opening only the standing
  warning (meant to show every time), the red bar and both pop-ups give the same time, the position not squared off,
  no pop-up for two other users; fits a 360 × 640 screen. **Maintenance notice** (announced through the Master
  page): amber bar and pop-up once per browser for a user, a second device, a visitor and the Master in trader view;
  closable; after reload only the bar; markup typed in the note is shown as text; Clear removes the bar.
- U4: item 1 half answered (the button is there and works; the position card still does not show that a stop or a
  target is resting: only the Order Book does). Item 10 answered for phones.

#### Compliance (housekeeping, not a legal opinion)
- **First job: the fuller Master activity record, used for real** (every Master action over the API, 100 calls,
  each line read). Coins added / removed (amount, whose, balance before → after, the note), each of the 11 settings
  and every margin (name, old → new; "saved, nothing changed"), access switches default and per user (which, on →
  off; "back to the default"), user created (name, coins) / frozen / unfrozen / renamed (old → new) / password reset
  / two-step cleared / deleted (with the balance at that moment), Square off pressed (how many closed), Master
  login added / removed / password changed / two-step cleared: all say what and when, under the right Master's
  name. No line held any of 16 passwords, two-step secrets, code-step passes or the pasted price-feed key; nor did
  the server log or the errors file.
- **FAULT, FIXED, live: a user could write lines into the Master's activity record, without limit.** A
  user's own two-step set-up also answers under `/api/admin/2fa/…`, and the record wrote every such call under the
  user's name. Proven: 210 calls in 2.4 s by an ordinary user; the Master's list (last 200 lines) then showed only
  those and none of the Master's own actions, and the table grew by 85 rows a second for as long as he liked.
  No data was changed and nothing of the Master's was reachable. *Fix (main.py `_admin_audit`):* only a Master's
  own request is recorded. Check in `site_check.py`.
- **Completed, live (same request of the owner, own commit so that it can be left out): nine kinds of
  Master lines still said nothing but the address**: the Master's own test coins (1,000,000 coins added with no
  amount on the line), a message left for a user, the notice for everyone and its removal, the maintenance notice
  and its removal, two-step login started / turned on / turned off, the three price-feed buttons and the pasted
  key, the off-server copy sent by hand, the safety check run by hand, the weekly test cut-off (private copy
  only), and a user saved with nothing changed. Each now says what was done (`main._note` in each endpoint; a
  message's line keeps its title, not its text; the key is never written; no provider is named). Access switches
  and margins are written by the names the Master page uses ("Futures on Currency", not `CDS_FUT`).
- Checks added: `site_check.py`, one block "Master activity record" (32 checks: each action above leaves its line
  with the right words; settings and switches are put back; a user's call leaves no line; no line holds any
  password or secret used in the run). `weekly_sim.py` "activity record: …" (3): every Master address that changes
  something is built with its line of plain words (a new one without it fails on the day it is written), no line is
  built from a password / secret / key field, lines are cut to a fixed length.
- C1 (two-step enforced, in-process): 40 checks held. Password alone gives only the 5-minute pass to the code step;
  that pass, as cookie or header, is refused on all 56 Master addresses (counted by method), gets no user data and only the small login
  page; wrong codes are stopped after a few tries; the two-step secret cannot be swapped while it is on; a second
  Master login behaves the same (the first Master's code is refused for him) and his actions are under his own
  name; a user and a visitor are refused on every Master address. The small login page (4,151 characters): the
  login form, the code step and calls to login / code / logout only; no Master code, no provider name, nothing
  stored but the theme. The Master page file cannot be fetched under ten other spellings. Passwords are hashes;
  none on any Master screen, Excel file, log, errors file, activity record or backup. Still as before: the two-step
  secret is readable in the database and the on-server backup (Waiting list); so is the day's price-feed login,
  which runs out every morning.
- C2: no record at all for: a Master login (password and code step) and log-out, the Master's own password change
  on the Master page (`/api/password`), a refused action, the daily price-feed login, backup / Excel downloads and
  looking at a user (reading addresses). Answered by the new lines (can come off the Waiting list): "say WHAT
  changed (amount, setting old / new, which switch, freeze vs password reset)". Partly answered: "keep a deleted
  user's coin history": the record keeps his creation line with the starting coins, every coins-added / removed
  line with the balance before and after and the note, and the balance at deletion (not his trades or ledger).
  Still open: lines for Master logins, for backup / Excel downloads, for the Master's own password change, the
  daily price-feed login and a refused action.
- C3: held: login name, display name, password hash, two-step secret, balance, orders, trades, positions, ledger,
  watchlist, weekly / day-start records, pop-up texts, access switches; Master name and address in the activity
  record; no e-mail, phone or address. One user's 21 screens and Excel hold nothing of another (marks planted in
  name, coins note, message); asking by another account's number gives nothing; his socket hears nothing of the
  other's coins, order, message or square-off. Deleted user: no row in any table keyed by account, on none of 14
  Master screens and Excel files, login dead. **What is kept: the activity record** (8 lines in the test: created
  with coins, coins added with note, message title, square-off, access switch, deleted with balance) under his
  login name and display name. Only reported (the owner wished the coin history kept).
- C4: commission shown before the order = the Master's setting = charged on the trade, by hand, in seven markets
  with unusual rates (14 checks); the week's commission on the user's P&L = the sum of his trades. No provider name
  on 18 visitor addresses, 34 user addresses, refusal messages and the user's Excel, with one remark: the
  price-feed login's return address is itself named after the broker's product and sends a visitor who types it to
  `/admin?kite=failed…` (the address is fixed at the broker; nothing links to it). Nothing promises profit. The
  app still does not state plainly that trading is in coins (already on the Waiting list; the install description
  says "trading simulator").
- Whether the business model, the settlement of coins, the use of exchange prices and the tax treatment are within
  the law is for the owner's lawyer and accountant; nothing here is a legal opinion.

#### Release
- Independent reviewer (fresh, saw only the diff against the live code, the rules, D and the list of what each
  change claims): **approved, no item held** (26 items). His closest call: the bought option recognised by its
  symbol while the contract list is not loaded (it changes Available Balance / maintenance at night and at the
  weekend to the daytime figure; approved because the owner's rule itself is unchanged, nothing is stored, and the
  only direction is fewer wrongful square-offs).
- Answered the same night (checks only): the "counted in two weeks" daily check now counts trading lines only (coins
  moved by the Master in that second would have failed it for a week); the Master-page check no longer prints the
  matched provider word in its failure text.
- Remarks kept for later: `remember_marks` caps the kept closing price of EVERY open position at the other side of
  the book (options and crypto too), so a long with no bid at the close can be valued lower over the weekend than
  before; in `_settle_expired` the cap is applied against whatever book is in memory up to a minute after expiry
  (apply it to the last-trade fallback only); a feed that stays down until the next day still settles at the kept
  last price; a position waiting to be settled writes one error line and nothing more (a line on Site health
  "expired, waiting for a price" would help); the daily check "nothing booked in the finished week dated after its
  cut-off" will FAIL on the live site until the next cut-off if the fault already happened last Sunday (a true
  report of a past event: adjust nothing); `_offline_auto` and `_one_sided` flip a feed flag / plant a price in
  memory for one function call (restored in `finally`), a looser reading of "only through the test accounts";
  "Less than one lot is on offer" is also shown on a SELL; `.bad` backups are never pruned; two backup downloads
  in the same minute share one temporary file name; the shut-market card freezes only after the positions list
  was read again after the close; a login that queues eight reports waits behind them itself.
- Coordinator's own changes after the merge: the activity-record browser check reads the Master's own two-step
  line (another block sets up a second Master with markup in his name); the browser check's time limit in run.sh
  400 → 600 s (it now runs about 330 s); the daily check "the same sellers cannot be taken twice" failed once on
  the merged code (Currency, 98 lots): a new book had arrived between its two orders; it now also needs the book
  unchanged AFTER the second order, otherwise the "two orders together stay within what was offered" form is used.
- From 3:30 am IST on a Saturday the simulated Global contracts are shut by the real clock: the plain run then has
  284 checks instead of 316 (Global only "market is closed: refused"); `FAKE_OPEN=1` keeps them open.

##### Held patches of 21 Nov 2026 (not on main; say "apply the held patch …" to have one built and tested again)
`held_opening_valuation` (Price): in `engine.value_price`, when `p.last_mark` is set and the contract's session has
opened but `engine.session_price(ins)` is still false, return `p.last_mark`; same guard in `weekly.remember_marks`
so the kept price is not overwritten in those seconds; weekly_sim checks "opening valuation: …".
`held_coins_whole_paise` (Accounts): `main.admin_coins` rounds the typed amount to whole paise once, before the
balance and the ledger line are written (250000.335 was booked as .33 in the ledger and .34 on the balance).

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
- Masters, 26 Nov 2026: every /api/master address as visitor, user and owner, every /api/admin address and price-feed
  button as a master, another book's user by number on all five per-user addresses (seven kinds of account): all
  refused, nothing leaked; a master trading with his stock; the name of a master or of a deleted account at the
  login (same words as an unknown name); a withdrawal above the user's free balance or above what he was given; a
  user deleted while in loss (the loss stays in the week, the stock gets the allocated coins once); changing the
  share % or the MCX percentage to alter a finished week or a past trade; a removed master's number handed to the
  next account (nothing is left under it); markup in a master's name, his user's name and a deposit note on the
  owner's Masters section and the master's page (shown as text).
- Access switches with PT_ACCESS_ALL=0 (26 Nov 2026): a new order, an add, a flip and an exit bigger than the position
  in a switched-off segment: refused, position intact.
- Risk rows 18, 21, 31, 50, 58 (26 Nov 2026): a stale stop after the user's own flip (margin checked again at the
  fill); an intraday order after square-off time (same margin as overnight); leverage 200x / 0.5x / negative
  (refused); add / reduce rounds on a position from before the 50x cap (its margin only rises); waiting through
  the hedged 30 s with a truly short account (judged at 30 s at the latest); an opening stop filled in part (the
  reservation is split in proportion).
- Price, 26 Nov 2026: the forex ticket's rate against the crypto dollar rate (the factor used is the forex one); the
  option-chain address answering for an expired date (nothing in it can be traded, the date is not offered); a
  Global chip "open" on a pretend Saturday (the contract timetable runs on the real clock: the test's artefact).
- Technology, 26 Nov 2026: a Masters call holding the order lock or a write through slow work (none; the opposite was
  the fault); kill -9 between an order's commit and its answer (booked whole, only the answer is lost).
- Gaining from the closing price kept until a session's first price (25 Nov 2026; stray quotes in every direction,
  six markets, 40 risk runs): orders on that contract are refused, the square-off waits, Available is the
  closing-price figure as before; judged on the real price once it is there.
- Currency conversion in Crypto / Forex / Global by round trips, leverage and cross currencies (25 Nov 2026): the
  factor is the pair prices themselves; five restarts lose no rate.
- Reading another account through report / Excel / list addresses with its number or name (25 Nov 2026): own data only.
- Junk names into the Pulse / futures address (25 Nov 2026): empty list, nothing echoed.
- A stop-loss turning the account short after a partial square-off (25 Nov 2026): refused for margin (the target did
  it: fixed). A crowd of twenty on a deep book: nothing for anybody else.
- A fill at a closing, weekend, holiday or pre-opening price in 13 kinds of contract; a limit filled better than
  the book; a pre-drop price across 88 orders during a real crypto reconnect (25 Nov 2026): none.
- Reconnect pressed 2 or 3 times at the same instant with a FAST contract list (25 Nov 2026): one connection; the
  fault needs the list to take seconds (or the rebuilds to overlap).
- "Back leaves the Market tab" / "the sheet closes right after a Pulse row" (25 Nov 2026): only when tapped within
  0.2 s of the sheet opening; no person taps that fast.
- Fetching the Master page file another way (21 Nov 2026): 31 spellings, HEAD, range, conditional, eight kinds of
  login that are not a live Master's: nothing.
- Stop + target + Exit at the same instant, all seven markets (21 Nov 2026): flat, or an ordinary short with full margin.
- Opening anything in the weekly grace time, or with a carried option's paid-out profit (21 Nov 2026): refused.
- Price socket with contract numbers that do not exist (21 Nov 2026): never streamed; they use up the sender's allowance only.
- Huge numbers (10^25) in an address or body (21 Nov 2026): "500" for the sender on four addresses, nobody else affected.
- A deleted account's figures in a total, a frozen account dropping out, a wrong commission after a settings change,
  carried positions after partial exit / add / flip, Shadow Book against the mirror prices (21 Nov 2026, a real
  week on the copy's own clock, thirteen states): nothing.
- Margin of a sold option with no index price (21 Nov 2026): falls back to the strike; same figure at the money.
- Many accounts on one side of a deep book (21 Nov 2026): nothing changes for anybody else.
- A second Master's code, the code-step pass as a login, a full login as a code-step pass (21 Nov 2026): refused.
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
- (25 Nov) Crypto: price message before book message (a stop filled against the book from before a jump): measure on
  the live feed how often and how far the book's top is on the wrong side of the price message's own quote (a note
  in the daily check) before any rule; the same test for the forex ladder.
- (25 Nov) Calendar spreads and option hedges in the opening seconds; the stop on an emptied book; the risk
  harness (hours enforced for all six opening markets) is worth keeping in tools/selftest.
- (25 Nov) One account trading without pause keeps the margin recorder asking the broker's calculator all day (the
  broker's limit on calls is not known; charts use the same key).
- (25 Nov) Every request that crashes writes about 20,000 characters to the server's output; the four known "500
  for a number too large" addresses can still be repeated by a logged-in user.
- (25 Nov) Accounts: read the Master dashboard off the real browser in the weekend and opening states; a real
  Sunday cut-off on the copy's own clock.
- (21 Nov 2026) Release remarks to work off: apply the "other side of the book" cap in `_settle_expired` to the
  last-trade fallback only; a Site health line "expired, waiting for a price"; prune `.bad` backups; unique
  temporary name per backup download; freeze the shut-market card at the close itself.
- (21 Nov 2026) While a thin contract is still trading with nobody on its exit side, screens and the margin call
  value it at the last trade (closing price and settlement are capped since 21 Nov).
- (21 Nov 2026) The daily check notes the longest wait between two PRICES of a crypto perpetual, not between two
  BOOK messages; the second decides whether the 8 s rule of 20 Nov bites (then a big order meets only the top
  quote, and the square-off closes tens of lots a pass: −891,264 instead of +65,957 in a 5% slide in the test).
- (21 Nov 2026) A rupee rate that is positive but absurd (ten times off) is still taken.
- (21 Nov 2026) While the contract list is not loaded the Master's Live Positions rows have no name / segment, and
  a crypto / forex position falls back to half its blocked margin as maintenance.
- (21 Nov 2026) The day-start record of an ordinary day is written up to 45 s after midnight: a Crypto move in
  those seconds lands in the day before (days still add up to the week). The ticket's estimate before the first
  price is the flat fee alone, margin 0. Crypto and Forex refuse orders in the last second of every day.
- (21 Nov 2026) The sum of a ledger's amounts can differ from the balance by a paisa or two after hundreds of
  trades (each amount rounded on its own; the running balance column agrees).
- (21 Nov 2026) The off-server copy is one Telegram document (50 MB limit; far away, nothing warns). A Master login
  can be marked frozen through the users address (changes nothing). Four addresses answer "500" for a number too
  large for the database.
- (21 Nov 2026) Code notes: an automatic close must go through `engine.feed_delivering(ins)`, a settlement through
  `engine.feed_up(ins)`; whether a position is a bought option is asked with `engine._bought_option(p, ins)`,
  never from the contract alone (the list is missing every night until the morning login); a new Master address
  that changes something needs its `_note(...)` line (weekly_sim fails without it); a new heavy per-user address
  belongs in `_Turnstile.HEAVY`.
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

## 20 Nov 2026 (early morning, owner's requests of 19 Nov)
- Stop-loss / Target button on every open position in the user app ([data-slt]): opens the existing order sheet on the
  exit side, for the whole position, on Stop-loss, with a two-line hint (Target = Limit). No new order logic.
  NEEDS a browser check in site_check.py (button present, sheet opens on SL with exit side and full lots).
- Fuller Master activity record: admin_log.detail (new column, added by init_db on an old database) holds what the
  action changed in plain words (coins from → to, settings from → to, access switches, user created / frozen /
  renamed / deleted, square-off pressed, Master logins). main._note() inside the endpoint; never a password or key.
  NEEDS a check that each of those actions leaves a detail line, and that no detail line ever holds a password.
- STILL OPEN for the UI officer (from the 19 Nov live audit): at laptop size the Master's Users, Live Positions and
  Performance tables are wider than their box, so the last column needs a sideways scroll. Fit the columns at
  1280 / 1440 / 1728 wide and add a site_check for it.

## Owner's decisions, 20 Nov 2026
- Nobody holds a position above 50x (live audit, 20 Nov), so there is nothing to ask users to close. Closed.
- A shorter Monday-noon grace for Crypto: NOT decided. Leave as it is; do not raise again unless he asks.
- The Master page is sent only to a logged-in Master. The file now lives in app/pages/admin.html (NOT under
  app/static, which is open to everybody). /admin gives anyone else app/static/admin_login.html, which holds
  nothing but the login (no Master code, no provider names). Never move admin.html back under static.
- Order Book on a phone (640 px and narrower): each order is a small card, so Status and Cancel are always on
  the screen. Wider screens keep the table.

## 21 Nov 2026 (early morning, owner's requests)
Live: Stop-loss / Target button and the fuller Master activity record (held from the night before); the Master
page behind the login; the Order Book cards on a phone. NEED checks added by the officers: /admin without a login
or with a user's login returns the small login page (no "api/admin", no provider names) and /static/admin.html
is 404; on a 360 and 412 wide screen no status pill or Cancel button of the Order Book is off the screen.

## Owner's decisions, 21 Nov 2026 ("Yes to all"; and: weekend changes may go live in the daytime while markets are shut)
- CONFIRMED: a future that expires with nobody quoting on its exit side is settled no better than the price it
  could be dealt at. Do not raise again.
- APPLIED (was held_opening_valuation): a position stays on its closing price until the first price of the new
  session (engine.awaiting_first_price; same guard in weekly.remember_marks).
- APPLIED (was held_coins_whole_paise): coins typed by the Master, and a new user's first allocation, are booked in
  whole paise. Both held patches are now on main: remove them from "Waiting for the owner".
- Position card shows resting exit orders of the position ("Resting: Stop-loss … · Target …", [data-rest]).
- Shadow Book: margin worked out the broker's way is for the SHADOW BOOK ONLY. Users' margin is NOT to change.
  app/margin_watch.py keeps, per IST day, the highest margin by limefx's rule and by the broker's own margin
  calculator (asked within 20 s of every trade and every 15 min while the price-feed login is live; calculator
  calls only, never an order). Days before 21 Nov are rebuilt from the trades and marked rebuilt (rough).
  Cards: Margin Now, Peak Margin, Peak Real Margin; the same three columns per user.
NEED checks from the officers: opening valuation (position on its closing price until the session's first price);
coins in whole paise (ledger line = balance step); the resting line on a position card; Shadow Book peak >= now and
the peak survives a square-off; the margin watch never delays an order and never sends one.

## 23 Nov 2026 (morning, owner's request) — crypto connection cut again and again all night
From about 12:34 am the crypto exchange cut the site's connection within seconds of each reconnect, all night;
no price arrived for 8 hours. A connection opened at the same time from the owner's laptop worked at once, so the
exchange was fine: it refused the website's server. Now: each drop is recorded with its reason (crypto status
"drops", also in the crypto card's message and in the Telegram alert); after quick drops the site waits 5, 10, 20,
40, 80, 120 s instead of retrying every 5 s; the feed alarm sends one DOWN message per outage and "back and steady"
only after 10 minutes up (PT_FEED_STEADY_SECS). Officers: if drops keep showing an HTTP refusal (403 / 429) from
the exchange, a fallback that reads crypto prices over the exchange's REST address is the next step (owner to decide).
- Owner's decision, 23 Nov 2026: Reconnect must always be within reach and must really connect again (as with the
  Zerodha login button). "Reconnect crypto" is always shown and rebuilds the crypto connection from scratch (stops the
  old connection and its retries, reloads the contract list, connects at once) and tells the Master within 20 s whether
  prices are arriving. Six quick drops in a row do the same by themselves (at most every 15 min). "Reconnect forex" is
  always shown once a token is saved and drops the old connection at once. Do not hide these buttons in any state.

## 24 Nov 2026, 9:00 am — Zerodha prices stuck at "connecting" after the morning login
Login worked 10 times (today's login saved, contract list downloaded) but the price connection never opened. Cause:
since 19 Nov the site stops retrying a refused login; with nothing left to do, the price library's background
loop (Twisted reactor) sits idle, and a new connection asked for from another thread is never picked up until
something wakes the loop. A restart (this note's release) starts the loop fresh. Proper fix to follow: start and
close the Zerodha connection through reactor.callFromThread.
## 24 Nov 2026 (owner) — no alarm at 7:06 am for yesterday's Zerodha login running out
Zerodha clears every login at about 7 am. The site still held Monday's login, was refused at 7:06 and sent
"Zerodha refused the login" plus "the server logged 6 errors", although the owner logs in after 7:30 as asked.
Now: a refusal of a login from an earlier (Indian) day stops the retries at once, says "Today's Zerodha login is
needed first" and sends nothing. A refusal of TODAY's login still sends the one message with the login link.
Zerodha 403 / "error parsing request" lines no longer count towards the "server logged N errors" alarm.
- Proper fix (same day): every Zerodha connect and close goes through the library's own loop (kite._in_reactor,
  reactor.callFromThread). Reproduced with the real library against a local server: opened from another thread
  after a stop, 0 connections; handed to the loop, it connects (tools/selftest/kite_reactor_check.py, prints
  KITE-REACTOR OK). Officers: run that check every night.

## 24 Nov 2026 (holiday) — daily check flagged two never-traded futures
APARINDS and ACUTAAS Dec futures had no last trade, no close and an empty book (not traded by anyone yet). The price
check now notes such contracts instead of failing; a zero price anywhere else still fails. Such a contract cannot be
filled: an order needs a live book. (One run of the browser check failed once on the Stop-loss / Target comparison and
passed on the next fresh run: officers, look at that check for a timing flake.)

## 24 Nov 2026 (owner) — a Pulse row opens the future
Tapping a Pulse row opens that name's nearest future (it opened the option chain). The order sheet has "Other
months" and "Options ›"; with no options it says so, with Back / Futures page / Options page. Owner approved the preview.

## Owner's decisions, 25 Nov 2026 (08:48 IST)
- HELD 2, 3, 4, 5, 6 of security-fix/2026-11-25: approved and put live.
- HELD 1 REFUSED: a trade or cut-off must never book at the closing price. The closing price is only the base for the day's change (and the mark shown until the first price); every execution uses the live price of the moment. Do not offer this again.

## Masters under the owner, 25 Nov 2026 (owner's request and decisions)
- The owner creates a master with a share % and a stock of coins. The master logs in at /admin, gets his own page
  (app/pages/master.html) and only the /api/master/... calls. Two-step login compulsory; first login forces his own password.
- Owner's decisions: a master deposits/withdraws only for his own users and only from his stock; the owner SEES a
  master's users but cannot change them (no "move user" button); brokerage, leverage, access, price connections,
  Shadow Book, backups, health, settings stay with the owner alone; his users' trades count in the Shadow Book;
  the owner's own lists (Users, Positions, Weekly, Performance, Excel) hold only the owner's own users.
- Rules that must hold (tools/selftest/masters_check.py, run by run.sh): every /api/admin call answers a master 403
  (deny by default: current_admin refuses is_sub); a master's calls answer 404 for any user that is not his;
  stock + coins with his users = coins the owner gave; the weekly cut-off never touches a master's stock
  (weekly.accounts leaves is_sub out); a master cannot trade; a finished week keeps the share % it was closed with
  (setting mshare_<master>_<week>); a paused master cannot log in while his users trade on.
- Share (owner's words, 13:38): the book and its brokerage are the MASTER's; the percentage is what the OWNER takes,
  of the P&L and of the brokerage alike. Book P&L (users' P&L before brokerage, turned round) + brokerage = book
  total = owner's share + master's share, to the paisa. A finished week is written down at the cut-off
  (setting mweek_<master>_<week>) and never worked out again: a later percentage or a deleted user cannot alter it.
- The master (not the owner) squares off and deletes his users. Owner's decision 14:03: a deleted user's data never
  goes away. The account is shut (deleted_at, cannot log in, name freed), its allocated coins return to the master,
  and its trades, ledger and weeks stay in the master's records and the owner's; the running week still counts it.
  Delete needs a flat account with no waiting orders.
- Not built (say so if asked): per-master brokerage or leverage; moving a user between masters.
- Owner's decision 14:20: "records should always remain, deleted or not". Every delete (the owner's own users too)
  now shuts the account and keeps its trades, ledger and weeks; before, the owner's delete threw them away. A delete
  needs a flat account with no waiting orders. An account's number is therefore never handed out again.
- 25 Nov, 17:45: FAULT ON LIVE, 35 minutes, nobody affected (no master existed yet): the master's own page showed
  no name, coins or users. Cause: one line of its script assigned to a constant and the page hid the error. It was
  added after the screenshots were taken and only server checks were run afterwards. Fixed; a click-through of both
  pages (tools/selftest/masters_screens_check.py, 25 checks) now exists and must be run on any change to those pages.
- Owner's decision 25 Nov 20:33: MCX futures commission is its own figure, 0.01% of value + the flat fee per order
  (a 10 lakh contract bought and sold: 240 on MCX, 640 on NSE / BSE / Currency). Setting commission_pct_MCX, on the
  Settings page; MCX options keep the options percentage. Applies to fills from the release on, never to past trades.
