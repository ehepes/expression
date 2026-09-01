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

        signals = self._score_universe(report.positions)

        held = {position.symbol for position in report.positions if position.qty > 0}
        exits = [s for s in signals if s.action == strategy_mod.EXIT and s.symbol in held]
        entries = sorted(
            (s for s in signals if s.action == strategy_mod.ENTER and s.symbol not in held),
            key=lambda s: s.score,
            reverse=True,
        )
        holds = [s for s in signals if s.action == strategy_mod.HOLD]

        # 1. Exits first — always reduce risk before adding it.
        for signal in exits:
            report.actions.append(
                self._do_exit(run_id, signal, account, dry_run=dry_run, report=report)
            )

        # 2. Then entries, best-scoring first.
        for signal in entries:
            report.actions.append(
                self._do_entry(run_id, signal, account, dry_run=dry_run, report=report)
            )

        # 3. Record the rest so the journal explains inaction too.
        for signal in holds:
            self.ledger.record_decision(
                run_id,
                symbol=signal.symbol,
                action="hold",
                reason=signal.reason,
                score=signal.score,
                price=signal.price,
            )
            report.actions.append(Action(signal.symbol, "hold", signal.reason))

        return report

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
    ) -> Action:
        veto = self.risk.check_exit(signal.symbol, account)
        if veto:
            self.ledger.record_decision(
                run_id,
                symbol=signal.symbol,
                action="exit",
                reason=signal.reason,
                price=signal.price,
                block_reason=veto.reason,
            )
            return Action(signal.symbol, "exit", signal.reason, blocked_by=veto.reason)

        if dry_run:
            self.ledger.record_decision(
                run_id,
                symbol=signal.symbol,
                action="exit",
                reason=signal.reason,
                price=signal.price,
                block_reason="dry run",
            )
            return Action(signal.symbol, "exit", signal.reason, blocked_by="dry run — not sent")

        try:
            order = self.broker.close_position(signal.symbol)
        except BrokerError as exc:
            self.ledger.record_decision(
                run_id,
                symbol=signal.symbol,
                action="exit",
                reason=signal.reason,
                price=signal.price,
                block_reason=f"broker rejected: {exc}",
            )
            return Action(signal.symbol, "exit", signal.reason, blocked_by=f"broker rejected: {exc}")

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
            reason=signal.reason,
            price=signal.price,
            executed=True,
        )
        report.positions = [p for p in report.positions if p.symbol != signal.symbol]
        return Action(signal.symbol, "exit", signal.reason, executed=True, order_id=order.order_id)

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
