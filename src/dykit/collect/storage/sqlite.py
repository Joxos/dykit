"""SQLite run-file storage handler.

One database file per collection run. Each file carries the full run history
(``danmaku`` rows) plus run metadata (``meta`` table: room, started_at,
ended_at, messages). A file whose ``meta`` lacks ``ended_at`` is an
interrupted run (process killed) - downtime is visible at a glance.

The handler refuses to overwrite an existing file: run files are immutable
history, and each run must get its own file.

Example:
    from dykit import SQLiteStorage

    async with SQLiteStorage("run.db", room_id="6657") as storage:
        await storage.save(message)
    # run.db now contains danmaku rows + meta (room/started_at/ended_at/messages)
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import sqlite3
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from ...schema import SCHEMA_SQL, columns_sql, format_timestamp
from ..types import DanmuMessage
from .base import StorageHandler

DEFAULT_BATCH_SIZE = 100
# Upper bound on what a killed process can lose: everything still in the
# in-memory buffer. Measured to cost nothing between 2.0s and 0.05s, so it is
# kept small on purpose.
DEFAULT_FLUSH_INTERVAL_SECONDS = 0.2

# Raw payload keys whose value is already stored in a dedicated column.
# These are stripped from raw_data at write time (deduplication); the column
# plus raw_data together remain the complete original payload.
_EXTRACTED_KEYS: frozenset[str] = frozenset(
    {
        "type",  # -> msg_type
        "rid",  # -> room_id
        "uid",  # -> user_id
        "nn",  # -> username
        "txt",  # -> content
        "level",  # -> user_level
        "col",  # -> color
        "color",  # -> color
        "ic",  # -> avatar_url
        "av",  # -> avatar_url
        "bl",  # -> badge_level
        "bnn",  # -> badge_name
        "brid",  # -> badge_room_id
        "nl",  # -> noble_level
        "gfid",  # -> gift_id
        "gfcnt",  # -> gift_count
        "gfn",  # -> gift_name
        "gftype",  # -> gift_name
        "hits",  # -> gift_hits
        "receive_uid",  # -> gift_receiver_uid
        "receive_nn",  # -> gift_receiver_name
        "ct",  # -> client_type
    }
)


def _leftover_raw_data(message: DanmuMessage) -> str | None:
    """Serialize raw_data minus the fields already stored as columns."""
    if message.raw_data is None:
        return None
    leftover = {key: value for key, value in message.raw_data.items() if key not in _EXTRACTED_KEYS}
    if not leftover:
        return None
    return json.dumps(leftover, ensure_ascii=False)


def _timestamp(message: DanmuMessage) -> str:
    return format_timestamp(message.timestamp)


def _msg_type(message: DanmuMessage) -> str:
    return message.msg_type.value


def _raw_data(message: DanmuMessage) -> str | None:
    return _leftover_raw_data(message)


def _attribute(name: str) -> Callable[[DanmuMessage], Any]:
    def read(message: DanmuMessage) -> Any:
        return getattr(message, name)

    return read


# Column -> value source, in INSERT order. This is the only ordered column
# list in the writer; the table itself is defined by `dykit.schema` and the
# reader projects the same columns (`tests/test_schema_contract.py` pins the
# two together). Adding a column means adding one entry here.
_ROW_FIELDS: dict[str, Callable[[DanmuMessage], Any]] = {
    "timestamp": _timestamp,
    "room_id": _attribute("room_id"),
    "msg_type": _msg_type,
    "user_id": _attribute("user_id"),
    "username": _attribute("username"),
    "user_level": _attribute("user_level"),
    "avatar_url": _attribute("avatar_url"),
    "color": _attribute("color"),
    "content": _attribute("content"),
    "badge_level": _attribute("badge_level"),
    "badge_name": _attribute("badge_name"),
    "badge_room_id": _attribute("badge_room_id"),
    "gift_id": _attribute("gift_id"),
    "gift_count": _attribute("gift_count"),
    "gift_name": _attribute("gift_name"),
    "gift_hits": _attribute("gift_hits"),
    "gift_receiver_uid": _attribute("gift_receiver_uid"),
    "gift_receiver_name": _attribute("gift_receiver_name"),
    "noble_level": _attribute("noble_level"),
    "client_type": _attribute("client_type"),
    "raw_data": _raw_data,
}

_INSERT_COLUMNS = tuple(_ROW_FIELDS)

#: Columns written per message, in INSERT order. Public so tests and callers
#: can assert the writer and the reader (``dykit.stats``) agree on the column set.
ROW_COLUMNS: tuple[str, ...] = _INSERT_COLUMNS

INSERT_DANMAKU_SQL = (
    f"INSERT INTO danmaku ({columns_sql(_INSERT_COLUMNS)}) "
    f"VALUES ({', '.join('?' * len(_INSERT_COLUMNS))})"
)


def _message_row(message: DanmuMessage) -> tuple[Any, ...]:
    return tuple(read(message) for read in _ROW_FIELDS.values())


class SQLiteStorage(StorageHandler):
    """SQLite run-file storage with buffered commits.

    Messages are buffered and committed in batches (size or interval
    triggered) to keep write cost negligible at danmu rates.
    """

    def __init__(
        self,
        path: str | Path,
        room_id: str = "",
        batch_size: int = DEFAULT_BATCH_SIZE,
        flush_interval: float = DEFAULT_FLUSH_INTERVAL_SECONDS,
        rotate_after: int = 0,
    ) -> None:
        """Initialize run-file storage.

        Args:
            path: Output .db file path. Must not exist yet (refuses to overwrite).
            room_id: Room ID recorded in meta.
            batch_size: Messages buffered before an automatic commit.
            flush_interval: Maximum seconds between automatic commits.
            rotate_after: Committed rows after which the collector should roll
                over to a new file. 0 disables it.
        """
        self._path = Path(path)
        self._room_id = room_id
        self._batch_size = batch_size
        self._flush_interval = flush_interval
        self._rotate_after = rotate_after

        self._conn: sqlite3.Connection | None = None
        self._buffer: list[DanmuMessage] = []
        self._flush_task: asyncio.Task[None] | None = None
        self._closed = False
        self._stats: dict[str, int] = {
            "messages": 0,  # handed to save()
            "committed": 0,  # actually on disk
            "flushes": 0,
            "flush_errors": 0,
        }

    async def __aenter__(self) -> SQLiteStorage:
        if self._path.exists():
            raise FileExistsError(
                f"Output database already exists: {self._path} (refusing to overwrite a run file)"
            )
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path))
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(SCHEMA_SQL)
        self._set_meta("room", self._room_id)
        self._set_meta("started_at", format_timestamp(datetime.now()))
        self._flush_task = asyncio.create_task(self._flush_loop())
        return self

    @property
    def needs_rotation(self) -> bool:
        """True once this run file has reached its configured message budget.

        Driven by *committed* rows so a stuck buffer cannot trigger a rollover
        that would strand the still-buffered messages in the old file.
        """
        return self._rotate_after > 0 and self._stats["committed"] >= self._rotate_after

    @property
    def run_ref(self) -> str:
        return str(self._path)

    def _set_meta(self, key: str, value: str) -> None:
        if self._conn is None:
            return
        self._conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value))
        self._conn.commit()

    async def _flush_loop(self) -> None:
        while not self._closed:
            await asyncio.sleep(self._flush_interval)
            if self._buffer and not self._closed:
                await self._flush()

    async def _flush(self) -> None:
        """Commit the buffer.

        The buffer is only trimmed *after* the commit succeeds. A failed
        executemany therefore leaves the messages queued instead of dropping
        them on the floor, and the error is counted into ``meta.flush_errors``.
        """
        if not self._buffer or self._conn is None:
            return
        rows = [_message_row(message) for message in self._buffer]
        try:
            with self._conn:
                self._conn.executemany(INSERT_DANMAKU_SQL, rows)
        except sqlite3.Error:
            self._stats["flush_errors"] += 1
            raise
        del self._buffer[: len(rows)]
        self._stats["committed"] += len(rows)
        self._stats["flushes"] += 1

    async def save(self, message: DanmuMessage) -> None:
        """Buffer one message (committed in batches)."""
        if self._closed:
            return
        self._buffer.append(message)
        self._stats["messages"] += 1
        if len(self._buffer) >= self._batch_size:
            await self._flush()

    async def close(self) -> None:
        """Flush remaining messages and finalize run metadata.

        If the final flush fails the run is left *without* ``meta.ended_at`` on
        purpose: an interrupted run is the honest signal that something was
        lost. Writing ended_at anyway would hide the failure from
        ``scripts/scan_runs.py``.
        """
        if self._closed:
            return
        self._closed = True

        if self._flush_task:
            self._flush_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._flush_task

        try:
            if self._buffer and self._conn:
                await self._flush()
        except sqlite3.Error:
            if self._conn:
                with contextlib.suppress(sqlite3.Error):
                    self._set_meta("flush_errors", str(self._stats["flush_errors"]))
                    self._conn.close()
                    self._conn = None
            raise

        if self._conn:
            # Report what actually landed, not what was handed to save().
            self._set_meta("messages", str(self._stats["committed"]))
            self._set_meta("flush_errors", str(self._stats["flush_errors"]))
            self._set_meta("ended_at", format_timestamp(datetime.now()))
            self._conn.close()
            self._conn = None

    @property
    def stats(self) -> dict[str, int]:
        """Observed counters for this run (messages/committed/flushes/errors)."""
        return dict(self._stats)
