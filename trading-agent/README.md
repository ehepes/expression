# Autonomous trading agent

A small, auditable trading agent that connects to a brokerage account, scores a
universe of instruments once per cycle, and places orders inside hard limits it
is not allowed to exceed.

Default venue is **Kraken** (EUR-native, MiCA/CASP licensed by the Central Bank
of Ireland). Alpaca and an offline simulator are also supported.

> **Kraken has no paper mode.** Selecting it means real money from the first
> connection. The agent refuses to place any order until you arm it
> deliberately — see [Going live](#going-live).

---

## The three costs that decide everything at €50

Trading cost is not one number. At this size all three matter, and the third is
the one nobody mentions until it is too late:

| | Cost to trade | Cost in (FX) | **Cost to get your money out** |
|---|---|---|---|
| **Kraken** | 0.25–0.40% | none, EUR-native | ~€1 SEPA |
| **Alpaca** | €0 commission | EUR→USD, ~1.5% | **$50 international wire** |
| **IBKR Ireland** | ~€1.25 min/order | none on EU stocks | 1 free withdrawal/month |

Alpaca is the cheapest place to *trade* and the most expensive place to
*leave*: withdrawing €50 by international wire costs $50, the whole account.
IBKR's €1.25 minimum is ~8% round-trip on a €15 position, which no strategy
overcomes. Kraken is the only one of the three where all three costs stay small
on a €50 balance — at the price of trading crypto rather than equities.

### What the upside actually looks like

A genuinely excellent 20% year on €50 is **€10**. That is the realistic
ceiling, and it is why the table above decides more than the strategy does.

Nothing here has a private edge. The strategies are public techniques,
implemented carefully with the costs counted honestly. Over any given month the
most likely outcome is a small loss; the second most likely is a small gain.

### What trading crypto instead of ETFs actually changes

- **Volatility is several times higher.** The agent responds by sizing
  positions *down* — risking a fixed 1.5% of equity to the stop means a wide
  stop produces a small position. On a €50 balance expect positions around
  €3–5, not €15. That is the risk model working, not a bug.
- **Markets never close.** There is no overnight gap, but also no close to
  reset at. Run the agent on a schedule; it is not more profitable for
  watching continuously.
- **No investor-protection scheme covers crypto.** MiCA regulates conduct and
  custody standards, not your losses. There is no ICS or SIPC equivalent here.

---

## Credentials

**I cannot hold your API keys, and you should not paste them into a chat.**
They are bearer credentials — anything holding them can move your money, and a
transcript is not a safe place to keep one.

The credential step runs on your machine, in a gitignored `.env`, and the agent
proves the connection itself:

```bash
python -m agent preflight   # verifies credentials, balance, data, minimum order sizes
python -m agent go-live     # real-money arming checklist
```

When you create the Kraken API key, grant only:

- Query Funds
- Query Open Orders & Trades
- Query Closed Orders & Trades
- Create & Modify Orders
- Cancel Orders

**Do not enable Withdraw Funds.** The agent never needs it, and a key that
cannot withdraw cannot be used to drain the account if it leaks.

---

## Setup

```bash
cd trading-agent
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Fill in `KRAKEN_KEY` and `KRAKEN_SECRET`, then:

```bash
python -m agent preflight
```

Preflight checks credentials, balance, market data, and — the constraint that
actually binds at €50 — each pair's **minimum order size**. Kraken enforces a
per-pair `ordermin`; if a pair's minimum exceeds your `MAX_ORDER_NOTIONAL`,
preflight fails that pair rather than letting you discover it from a rejected
order.

Watch it think without letting it act:

```bash
python -m agent run --dry-run
```

Every decision, including refusals, is journalled to `agent.db`.

---

## Running

```bash
python -m agent run                  # one decision cycle
python -m agent run --loop 900       # every 15 minutes
python -m agent status               # balance, positions, stops, recent orders
python -m agent backtest --bars 500  # replay the strategy over history
python -m agent go-live              # real-money arming checklist
python -m agent halt                 # stop trading immediately
python -m agent resume               # clear the halt
```

A daily cycle is enough for both strategies; they are designed to trade rarely.
Crypto trades continuously, so pick a fixed time rather than polling hard:

```cron
0 9 * * * cd /path/to/trading-agent && .venv/bin/python -m agent run >> agent.log 2>&1
```

---

## Going live

Real money takes **four** deliberate steps, so it cannot happen by accident:

1. `BROKER=kraken` (or `ALPACA_ENV=live`)
2. A real key pair in `.env`
3. `LIVE_CONFIRM=I ACCEPT REAL MONEY LOSS` — exact, case-sensitive
4. `python -m agent go-live` — shows your real balance and the limits that will
   bind, then makes you type the phrase back

Miss any one and the agent halts with `live_unarmed` and places no orders.
There is a test asserting exactly that, for both venues.

An unarmed real-money config reports `mode=UNARMED`, never `paper` — it is
pointed at real money and refusing, which is a different thing from being safe.

Set `MAX_DEPLOYED` to the amount you are actually willing to lose.

---

## Stop losses

Every position gets a stop, recorded when it opens and persisted in the ledger.
It is a **ratchet**: it follows the high-water price up and never moves down, so
a position that runs up locks in the gain.

Enforced in two independent places:

- **At cycle time**, against the *live* price, not the last daily close. A
  breach is a forced exit that overrides the strategy — and overrides the
  day-trade guard, because a pattern-day-trader flag is recoverable and an
  unstopped loss is not.
- **At the broker**, as a resting `stop-loss` order, so the position stays
  guarded even if this process never runs again. It is cancelled and re-armed
  each cycle as the trail moves up.

Two limits worth knowing:

- **Stops are clamped by `MAX_STOP_DISTANCE_PCT` (default 25%).** On a volatile
  instrument an ATR-derived stop can come out wider than the price itself,
  which is not a stop at all. The clamp guarantees `0 < stop < price` always.
  This matters far more on crypto than it ever did on ETFs.
- **A stop is not a guarantee.** It becomes a market order when triggered. In a
  fast move you can fill below it. No retail setup avoids this.

If a position ever ends a cycle without a usable stop, the agent says so
explicitly rather than continuing quietly.

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
| `MAX_STOP_DISTANCE_PCT` | 25 | Ceiling on how far below entry a stop may sit |
| `DAILY_LOSS_LIMIT_PCT` | 4 | Stop trading for the day after this loss |
| `MAX_DRAWDOWN_PCT` | 25 | **Permanent** stop once equity falls this far below peak |
| `MAX_ORDERS_PER_DAY` | 6 | Hard cap on daily order count |
| `MAX_DAY_TRADES` | 2 | Guards against a US pattern-day-trader flag (Alpaca only) |
| `MAX_POSITIONS` | 2 | Simultaneous open positions |
| `HALT_FILE` | `./HALT` | If this file exists, no orders are placed, full stop |

Beyond those: the agent is **long-only**, never uses leverage or margin, never
shorts, and places only day orders — an order that did not fill was based on
stale information, so it expires rather than resting.

The kill switch is a file. `touch HALT` stops it from anywhere — another
terminal, a phone over SSH, a cron job — without needing to find a process.

---

## Strategies

**`trend`** (default) — dual moving-average crossover (20/100) with a 200-day
regime filter and an ATR stop. Buys only what is above its long-term average
and trending up; exits on the reverse cross or a regime break.

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
    kraken.py     Kraken spot adapter (EUR-native; real money only)
    alpaca.py     Alpaca adapter (paper and live share this path)
    sim.py        fully offline simulator — no keys, no network, no money
  indicators.py   SMA / ATR / RSI, returning None until fully warmed up
  strategy.py     signal generation; never sizes, never touches a broker
  protection.py   persistent ratcheting stops; the loss limiter
  risk.py         the layer allowed to say no
  ledger.py       SQLite journal of every decision, refusal and fill
  engine.py       the decision loop; exits processed before entries, always
  backtest.py     next-open fills, costs on both sides
  cli.py          preflight / go-live / run / status / backtest / halt / resume
tests/            111 tests, no network required
```

Adding another venue means writing one file against `brokers/base.Broker`. The
engine, risk layer and stops did not change when Kraken was added.

---

## Tests

```bash
python -m unittest discover -s tests -t .
```

111 tests, fully offline — the Kraken adapter is tested against a fake HTTP
layer that asserts on request signing, nonce ordering, pair-alias resolution,
volume rounding and minimum-order enforcement.

They also cover: that live mode without the confirmation phrase places no
orders on either venue; that a cycle never re-buys an open position; that the
deployment and position caps hold across repeated cycles; that stops ratchet
up, never loosen, fire on a breach, and bank a gain when they trail above
entry; and that a stop is never stored negative, zero, or above the price.

Run the whole pipeline right now with no credentials:

```bash
BROKER=sim UNIVERSE=SPY,QQQ,IWM python -m agent preflight
BROKER=sim UNIVERSE=SPY,QQQ,IWM python -m agent run --dry-run
```

---

## Tax

Irish CGT applies to gains on crypto disposals, and every sale is a disposal —
an automated agent can generate a lot of them. The annual exemption is small;
the record-keeping burden is real. `agent.db` journals every fill with
timestamp, price and quantity, which is what you will need. I am not a tax
adviser; if this grows beyond trivial amounts, get one.

---

## Sources

- [Kraken — MiCA licence via the Central Bank of Ireland](https://casptracker.eu/exchange/kraken/)
- [Kraken — EU/MiCA entity and fees](https://www.kraken.com/europe-switch)
- [Alpaca — EEA passporting to 29 countries incl. Ireland](https://alpaca.markets/blog/alpaca-completes-eea-passporting-to-29-countries-expanding-access-to-regulated-investment-services-across-europe/)
- [Alpaca — transfer fees outside the US](https://alpaca.markets/support/fees-transfers-outside-us)
- [Alpaca — fractional trading order types](https://docs.alpaca.markets/us/docs/fractional-trading)
- [Interactive Brokers Ireland — commissions](https://www.interactivebrokers.ie/en/pricing/commissions-stocks.php)

---

*Nothing here is financial advice. You are responsible for your own money, your
own tax position, and for reading the code before you run it.*
