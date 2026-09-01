"""Configuration, loaded from the environment (and optionally a .env file).

Every money limit lives here so that a reader can audit the agent's blast
radius in one place.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


class ConfigError(Exception):
    """Raised when configuration is missing or internally inconsistent."""


def load_dotenv(path: str | Path = ".env") -> None:
    """Populate os.environ from a .env file. Existing env vars win."""
    p = Path(path)
    if not p.is_file():
        return
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _str(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _float(name: str, default: float) -> float:
    raw = _str(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number, got {raw!r}") from exc


def _int(name: str, default: int) -> int:
    return int(_float(name, default))


def _list(name: str, default: str) -> list[str]:
    raw = _str(name, default)
    return [item.strip().upper() for item in raw.split(",") if item.strip()]


# The exact phrase a human must type into LIVE_CONFIRM to arm real-money mode.
LIVE_CONFIRM_PHRASE = "I ACCEPT REAL MONEY LOSS"


@dataclass(frozen=True)
class Limits:
    """Hard money limits. The risk engine treats these as inviolable."""

    max_deployed: float = 50.0
    max_order_notional: float = 15.0
    min_order_notional: float = 2.0
    daily_loss_limit_pct: float = 4.0
    max_drawdown_pct: float = 25.0
    max_orders_per_day: int = 6
    max_day_trades: int = 2
    max_positions: int = 2
    # Fraction of equity risked per trade, measured to the stop price.
    risk_per_trade_pct: float = 1.5

    def validate(self) -> None:
        if self.min_order_notional < 1.0:
            raise ConfigError("MIN_ORDER_NOTIONAL must be at least 1.00")
        if self.max_order_notional < self.min_order_notional:
            raise ConfigError("MAX_ORDER_NOTIONAL must be >= MIN_ORDER_NOTIONAL")
        if self.max_deployed < self.max_order_notional:
            raise ConfigError("MAX_DEPLOYED must be >= MAX_ORDER_NOTIONAL")
        for name in ("daily_loss_limit_pct", "max_drawdown_pct"):
            value = getattr(self, name)
            if not 0 < value <= 100:
                raise ConfigError(f"{name} must be in (0, 100], got {value}")
        if self.max_positions < 1:
            raise ConfigError("MAX_POSITIONS must be >= 1")
        if not 0 < self.risk_per_trade_pct <= 100:
            raise ConfigError(
                f"risk_per_trade_pct must be in (0, 100], got {self.risk_per_trade_pct}"
            )


@dataclass(frozen=True)
class Config:
    broker: str = "alpaca"
    alpaca_env: str = "paper"
    alpaca_key_id: str = ""
    alpaca_secret_key: str = ""
    alpaca_data_feed: str = "iex"
    strategy: str = "trend"
    universe: list[str] = field(default_factory=lambda: ["SPY"])
    limits: Limits = field(default_factory=Limits)
    live_confirm: str = ""
    halt_file: str = "./HALT"
    db_path: str = "./agent.db"

    @property
    def is_live(self) -> bool:
        """True only when real-money mode is both selected and explicitly armed."""
        return self.alpaca_env == "live" and self.live_confirm == LIVE_CONFIRM_PHRASE

    @property
    def live_requested_but_unarmed(self) -> bool:
        return self.alpaca_env == "live" and not self.is_live

    @property
    def trading_base_url(self) -> str:
        if self.alpaca_env == "live":
            return "https://api.alpaca.markets"
        return "https://paper-api.alpaca.markets"

    @property
    def data_base_url(self) -> str:
        return "https://data.alpaca.markets"


def load(dotenv_path: str | Path = ".env") -> Config:
    """Build a validated Config from the environment."""
    load_dotenv(dotenv_path)

    limits = Limits(
        max_deployed=_float("MAX_DEPLOYED", 50.0),
        max_order_notional=_float("MAX_ORDER_NOTIONAL", 15.0),
        min_order_notional=_float("MIN_ORDER_NOTIONAL", 2.0),
        daily_loss_limit_pct=_float("DAILY_LOSS_LIMIT_PCT", 4.0),
        max_drawdown_pct=_float("MAX_DRAWDOWN_PCT", 25.0),
        max_orders_per_day=_int("MAX_ORDERS_PER_DAY", 6),
        max_day_trades=_int("MAX_DAY_TRADES", 2),
        max_positions=_int("MAX_POSITIONS", 2),
        risk_per_trade_pct=_float("RISK_PER_TRADE_PCT", 1.5),
    )
    limits.validate()

    broker = _str("BROKER", "alpaca").lower()
    if broker not in {"alpaca", "sim"}:
        raise ConfigError(f"BROKER must be 'alpaca' or 'sim', got {broker!r}")

    alpaca_env = _str("ALPACA_ENV", "paper").lower()
    if alpaca_env not in {"paper", "live"}:
        raise ConfigError(f"ALPACA_ENV must be 'paper' or 'live', got {alpaca_env!r}")

    strategy = _str("STRATEGY", "trend").lower()
    if strategy not in {"trend", "meanrev"}:
        raise ConfigError(f"STRATEGY must be 'trend' or 'meanrev', got {strategy!r}")

    cfg = Config(
        broker=broker,
        alpaca_env=alpaca_env,
        alpaca_key_id=_str("ALPACA_KEY_ID"),
        alpaca_secret_key=_str("ALPACA_SECRET_KEY"),
        alpaca_data_feed=_str("ALPACA_DATA_FEED", "iex").lower(),
        strategy=strategy,
        universe=_list("UNIVERSE", "SPY,QQQ,IWM"),
        limits=limits,
        live_confirm=_str("LIVE_CONFIRM"),
        halt_file=_str("HALT_FILE", "./HALT"),
        db_path=_str("DB_PATH", "./agent.db"),
    )

    if cfg.broker == "alpaca" and not (cfg.alpaca_key_id and cfg.alpaca_secret_key):
        raise ConfigError(
            "ALPACA_KEY_ID and ALPACA_SECRET_KEY are required when BROKER=alpaca. "
            "Copy .env.example to .env and fill them in."
        )
    if not cfg.universe:
        raise ConfigError("UNIVERSE must list at least one symbol")

    return cfg
