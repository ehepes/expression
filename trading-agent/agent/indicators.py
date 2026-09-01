"""Small, dependency-free technical indicators over lists of floats.

All functions return a value for the *last* bar, or None when there is not
enough history. Returning None rather than a partial value is deliberate:
a strategy must never act on a half-warmed indicator.
"""

from __future__ import annotations

from collections.abc import Sequence

from .brokers.base import Bar


def sma(values: Sequence[float], window: int) -> float | None:
    if window <= 0 or len(values) < window:
        return None
    return sum(values[-window:]) / window


def stdev(values: Sequence[float], window: int) -> float | None:
    if window < 2 or len(values) < window:
        return None
    window_values = values[-window:]
    mean = sum(window_values) / window
    variance = sum((v - mean) ** 2 for v in window_values) / (window - 1)
    return variance**0.5


def true_ranges(bars: Sequence[Bar]) -> list[float]:
    """Wilder's true range, one value per bar after the first."""
    out: list[float] = []
    for previous, current in zip(bars, bars[1:]):
        out.append(
            max(
                current.high - current.low,
                abs(current.high - previous.close),
                abs(current.low - previous.close),
            )
        )
    return out


def atr(bars: Sequence[Bar], window: int = 14) -> float | None:
    """Average true range — the agent's unit of volatility for sizing/stops."""
    ranges = true_ranges(bars)
    if len(ranges) < window:
        return None
    return sum(ranges[-window:]) / window


def rsi(values: Sequence[float], window: int = 14) -> float | None:
    """Wilder-smoothed RSI on closing prices."""
    if len(values) < window + 1:
        return None
    gains: list[float] = []
    losses: list[float] = []
    for previous, current in zip(values, values[1:]):
        change = current - previous
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))

    avg_gain = sum(gains[:window]) / window
    avg_loss = sum(losses[:window]) / window
    for gain, loss in zip(gains[window:], losses[window:]):
        avg_gain = (avg_gain * (window - 1) + gain) / window
        avg_loss = (avg_loss * (window - 1) + loss) / window

    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def closes(bars: Sequence[Bar]) -> list[float]:
    return [bar.close for bar in bars]
