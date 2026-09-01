"""A fully offline broker simulator.

Purpose: let the whole pipeline — strategy, risk, ledger, CLI — be exercised
with no credentials, no network and no money. Prices are a deterministic
seeded random walk, so runs are reproducible.
"""

from __future__ import annotations

import hashlib
import random
from datetime import date, datetime, timedelta, timezone

from ..config import Config
from .base import Account, Bar, BrokerError, Order, Position

_SEED_BASE = 20260901
_TRADING_DAYS = 500


def _seed_for(symbol: str) -> int:
    digest = hashlib.sha256(symbol.upper().encode()).hexdigest()[:8]
    return _SEED_BASE + int(digest, 16)


def synthetic_bars(symbol: str, limit: int, *, end: date | None = None) -> list[Bar]:
    """Deterministic daily bars for `symbol`, oldest first."""
    rng = random.Random(_seed_for(symbol))
    end = end or datetime.now(timezone.utc).date()

    price = rng.uniform(40.0, 400.0)
    drift = rng.uniform(-0.0002, 0.0006)
    vol = rng.uniform(0.008, 0.018)

    bars: list[Bar] = []
    day = end - timedelta(days=int(_TRADING_DAYS * 1.45))
    while len(bars) < _TRADING_DAYS and day <= end:
        if day.weekday() < 5:  # skip weekends
            shock = rng.gauss(drift, vol)
            open_ = price
            price = max(1.0, price * (1.0 + shock))
            high = max(open_, price) * (1 + abs(rng.gauss(0, vol / 3)))
            low = min(open_, price) * (1 - abs(rng.gauss(0, vol / 3)))
            bars.append(
                Bar(
                    symbol=symbol.upper(),
                    day=day,
                    open=round(open_, 4),
                    high=round(high, 4),
                    low=round(low, 4),
                    close=round(price, 4),
                    volume=round(rng.uniform(1e6, 5e7), 0),
                )
            )
        day += timedelta(days=1)
    return bars[-limit:]


class SimBroker:
    """In-memory paper account. State lives only for the life of the process."""

    def __init__(self, cfg: Config, starting_cash: float | None = None) -> None:
        self._cfg = cfg
        self.name = "sim"
        self.cash = (
            starting_cash if starting_cash is not None else cfg.limits.max_deployed
        )
        self._positions: dict[str, list[float]] = {}  # symbol -> [qty, cost_basis]
        self.orders: list[Order] = []
        self.market_open = True
        self._bar_cache: dict[str, list[Bar]] = {}

    # -- data --------------------------------------------------------------

    def get_daily_bars(self, symbol: str, limit: int) -> list[Bar]:
        key = symbol.upper()
        if key not in self._bar_cache:
            self._bar_cache[key] = synthetic_bars(key, _TRADING_DAYS)
        return self._bar_cache[key][-limit:]

    def latest_price(self, symbol: str) -> float:
        bars = self.get_daily_bars(symbol, 1)
        if not bars:
            raise BrokerError(f"no price for {symbol}")
        return bars[-1].close

    def is_market_open(self) -> bool:
        return self.market_open

    def is_fractionable(self, symbol: str) -> bool:
        return True

    # -- account -----------------------------------------------------------

    def _market_value(self) -> float:
        return sum(
            qty * self.latest_price(symbol)
            for symbol, (qty, _cost) in self._positions.items()
            if qty
        )

    def get_account(self) -> Account:
        equity = self.cash + self._market_value()
        return Account(
            account_id="SIM-0001",
            currency="USD",
            cash=round(self.cash, 2),
            equity=round(equity, 2),
            buying_power=round(self.cash, 2),
            day_trade_count=0,
            pattern_day_trader=False,
            trading_blocked=False,
            status="ACTIVE",
        )

    def get_positions(self) -> list[Position]:
        out: list[Position] = []
        for symbol, (qty, cost) in self._positions.items():
            if qty <= 0:
                continue
            price = self.latest_price(symbol)
            out.append(
                Position(
                    symbol=symbol,
                    qty=round(qty, 9),
                    avg_entry_price=round(cost / qty, 4) if qty else 0.0,
                    market_value=round(qty * price, 2),
                    unrealized_pl=round(qty * price - cost, 2),
                )
            )
        return out

    # -- orders ------------------------------------------------------------

    def submit_order(
        self,
        symbol: str,
        side: str,
        *,
        notional: float | None = None,
        qty: float | None = None,
    ) -> Order:
        if (notional is None) == (qty is None):
            raise BrokerError("submit_order needs exactly one of notional or qty")
        key = symbol.upper()
        price = self.latest_price(key)
        held_qty, held_cost = self._positions.get(key, [0.0, 0.0])

        if side == "buy":
            spend = notional if notional is not None else (qty or 0.0) * price
            if spend > self.cash + 1e-9:
                raise BrokerError(f"insufficient sim cash: need {spend:.2f}, have {self.cash:.2f}")
            filled_qty = spend / price
            self.cash -= spend
            self._positions[key] = [held_qty + filled_qty, held_cost + spend]
        elif side == "sell":
            sell_qty = qty if qty is not None else (notional or 0.0) / price
            sell_qty = min(sell_qty, held_qty)
            if sell_qty <= 0:
                raise BrokerError(f"no position in {key} to sell")
            proceeds = sell_qty * price
            self.cash += proceeds
            remaining = held_qty - sell_qty
            self._positions[key] = [
                remaining,
                held_cost * (remaining / held_qty) if held_qty else 0.0,
            ]
            filled_qty = sell_qty
        else:
            raise BrokerError(f"side must be buy or sell, got {side!r}")

        order = Order(
            order_id=f"sim-{len(self.orders) + 1}",
            symbol=key,
            side=side,
            notional=notional,
            qty=round(filled_qty, 9),
            status="filled",
            submitted_at=datetime.now(timezone.utc),
            filled_avg_price=price,
        )
        self.orders.append(order)
        return order

    def close_position(self, symbol: str) -> Order:
        key = symbol.upper()
        held_qty, _cost = self._positions.get(key, [0.0, 0.0])
        if held_qty <= 0:
            raise BrokerError(f"no position in {key}")
        return self.submit_order(key, "sell", qty=held_qty)
