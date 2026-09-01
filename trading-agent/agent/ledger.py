"""SQLite decision journal.

Every signal, every refusal and every order goes in here. An autonomous agent
that spends your money without leaving an auditable trail is not something you
should run, so the journal is not optional — the engine writes to it before it
is allowed to trade.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,
    mode        TEXT NOT NULL,
    broker      TEXT NOT NULL,
    strategy    TEXT NOT NULL,
    equity      REAL,
    cash        REAL,
    note        TEXT
);

CREATE TABLE IF NOT EXISTS decisions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id       INTEGER NOT NULL,
    ts           TEXT NOT NULL,
    symbol       TEXT NOT NULL,
    action       TEXT NOT NULL,
    reason       TEXT,
    score        REAL,
    price        REAL,
    executed     INTEGER NOT NULL DEFAULT 0,
    block_reason TEXT,
    FOREIGN KEY (run_id) REFERENCES runs (id)
);

CREATE TABLE IF NOT EXISTS orders (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          INTEGER NOT NULL,
    ts              TEXT NOT NULL,
    day             TEXT NOT NULL,
    broker_order_id TEXT,
    symbol          TEXT NOT NULL,
    side            TEXT NOT NULL,
    notional        REAL,
    qty             REAL,
    status          TEXT,
    fill_price      REAL,
    FOREIGN KEY (run_id) REFERENCES runs (id)
);

CREATE TABLE IF NOT EXISTS equity_curve (
    ts     TEXT PRIMARY KEY,
    day    TEXT NOT NULL,
    equity REAL NOT NULL,
    cash   REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS state (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_orders_day ON orders (day);
CREATE INDEX IF NOT EXISTS idx_equity_day ON equity_curve (day);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


@dataclass
class Ledger:
    """Thin wrapper over a SQLite file. Safe to open per-run."""

    path: str = "./agent.db"

    def __post_init__(self) -> None:
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "Ledger":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- runs --------------------------------------------------------------

    def start_run(
        self, *, mode: str, broker: str, strategy: str, equity: float, cash: float, note: str = ""
    ) -> int:
        cursor = self._conn.execute(
            "INSERT INTO runs (ts, mode, broker, strategy, equity, cash, note)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (_now(), mode, broker, strategy, equity, cash, note),
        )
        self._conn.commit()
        return int(cursor.lastrowid)

    # -- decisions ---------------------------------------------------------

    def record_decision(
        self,
        run_id: int,
        *,
        symbol: str,
        action: str,
        reason: str,
        score: float = 0.0,
        price: float = 0.0,
        executed: bool = False,
        block_reason: str | None = None,
    ) -> None:
        self._conn.execute(
            "INSERT INTO decisions (run_id, ts, symbol, action, reason, score, price,"
            " executed, block_reason) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (run_id, _now(), symbol, action, reason, score, price, int(executed), block_reason),
        )
        self._conn.commit()

    # -- orders ------------------------------------------------------------

    def record_order(
        self,
        run_id: int,
        *,
        broker_order_id: str,
        symbol: str,
        side: str,
        notional: float | None,
        qty: float | None,
        status: str,
        fill_price: float | None,
    ) -> None:
        self._conn.execute(
            "INSERT INTO orders (run_id, ts, day, broker_order_id, symbol, side,"
            " notional, qty, status, fill_price) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (run_id, _now(), _today(), broker_order_id, symbol, side, notional, qty, status, fill_price),
        )
        self._conn.commit()

    def orders_today(self) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM orders WHERE day = ?", (_today(),)
        ).fetchone()
        return int(row["n"])

    def recent_orders(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM orders ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(row) for row in rows]

    def bought_today(self, symbol: str) -> bool:
        """Used to avoid selling something bought the same session (day trade)."""
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM orders WHERE day = ? AND symbol = ? AND side = 'buy'",
            (_today(), symbol.upper()),
        ).fetchone()
        return int(row["n"]) > 0

    # -- equity ------------------------------------------------------------

    def record_equity(self, equity: float, cash: float) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO equity_curve (ts, day, equity, cash) VALUES (?, ?, ?, ?)",
            (_now(), _today(), equity, cash),
        )
        self._conn.commit()

    def first_equity_today(self) -> float | None:
        row = self._conn.execute(
            "SELECT equity FROM equity_curve WHERE day = ? ORDER BY ts ASC LIMIT 1",
            (_today(),),
        ).fetchone()
        return float(row["equity"]) if row else None

    def equity_history(self, limit: int = 200) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM equity_curve ORDER BY ts DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(row) for row in reversed(rows)]

    # -- key/value state ---------------------------------------------------

    def get_state(self, key: str, default: Any = None) -> Any:
        row = self._conn.execute("SELECT value FROM state WHERE key = ?", (key,)).fetchone()
        if row is None:
            return default
        try:
            return json.loads(row["value"])
        except json.JSONDecodeError:
            return row["value"]

    def set_state(self, key: str, value: Any) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO state (key, value) VALUES (?, ?)",
            (key, json.dumps(value)),
        )
        self._conn.commit()

    def high_water_mark(self, current_equity: float) -> float:
        """Running peak equity, used for the permanent drawdown kill switch."""
        peak = float(self.get_state("high_water_mark", 0.0) or 0.0)
        if current_equity > peak:
            peak = current_equity
            self.set_state("high_water_mark", peak)
        return peak
