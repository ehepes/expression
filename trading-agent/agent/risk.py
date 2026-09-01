"""The layer that is allowed to say no.

Design rule: the strategy proposes, the risk engine disposes. Nothing in this
file trusts the strategy, the market data, or the caller. Every limit is
checked immediately before an order, against a freshly fetched account — not
against cached state from earlier in the run.

The checks are ordered cheapest-and-most-fatal first, so a halted agent stops
before it spends a single API call on market data.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .brokers.base import Account, Position
from .config import LIVE_CONFIRM_PHRASE, Config
from .ledger import Ledger


@dataclass(frozen=True)
class Veto:
    """A refusal, with a human-readable reason and whether it is permanent."""

    code: str
    reason: str
    permanent: bool = False


@dataclass(frozen=True)
class Sizing:
    """An approved order size, or a veto explaining why there isn't one."""

    notional: float = 0.0
    veto: Veto | None = None

    @property
    def approved(self) -> bool:
        return self.veto is None and self.notional > 0


class RiskEngine:
    def __init__(self, cfg: Config, ledger: Ledger) -> None:
        self._cfg = cfg
        self._limits = cfg.limits
        self._ledger = ledger

    # -- global gates ------------------------------------------------------

    def preflight(self, account: Account) -> list[Veto]:
        """Checks that, if any fail, stop the entire run before any order."""
        vetoes: list[Veto] = []
        limits = self._limits

        halt = Path(self._cfg.halt_file)
        if halt.exists():
            vetoes.append(
                Veto("halt_file", f"halt file present at {halt} — remove it to resume", True)
            )

        if self._cfg.live_requested_but_unarmed:
            why = (
                "BROKER=kraken is always a real-money account (Kraken has no paper mode)"
                if self._cfg.broker == "kraken"
                else "ALPACA_ENV=live selects a real-money account"
            )
            vetoes.append(
                Veto(
                    "live_unarmed",
                    f"{why}, but LIVE_CONFIRM is not set to the exact phrase "
                    f"{LIVE_CONFIRM_PHRASE!r}. Refusing to trade real money.",
                    True,
                )
            )

        if not account.tradable:
            vetoes.append(
                Veto("account_blocked", f"broker reports account status={account.status}, trading_blocked={account.trading_blocked}", True)
            )

        if account.equity <= 0:
            vetoes.append(Veto("no_equity", "account equity is zero", True))
            return vetoes

        peak = self._ledger.high_water_mark(account.equity)
        if peak > 0:
            drawdown_pct = (peak - account.equity) / peak * 100
            if drawdown_pct >= limits.max_drawdown_pct:
                vetoes.append(
                    Veto(
                        "max_drawdown",
                        f"equity {account.equity:.2f} is {drawdown_pct:.1f}% below the "
                        f"peak of {peak:.2f} (limit {limits.max_drawdown_pct:.1f}%)",
                        True,
                    )
                )

        opening_equity = self._ledger.first_equity_today()
        if opening_equity and opening_equity > 0:
            day_loss_pct = (opening_equity - account.equity) / opening_equity * 100
            if day_loss_pct >= limits.daily_loss_limit_pct:
                vetoes.append(
                    Veto(
                        "daily_loss",
                        f"down {day_loss_pct:.1f}% today (limit "
                        f"{limits.daily_loss_limit_pct:.1f}%) — stopping until tomorrow",
                    )
                )

        if self._ledger.orders_today() >= limits.max_orders_per_day:
            vetoes.append(
                Veto("order_cap", f"already placed {limits.max_orders_per_day} orders today")
            )

        return vetoes

    # -- per-order gates ---------------------------------------------------

    def check_exit(self, symbol: str, account: Account) -> Veto | None:
        """Exits are almost always allowed — the exception is a day-trade trap."""
        if self._would_be_day_trade(symbol, account):
            return Veto(
                "day_trade",
                f"selling {symbol} today would be a day trade "
                f"({account.day_trade_count} used, limit {self._limits.max_day_trades}); "
                "holding to avoid a pattern-day-trader flag",
            )
        return None

    def size_entry(
        self,
        *,
        symbol: str,
        price: float,
        stop_price: float | None,
        account: Account,
        positions: Sequence[Position],
    ) -> Sizing:
        """Decide how much of `symbol` to buy, or refuse."""
        limits = self._limits

        if price <= 0:
            return Sizing(veto=Veto("bad_price", f"non-positive price for {symbol}"))

        if any(p.symbol == symbol and p.qty > 0 for p in positions):
            return Sizing(veto=Veto("already_held", f"already holding {symbol}"))

        open_positions = sum(1 for p in positions if p.qty > 0)
        if open_positions >= limits.max_positions:
            return Sizing(
                veto=Veto("max_positions", f"already holding {open_positions} positions (limit {limits.max_positions})")
            )

        deployed = sum(p.market_value for p in positions if p.qty > 0)
        deployable = limits.max_deployed - deployed
        if deployable < limits.min_order_notional:
            return Sizing(
                veto=Veto("deploy_cap", f"deployed {deployed:.2f} of {limits.max_deployed:.2f} cap; no room left")
            )

        # Risk-based sizing: lose at most risk_per_trade_pct of equity if the
        # stop is hit. Falls back to the hard per-order cap when no stop is
        # supplied, so a missing stop can never *increase* size.
        budget = limits.max_order_notional
        if stop_price and 0 < stop_price < price:
            stop_fraction = (price - stop_price) / price
            risk_amount = account.equity * limits.risk_per_trade_pct / 100.0
            budget = min(budget, risk_amount / stop_fraction)

        notional = min(budget, deployable, account.cash, limits.max_order_notional)
        notional = float(f"{notional:.2f}")

        if notional < limits.min_order_notional:
            return Sizing(
                veto=Veto(
                    "too_small",
                    f"sized order {notional:.2f} is below the {limits.min_order_notional:.2f} "
                    f"minimum (cash {account.cash:.2f}, room {deployable:.2f})",
                )
            )

        return Sizing(notional=notional)

    # -- helpers -----------------------------------------------------------

    def _would_be_day_trade(self, symbol: str, account: Account) -> bool:
        """True if selling now closes a position opened earlier the same day."""
        if not self._ledger.bought_today(symbol):
            return False
        return account.day_trade_count >= self._limits.max_day_trades
