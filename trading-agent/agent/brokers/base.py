"""Broker-neutral domain types and the interface every adapter implements.

Keeping this surface small is what makes the agent portable: swapping Alpaca
for another venue means writing one new file, not touching the engine.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol, Sequence


class BrokerError(Exception):
    """Any failure talking to the venue, including rejected orders."""


@dataclass(frozen=True)
class Account:
    """A point-in-time snapshot of the trading account."""

    account_id: str
    currency: str
    cash: float
    equity: float
    buying_power: float
    # Rolling count of day trades in the last 5 business days (US PDT rule).
    day_trade_count: int = 0
    pattern_day_trader: bool = False
    trading_blocked: bool = False
    status: str = "ACTIVE"

    @property
    def tradable(self) -> bool:
        return not self.trading_blocked and self.status.upper() == "ACTIVE"


@dataclass(frozen=True)
class Position:
    symbol: str
    qty: float
    avg_entry_price: float
    market_value: float
    unrealized_pl: float

    @property
    def is_long(self) -> bool:
        return self.qty > 0


@dataclass(frozen=True)
class Order:
    order_id: str
    symbol: str
    side: str  # "buy" | "sell"
    notional: float | None
    qty: float | None
    status: str
    submitted_at: datetime | None = None
    filled_avg_price: float | None = None
    order_type: str = "market"
    stop_price: float | None = None

    @property
    def is_protective(self) -> bool:
        """A resting sell stop the agent placed to guard an open position."""
        return self.side == "sell" and self.order_type in {"stop", "stop_limit"}


@dataclass(frozen=True)
class Bar:
    """One OHLCV candle."""

    symbol: str
    day: date
    open: float
    high: float
    low: float
    close: float
    volume: float


class Broker(Protocol):
    """The whole contract between the engine and a trading venue."""

    name: str

    def get_account(self) -> Account:
        """Cash, equity and trading eligibility."""

    def get_positions(self) -> list[Position]:
        """Currently open positions."""

    def is_market_open(self) -> bool:
        """True when the venue is accepting orders right now."""

    def get_daily_bars(self, symbol: str, limit: int) -> list[Bar]:
        """Most recent `limit` daily bars, oldest first."""

    def submit_order(
        self,
        symbol: str,
        side: str,
        *,
        notional: float | None = None,
        qty: float | None = None,
    ) -> Order:
        """Place a market, day-length order. Exactly one of notional/qty."""

    def close_position(self, symbol: str) -> Order:
        """Liquidate the whole position in `symbol`."""

    def latest_price(self, symbol: str) -> float:
        """Most recent traded price."""

    def list_open_orders(self, symbol: str | None = None) -> list[Order]:
        """Orders still working at the venue."""

    def cancel_order(self, order_id: str) -> None:
        """Cancel a working order. Must not raise if it already filled."""

    def submit_stop_order(self, symbol: str, qty: float, stop_price: float) -> Order:
        """Rest a protective sell stop against an open position."""


def latest_close(bars: Sequence[Bar]) -> float:
    if not bars:
        raise BrokerError("no bars available")
    return bars[-1].close
