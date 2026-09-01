"""Alpaca adapter, written directly against the REST API.

No vendor SDK on purpose: the surface we need is ~6 endpoints, and a thin
adapter is easier to audit than a dependency you have to trust.

Paper and live share this code path; only the base URL and the API keys
differ. That is deliberate — it means the strategy you validate on paper is
byte-for-byte the strategy that later trades real money.
"""

from __future__ import annotations

import time
from datetime import date, datetime, timedelta, timezone
from typing import Any

import requests

from ..config import Config
from .base import Account, Bar, BrokerError, Order, Position

_RETRY_STATUSES = {429, 500, 502, 503, 504}
_MAX_ATTEMPTS = 4
_TIMEOUT = 20


def _parse_ts(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _num(value: Any, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class AlpacaBroker:
    """Implements `base.Broker` against Alpaca's trading and data APIs."""

    def __init__(self, cfg: Config, session: requests.Session | None = None) -> None:
        self._cfg = cfg
        self._session = session or requests.Session()
        self._session.headers.update(
            {
                "APCA-API-KEY-ID": cfg.alpaca_key_id,
                "APCA-API-SECRET-KEY": cfg.alpaca_secret_key,
                "accept": "application/json",
            }
        )
        self.name = f"alpaca:{cfg.alpaca_env}"

    # -- plumbing ----------------------------------------------------------

    def _request(self, method: str, url: str, **kwargs: Any) -> Any:
        last_error: str = ""
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                response = self._session.request(
                    method, url, timeout=_TIMEOUT, **kwargs
                )
            except requests.RequestException as exc:
                last_error = f"network error: {exc}"
                if attempt == _MAX_ATTEMPTS:
                    break
                time.sleep(2**attempt)
                continue

            if response.status_code in _RETRY_STATUSES and attempt < _MAX_ATTEMPTS:
                time.sleep(2**attempt)
                continue

            if response.status_code == 401:
                raise BrokerError(
                    "Alpaca rejected the API key (401). Check that ALPACA_KEY_ID / "
                    f"ALPACA_SECRET_KEY are the *{self._cfg.alpaca_env}* pair."
                )
            if response.status_code == 403:
                raise BrokerError(
                    f"Alpaca refused the request (403): {response.text[:300]}"
                )
            if not response.ok:
                raise BrokerError(
                    f"{method} {url} -> {response.status_code}: {response.text[:300]}"
                )
            if not response.content:
                return None
            return response.json()

        raise BrokerError(f"{method} {url} failed after {_MAX_ATTEMPTS} attempts: {last_error}")

    def _trading(self, method: str, path: str, **kwargs: Any) -> Any:
        return self._request(method, f"{self._cfg.trading_base_url}{path}", **kwargs)

    def _data(self, method: str, path: str, **kwargs: Any) -> Any:
        return self._request(method, f"{self._cfg.data_base_url}{path}", **kwargs)

    # -- account -----------------------------------------------------------

    def get_account(self) -> Account:
        raw = self._trading("GET", "/v2/account")
        return Account(
            account_id=str(raw.get("account_number", "")),
            currency=str(raw.get("currency", "USD")),
            cash=_num(raw.get("cash")),
            equity=_num(raw.get("equity")),
            buying_power=_num(raw.get("buying_power")),
            day_trade_count=int(_num(raw.get("daytrade_count"))),
            pattern_day_trader=bool(raw.get("pattern_day_trader", False)),
            trading_blocked=bool(raw.get("trading_blocked", False))
            or bool(raw.get("account_blocked", False)),
            status=str(raw.get("status", "UNKNOWN")),
        )

    def get_positions(self) -> list[Position]:
        raw = self._trading("GET", "/v2/positions") or []
        return [
            Position(
                symbol=str(item["symbol"]).upper(),
                qty=_num(item.get("qty")),
                avg_entry_price=_num(item.get("avg_entry_price")),
                market_value=_num(item.get("market_value")),
                unrealized_pl=_num(item.get("unrealized_pl")),
            )
            for item in raw
        ]

    def is_market_open(self) -> bool:
        raw = self._trading("GET", "/v2/clock")
        return bool(raw.get("is_open", False))

    def is_fractionable(self, symbol: str) -> bool:
        """Fractional support decides whether a €50 account can hold the name."""
        raw = self._trading("GET", f"/v2/assets/{symbol.upper()}")
        return bool(raw.get("fractionable", False)) and bool(raw.get("tradable", False))

    # -- market data -------------------------------------------------------

    def get_daily_bars(self, symbol: str, limit: int) -> list[Bar]:
        # Ask for a generous calendar window: `limit` *trading* days needs
        # roughly 1.5x that in calendar days, plus slack for holidays.
        lookback_days = int(limit * 1.6) + 10
        start = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).date()
        params = {
            "symbols": symbol.upper(),
            "timeframe": "1Day",
            "start": start.isoformat(),
            "limit": max(limit, 1) * 2,
            "adjustment": "all",
            "feed": self._cfg.alpaca_data_feed,
            "sort": "asc",
        }
        payload = self._data("GET", "/v2/stocks/bars", params=params)
        rows = (payload.get("bars") or {}).get(symbol.upper()) or []

        bars: list[Bar] = []
        for row in rows:
            stamp = _parse_ts(row.get("t"))
            if stamp is None:
                continue
            bars.append(
                Bar(
                    symbol=symbol.upper(),
                    day=stamp.date(),
                    open=_num(row.get("o")),
                    high=_num(row.get("h")),
                    low=_num(row.get("l")),
                    close=_num(row.get("c")),
                    volume=_num(row.get("v")),
                )
            )
        bars.sort(key=lambda bar: bar.day)
        return bars[-limit:]

    def latest_price(self, symbol: str) -> float:
        """Most recent trade price, falling back to the last daily close."""
        try:
            payload = self._data(
                "GET",
                f"/v2/stocks/{symbol.upper()}/trades/latest",
                params={"feed": self._cfg.alpaca_data_feed},
            )
            price = _num((payload.get("trade") or {}).get("p"))
            if price > 0:
                return price
        except BrokerError:
            pass
        bars = self.get_daily_bars(symbol, 1)
        if not bars:
            raise BrokerError(f"no price available for {symbol}")
        return bars[-1].close

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
        if side not in {"buy", "sell"}:
            raise BrokerError(f"side must be buy or sell, got {side!r}")

        body: dict[str, Any] = {
            "symbol": symbol.upper(),
            "side": side,
            "type": "market",
            # `day` rather than `gtc`: an order that did not fill today is a
            # decision made on stale information, so let it expire.
            "time_in_force": "day",
        }
        if notional is not None:
            body["notional"] = f"{notional:.2f}"
        else:
            body["qty"] = f"{qty:.9f}".rstrip("0").rstrip(".")

        raw = self._trading("POST", "/v2/orders", json=body)
        return self._to_order(raw, fallback_symbol=symbol, fallback_side=side)

    def _to_order(
        self, raw: dict, *, fallback_symbol: str = "", fallback_side: str = ""
    ) -> Order:
        return Order(
            order_id=str(raw.get("id", "")),
            symbol=str(raw.get("symbol") or fallback_symbol).upper(),
            side=str(raw.get("side") or fallback_side),
            notional=_num(raw.get("notional"), 0.0) or None,
            qty=_num(raw.get("qty"), 0.0) or None,
            status=str(raw.get("status", "unknown")),
            submitted_at=_parse_ts(raw.get("submitted_at")),
            filled_avg_price=_num(raw.get("filled_avg_price"), 0.0) or None,
            order_type=str(raw.get("type") or raw.get("order_type") or "market"),
            stop_price=_num(raw.get("stop_price"), 0.0) or None,
        )

    def list_open_orders(self, symbol: str | None = None) -> list[Order]:
        params: dict[str, Any] = {"status": "open", "limit": 100, "nested": "false"}
        if symbol:
            params["symbols"] = symbol.upper()
        raw = self._trading("GET", "/v2/orders", params=params) or []
        return [self._to_order(item) for item in raw]

    def cancel_order(self, order_id: str) -> None:
        """Cancel a working order.

        A 404/422 means the order already filled or was cancelled — that is the
        outcome we wanted, so it is not an error.
        """
        url = f"{self._cfg.trading_base_url}/v2/orders/{order_id}"
        try:
            self._request("DELETE", url)
        except BrokerError as exc:
            message = str(exc)
            if "404" in message or "422" in message:
                return
            raise

    def submit_stop_order(self, symbol: str, qty: float, stop_price: float) -> Order:
        """Rest a protective sell stop.

        Alpaca supports fractional stop orders, but only with
        `time_in_force=day` — so the order dies at the close and the agent
        re-arms it on the next cycle. It therefore protects during sessions,
        not across overnight gaps.
        """
        if qty <= 0:
            raise BrokerError(f"cannot place a stop for non-positive qty {qty}")
        if stop_price <= 0:
            raise BrokerError(f"invalid stop price {stop_price}")

        body = {
            "symbol": symbol.upper(),
            "side": "sell",
            "type": "stop",
            "time_in_force": "day",
            "qty": f"{qty:.9f}".rstrip("0").rstrip("."),
            "stop_price": f"{stop_price:.2f}",
        }
        raw = self._trading("POST", "/v2/orders", json=body)
        return self._to_order(raw, fallback_symbol=symbol, fallback_side="sell")

    def close_position(self, symbol: str) -> Order:
        # A resting sell order reserves the shares, so a close would be
        # rejected for insufficient quantity. Clear the way first.
        self.cancel_orders_for(symbol)
        raw = self._trading("DELETE", f"/v2/positions/{symbol.upper()}") or {}
        return self._to_order(raw, fallback_symbol=symbol, fallback_side="sell")

    def cancel_orders_for(self, symbol: str) -> int:
        """Cancel every working order on `symbol`. Returns how many were cancelled."""
        cancelled = 0
        for order in self.list_open_orders(symbol):
            self.cancel_order(order.order_id)
            cancelled += 1
        return cancelled
