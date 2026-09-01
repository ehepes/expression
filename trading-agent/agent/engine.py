"""The decision loop.

One `cycle()` is one complete pass: read the account, re-check every limit,
score the universe, close what should be closed, open what may be opened, and
write all of it to the journal. It is idempotent in the sense that running it
twice in a row will not double up a position — the second pass sees the first
pass's position and declines.

Exits are processed before entries, always. Reducing risk never waits behind
an attempt to add it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from . import strategy as strategy_mod
from .brokers import build as build_broker
from .brokers.base import Account, Broker, BrokerError, Position
from .config import Config
from .ledger import Ledger
from .protection import StopBook
from .risk import RiskEngine, Veto


@dataclass
class Action:
    """Something the engine did, or declined to do, for one symbol."""

    symbol: str
    intent: str  # enter | exit | hold
    reason: str
    executed: bool = False
    notional: float | None = None
    order_id: str | None = None
    blocked_by: str | None = None

    def describe(self) -> str:
        if self.executed:
            size = f" {self.notional:.2f}" if self.notional else ""
            return f"  [DONE] {self.intent.upper():<5} {self.symbol:<6}{size}  ({self.reason})"
        if self.blocked_by:
            return f"  [SKIP] {self.intent.upper():<5} {self.symbol:<6}  {self.blocked_by}"
        return f"  [    ] {self.intent.upper():<5} {self.symbol:<6}  {self.reason}"


@dataclass
class CycleReport:
    started_at: datetime
    mode: str
    broker_name: str
    strategy_name: str
    equity: float = 0.0
    cash: float = 0.0
    positions: list[Position] = field(default_factory=list)
    halted: list[Veto] = field(default_factory=list)
    actions: list[Action] = field(default_factory=list)
    protective_stops: list[tuple[str, float]] = field(default_factory=list)
    market_open: bool = True
    error: str | None = None

    @property
    def traded(self) -> bool:
        return any(action.executed for action in self.actions)

    def render(self) -> str:
        lines = [
            f"=== {self.started_at:%Y-%m-%d %H:%M:%S} UTC | {self.broker_name} "
            f"| {self.strategy_name} | mode={self.mode} ===",
            f"  equity {self.equity:.2f}   cash {self.cash:.2f}   "
            f"positions {len(self.positions)}   market {'OPEN' if self.market_open else 'CLOSED'}",
        ]
        for position in self.positions:
            lines.append(
                f"    holding {position.symbol:<6} {position.qty:.6f} @ "
                f"{position.avg_entry_price:.2f}  value {position.market_value:.2f}  "
                f"P/L {position.unrealized_pl:+.2f}"
            )
        if self.error:
            lines.append(f"  ERROR: {self.error}")
        for veto in self.halted:
            flag = "PERMANENT" if veto.permanent else "today"
            lines.append(f"  HALTED ({flag}): {veto.reason}")
        lines.extend(action.describe() for action in self.actions)
        if not self.actions and not self.halted and not self.error:
            lines.append("  no actionable signals")
        for symbol, stop in self.protective_stops:
            lines.append(f"  [STOP] resting sell stop armed on {symbol} at {stop:.2f}")
        return "\n".join(lines)


class Engine:
    def __init__(
        self,
        cfg: Config,
        *,
        broker: Broker | None = None,
        ledger: Ledger | None = None,
    ) -> None:
        self.cfg = cfg
        self.broker = broker or build_broker(cfg)
        self.ledger = ledger or Ledger(cfg.db_path)
        self.strategy = strategy_mod.build(cfg.strategy)
        self.risk = RiskEngine(cfg, self.ledger)
        self.stops = StopBook(self.ledger)

    @property
    def mode(self) -> str:
        if self.cfg.broker == "sim":
            return "sim"
        return "LIVE" if self.cfg.is_live else "paper"

    # -- main entry point --------------------------------------------------

    def cycle(self, *, dry_run: bool = False, ignore_market_hours: bool = False) -> CycleReport:
        report = CycleReport(
            started_at=datetime.now(timezone.utc),
            mode="dry-run" if dry_run else self.mode,
            broker_name=self.broker.name,
            strategy_name=self.strategy.name,
        )

        try:
            account = self.broker.get_account()
        except BrokerError as exc:
            report.error = str(exc)
            return report

        report.equity = account.equity
        report.cash = account.cash
        self.ledger.record_equity(account.equity, account.cash)

        run_id = self.ledger.start_run(
            mode=report.mode,
            broker=self.broker.name,
            strategy=self.strategy.name,
            equity=account.equity,
            cash=account.cash,
        )

        report.halted = self.risk.preflight(account)
        if report.halted:
            for veto in report.halted:
                self.ledger.record_decision(
                    run_id,
                    symbol="*",
                    action="halt",
                    reason=veto.reason,
                    block_reason=veto.code,
                )
            return report

        try:
            report.market_open = self.broker.is_market_open()
            report.positions = self.broker.get_positions()
        except BrokerError as exc:
            report.error = str(exc)
            return report

        if not report.market_open and not ignore_market_hours:
            report.actions.append(
                Action("*", "hold", "market closed", blocked_by="market closed — no orders placed")
            )
            return report

        held = {position.symbol for position in report.positions if position.qty > 0}
        # Forget stops for anything no longer held, so a stale stop can never
        # fire against a position that was closed elsewhere.
        self.stops.sync(held)

        # Resting protective stops reserve the shares, which would make an exit
        # fail for insufficient quantity. Clear them, trade, then re-arm.
        if not dry_run:
            self._clear_protective_orders(held, report)

        signals = self._score_universe(report.positions)
        by_symbol = {signal.symbol: signal for signal in signals}

        # Advance every trailing stop and find the breaches before deciding
        # anything else — a breach outranks whatever the strategy wants.
        breached = self._refresh_stops(report.positions, by_symbol)

        strategy_exits = [
            s for s in signals
            if s.action == strategy_mod.EXIT and s.symbol in held and s.symbol not in breached
        ]
        entries = sorted(
            (s for s in signals if s.action == strategy_mod.ENTER and s.symbol not in held),
            key=lambda s: s.score,
            reverse=True,
        )
        holds = [
            s for s in signals
            if s.action == strategy_mod.HOLD and s.symbol not in breached
        ]

        # 1. Stop breaches first. These are not negotiable.
        for symbol, (state, breach_price) in breached.items():
            signal = by_symbol.get(symbol) or strategy_mod.Signal(
                symbol, strategy_mod.EXIT, 0.0, "stop breached", breach_price
            )
            reason = (
                f"STOP HIT: price {breach_price:.2f} <= stop {state.stop_price:.2f} "
                f"(entry {state.entry_price:.2f}, peak {state.high_water:.2f})"
            )
            report.actions.append(
                self._do_exit(
                    run_id,
                    signal,
                    account,
                    dry_run=dry_run,
                    report=report,
                    reason_override=reason,
                    force=True,
                )
            )

        # 2. Then ordinary strategy exits — always reduce risk before adding it.
        for signal in strategy_exits:
            report.actions.append(
                self._do_exit(run_id, signal, account, dry_run=dry_run, report=report)
            )

        # 3. Then entries, best-scoring first.
        for signal in entries:
            report.actions.append(
                self._do_entry(run_id, signal, account, dry_run=dry_run, report=report)
            )

        # 4. Record the rest so the journal explains inaction too.
        for signal in holds:
            state = self.stops.get(signal.symbol)
            reason = signal.reason
            if state and signal.symbol in held:
                reason = f"{reason} (stop {state.stop_price:.2f})"
            self.ledger.record_decision(
                run_id,
                symbol=signal.symbol,
                action="hold",
                reason=reason,
                score=signal.score,
                price=signal.price,
            )
            report.actions.append(Action(signal.symbol, "hold", reason))

        # 5. Re-arm broker-side protection on whatever is still open, so the
        #    position is guarded even if this process never runs again.
        if not dry_run:
            self._arm_protective_stops(report, run_id)

        return report

    # -- stop-loss plumbing ------------------------------------------------

    def _refresh_stops(
        self,
        positions: list[Position],
        by_symbol: dict[str, strategy_mod.Signal],
    ) -> dict[str, tuple["object", float]]:
        """Ratchet every trailing stop; return breaches with the breaching price."""
        breached: dict[str, tuple[object, float]] = {}
        for position in positions:
            if position.qty <= 0:
                continue
            signal = by_symbol.get(position.symbol)
            # Prefer the live traded price over the last daily close. A stop
            # checked against yesterday's close is a stop that fires a day
            # late, which is the same as not having one.
            price = 0.0
            try:
                price = self.broker.latest_price(position.symbol)
            except (BrokerError, AttributeError):
                price = 0.0
            if price <= 0 and signal and signal.price > 0:
                price = signal.price
            if price <= 0:
                continue
            state = self.stops.update(
                position.symbol,
                price,
                signal.stop_price if signal else None,
                entry_price=position.avg_entry_price,
            )
            if state and state.breached(price):
                breached[position.symbol] = (state, price)
        return breached

    def _clear_protective_orders(self, held: set[str], report: CycleReport) -> None:
        """Cancel resting protective stops so the shares are free to trade."""
        canceller = getattr(self.broker, "cancel_orders_for", None)
        if not callable(canceller):
            return
        for symbol in sorted(held):
            try:
                canceller(symbol)
            except BrokerError as exc:
                report.actions.append(
                    Action(symbol, "hold", "stop cleanup", blocked_by=f"could not cancel resting orders: {exc}")
                )

    def _arm_protective_stops(self, report: CycleReport, run_id: int) -> None:
        """Place a resting sell stop under every open position."""
        placer = getattr(self.broker, "submit_stop_order", None)
        if not callable(placer):
            return

        try:
            positions = self.broker.get_positions()
        except BrokerError:
            positions = report.positions

        for position in positions:
            if position.qty <= 0:
                continue
            state = self.stops.get(position.symbol)
            if state is None or state.stop_price <= 0:
                continue
            try:
                order = placer(position.symbol, position.qty, state.stop_price)
            except BrokerError as exc:
                report.actions.append(
                    Action(
                        position.symbol,
                        "hold",
                        "protective stop",
                        blocked_by=f"could not arm stop at {state.stop_price:.2f}: {exc}",
                    )
                )
                continue
            self.ledger.record_order(
                run_id,
                broker_order_id=order.order_id,
                symbol=order.symbol,
                side="sell",
                notional=None,
                qty=order.qty,
                status=f"protective-{order.status}",
                fill_price=None,
            )
            report.protective_stops.append((position.symbol, state.stop_price))

    # -- internals ---------------------------------------------------------

    def _score_universe(self, positions: list[Position]) -> list[strategy_mod.Signal]:
        held = {position.symbol for position in positions if position.qty > 0}
        # Everything currently held is evaluated too, even if it has dropped
        # out of the configured universe — otherwise a config edit would strand
        # an open position with no exit logic watching it.
        symbols = list(dict.fromkeys(self.cfg.universe + sorted(held)))

        signals: list[strategy_mod.Signal] = []
        for symbol in symbols:
            try:
                bars = self.broker.get_daily_bars(symbol, self.strategy.warmup + 5)
            except BrokerError as exc:
                signals.append(
                    strategy_mod.Signal(symbol, strategy_mod.HOLD, 0.0, f"data error: {exc}", 0.0)
                )
                continue
            signals.append(self.strategy.evaluate(bars, held=symbol in held))
        return signals

    def _do_exit(
        self,
        run_id: int,
        signal: strategy_mod.Signal,
        account: Account,
        *,
        dry_run: bool,
        report: CycleReport,
        reason_override: str | None = None,
        force: bool = False,
    ) -> Action:
        reason = reason_override or signal.reason
        # `force` is set for stop breaches. A pattern-day-trader flag is a bad
        # outcome; riding an unstopped loss is a worse one, so the stop wins.
        veto = None if force else self.risk.check_exit(signal.symbol, account)
        if veto:
            self.ledger.record_decision(
                run_id,
                symbol=signal.symbol,
                action="exit",
                reason=reason,
                price=signal.price,
                block_reason=veto.reason,
            )
            return Action(signal.symbol, "exit", reason, blocked_by=veto.reason)

        if dry_run:
            self.ledger.record_decision(
                run_id,
                symbol=signal.symbol,
                action="exit",
                reason=reason,
                price=signal.price,
                block_reason="dry run",
            )
            return Action(signal.symbol, "exit", reason, blocked_by="dry run — not sent")

        try:
            order = self.broker.close_position(signal.symbol)
        except BrokerError as exc:
            self.ledger.record_decision(
                run_id,
                symbol=signal.symbol,
                action="exit",
                reason=reason,
                price=signal.price,
                block_reason=f"broker rejected: {exc}",
            )
            return Action(signal.symbol, "exit", reason, blocked_by=f"broker rejected: {exc}")

        self.ledger.record_order(
            run_id,
            broker_order_id=order.order_id,
            symbol=order.symbol,
            side="sell",
            notional=None,
            qty=order.qty,
            status=order.status,
            fill_price=order.filled_avg_price,
        )
        self.ledger.record_decision(
            run_id,
            symbol=signal.symbol,
            action="exit",
            reason=reason,
            price=signal.price,
            executed=True,
        )
        self.stops.close(signal.symbol)
        report.positions = [p for p in report.positions if p.symbol != signal.symbol]
        return Action(signal.symbol, "exit", reason, executed=True, order_id=order.order_id)

    def _do_entry(
        self,
        run_id: int,
        signal: strategy_mod.Signal,
        account: Account,
        *,
        dry_run: bool,
        report: CycleReport,
    ) -> Action:
        sizing = self.risk.size_entry(
            symbol=signal.symbol,
            price=signal.price,
            stop_price=signal.stop_price,
            account=account,
            positions=report.positions,
        )
        if not sizing.approved:
            reason = sizing.veto.reason if sizing.veto else "not approved"
            self.ledger.record_decision(
                run_id,
                symbol=signal.symbol,
                action="enter",
                reason=signal.reason,
                score=signal.score,
                price=signal.price,
                block_reason=reason,
            )
            return Action(signal.symbol, "enter", signal.reason, blocked_by=reason)

        if dry_run:
            self.ledger.record_decision(
                run_id,
                symbol=signal.symbol,
                action="enter",
                reason=signal.reason,
                score=signal.score,
                price=signal.price,
                block_reason="dry run",
            )
            return Action(
                signal.symbol,
                "enter",
                signal.reason,
                notional=sizing.notional,
                blocked_by=f"dry run — would buy {sizing.notional:.2f}",
            )

        try:
            order = self.broker.submit_order(signal.symbol, "buy", notional=sizing.notional)
        except BrokerError as exc:
            self.ledger.record_decision(
                run_id,
                symbol=signal.symbol,
                action="enter",
                reason=signal.reason,
                score=signal.score,
                price=signal.price,
                block_reason=f"broker rejected: {exc}",
            )
            return Action(signal.symbol, "enter", signal.reason, blocked_by=f"broker rejected: {exc}")

        self.ledger.record_order(
            run_id,
            broker_order_id=order.order_id,
            symbol=order.symbol,
            side="buy",
            notional=sizing.notional,
            qty=order.qty,
            status=order.status,
            fill_price=order.filled_avg_price,
        )
        self.ledger.record_decision(
            run_id,
            symbol=signal.symbol,
            action="enter",
            reason=signal.reason,
            score=signal.score,
            price=signal.price,
            executed=True,
        )
        # Record the protective stop that justified this position size. Without
        # this the stop would be recomputed from scratch every cycle and would
        # never actually fire.
        if signal.stop_price and signal.price > 0:
            self.stops.open_position(signal.symbol, signal.price, signal.stop_price)

        # Reflect the new position immediately so later entries in this same
        # cycle see the reduced headroom.
        report.positions.append(
            Position(
                symbol=signal.symbol,
                qty=sizing.notional / signal.price if signal.price else 0.0,
                avg_entry_price=signal.price,
                market_value=sizing.notional,
                unrealized_pl=0.0,
            )
        )
        return Action(
            signal.symbol,
            "enter",
            signal.reason,
            executed=True,
            notional=sizing.notional,
            order_id=order.order_id,
        )
