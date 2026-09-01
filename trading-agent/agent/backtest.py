"""A deliberately pessimistic backtester.

Two choices make it honest rather than flattering:

  * Orders fill at the **next** bar's open, never at the close that generated
    the signal. Filling at the signal bar's close is the single most common
    way a backtest invents profit that does not exist.
  * Every fill pays `cost_bps` in spread/slippage, both entering and exiting.

It still cannot model the things that actually kill small live accounts —
regime change, gap risk, your own behaviour — so treat the output as a sanity
check on the plumbing, not a forecast.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date

from .brokers.base import Bar
from .strategy import ENTER, EXIT, Strategy


@dataclass
class Trade:
    symbol: str
    entry_day: date
    entry_price: float
    exit_day: date | None = None
    exit_price: float | None = None
    qty: float = 0.0

    @property
    def pnl(self) -> float:
        if self.exit_price is None:
            return 0.0
        return (self.exit_price - self.entry_price) * self.qty

    @property
    def closed(self) -> bool:
        return self.exit_price is not None


@dataclass
class BacktestResult:
    starting_equity: float
    final_equity: float
    equity_curve: list[tuple[date, float]] = field(default_factory=list)
    trades: list[Trade] = field(default_factory=list)
    cost_bps: float = 5.0

    @property
    def total_return_pct(self) -> float:
        if self.starting_equity <= 0:
            return 0.0
        return (self.final_equity / self.starting_equity - 1) * 100

    @property
    def max_drawdown_pct(self) -> float:
        peak = 0.0
        worst = 0.0
        for _day, equity in self.equity_curve:
            peak = max(peak, equity)
            if peak > 0:
                worst = max(worst, (peak - equity) / peak * 100)
        return worst

    @property
    def closed_trades(self) -> list[Trade]:
        return [trade for trade in self.trades if trade.closed]

    @property
    def win_rate_pct(self) -> float:
        closed = self.closed_trades
        if not closed:
            return 0.0
        return sum(1 for trade in closed if trade.pnl > 0) / len(closed) * 100

    @property
    def years(self) -> float:
        if len(self.equity_curve) < 2:
            return 0.0
        span = (self.equity_curve[-1][0] - self.equity_curve[0][0]).days
        return span / 365.25

    @property
    def cagr_pct(self) -> float:
        if self.years <= 0 or self.starting_equity <= 0 or self.final_equity <= 0:
            return 0.0
        return ((self.final_equity / self.starting_equity) ** (1 / self.years) - 1) * 100

    def render(self) -> str:
        closed = self.closed_trades
        gross = sum(trade.pnl for trade in closed)
        return "\n".join(
            [
                "=== backtest ===",
                f"  period          {self.equity_curve[0][0]} -> {self.equity_curve[-1][0]}"
                if self.equity_curve
                else "  period          (none)",
                f"  starting equity {self.starting_equity:.2f}",
                f"  final equity    {self.final_equity:.2f}",
                f"  total return    {self.total_return_pct:+.2f}%",
                f"  CAGR            {self.cagr_pct:+.2f}%",
                f"  max drawdown    {self.max_drawdown_pct:.2f}%",
                f"  closed trades   {len(closed)}",
                f"  win rate        {self.win_rate_pct:.1f}%",
                f"  net P/L         {gross:+.2f}  (after {self.cost_bps:.1f}bps per fill)",
            ]
        )


def run_backtest(
    bars_by_symbol: dict[str, Sequence[Bar]],
    strategy: Strategy,
    *,
    starting_equity: float = 50.0,
    max_positions: int = 2,
    risk_per_trade_pct: float = 1.5,
    max_order_notional: float = 15.0,
    min_order_notional: float = 2.0,
    cost_bps: float = 5.0,
) -> BacktestResult:
    symbols = sorted(bars_by_symbol)
    if not symbols:
        raise ValueError("no symbols to backtest")

    # Trade only on days every symbol has a bar for; a missing bar means a
    # signal computed on stale data.
    common_days = set.intersection(
        *({bar.day for bar in bars_by_symbol[symbol]} for symbol in symbols)
    )
    timeline = sorted(common_days)
    if len(timeline) <= strategy.warmup + 2:
        raise ValueError(
            f"need more than {strategy.warmup + 2} common bars, got {len(timeline)}"
        )

    by_day: dict[str, dict[date, Bar]] = {
        symbol: {bar.day: bar for bar in bars_by_symbol[symbol]} for symbol in symbols
    }
    history: dict[str, list[Bar]] = {symbol: [] for symbol in symbols}

    cash = starting_equity
    open_trades: dict[str, Trade] = {}
    result = BacktestResult(starting_equity=starting_equity, final_equity=starting_equity, cost_bps=cost_bps)
    cost = cost_bps / 10_000.0
    pending: list[tuple[str, str, float]] = []  # (symbol, side, notional)

    for index, day in enumerate(timeline):
        for symbol in symbols:
            history[symbol].append(by_day[symbol][day])

        # --- fill yesterday's decisions at today's open --------------------
        for symbol, side, notional in pending:
            open_price = by_day[symbol][day].open
            if open_price <= 0:
                continue
            if side == "buy":
                fill = open_price * (1 + cost)
                spend = min(notional, cash)
                if spend < min_order_notional:
                    continue
                qty = spend / fill
                cash -= spend
                trade = Trade(symbol=symbol, entry_day=day, entry_price=fill, qty=qty)
                open_trades[symbol] = trade
                result.trades.append(trade)
            else:
                trade = open_trades.pop(symbol, None)
                if trade is None:
                    continue
                fill = open_price * (1 - cost)
                cash += trade.qty * fill
                trade.exit_day = day
                trade.exit_price = fill
        pending = []

        # --- mark to market -------------------------------------------------
        market_value = sum(
            trade.qty * by_day[trade.symbol][day].close for trade in open_trades.values()
        )
        equity = cash + market_value
        result.equity_curve.append((day, equity))

        if index < strategy.warmup or index == len(timeline) - 1:
            continue

        # --- decide, to be executed at tomorrow's open ----------------------
        signals = [
            strategy.evaluate(history[symbol], held=symbol in open_trades)
            for symbol in symbols
        ]

        for signal in signals:
            if signal.action == EXIT and signal.symbol in open_trades:
                pending.append((signal.symbol, "sell", 0.0))

        exiting = {symbol for symbol, side, _ in pending if side == "sell"}
        slots = max_positions - (len(open_trades) - len(exiting))
        candidates = sorted(
            (s for s in signals if s.action == ENTER and s.symbol not in open_trades),
            key=lambda s: s.score,
            reverse=True,
        )
        for signal in candidates[: max(slots, 0)]:
            budget = max_order_notional
            if signal.stop_price and 0 < signal.stop_price < signal.price:
                stop_fraction = (signal.price - signal.stop_price) / signal.price
                budget = min(budget, equity * risk_per_trade_pct / 100.0 / stop_fraction)
            notional = min(budget, cash, max_order_notional)
            if notional >= min_order_notional:
                pending.append((signal.symbol, "buy", notional))

    last_day = timeline[-1]
    result.final_equity = cash + sum(
        trade.qty * by_day[trade.symbol][last_day].close for trade in open_trades.values()
    )
    return result
