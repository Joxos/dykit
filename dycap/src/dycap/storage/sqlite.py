"""SQLite run-file storage handler.

One database file per collection run. Each file carries the full run history
(``danmaku`` rows) plus run metadata (``meta`` table: room, started_at,
ended_at, messages). A file whose ``meta`` lacks ``ended_at`` is an
interrupted run (process killed) - downtime is visible at a glance.

The handler refuses to overwrite an existing file: run files are immutable
history, and each run must get its own file.

Example:
    from dycap.storage import SQLiteStorage

    async with SQLiteStorage("run.db", room_id="6657") as storage:
        await storage.save(message)
    # run.db now contains danmaku rows + meta (room/started_at/ended_at/messages)
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from dycommon.timestamps import format_timestamp

from ..schema import SCHEMA_SQL
from ..types import DanmuMessage
from .base import StorageHandler

DEFAULT_BATCH_SIZE = 100
DEFAULT_FLUSH_INTERVAL_SECONDS = 2.0

INSERT_DANMAKU_SQL = """
INSERT INTO danmaku (
    timestamp, room_id, msg_type, user_id, username, content, raw_data
) VALUES (?, ?, ?, ?, ?, ?, ?)
"""


def _message_row(message: DanmuMessage) -> tuple[Any, ...]:
    raw_data = None
    if message.raw_data is not None:
        raw_data = json.dumps(message.raw_data, ensure_ascii=False)
    return (
        format_timestamp(message.timestamp),
        message.room_id,
        message.msg_type.value,
        message.user_id,
        message.username,
        message.content,
        raw_data,
    )


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
    ) -> None:
        """Initialize run-file storage.

        Args:
            path: Output .db file path. Must not exist yet (refuses to overwrite).
            room_id: Room ID recorded in meta.
            batch_size: Messages buffered before an automatic commit.
            flush_interval: Maximum seconds between automatic commits.
        """
        self._path = Path(path)
        self._room_id = room_id
        self._batch_size = batch_size
        self._flush_interval = flush_interval

        self._conn: sqlite3.Connection | None = None
        self._buffer: list[DanmuMessage] = []
        self._flush_task: asyncio.Task[None] | None = None
        self._closed = False
        self._stats: dict[str, int] = {"messages": 0, "flushes": 0}

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

    def _set_meta(self, key: str, value: str) -> None:
        if self._conn is None:
            return
        self._conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value)
        )
        self._conn.commit()

    async def _flush_loop(self) -> None:
        while not self._closed:
            await asyncio.sleep(self._flush_interval)
            if self._buffer and not self._closed:
                await self._flush()

    async def _flush(self) -> None:
        if not self._buffer or self._conn is None:
            return
        rows = [_message_row(message) for message in self._buffer]
        self._buffer.clear()
        with self._conn:
            self._conn.executemany(INSERT_DANMAKU_SQL, rows)
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
        """Flush remaining messages and finalize run metadata."""
        if self._closed:
            return
        self._closed = True

        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass

        if self._buffer and self._conn:
            await self._flush()

        if self._conn:
            self._set_meta("ended_at", format_timestamp(datetime.now()))
            self._set_meta("messages", str(self._stats["messages"]))
            self._conn.close()
            self._conn = None

    @property
    def stats(self) -> dict[str, int]:
        """Observed counters for this run (messages/flushes)."""
        return dict(self._stats)
