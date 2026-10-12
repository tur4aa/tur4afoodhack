"""SQLite storage. One local file, WAL mode, explicit schema versioning."""
from __future__ import annotations

import json
import re
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

SCHEMA_VERSION = 2

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- amounts are stored in minor units (fils/cents) to avoid float errors
CREATE TABLE IF NOT EXISTS transactions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    uid           TEXT NOT NULL UNIQUE,
    type          TEXT NOT NULL CHECK (type IN ('expense','income','refund','transfer')),
    amount_minor  INTEGER NOT NULL CHECK (amount_minor > 0),
    currency      TEXT NOT NULL,
    category      TEXT NOT NULL,
    description   TEXT NOT NULL DEFAULT '',
    occurred_on   TEXT NOT NULL,            -- local date YYYY-MM-DD
    created_at    TEXT NOT NULL,            -- UTC 'YYYY-MM-DD HH:MM:SS'
    source_msg_id INTEGER
);
CREATE INDEX IF NOT EXISTS ix_tx_date ON transactions(occurred_on);

CREATE TABLE IF NOT EXISTS tasks (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    uid           TEXT NOT NULL UNIQUE,
    title         TEXT NOT NULL,
    norm_title    TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'new'
                  CHECK (status IN ('new','in_progress','waiting','done','cancelled')),
    due_date      TEXT,                     -- local date, NULL = no deadline
    due_at        TEXT,                     -- UTC datetime when a time was given
    is_deadline   INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    done_at       TEXT,
    source_msg_id INTEGER
);
CREATE INDEX IF NOT EXISTS ix_tasks_status ON tasks(status, due_date);

CREATE TABLE IF NOT EXISTS events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    uid           TEXT NOT NULL UNIQUE,
    title         TEXT NOT NULL,
    start_at      TEXT NOT NULL,            -- UTC
    end_at        TEXT,                     -- UTC, may be on the next day (night shifts)
    all_day       INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL,
    source_msg_id INTEGER
);
CREATE INDEX IF NOT EXISTS ix_events_start ON events(start_at);

CREATE TABLE IF NOT EXISTS reminders (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    uid           TEXT NOT NULL UNIQUE,
    task_id       INTEGER,
    event_id      INTEGER,
    text          TEXT NOT NULL,
    remind_at     TEXT NOT NULL,            -- UTC
    recurrence    TEXT CHECK (recurrence IN ('daily','weekly','monthly')),
    rec_day       INTEGER,                  -- day of month for monthly rules
    local_time    TEXT,                     -- 'HH:MM' local, keeps recurring time stable
    status        TEXT NOT NULL DEFAULT 'active'
                  CHECK (status IN ('active','fired','done','cancelled')),
    pending_ack   INTEGER NOT NULL DEFAULT 0,
    last_fired_at TEXT,
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_rem_due ON reminders(status, remind_at);

CREATE TABLE IF NOT EXISTS inbox (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    uid           TEXT NOT NULL UNIQUE,
    text          TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'new' CHECK (status IN ('new','processed','deleted')),
    error         TEXT,
    created_at    TEXT NOT NULL,
    source_msg_id INTEGER
);

CREATE TABLE IF NOT EXISTS notes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    uid        TEXT NOT NULL UNIQUE,
    text       TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- mandatory monthly payments (rent, internet, ...)
CREATE TABLE IF NOT EXISTS payments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    uid             TEXT NOT NULL UNIQUE,
    name            TEXT NOT NULL,
    amount_minor    INTEGER NOT NULL,
    currency        TEXT NOT NULL,
    day_of_month    INTEGER NOT NULL CHECK (day_of_month BETWEEN 1 AND 31),
    category        TEXT NOT NULL,
    last_paid_month TEXT,                   -- 'YYYY-MM'
    created_at      TEXT NOT NULL
);

-- money set aside for a goal; subtracted from the "until payday" budget
CREATE TABLE IF NOT EXISTS reserves (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    uid          TEXT NOT NULL UNIQUE,
    name         TEXT NOT NULL UNIQUE,
    amount_minor INTEGER NOT NULL,
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS category_limits (
    category     TEXT PRIMARY KEY,
    amount_minor INTEGER NOT NULL
);

-- learned "word -> category" pairs (from manual category fixes)
CREATE TABLE IF NOT EXISTS category_memory (
    keyword  TEXT PRIMARY KEY,
    category TEXT NOT NULL,
    hits     INTEGER NOT NULL DEFAULT 1
);

-- every user-visible change, for /undo
CREATE TABLE IF NOT EXISTS actions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at    TEXT NOT NULL,
    description   TEXT NOT NULL,
    payload       TEXT NOT NULL,
    source_msg_id INTEGER,
    undone        INTEGER NOT NULL DEFAULT 0
);

-- Telegram message ids already handled (protects against re-delivery)
CREATE TABLE IF NOT EXISTS processed_messages (
    message_id INTEGER PRIMARY KEY,
    created_at TEXT NOT NULL
);

-- exchange rates: units of `code` per 1 USD (manual entries beat downloaded ones on the same day)
CREATE TABLE IF NOT EXISTS rates (
    code       TEXT NOT NULL,
    day        TEXT NOT NULL,
    source     TEXT NOT NULL,          -- 'api' | 'manual'
    per_usd    REAL NOT NULL CHECK (per_usd > 0),
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (code, day, source)
);

-- savings, brokerage, deposits, crypto wallets, other assets (car, gold...)
CREATE TABLE IF NOT EXISTS accounts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    uid        TEXT NOT NULL UNIQUE,
    name       TEXT NOT NULL UNIQUE,
    kind       TEXT NOT NULL CHECK (kind IN ('savings','broker','deposit','crypto','asset','other')),
    currency   TEXT NOT NULL,
    rate_pct   REAL,                   -- deposit interest, % per year (estimate only)
    created_at TEXT NOT NULL
);

-- every movement of money/assets outside everyday spending
CREATE TABLE IF NOT EXISTS moves (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    uid           TEXT NOT NULL UNIQUE,
    kind          TEXT NOT NULL CHECK (kind IN
                  ('exchange','deposit','withdraw','buy','sell','dividend','interest','fee','value')),
    account_id    INTEGER,             -- NULL for wallet currency exchange
    from_currency TEXT,
    from_minor    INTEGER,
    to_currency   TEXT,
    to_minor      INTEGER,
    symbol        TEXT,                -- AAPL, BTC, ...
    qty           REAL,
    occurred_on   TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    source_msg_id INTEGER,
    note          TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_moves_acc ON moves(account_id);

CREATE TABLE IF NOT EXISTS prices (
    symbol     TEXT NOT NULL,
    day        TEXT NOT NULL,
    price      REAL NOT NULL CHECK (price > 0),
    currency   TEXT NOT NULL,
    source     TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (symbol, day)
);

-- daily net worth history (in USD) for the capital chart
CREATE TABLE IF NOT EXISTS networth (
    day    TEXT PRIMARY KEY,
    usd    REAL NOT NULL,
    detail TEXT NOT NULL DEFAULT '{}'
);

-- short-lived state: pending questions, awaited input
CREATE TABLE IF NOT EXISTS kv (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    expires_at TEXT
);
"""

ALLOWED_TABLES = {
    "transactions", "tasks", "events", "reminders", "inbox", "notes",
    "payments", "reserves", "category_limits", "category_memory", "settings",
    "accounts", "moves", "rates", "prices", "networth",
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


def fmt_utc(dt: datetime) -> str:
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def parse_utc(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)


def new_uid() -> str:
    return uuid.uuid4().hex


class DB:
    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        self._depth = 0
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute("PRAGMA busy_timeout=5000")
        self.migrate()

    def migrate(self) -> None:
        with self.tx():
            for stmt in re.sub(r"--[^\n]*", "", SCHEMA).split(";"):
                if stmt.strip():
                    self.conn.execute(stmt)
            row = self.conn.execute("PRAGMA user_version").fetchone()
            if row[0] < SCHEMA_VERSION:
                self.conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        """Atomic block; nested calls join the outer transaction."""
        with self.lock:
            outer = self._depth == 0
            if outer:
                self.conn.execute("BEGIN IMMEDIATE")
            self._depth += 1
            try:
                yield self.conn
            except BaseException:
                self._depth -= 1
                if outer:
                    self.conn.execute("ROLLBACK")
                raise
            else:
                self._depth -= 1
                if outer:
                    self.conn.execute("COMMIT")

    # -- generic helpers
    def all(self, sql: str, params: tuple | list = ()) -> list[sqlite3.Row]:
        with self.lock:
            return self.conn.execute(sql, params).fetchall()

    def one(self, sql: str, params: tuple | list = ()) -> sqlite3.Row | None:
        with self.lock:
            return self.conn.execute(sql, params).fetchone()

    def scalar(self, sql: str, params: tuple | list = ()) -> Any:
        row = self.one(sql, params)
        return None if row is None else row[0]

    def execute(self, sql: str, params: tuple | list = ()) -> sqlite3.Cursor:
        with self.lock:
            return self.conn.execute(sql, params)

    def insert(self, table: str, values: dict[str, Any]) -> int:
        assert table in ALLOWED_TABLES, table
        cols = ", ".join(values)
        marks = ", ".join("?" for _ in values)
        cur = self.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", list(values.values()))
        return int(cur.lastrowid)

    def update(self, table: str, row_id: int, values: dict[str, Any]) -> None:
        assert table in ALLOWED_TABLES, table
        sets = ", ".join(f"{k} = ?" for k in values)
        self.execute(f"UPDATE {table} SET {sets} WHERE id = ?", [*values.values(), row_id])

    def get(self, table: str, row_id: int) -> dict | None:
        assert table in ALLOWED_TABLES, table
        row = self.one(f"SELECT * FROM {table} WHERE id = ?", (row_id,))
        return dict(row) if row else None

    # -- settings
    def get_setting(self, key: str, default: str | None = None) -> str | None:
        v = self.scalar("SELECT value FROM settings WHERE key = ?", (key,))
        return default if v is None else v

    def set_setting(self, key: str, value: Any) -> None:
        self.execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, str(value)),
        )

    def del_setting(self, key: str) -> None:
        self.execute("DELETE FROM settings WHERE key = ?", (key,))

    # -- kv with expiry
    def kv_set(self, key: str, value: Any, expires_at: datetime | None = None) -> None:
        self.execute(
            "INSERT INTO kv(key, value, expires_at) VALUES(?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, expires_at = excluded.expires_at",
            (key, json.dumps(value, ensure_ascii=False), fmt_utc(expires_at) if expires_at else None),
        )

    def kv_get(self, key: str, now: datetime | None = None) -> Any:
        row = self.one("SELECT value, expires_at FROM kv WHERE key = ?", (key,))
        if not row:
            return None
        if row["expires_at"] and now is not None and fmt_utc(now) > row["expires_at"]:
            self.kv_del(key)
            return None
        return json.loads(row["value"])

    def kv_del(self, key: str) -> None:
        self.execute("DELETE FROM kv WHERE key = ?", (key,))

    def close(self) -> None:
        with self.lock:
            self.conn.close()
