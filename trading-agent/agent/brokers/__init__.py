"""Broker adapters. Everything above this layer speaks only `base.Broker`."""

from __future__ import annotations

from ..config import Config
from .base import Account, Bar, Broker, BrokerError, Order, Position


def build(cfg: Config) -> Broker:
    """Instantiate the broker adapter named by the config."""
    if cfg.broker == "alpaca":
        from .alpaca import AlpacaBroker

        return AlpacaBroker(cfg)
    if cfg.broker == "sim":
        from .sim import SimBroker

        return SimBroker(cfg)
    raise BrokerError(f"unknown broker {cfg.broker!r}")


__all__ = [
    "Account",
    "Bar",
    "Broker",
    "BrokerError",
    "Order",
    "Position",
    "build",
]
