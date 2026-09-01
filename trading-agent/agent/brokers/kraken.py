"""Kraken spot adapter (EUR-native).

Chosen for a small Irish account because all three costs stay small: no FX on
a EUR balance, ~€1 to withdraw over SEPA, and 0.25–0.40% per fill. Payward
Europe Solutions Ltd is MiCA/CASP licensed by the Central Bank of Ireland.

Two things differ structurally from an equities broker, and both are handled
here rather than leaked into the engine:

  * **There is no paper mode.** Connecting means real money. `config.py`
    therefore treats BROKER=kraken as real money unconditionally.
  * **Spot crypto has no "position" object.** A holding is just a balance, and
    Kraken does not track cost basis for it. Average entry is reconstructed
    from trade history for display; the authoritative entry price for risk
    purposes is the one `protection.StopBook` recorded when the agent bought.

Minimum order sizes are per-pair and are enforced before anything is sent —
at €50 an order below `ordermin` is the most likely rejection, so it is
checked locally rather than discovered from an error.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import math
import time
import urllib.parse
from datetime import datetime, timezone
from typing import Any

import requests

from ..config import Config
from .base import Account, Bar, BrokerError, Order, Position

_BASE = "https://api.kraken.com"
_MAX_ATTEMPTS = 4
_TIMEOUT = 25
# Balances worth less than this in quote currency are exchange dust, not a
# position — trying to sell them produces nothing but rejected orders.
_DUST_QUOTE_VALUE = 0.50


def _num(value: Any, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _floor_to(value: float, decimals: int) -> float:
    """Round *down*, so a computed size can never exceed available funds."""
    factor = 10**decimals
    return math.floor(value * factor) / factor


class KrakenBroker:
    """Implements `base.Broker` against Kraken's spot REST API."""

    def __init__(self, cfg: Config, session: requests.Session | None = None) -> None:
        self._cfg = cfg
        self._session = session or requests.Session()
        self._session.headers.update({"User-Agent": "autonomous-trading-agent/0.1"})
        self.name = "kraken:live"
        self.quote = cfg.quote_currency.upper()
        self._pairs: dict[str, dict] | None = None
        self._nonce = int(time.time() * 1000)
        self._trades_cache: dict[str, list[dict]] | None = None

    # -- plumbing ----------------------------------------------------------

    def _next_nonce(self) -> int:
        # Kraken requires a strictly increasing nonce per key.
        self._nonce = max(self._nonce + 1, int(time.time() * 1000))
        return self._nonce

    def _sign(self, path: str, data: dict[str, Any]) -> str:
        post = urllib.parse.urlencode(data)
        encoded = (str(data["nonce"]) + post).encode()
        message = path.encode() + hashlib.sha256(encoded).digest()
        try:
            secret = base64.b64decode(self._cfg.kraken_secret)
        except Exception as exc:  # malformed key material
            raise BrokerError(
                "KRAKEN_SECRET is not valid base64 — copy it exactly as shown when created"
            ) from exc
        signature = hmac.new(secret, message, hashlib.sha512)
        return base64.b64encode(signature.digest()).decode()

    def _call(self, path: str, data: dict[str, Any] | None = None, *, private: bool = False) -> Any:
        url = f"{_BASE}{path}"
        last_error = ""

        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                if private:
                    body = dict(data or {})
                    body["nonce"] = self._next_nonce()
                    headers = {
                        "API-Key": self._cfg.kraken_key,
                        "API-Sign": self._sign(path, body),
                        "Content-Type": "application/x-www-form-urlencoded",
                    }
                    response = self._session.post(
                        url, data=body, headers=headers, timeout=_TIMEOUT
                    )
                else:
                    response = self._session.get(url, params=data or {}, timeout=_TIMEOUT)
            except requests.RequestException as exc:
                last_error = f"network error: {exc}"
                if attempt == _MAX_ATTEMPTS:
                    break
                time.sleep(2**attempt)
                continue

            if response.status_code in {429, 500, 502, 503, 504} and attempt < _MAX_ATTEMPTS:
                time.sleep(2**attempt)
                continue
            if not response.ok:
                raise BrokerError(f"{path} -> {response.status_code}: {response.text[:300]}")

            try:
                payload = response.json()
            except ValueError as exc:
                raise BrokerError(f"{path}: malformed response") from exc

            errors = payload.get("error") or []
            if errors:
                joined = "; ".join(str(item) for item in errors)
                # Rate limiting is transient; everything else is not.
                if "Rate limit" in joined and attempt < _MAX_ATTEMPTS:
                    time.sleep(2**attempt)
                    continue
                if "Invalid key" in joined or "Permission denied" in joined:
                    raise BrokerError(
                        f"Kraken rejected the credentials ({joined}). Check KRAKEN_KEY / "
                        "KRAKEN_SECRET and that the key has the required permissions."
                    )
                raise BrokerError(f"{path}: {joined}")
            return payload.get("result", {})

        raise BrokerError(f"{path} failed after {_MAX_ATTEMPTS} attempts: {last_error}")

    # -- pair metadata -----------------------------------------------------

    def _load_pairs(self) -> dict[str, dict]:
        if self._pairs is not None:
            return self._pairs
        result = self._call("/0/public/AssetPairs")
        lookup: dict[str, dict] = {}
        for key, meta in result.items():
            meta = dict(meta)
            meta["_key"] = key
            for alias in (key, meta.get("altname"), meta.get("wsname")):
                if alias:
                    lookup[alias.upper().replace("/", "")] = meta
        self._pairs = lookup
        return lookup

    def _pair(self, symbol: str) -> dict:
        key = symbol.upper().replace("/", "")
        pairs = self._load_pairs()
        if key not in pairs:
            raise BrokerError(
                f"unknown Kraken pair {symbol!r}. Use an altname such as XBTEUR or ETHEUR."
            )
        return pairs[key]

    def pair_limits(self, symbol: str) -> tuple[float, float]:
        """(minimum order size in base units, minimum order cost in quote)."""
        meta = self._pair(symbol)
        return _num(meta.get("ordermin")), _num(meta.get("costmin"))

    def is_fractionable(self, symbol: str) -> bool:
        # Crypto is divisible; what actually binds is `ordermin`, checked at
        # order time and surfaced by preflight.
        self._pair(symbol)
        return True

    # -- market data -------------------------------------------------------

    def get_daily_bars(self, symbol: str, limit: int) -> list[Bar]:
        meta = self._pair(symbol)
        result = self._call(
            "/0/public/OHLC", {"pair": meta["_key"], "interval": 1440}
        )
        rows = next((v for k, v in result.items() if k != "last"), [])
        bars: list[Bar] = []
        for row in rows:
            # [time, open, high, low, close, vwap, volume, count]
            bars.append(
                Bar(
                    symbol=symbol.upper(),
                    day=datetime.fromtimestamp(int(row[0]), tz=timezone.utc).date(),
                    open=_num(row[1]),
                    high=_num(row[2]),
                    low=_num(row[3]),
                    close=_num(row[4]),
                    volume=_num(row[6]),
                )
            )
        bars.sort(key=lambda bar: bar.day)
        return bars[-limit:]

    def latest_price(self, symbol: str) -> float:
        meta = self._pair(symbol)
        result = self._call("/0/public/Ticker", {"pair": meta["_key"]})
        ticker = next(iter(result.values()), {})
        # "c" is [last trade price, lot volume].
        price = _num((ticker.get("c") or [0])[0])
        if price <= 0:
            raise BrokerError(f"no price available for {symbol}")
        return price

    def is_market_open(self) -> bool:
        """Crypto trades continuously; what matters is whether Kraken is up."""
        try:
            status = self._call("/0/public/SystemStatus")
        except BrokerError:
            return False
        return str(status.get("status", "")).lower() == "online"

    # -- account -----------------------------------------------------------

    def _balances(self) -> dict[str, float]:
        raw = self._call("/0/private/Balance", private=True) or {}
        return {asset: _num(amount) for asset, amount in raw.items()}

    def get_account(self) -> Account:
        quote_asset = f"Z{self.quote}" if len(self.quote) == 3 else self.quote
        try:
            trade_balance = self._call(
                "/0/private/TradeBalance", {"asset": quote_asset}, private=True
            )
            equity = _num(trade_balance.get("eb"))
        except BrokerError:
            equity = 0.0

        balances = self._balances()
        cash = balances.get(quote_asset, balances.get(self.quote, 0.0))
        if equity <= 0:
            equity = cash + self._holdings_value(balances)

        return Account(
            account_id="kraken",
            currency=self.quote,
            cash=cash,
            equity=equity,
            buying_power=cash,
            # Spot crypto has no pattern-day-trader rule and no margin here.
            day_trade_count=0,
            pattern_day_trader=False,
            trading_blocked=False,
            status="ACTIVE",
        )

    def _holdings_value(self, balances: dict[str, float]) -> float:
        total = 0.0
        for symbol in self._cfg.universe:
            try:
                meta = self._pair(symbol)
            except BrokerError:
                continue
            qty = balances.get(meta.get("base", ""), 0.0)
            if qty <= 0:
                continue
            try:
                total += qty * self.latest_price(symbol)
            except BrokerError:
                continue
        return total

    def get_positions(self) -> list[Position]:
        balances = self._balances()
        positions: list[Position] = []
        for symbol in self._cfg.universe:
            try:
                meta = self._pair(symbol)
            except BrokerError:
                continue
            qty = balances.get(meta.get("base", ""), 0.0)
            if qty <= 0:
                continue
            try:
                price = self.latest_price(symbol)
            except BrokerError:
                continue
            value = qty * price
            if value < _DUST_QUOTE_VALUE:
                continue
            avg_entry = self._average_entry(symbol, qty)
            positions.append(
                Position(
                    symbol=symbol.upper(),
                    qty=qty,
                    avg_entry_price=avg_entry,
                    market_value=round(value, 2),
                    unrealized_pl=round(value - avg_entry * qty, 2) if avg_entry else 0.0,
                )
            )
        return positions

    def _average_entry(self, symbol: str, held_qty: float) -> float:
        """Reconstruct average cost from trade history.

        Display only. The stop book is the authority on entry price, so a
        failure here degrades the report rather than the risk logic.
        """
        try:
            if self._trades_cache is None:
                result = self._call("/0/private/TradesHistory", private=True) or {}
                trades: dict[str, list[dict]] = {}
                for trade in (result.get("trades") or {}).values():
                    trades.setdefault(str(trade.get("pair", "")).upper(), []).append(trade)
                for entries in trades.values():
                    entries.sort(key=lambda item: _num(item.get("time")), reverse=True)
                self._trades_cache = trades
        except BrokerError:
            self._trades_cache = {}

        meta = self._pair(symbol)
        candidates = (self._trades_cache or {}).get(str(meta["_key"]).upper(), [])
        remaining, cost = held_qty, 0.0
        for trade in candidates:
            if str(trade.get("type")) != "buy" or remaining <= 0:
                continue
            volume = _num(trade.get("vol"))
            used = min(volume, remaining)
            cost += used * _num(trade.get("price"))
            remaining -= used
        filled = held_qty - remaining
        return round(cost / filled, 8) if filled > 0 else 0.0

    # -- orders ------------------------------------------------------------

    def _volume_for(self, symbol: str, notional: float, price: float) -> float:
        meta = self._pair(symbol)
        decimals = int(_num(meta.get("lot_decimals"), 8))
        volume = _floor_to(notional / price, decimals)
        ordermin, costmin = self.pair_limits(symbol)
        if ordermin and volume < ordermin:
            raise BrokerError(
                f"{symbol}: size {volume:.10f} is below Kraken's minimum of {ordermin:g} "
                f"(needs about {ordermin * price:.2f} {self.quote} at {price:.2f})"
            )
        if costmin and volume * price < costmin:
            raise BrokerError(
                f"{symbol}: order value {volume * price:.2f} {self.quote} is below "
                f"Kraken's minimum of {costmin:g} {self.quote}"
            )
        if volume <= 0:
            raise BrokerError(f"{symbol}: computed a zero order size")
        return volume

    def submit_order(
        self,
        symbol: str,
        side: str,
        *,
        notional: float | None = None,
        qty: float | None = None,
        validate: bool = False,
    ) -> Order:
        if (notional is None) == (qty is None):
            raise BrokerError("submit_order needs exactly one of notional or qty")
        if side not in {"buy", "sell"}:
            raise BrokerError(f"side must be buy or sell, got {side!r}")

        meta = self._pair(symbol)
        price = self.latest_price(symbol)
        if qty is not None:
            volume = _floor_to(qty, int(_num(meta.get("lot_decimals"), 8)))
        else:
            volume = self._volume_for(symbol, notional or 0.0, price)

        body: dict[str, Any] = {
            "pair": meta["_key"],
            "type": side,
            "ordertype": "market",
            "volume": f"{volume:.10f}".rstrip("0").rstrip("."),
        }
        if validate:
            body["validate"] = "true"

        result = self._call("/0/private/AddOrder", body, private=True)
        txids = result.get("txid") or []
        return Order(
            order_id=str(txids[0]) if txids else "",
            symbol=symbol.upper(),
            side=side,
            notional=notional,
            qty=volume,
            status="validated" if validate else "submitted",
            submitted_at=datetime.now(timezone.utc),
            filled_avg_price=price,
        )

    def submit_stop_order(self, symbol: str, qty: float, stop_price: float) -> Order:
        if qty <= 0:
            raise BrokerError(f"cannot place a stop for non-positive qty {qty}")
        if stop_price <= 0:
            raise BrokerError(f"invalid stop price {stop_price}")

        meta = self._pair(symbol)
        volume = _floor_to(qty, int(_num(meta.get("lot_decimals"), 8)))
        ordermin, _costmin = self.pair_limits(symbol)
        if ordermin and volume < ordermin:
            raise BrokerError(
                f"{symbol}: cannot rest a stop for {volume:.10f}, below the "
                f"{ordermin:g} minimum"
            )
        # Floor rather than round: a protective stop must never end up
        # *higher* than the price the risk layer computed, or noise could
        # trigger it early. Rounding down costs at most one tick.
        price_decimals = int(_num(meta.get("pair_decimals"), 2))
        trigger = _floor_to(stop_price, price_decimals)
        body = {
            "pair": meta["_key"],
            "type": "sell",
            "ordertype": "stop-loss",
            "price": f"{trigger:.{price_decimals}f}",
            "volume": f"{volume:.10f}".rstrip("0").rstrip("."),
        }
        result = self._call("/0/private/AddOrder", body, private=True)
        txids = result.get("txid") or []
        return Order(
            order_id=str(txids[0]) if txids else "",
            symbol=symbol.upper(),
            side="sell",
            notional=None,
            qty=volume,
            status="open",
            submitted_at=datetime.now(timezone.utc),
            order_type="stop",
            stop_price=trigger,
        )

    def list_open_orders(self, symbol: str | None = None) -> list[Order]:
        result = self._call("/0/private/OpenOrders", private=True) or {}
        wanted = self._pair(symbol)["_key"] if symbol else None

        orders: list[Order] = []
        for txid, raw in (result.get("open") or {}).items():
            description = raw.get("descr") or {}
            pair_name = str(description.get("pair", "")).upper().replace("/", "")
            if wanted:
                try:
                    if self._pair(pair_name)["_key"] != wanted:
                        continue
                except BrokerError:
                    continue
            ordertype = str(description.get("ordertype", "market"))
            orders.append(
                Order(
                    order_id=str(txid),
                    symbol=(symbol or pair_name).upper(),
                    side=str(description.get("type", "")),
                    notional=None,
                    qty=_num(raw.get("vol")),
                    status=str(raw.get("status", "open")),
                    order_type="stop" if "stop" in ordertype else ordertype,
                    stop_price=_num(description.get("price")) or None,
                )
            )
        return orders

    def cancel_order(self, order_id: str) -> None:
        try:
            self._call("/0/private/CancelOrder", {"txid": order_id}, private=True)
        except BrokerError as exc:
            # Already gone is the outcome we wanted.
            if "Unknown order" in str(exc) or "Invalid order" in str(exc):
                return
            raise

    def cancel_orders_for(self, symbol: str) -> int:
        cancelled = 0
        for order in self.list_open_orders(symbol):
            self.cancel_order(order.order_id)
            cancelled += 1
        return cancelled

    def close_position(self, symbol: str) -> Order:
        # A resting stop reserves the balance; clear it before selling.
        self.cancel_orders_for(symbol)
        meta = self._pair(symbol)
        qty = self._balances().get(meta.get("base", ""), 0.0)
        if qty <= 0:
            raise BrokerError(f"no balance in {symbol} to sell")
        return self.submit_order(symbol, "sell", qty=qty)
