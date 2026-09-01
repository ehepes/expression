# Autonomous trading agent

A small, auditable trading agent that connects to a brokerage account, scores a
universe of instruments once per cycle, and places orders inside hard limits it
is not allowed to exceed.

It defaults to **paper money** and will not touch real money until you
explicitly arm it. Read [the three costs](#the-three-costs-that-decide-everything-at-50)
first — at a €50 account size that section decides more than the strategy does.

---

## The three costs that decide everything at €50

Trading costs are not one number. At this account size all three matter, and
the third one is the one nobody mentions until it is too late:

| | Cost to trade | Cost in (FX) | **Cost to get your money out** |
|---|---|---|---|
| **Alpaca** | €0 commission | EUR→USD, ~1.5% | **$50 international wire** |
| **IBKR Ireland** | ~€1.25 min/order | none if you trade EU stocks | 1 free withdrawal per calendar month |
| **Kraken** | 0.25–0.40% | none, EUR-native | ~€1 SEPA |

Alpaca is the cheapest place to *trade* and the most expensive place to
*leave*. Withdrawing €50 by international wire costs $50 — the whole account.
That is not a reason to avoid it, but it changes what funding it means: money
you put into Alpaca is money you should plan to leave there and add to, not
money you expect to move back to your Irish bank next month.

If you want the €50 to be genuinely round-trippable, the euro-native options
(Kraken, or IBKR with its one free monthly withdrawal) are the ones where all
three costs stay small.

### What the upside actually looks like

A genuinely excellent 20% year on €50 is **€10**. That is the realistic
ceiling, and it is why the table above dominates the decision — a €1.25
commission on a €15 position is 8% round-trip, which no strategy overcomes.
The agent defaults to a commission-free venue for exactly this reason.

Nothing here has a private edge. The strategies are public techniques,
implemented carefully and with the costs counted honestly. Over any given
month the most likely outcome is a small loss; the second most likely is a
small gain.

## Broker options in Ireland

You asked for options other than Trading 212. To run an agent like this, a
broker needs a **documented trading API** — which rules out most retail apps
Irish residents use. DEGIRO, Revolut, Lightyear and eToro have no public
order-placing API for retail customers, so none of them can be automated at
all, regardless of how good they are as manual brokers.

That leaves a short list.

| Broker | Regulated entity | API | Cost per trade | Fractional | Verdict at €50 |
|---|---|---|---|---|---|
| **Alpaca** | Alpaca Securities / EU entity, [EEA-passported to Ireland](https://alpaca.markets/blog/alpaca-completes-eea-passporting-to-29-countries-expanding-access-to-regulated-investment-services-across-europe/) since July 2026 | Excellent REST API, first-class; free paper API identical to live | Commission-free US equities/ETFs | Yes | **Best fit.** The only option where €50 is not eaten by fees |
| **Interactive Brokers Ireland (IBIE)** | Central Bank of Ireland | [Web API / TWS API](https://www.interactivebrokers.com/campus/ibkr-api-page/webapi-doc/), mature but heavier | ~€1.25 min per EU order, ~$0.35 min per US order | Yes | Excellent broker, wrong size. Commission minimums dominate a €50 account |
| **Kraken** | Payward Europe Solutions Ltd, MiCA/CASP licensed by the Central Bank of Ireland | Good REST/WebSocket API | 0.25% maker / 0.40% taker | Yes, to tiny amounts | Viable mechanically, but crypto volatility on €50 is a different risk than you asked for |
| **Capital.com / IG** | CySEC / CBI | Yes | Spread-based | N/A | **Avoid.** These are CFD venues; leverage on €50 is how €50 becomes €0 |

**Recommendation: start with Alpaca paper trading.** It costs nothing, needs no
funding, and the paper API is byte-for-byte the same API as live — so the code
you validate is the code that later trades. If after a few weeks of paper
results you still want to fund it, Alpaca is also the only one on this list
where €50 is not immediately consumed by per-trade costs.

Two caveats to verify yourself, because they depend on your circumstances:

- Confirm at signup that Alpaca opens accounts for Irish residents in your
  situation — passporting is in place, but eligibility is theirs to confirm.
- US shares held via a US broker involve a **W-8BEN** form, US dividend
  withholding tax, and Irish tax on gains. Irish CGT rules and the annual
  exemption apply to your gains regardless of size. I am not a tax adviser;
  if the amounts ever grow beyond trivial, get one.

---

## Credentials

**I cannot hold your API keys, and you should not paste them into a chat.**
They are bearer credentials — anything holding them can move your money, and a
transcript is not a safe place to keep one.

So the credential step runs on your machine, in a gitignored `.env`, and the
agent proves the connection itself:

```bash
python -m agent preflight   # verifies credentials, account, data, fractionability
python -m agent go-live     # real-money arming checklist
```

`preflight` tells you exactly what is wrong if anything is. `go-live` shows
your real balance and the limits that will bind, then requires you to type a
confirmation phrase before anything is armed.

## Setup

```bash
cd trading-agent
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
```

Then, in `.env`, set `ALPACA_KEY_ID` and `ALPACA_SECRET_KEY` from
**app.alpaca.markets → Home → API Keys**. Generate **paper** keys — they are a
different pair from live keys.

Verify the connection:

```bash
python -m agent preflight
```

This checks credentials, account status, tradability, the market clock, and
that every symbol in your universe has enough history and supports fractional
shares. It prints `READY` or a list of exactly what is blocking.

Then watch it think without letting it act:

```bash
python -m agent run --dry-run --ignore-market-hours
```

Every decision, including refusals, is written to `agent.db`. Run it daily for
a few weeks and read that journal before considering real money.

---

## Running

```bash
python -m agent run                  # one decision cycle
python -m agent run --loop 900       # every 15 minutes
python -m agent status               # account, positions, recent orders
python -m agent backtest --bars 500  # replay the strategy over history
python -m agent go-live              # real-money arming checklist
python -m agent halt                 # stop trading immediately
python -m agent resume               # clear the halt
```

A daily cycle is enough for both shipped strategies. They are designed to trade
rarely; running the loop every minute costs API calls and changes nothing.

Under cron, one pass shortly after the US open is a reasonable cadence:

```cron
35 14 * * 1-5 cd /path/to/trading-agent && .venv/bin/python -m agent run >> agent.log 2>&1
```

---

## Going live

Funding, in order:

1. Open a **live** account at app.alpaca.markets and complete the **W-8BEN**
   (it cuts US dividend withholding from 30% to 15% under the Ireland–US
   treaty). Irish CGT applies to your gains regardless of size.
2. Fund it. From Ireland that means EUR→USD conversion; send **euros** from a
   euro account, not another currency, or the transfer fails. Alpaca holds USD
   only.
3. Re-read the withdrawal line in the table at the top before you send money.

Then arm it. Real money takes **four** deliberate steps, so it cannot happen
by accident:

1. `ALPACA_ENV=live`
2. A live key pair (different from your paper keys)
3. `LIVE_CONFIRM=I ACCEPT REAL MONEY LOSS` — exact, case-sensitive
4. `python -m agent go-live` — which shows your real balance and makes you type
   the phrase back

Miss any one and the agent halts with `live_unarmed` and places no orders.
There is a test asserting exactly that.

Set `MAX_DEPLOYED` to the amount you are actually willing to lose. It caps
deployment even if the account later holds more.

## Stop losses

Every position gets a stop, recorded when it opens and persisted in the
ledger. It is a **ratchet**: it follows the high-water price up and never
moves down, so a position that runs up locks in the gain.

The stop is enforced in two independent places:

- **At cycle time**, against the *live* price rather than the last daily
  close. A breach is a forced exit that overrides the strategy — and overrides
  the day-trade guard, because a pattern-day-trader flag is a bad outcome and
  an unstopped loss is a worse one.
- **At the broker**, as a resting sell stop, so the position is guarded even
  if this process never runs again.

**The limit you need to know:** Alpaca supports fractional stop orders only
with `time_in_force=day`, so the resting stop expires at the close and is
re-armed on the next cycle. It protects you *during* sessions, not across
overnight gaps. If the market gaps down through your stop overnight, you exit
below it. No retail setup avoids that; be aware of it rather than surprised by
it.

## Safety limits

Every limit lives in `.env` and is enforced in `agent/risk.py`, re-checked
against a freshly fetched account immediately before every order.

| Setting | Default | What it does |
|---|---|---|
| `MAX_DEPLOYED` | 50 | Total capital the agent may ever have in the market |
| `MAX_ORDER_NOTIONAL` | 15 | Largest single order |
| `MIN_ORDER_NOTIONAL` | 2 | Below this, skip rather than place a pointless order |
| `RISK_PER_TRADE_PCT` | 1.5 | Equity risked per trade, measured to the stop |
| `DAILY_LOSS_LIMIT_PCT` | 4 | Stop trading for the day after this loss |
| `MAX_DRAWDOWN_PCT` | 25 | **Permanent** stop once equity falls this far below its peak |
| `MAX_ORDERS_PER_DAY` | 6 | Hard cap on daily order count |
| `MAX_DAY_TRADES` | 2 | Guards against a US pattern-day-trader flag |
| `MAX_POSITIONS` | 2 | Simultaneous open positions |
| `HALT_FILE` | `./HALT` | If this file exists, no orders are placed, full stop |

Stops are covered in their own section above. Beyond those: the agent is **long-only**, never uses leverage or margin, never
shorts, trades only whole-market ETFs by default, and places only day orders —
an order that did not fill today was based on stale information, so it expires
rather than resting.

The kill switch is a file. `touch HALT` stops it from anywhere — another
terminal, a phone over SSH, a cron job — without needing to find a process.

---

## Strategies

**`trend`** (default) — dual moving-average crossover (20/100) with a 200-day
regime filter and an ATR-based stop. Buys only what is above its long-term
average and trending up; exits on the reverse cross or a regime break. Trades
rarely, which is the point at this account size.

**`meanrev`** — buys 2-day RSI dips below 10, but only in instruments already
above their 200-day average; exits on the bounce. Higher turnover, so it is the
second choice when every fill costs a spread.

Neither is original and neither is secret. They are here because they are
transparent enough to audit and slow enough not to bleed to costs.

---

## Layout

```
agent/
  config.py       env-driven config; every money limit in one auditable place
  brokers/
    base.py       broker-neutral types + the Protocol every adapter implements
    alpaca.py     Alpaca REST adapter (paper and live share this path)
    sim.py        fully offline simulator — no keys, no network, no money
  indicators.py   SMA / ATR / RSI, returning None until fully warmed up
  strategy.py     signal generation; never sizes, never touches a broker
  risk.py         the layer allowed to say no
  protection.py   persistent ratcheting stops; the loss limiter
  ledger.py       SQLite journal of every decision, refusal and fill
  engine.py       the decision loop; exits processed before entries, always
  backtest.py     next-open fills, costs on both sides
  cli.py          preflight / go-live / run / status / backtest / halt / resume
tests/            80 tests, no network required
```

Adding another broker means writing one file against `brokers/base.Broker`. The
engine, risk layer and strategies do not change.

---

## Tests

```bash
python -m unittest discover -s tests -t .
```

80 tests, fully offline. They cover indicator warm-up, the risk vetoes
individually, that live mode without the confirmation phrase places no orders,
that a cycle never re-buys an open position, that the deployment cap and
position cap hold across repeated cycles, that the halt file stops everything,
and that stops ratchet up, never loosen, fire on a breach, and bank a gain
when they trail above the entry price.

Try the whole pipeline right now without any credentials:

```bash
BROKER=sim UNIVERSE=SPY,QQQ,IWM python -m agent preflight
BROKER=sim UNIVERSE=SPY,QQQ,IWM python -m agent run --dry-run
```

---

## Sources

- [Alpaca — EEA passporting to 29 countries incl. Ireland](https://alpaca.markets/blog/alpaca-completes-eea-passporting-to-29-countries-expanding-access-to-regulated-investment-services-across-europe/)
- [Alpaca — opening a live account as a non-US resident](https://alpaca.markets/learn/live-trading-account-non-us)
- [Interactive Brokers Ireland — commissions](https://www.interactivebrokers.ie/en/pricing/commissions-stocks.php)
- [IBKR Web API documentation](https://www.interactivebrokers.com/campus/ibkr-api-page/webapi-doc/)
- [Kraken — MiCA licence via the Central Bank of Ireland](https://casptracker.eu/exchange/kraken/)
- [Alpaca — transfer fees outside the US](https://alpaca.markets/support/fees-transfers-outside-us)
- [Alpaca — funding as a non-US resident](https://alpaca.markets/support/international-use-fund-account)
- [Alpaca — fractional trading order types](https://docs.alpaca.markets/us/docs/fractional-trading)

---

*Nothing here is financial advice. You are responsible for your own money, your
own tax position, and for reading the code before you run it.*
