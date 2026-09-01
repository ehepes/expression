# Autonomous trading agent

A small, auditable trading agent that connects to a brokerage account, scores a
universe of instruments once per cycle, and places orders inside hard limits it
is not allowed to exceed.

It defaults to **paper money** and will not touch real money until you
explicitly arm it. Read [Before you fund anything](#before-you-fund-anything)
first — it is the most useful section in this file.

---

## Before you fund anything

Three things you should know before running this with €50 of your own money.

**1. Nobody can promise you profit, and this agent does not.** The strategies
here are public, well-documented techniques. They have no private edge. Over
any given month the most likely outcome is a small loss, the second most likely
is a small gain. Systematic trend following has historically produced positive
returns over multi-year horizons, with long losing stretches in between; it is
not a way to turn €50 into meaningful money.

**2. At €50, the arithmetic is unforgiving.** A genuinely excellent 20% annual
return on €50 is **€10 a year**. That is the realistic ceiling on the upside,
and it is why broker choice below is dominated by one question: *what does a
trade cost?* On a broker charging a €1.25 minimum commission, a €15 position
pays ~8% in commission round-trip — the strategy would need to be right by 8%
before you break even. That is not a strategy problem you can fix with better
code. It is why the recommendation below is a commission-free broker.

**3. Treat the €50 as the cost of learning, not as capital.** The right way to
use this is to run it on paper for a few weeks, read the journal it writes,
and decide from evidence whether you want to fund it at all.

If any of that changes your mind, that is a good outcome. The paper mode costs
nothing and teaches the same lessons.

---

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

## What I could not do for you

You offered to give me access to your account. I want to be straight about
this: **I cannot hold your broker credentials, and you should not give them to
me or paste them into any chat.** API keys are bearer credentials — anything
that has them can move your money, and a chat transcript is not a safe place
to keep one.

What I built instead is the whole system, ready to connect, with the credential
step left where it belongs: on your machine, in a `.env` file that is
gitignored. You paste your keys in once, and the `preflight` command proves the
connection works end to end and tells you exactly what is wrong if it does not.
That is the "make sure you're able to connect" part of your request — it just
runs on your side of the wall rather than mine.

---

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

Real money requires **three** separate deliberate steps, so it cannot happen by
accident or typo:

1. `ALPACA_ENV=live`
2. A live key pair in `ALPACA_KEY_ID` / `ALPACA_SECRET_KEY`
3. `LIVE_CONFIRM=I ACCEPT REAL MONEY LOSS` — the exact phrase, case-sensitive

Miss any one and the agent halts on preflight with `live_unarmed` and places no
orders. Set `MAX_DEPLOYED=50` so it can never deploy more than you intended,
even if the account later holds more.

---

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

Beyond those: the agent is **long-only**, never uses leverage or margin, never
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
  ledger.py       SQLite journal of every decision, refusal and fill
  engine.py       the decision loop; exits processed before entries, always
  backtest.py     next-open fills, costs on both sides
  cli.py          preflight / run / status / backtest / halt / resume
tests/            53 tests, no network required
```

Adding another broker means writing one file against `brokers/base.Broker`. The
engine, risk layer and strategies do not change.

---

## Tests

```bash
python -m unittest discover -s tests -t .
```

53 tests, fully offline. They cover indicator warm-up, the risk vetoes
individually, that live mode without the confirmation phrase places no orders,
that a cycle never re-buys an open position, that the deployment cap and
position cap hold across repeated cycles, and that the halt file stops
everything.

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

---

*Nothing here is financial advice. You are responsible for your own money, your
own tax position, and for reading the code before you run it.*
