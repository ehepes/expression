"""Stop-loss bookkeeping.

The strategies compute an ATR stop on every bar, but a stop that is only ever
*recomputed* is not a stop — it drifts down with the price and never fires.
This module makes it real:

  * the stop is recorded when the position opens and persisted in the ledger,
  * it ratchets **up** only, following the high-water price, never down,
  * a breach is a risk-level exit that overrides whatever the strategy thinks.

It is deliberately separate from `strategy.py`. A strategy is allowed to be
wrong; the stop is what limits how expensive being wrong gets.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from .ledger import Ledger

_STATE_KEY = "stops"


@dataclass
class StopState:
    symbol: str
    entry_price: float
    stop_price: float
    high_water: float
    # Stop distance as a fraction of price, captured at entry. This is what
    # makes the stop *trail*: without it the stop can only follow the daily
    # bars, so a position that runs up intraday keeps its original stop.
    trail_fraction: float = 0.0

    def breached(self, price: float) -> bool:
        return price > 0 and price <= self.stop_price

    @property
    def distance_pct(self) -> float:
        if self.high_water <= 0:
            return 0.0
        return (self.high_water - self.stop_price) / self.high_water * 100


class StopBook:
    """Per-symbol stop state, persisted across runs via the ledger."""

    def __init__(self, ledger: Ledger) -> None:
        self._ledger = ledger

    # -- persistence -------------------------------------------------------

    def _load(self) -> dict[str, dict]:
        raw = self._ledger.get_state(_STATE_KEY, {}) or {}
        return raw if isinstance(raw, dict) else {}

    def _save(self, book: dict[str, dict]) -> None:
        self._ledger.set_state(_STATE_KEY, book)

    def get(self, symbol: str) -> StopState | None:
        entry = self._load().get(symbol.upper())
        return StopState(**entry) if entry else None

    def all(self) -> dict[str, StopState]:
        return {key: StopState(**value) for key, value in self._load().items()}

    # -- lifecycle ---------------------------------------------------------

    def open_position(self, symbol: str, entry_price: float, stop_price: float) -> StopState:
        """Record the stop for a newly opened position."""
        symbol = symbol.upper()
        trail = (entry_price - stop_price) / entry_price if entry_price > 0 else 0.0
        state = StopState(
            symbol=symbol,
            entry_price=entry_price,
            stop_price=stop_price,
            high_water=entry_price,
            trail_fraction=max(trail, 0.0),
        )
        book = self._load()
        book[symbol] = asdict(state)
        self._save(book)
        return state

    def close(self, symbol: str) -> None:
        book = self._load()
        if book.pop(symbol.upper(), None) is not None:
            self._save(book)

    def sync(self, held_symbols: set[str]) -> None:
        """Drop stops for positions that no longer exist.

        Guards against a stale stop firing against a position that was closed
        manually, or outside the agent entirely.
        """
        held = {symbol.upper() for symbol in held_symbols}
        book = self._load()
        pruned = {key: value for key, value in book.items() if key in held}
        if pruned != book:
            self._save(pruned)

    # -- the ratchet -------------------------------------------------------

    def update(
        self,
        symbol: str,
        price: float,
        candidate_stop: float | None,
        *,
        entry_price: float | None = None,
    ) -> StopState | None:
        """Advance the trailing stop for `symbol`, never loosening it.

        `candidate_stop` is the strategy's freshly computed ATR stop. It is
        adopted only when it is *higher* than the stop already on file — a
        falling market must never be allowed to widen the stop.

        Adopts an untracked position (opened manually, or before this feature
        existed) rather than leaving it unprotected.
        """
        symbol = symbol.upper()
        book = self._load()
        entry = book.get(symbol)

        if entry is None:
            if price <= 0:
                return None
            base = candidate_stop if candidate_stop and candidate_stop < price else price * 0.9
            state = StopState(
                symbol=symbol,
                entry_price=entry_price or price,
                stop_price=base,
                high_water=price,
                trail_fraction=max((price - base) / price, 0.0) if price > 0 else 0.0,
            )
        else:
            state = StopState(**entry)
            if price > state.high_water:
                state.high_water = price

            # Two independent candidates; take whichever is highest, and only
            # if it is higher than the stop already on file. The stop is a
            # ratchet — it moves up or it stays put, never down.
            candidates = [state.stop_price]
            if state.trail_fraction > 0 and state.high_water > 0:
                candidates.append(state.high_water * (1 - state.trail_fraction))
            if candidate_stop:
                candidates.append(candidate_stop)

            best = max(candidates)
            # Never place the stop at or above the current price; that would
            # fire instantly and turn a stop into a market sell.
            if best > state.stop_price and best < price:
                state.stop_price = best

        book[symbol] = asdict(state)
        self._save(book)
        return state
