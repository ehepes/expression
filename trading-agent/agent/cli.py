"""Command line interface.

    python -m agent preflight     # can we actually connect and trade?
    python -m agent run --dry-run # full decision pass, no orders sent
    python -m agent run           # one live pass (paper unless armed)
    python -m agent run --loop 900
    python -m agent backtest
    python -m agent status
    python -m agent halt / resume
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from . import config as config_mod
from .backtest import run_backtest
from .brokers import build as build_broker
from .brokers.base import BrokerError
from .config import LIVE_CONFIRM_PHRASE, Config, ConfigError
from .engine import Engine
from .ledger import Ledger
from .protection import StopBook
from .strategy import build as build_strategy

PASS = "  PASS"
FAIL = "  FAIL"
WARN = "  WARN"


def _load(args: argparse.Namespace) -> Config:
    return config_mod.load(args.env_file)


# ---------------------------------------------------------------------------
# preflight
# ---------------------------------------------------------------------------


def cmd_preflight(args: argparse.Namespace) -> int:
    print("=== preflight ===")
    try:
        cfg = _load(args)
    except ConfigError as exc:
        print(f"{FAIL}  config: {exc}")
        return 1
    print(f"{PASS}  config loaded (broker={cfg.broker}, strategy={cfg.strategy})")

    if cfg.broker == "kraken":
        print(f"{WARN}  Kraken has no paper mode — this is a REAL MONEY account")
        if not cfg.is_armed:
            print(
                f"{FAIL}  LIVE_CONFIRM is not set to {LIVE_CONFIRM_PHRASE!r}; "
                "the agent will refuse to place orders"
            )
    if cfg.broker == "alpaca":
        target = "REAL MONEY" if cfg.is_live else "paper money"
        print(f"{PASS}  endpoint {cfg.trading_base_url}  -> {target}")
        if cfg.live_requested_but_unarmed:
            print(
                f"{FAIL}  ALPACA_ENV=live but LIVE_CONFIRM is not the exact phrase "
                f"{LIVE_CONFIRM_PHRASE!r}. The agent will refuse to place orders."
            )

    failures = 0
    try:
        broker = build_broker(cfg)
        account = broker.get_account()
    except BrokerError as exc:
        print(f"{FAIL}  cannot reach broker: {exc}")
        return 1
    print(
        f"{PASS}  authenticated — account {account.account_id or '(n/a)'} "
        f"status={account.status} currency={account.currency}"
    )

    if account.tradable:
        print(f"{PASS}  account is tradable")
    else:
        print(f"{FAIL}  account is NOT tradable (blocked={account.trading_blocked})")
        failures += 1

    print(
        f"{PASS}  equity {account.equity:.2f} {account.currency}, "
        f"cash {account.cash:.2f}, buying power {account.buying_power:.2f}"
    )
    if account.pattern_day_trader:
        print(f"{WARN}  account is flagged pattern-day-trader")

    limits = cfg.limits
    if account.equity > 0 and limits.max_deployed > account.equity:
        print(
            f"{WARN}  MAX_DEPLOYED {limits.max_deployed:.2f} exceeds equity "
            f"{account.equity:.2f}; the cash balance will bind first"
        )
    if account.equity > 0 and limits.min_order_notional > account.equity:
        print(f"{FAIL}  MIN_ORDER_NOTIONAL exceeds account equity — no order can ever be placed")
        failures += 1

    try:
        is_open = broker.is_market_open()
        print(f"{PASS}  market clock reachable — market is {'OPEN' if is_open else 'closed'}")
    except BrokerError as exc:
        print(f"{FAIL}  market clock unreachable: {exc}")
        failures += 1

    strategy = build_strategy(cfg.strategy, cfg.limits.max_stop_distance_pct / 100.0)
    print(f"  -- market data ({cfg.alpaca_data_feed} feed, need {strategy.warmup} daily bars) --")
    for symbol in cfg.universe:
        try:
            bars = broker.get_daily_bars(symbol, strategy.warmup + 5)
        except BrokerError as exc:
            print(f"{FAIL}  {symbol}: data error: {exc}")
            failures += 1
            continue
        if len(bars) < strategy.warmup:
            print(f"{FAIL}  {symbol}: only {len(bars)} bars, need {strategy.warmup}")
            failures += 1
            continue
        note = ""
        blocked = False
        checker = getattr(broker, "is_fractionable", None)
        if callable(checker):
            try:
                if not checker(symbol):
                    note = "  (NOT fractionable — unusable at this size)"
                    blocked = True
            except BrokerError as exc:
                note = f"  ({exc})"
                blocked = True

        # Venues with per-instrument minimums (Kraken) can make a symbol
        # untradable at this account size. That is the binding constraint at
        # €50, so it is checked here rather than discovered from a rejection.
        limits_for = getattr(broker, "pair_limits", None)
        if callable(limits_for) and not blocked:
            try:
                ordermin, costmin = limits_for(symbol)
                price = bars[-1].close
                floor = max(ordermin * price, costmin)
                if floor > 0:
                    note = f"  min order ~{floor:.2f} {account.currency}"
                    if floor > cfg.limits.max_order_notional:
                        note += (
                            f"  -> EXCEEDS MAX_ORDER_NOTIONAL "
                            f"({cfg.limits.max_order_notional:.2f}); this pair cannot be traded"
                        )
                        blocked = True
                    elif floor > cfg.limits.max_deployed:
                        note += "  -> exceeds MAX_DEPLOYED"
                        blocked = True
            except BrokerError as exc:
                note = f"  (minimums unknown: {exc})"

        if blocked:
            failures += 1
        print(
            f"{FAIL if blocked else PASS}  {symbol}: {len(bars)} bars, "
            f"last {bars[-1].close:.2f}{note}"
        )

    halt = Path(cfg.halt_file)
    if halt.exists():
        print(f"{WARN}  halt file present at {halt} — the agent will not trade until it is removed")

    print()
    if failures:
        print(f"VERDICT: NOT READY — {failures} blocking issue(s) above.")
        return 1
    print("VERDICT: READY. `python -m agent run --dry-run` next; it places no orders.")
    return 0


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------


def cmd_run(args: argparse.Namespace) -> int:
    try:
        cfg = _load(args)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 1

    if cfg.is_live and not args.dry_run:
        print("!! REAL MONEY MODE — orders will be placed against your funded account.")

    with Ledger(cfg.db_path) as ledger:
        engine = Engine(cfg, ledger=ledger)
        while True:
            report = engine.cycle(
                dry_run=args.dry_run, ignore_market_hours=args.ignore_market_hours
            )
            print(report.render(), flush=True)
            permanent = any(veto.permanent for veto in report.halted)
            if permanent:
                print("Permanent halt — exiting.", flush=True)
                return 2
            if not args.loop:
                return 1 if report.error else 0
            time.sleep(args.loop)


# ---------------------------------------------------------------------------
# backtest / status / halt
# ---------------------------------------------------------------------------


def cmd_backtest(args: argparse.Namespace) -> int:
    try:
        cfg = _load(args)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 1

    broker = build_broker(cfg)
    strategy = build_strategy(cfg.strategy, cfg.limits.max_stop_distance_pct / 100.0)
    needed = strategy.warmup + args.bars

    bars_by_symbol = {}
    for symbol in cfg.universe:
        try:
            bars_by_symbol[symbol] = broker.get_daily_bars(symbol, needed)
        except BrokerError as exc:
            print(f"skipping {symbol}: {exc}", file=sys.stderr)
    if not bars_by_symbol:
        print("no data for any symbol", file=sys.stderr)
        return 1

    result = run_backtest(
        bars_by_symbol,
        strategy,
        starting_equity=cfg.limits.max_deployed,
        max_positions=cfg.limits.max_positions,
        risk_per_trade_pct=cfg.limits.risk_per_trade_pct,
        max_order_notional=cfg.limits.max_order_notional,
        min_order_notional=cfg.limits.min_order_notional,
        cost_bps=args.cost_bps,
    )
    print(result.render())
    print(f"\n  universe: {', '.join(sorted(bars_by_symbol))}   strategy: {strategy.name}")
    if cfg.broker == "sim":
        print("  NOTE: prices are synthetic (BROKER=sim). This validates plumbing, not edge.")
    return 0


def cmd_go_live(args: argparse.Namespace) -> int:
    """Arming checklist. Verifies real-money readiness; places no orders."""
    print("=== go-live checklist ===\n")
    try:
        cfg = _load(args)
    except ConfigError as exc:
        print(f"{FAIL}  config: {exc}")
        return 1

    blockers: list[str] = []

    if not cfg.is_real_money:
        blockers.append(
            f"BROKER={cfg.broker}"
            + (" with ALPACA_ENV=paper" if cfg.broker == "alpaca" else "")
            + " does not point at a real-money account"
        )
        print(f"{FAIL}  BROKER={cfg.broker} (not real money)")
    elif cfg.broker == "kraken":
        print(f"{PASS}  BROKER=kraken (real money — Kraken has no paper mode)")
    else:
        print(f"{PASS}  BROKER=alpaca ALPACA_ENV=live -> {cfg.trading_base_url}")

    if cfg.live_confirm != LIVE_CONFIRM_PHRASE:
        blockers.append(f"LIVE_CONFIRM must be exactly: {LIVE_CONFIRM_PHRASE}")
        print(f"{FAIL}  LIVE_CONFIRM is not set to the required phrase")
    else:
        print(f"{PASS}  LIVE_CONFIRM phrase accepted")

    account = None
    if cfg.is_real_money:
        try:
            account = build_broker(cfg).get_account()
            print(
                f"{PASS}  connected — account {account.account_id or '(n/a)'} "
                f"status={account.status}"
            )
        except BrokerError as exc:
            blockers.append(f"cannot reach the live account: {exc}")
            print(f"{FAIL}  connection: {exc}")

    if account is not None:
        print(f"{PASS}  REAL balance: equity {account.equity:.2f} {account.currency}, "
              f"cash {account.cash:.2f}")
        if account.equity <= 0:
            blockers.append("the account holds no money — fund it before arming")
            print(f"{FAIL}  account is unfunded")
        if not account.tradable:
            blockers.append(f"account not tradable (status={account.status})")
            print(f"{FAIL}  account is not tradable")

    limits = cfg.limits
    print("\n  Limits that will bind every order:")
    print(f"    most it can ever deploy      {limits.max_deployed:.2f}")
    print(f"    largest single order         {limits.max_order_notional:.2f}")
    print(f"    risked per trade             {limits.risk_per_trade_pct:.2f}% of equity")
    print(f"    stops trading for the day at -{limits.daily_loss_limit_pct:.1f}%")
    print(f"    stops permanently at         -{limits.max_drawdown_pct:.1f}% from peak")
    print(f"    max orders per day           {limits.max_orders_per_day}")
    print(f"    max open positions           {limits.max_positions}")

    if account is not None and limits.max_deployed > account.equity:
        print(f"\n{WARN}  MAX_DEPLOYED ({limits.max_deployed:.2f}) exceeds your balance "
              f"({account.equity:.2f}); cash will bind first, but lower it to be explicit.")

    if blockers:
        print("\n  NOT ARMED. Fix these first:")
        for item in blockers:
            print(f"    - {item}")
        return 1

    worst = account.equity * limits.max_drawdown_pct / 100 if account else 0.0
    print("\n  Everything above is real money.")
    print(f"  The drawdown switch stops the agent after roughly {worst:.2f} "
          f"{account.currency if account else ''} of losses, but nothing guarantees that")
    print("  limit under a gap or an outage. You can lose the full balance.")

    if not sys.stdin.isatty():
        print(f"\n{FAIL}  go-live needs an interactive terminal to confirm.")
        return 1

    print(f"\n  Type the phrase to arm, or anything else to abort:\n    {LIVE_CONFIRM_PHRASE}")
    try:
        typed = input("  > ").strip()
    except EOFError:
        typed = ""
    if typed != LIVE_CONFIRM_PHRASE:
        print("\n  Aborted. Nothing was armed.")
        return 1

    print("\n  ARMED. The next `python -m agent run` will place real orders.")
    print("  Stop it at any time with `python -m agent halt` (or `touch HALT`).")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    try:
        cfg = _load(args)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 1

    with Ledger(cfg.db_path) as ledger:
        try:
            broker = build_broker(cfg)
            account = broker.get_account()
            positions = broker.get_positions()
        except BrokerError as exc:
            print(f"broker unreachable: {exc}", file=sys.stderr)
            return 1

        peak = float(ledger.get_state("high_water_mark", 0.0) or 0.0)
        opening = ledger.first_equity_today()
        print(f"=== status ({broker.name}) ===")
        print(f"  equity {account.equity:.2f} {account.currency}   cash {account.cash:.2f}")
        if peak:
            print(f"  peak equity {peak:.2f}   drawdown {(peak - account.equity) / peak * 100:.2f}%")
        if opening:
            print(f"  today: opened at {opening:.2f}, now {account.equity:.2f} "
                  f"({(account.equity - opening) / opening * 100:+.2f}%)")
        print(f"  orders today {ledger.orders_today()} / {cfg.limits.max_orders_per_day}")
        print(f"  day trades {account.day_trade_count} / {cfg.limits.max_day_trades}")

        stops = StopBook(ledger)
        if positions:
            print("  positions:")
            for position in positions:
                print(
                    f"    {position.symbol:<6} {position.qty:.6f} @ {position.avg_entry_price:.2f}"
                    f"   value {position.market_value:.2f}   P/L {position.unrealized_pl:+.2f}"
                )
                state = stops.get(position.symbol)
                if state:
                    print(
                        f"           stop {state.stop_price:.2f} "
                        f"({state.distance_pct:.1f}% below peak {state.high_water:.2f})"
                    )
                else:
                    print("           stop: NONE ON FILE — unprotected")
        else:
            print("  positions: none")

        try:
            resting = broker.list_open_orders()
        except (BrokerError, AttributeError):
            resting = []
        protective = [order for order in resting if order.is_protective]
        if protective:
            print("  resting protective stops:")
            for order in protective:
                print(f"    {order.symbol:<6} sell stop @ {order.stop_price:.2f}  ({order.status})")

        orders = ledger.recent_orders(10)
        if orders:
            print("  recent orders:")
            for order in orders:
                size = order["notional"] or order["qty"] or 0
                print(
                    f"    {order['ts']}  {order['side']:<4} {order['symbol']:<6} "
                    f"{size:>8.2f}  {order['status']}"
                )
    return 0


def cmd_halt(args: argparse.Namespace) -> int:
    cfg = _load(args)
    path = Path(cfg.halt_file)
    path.write_text("halted by operator\n", encoding="utf-8")
    print(f"halt file written to {path}. The agent will place no orders until it is removed.")
    return 0


def cmd_resume(args: argparse.Namespace) -> int:
    cfg = _load(args)
    path = Path(cfg.halt_file)
    if path.exists():
        path.unlink()
        print(f"removed {path}; trading may resume.")
    else:
        print(f"no halt file at {path}; nothing to do.")
    return 0


# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent", description=__doc__)
    parser.add_argument("--env-file", default=".env", help="path to the .env file")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("preflight", help="verify connectivity, account and data").set_defaults(
        func=cmd_preflight
    )

    run = subparsers.add_parser("run", help="run the decision loop")
    run.add_argument("--dry-run", action="store_true", help="decide and log, but send no orders")
    run.add_argument("--loop", type=int, metavar="SECONDS", help="repeat every SECONDS")
    run.add_argument(
        "--ignore-market-hours",
        action="store_true",
        help="evaluate even when the market is closed (useful with --dry-run)",
    )
    run.set_defaults(func=cmd_run)

    backtest = subparsers.add_parser("backtest", help="replay the strategy over history")
    backtest.add_argument("--bars", type=int, default=500, help="trading days to simulate")
    backtest.add_argument("--cost-bps", type=float, default=5.0, help="slippage per fill")
    backtest.set_defaults(func=cmd_backtest)

    subparsers.add_parser(
        "go-live", help="real-money arming checklist (places no orders)"
    ).set_defaults(func=cmd_go_live)
    subparsers.add_parser("status", help="account, positions and recent orders").set_defaults(
        func=cmd_status
    )
    subparsers.add_parser("halt", help="stop all trading immediately").set_defaults(func=cmd_halt)
    subparsers.add_parser("resume", help="clear the halt file").set_defaults(func=cmd_resume)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130
    except (ConfigError, BrokerError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
