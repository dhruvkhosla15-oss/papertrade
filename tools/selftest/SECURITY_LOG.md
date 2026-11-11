# limefx security log

The daily safety check (`app/probe.py`) attacks the live site every day at 10:05 am IST with two hidden
test accounts. This file is the memory of the nightly review that keeps adding to it: what has been
tried, what was found, what is waiting for the owner's go-ahead. Newest entry first. Read it before
thinking of new attacks so the same idea is not tried twice.

## Waiting for the owner's go-ahead
### Branch `security-fix/2026-11-12` (found 12 Nov 2026, tested on the private copy, NOT live)
To deploy: open Claude and say "put security-fix/2026-11-12 live". All 125 checks pass on the branch twice in a row.
1. **Crypto options settled late and at ten times their value (money, serious).** Crypto options really expire at
   5:30 pm IST. The site settled them at 9:30 pm, at the 9:30 pm price: four hours of free option time for anyone who
   holds through expiry. Worse, the hourly contract refresh drops the expired option in between, and from then on the
   position is valued and settled at its last quote times 1 instead of the contract's rupee factor (about 0.09 for a
   BTC option): roughly ten times the real profit or loss. A trainee keeps winners into expiry and closes losers
   before it. Proven: 10 lots of a BTC call, honest result about +550 coins, credited 12,785. Orders on the expired
   contract were also still accepted at its frozen quotes for a few minutes.
   *Fix:* the contract's own expiry moment from the exchange is used (fallback 5:30 pm); nothing trades on an expired
   contract; a contract someone still holds stays known after the exchange stops listing it (rebuilt from its symbol
   after a restart, contract size taken from the perpetual); a position whose contract is unknown is never settled
   at a guessed value (it waits, and the daily check reports it). The on-screen text "9:30 pm IST" becomes "5:30 pm IST".
   New daily check on the branch: crypto options stop trading and settle at the exchange's own expiry time.
   Until this is live: look at any crypto option that was held through its expiry (EXPIRY_SETTLEMENT lines in the ledger).
2. **Anyone can lock anyone out of logging in (nuisance, no money).** Five wrong passwords on a username, with no
   login needed, block that username for five minutes, even with the right password, and it can be repeated forever.
   Works on trainees and on the Master. *Fix:* a browser or phone that has logged in to an account before carries a
   signed marker and is counted separately, so a stranger's guesses no longer lock the real owner out. A brand-new
   device is still locked during an attack (that part of the guessing protection is kept).
3. **A half-finished 2FA login could listen in (small).** With only the password (no authenticator code yet) the live
   socket still treated the visitor as that user and sent the user's private order updates. *Fix:* such a login, and a
   frozen or deleted account, is a plain visitor on the socket.
4. **One account could ask for live prices on every contract at once (precaution).** Visitors are capped, logged-in
   users were not: one trainee pushed the subscription count to 3,407, above the price provider's limit of 3,000 per
   connection. Harm on the live site could not be measured here (simulated prices have no limit). *Fix:* 1,200 contracts
   per account across all its tabs and a ceiling of 2,900 for screens (orders and open positions are never limited).

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
- On branch security-fix/2026-11-12 only, until it is live: crypto options stop trading and settle at the exchange's own expiry time

## Findings

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
- Junk in dates, sizes and ids on the read / report / export endpoints (12 Nov 2026): only an error page for the sender
  (a few answer "500" instead of "400"); nothing leaks, nothing sticks, the site keeps answering.
- Export file name / sheet name tricks to smuggle text into the download header: refused before the name is built.
- Forged login tokens signed with the old built-in key or with no signature: refused.
- Reading another user's order updates over one's own live socket: nothing arrives.
- Hunting for a gap in the new flat-fee / options-rate costs (round trips, estimate vs charge): none.

## Open ideas for a later night (noted, not yet tested or not provable on the private copy)
- Currency (CDS) contracts stop trading at 12:30 pm on expiry day but are settled at 5:00 pm: same pattern as the
  crypto hole, much smaller. Check weekly currency options held through 12:30.
- A session stays valid for 30 days after the user changes the password or the Master resets it (only freezing or
  deleting the account ends it). Not a way to cheat, but a stolen or shared login cannot be ended by a new password.
- Looking up a contract that has no price yet subscribes it for good (until the next restart); thousands of look-ups
  could fill the price connection like the socket trick. Simulated prices never have "no price", so not shown here.
- The address used for login throttling is taken from a header the visitor may be able to set; whether the live
  hosting overwrites it could not be checked from here.
- Exchange position limit is checked per order against the current position only; several resting orders together
  could exceed it (margin is still required in full, so no free money expected).
- A Forex / Global position force-closed while its rupee conversion rate is missing would book zero profit or loss.
- Positions on a perpetual the crypto exchange suspends: now kept listed by the branch fix; re-check after it is live.
