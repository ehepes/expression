"""Signal generation.

Two strategies ship here, both long-only and both low-turnover. That is not
timidity, it is arithmetic: on a very small account every round trip pays a
spread, so any edge has to survive costs. A strategy that trades ten times a
day cannot.

A strategy's only job is to say *what looks attractive*. It never decides how
much to buy — that is `risk.py` — and it never talks to a broker.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .brokers.base import Bar
from .indicators import atr, closes, rsi, sma

ENTER = "enter"
EXIT = "exit"
HOLD = "hold"


@dataclass(frozen=True)
class Signal:
    symbol: str
    action: str  # ENTER | EXIT | HOLD
    score: float  # higher = ranked first among entry candidates
    reason: str
    price: float
    stop_price: float | None = None


class Strategy:
    """Base class. Subclasses implement `evaluate`."""

    name = "base"
    # How many daily bars the strategy needs before it will emit anything.
    warmup = 200

    def evaluate(self, bars: Sequence[Bar], *, held: bool) -> Signal:
        raise NotImplementedError


class TrendStrategy(Strategy):
    """Dual moving-average trend following with a long-term regime filter.

    Enter when the fast average is above the slow average *and* price is above
    its 200-day average. Exit on the reverse cross, a regime break, or an
    ATR-based trailing stop. This is the classic, heavily-documented trend
    template — chosen because it is transparent and rarely trades, not because
    it is clever.
    """

    name = "trend"

    def __init__(
        self,
        fast: int = 20,
        slow: int = 100,
        regime: int = 200,
        atr_window: int = 14,
        atr_stop_multiple: float = 2.5,
    ) -> None:
        self.fast = fast
        self.slow = slow
        self.regime = regime
        self.atr_window = atr_window
        self.atr_stop_multiple = atr_stop_multiple
        self.warmup = regime + 5

    def evaluate(self, bars: Sequence[Bar], *, held: bool) -> Signal:
        symbol = bars[-1].symbol if bars else "?"
        if len(bars) < self.warmup:
            return Signal(symbol, HOLD, 0.0, f"warming up ({len(bars)}/{self.warmup} bars)", 0.0)

        price_series = closes(bars)
        price = price_series[-1]
        fast_ma = sma(price_series, self.fast)
        slow_ma = sma(price_series, self.slow)
        regime_ma = sma(price_series, self.regime)
        volatility = atr(bars, self.atr_window)

        if None in (fast_ma, slow_ma, regime_ma) or not volatility:
            return Signal(symbol, HOLD, 0.0, "indicators unavailable", price)

        uptrend = fast_ma > slow_ma
        in_regime = price > regime_ma
        stop_price = price - self.atr_stop_multiple * volatility

        if held:
            if not uptrend:
                return Signal(symbol, EXIT, 0.0, f"MA{self.fast} crossed below MA{self.slow}", price, stop_price)
            if not in_regime:
                return Signal(symbol, EXIT, 0.0, f"price below MA{self.regime} (regime break)", price, stop_price)
            return Signal(symbol, HOLD, 0.0, "trend intact", price, stop_price)

        if uptrend and in_regime:
            # Rank candidates by how far price sits above its slow average,
            # normalised by volatility so a calm name is not outranked purely
            # for being jumpy.
            score = (price - slow_ma) / volatility
            return Signal(symbol, ENTER, score, f"MA{self.fast}>MA{self.slow} and price>MA{self.regime}", price, stop_price)

        why = "no MA cross" if not uptrend else f"below MA{self.regime}"
        return Signal(symbol, HOLD, 0.0, why, price, stop_price)


class MeanReversionStrategy(Strategy):
    """Buy short-term weakness inside a long-term uptrend.

    Only ever buys dips in names already above their 200-day average, and
    exits on a bounce. Higher turnover than trend following, so it is the
    second choice on a small account.
    """

    name = "meanrev"

    def __init__(
        self,
        rsi_window: int = 2,
        entry_rsi: float = 10.0,
        exit_rsi: float = 65.0,
        regime: int = 200,
        exit_ma: int = 10,
        atr_window: int = 14,
        atr_stop_multiple: float = 3.0,
    ) -> None:
        self.rsi_window = rsi_window
        self.entry_rsi = entry_rsi
        self.exit_rsi = exit_rsi
        self.regime = regime
        self.exit_ma = exit_ma
        self.atr_window = atr_window
        self.atr_stop_multiple = atr_stop_multiple
        self.warmup = regime + 5

    def evaluate(self, bars: Sequence[Bar], *, held: bool) -> Signal:
        symbol = bars[-1].symbol if bars else "?"
        if len(bars) < self.warmup:
            return Signal(symbol, HOLD, 0.0, f"warming up ({len(bars)}/{self.warmup} bars)", 0.0)

        price_series = closes(bars)
        price = price_series[-1]
        regime_ma = sma(price_series, self.regime)
        exit_ma = sma(price_series, self.exit_ma)
        strength = rsi(price_series, self.rsi_window)
        volatility = atr(bars, self.atr_window)

        if None in (regime_ma, exit_ma, strength) or not volatility:
            return Signal(symbol, HOLD, 0.0, "indicators unavailable", price)

        stop_price = price - self.atr_stop_multiple * volatility
        in_regime = price > regime_ma

        if held:
            if strength >= self.exit_rsi:
                return Signal(symbol, EXIT, 0.0, f"RSI{self.rsi_window} {strength:.0f} >= {self.exit_rsi:.0f}", price, stop_price)
            if price > exit_ma:
                return Signal(symbol, EXIT, 0.0, f"price recovered above MA{self.exit_ma}", price, stop_price)
            if not in_regime:
                return Signal(symbol, EXIT, 0.0, f"price below MA{self.regime} (regime break)", price, stop_price)
            return Signal(symbol, HOLD, 0.0, f"waiting for bounce (RSI {strength:.0f})", price, stop_price)

        if in_regime and strength <= self.entry_rsi:
            # The more oversold, the higher the rank.
            return Signal(symbol, ENTER, self.entry_rsi - strength, f"RSI{self.rsi_window} {strength:.0f} <= {self.entry_rsi:.0f} in uptrend", price, stop_price)

        why = f"RSI {strength:.0f} not oversold" if in_regime else f"below MA{self.regime}"
        return Signal(symbol, HOLD, 0.0, why, price, stop_price)


def build(name: str) -> Strategy:
    if name == "trend":
        return TrendStrategy()
    if name == "meanrev":
        return MeanReversionStrategy()
    raise ValueError(f"unknown strategy {name!r}")
