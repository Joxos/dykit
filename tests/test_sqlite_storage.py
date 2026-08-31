"""Unit tests for SQLite run-file storage."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

import pytest
from dycap.storage import SQLiteStorage
from dycap.types import DanmuMessage

from dyproto import MessageType

ROOM = "6657"


def _message(username: str = "alice", content: str = "hello") -> DanmuMessage:
    return DanmuMessage(
        timestamp=datetime(2026, 3, 7, 10, 0, 0, 123456),
        room_id=ROOM,
        msg_type=MessageType.CHATMSG,
        user_id="u1",
        username=username,
        content=content,
        user_level=5,
        color="2",
        raw_data={"type": "chatmsg", "txt": content, "col": "2", "level": "5"},
    )


def _rows(path: Path) -> list[tuple]:
    conn = sqlite3.connect(str(path))
    try:
        return conn.execute("SELECT username, content, timestamp FROM danmaku ORDER BY id").fetchall()
    finally:
        conn.close()


def _meta(path: Path) -> dict[str, str]:
    conn = sqlite3.connect(str(path))
    try:
        return dict(conn.execute("SELECT key, value FROM meta").fetchall())
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_open_creates_schema_and_started_meta(tmp_path: Path) -> None:
    path = tmp_path / "run.db"
    async with SQLiteStorage(path, room_id=ROOM):
        meta = _meta(path)
        assert meta["room"] == ROOM
        assert "started_at" in meta
        assert "ended_at" not in meta


@pytest.mark.asyncio
async def test_save_flushes_on_batch_and_close(tmp_path: Path) -> None:
    path = tmp_path / "run.db"
    async with SQLiteStorage(path, room_id=ROOM, batch_size=2, flush_interval=60.0) as storage:
        await storage.save(_message("alice", "first"))
        await storage.save(_message("bob", "second"))
        # batch_size=2 triggers an immediate flush
        assert _rows(path) == [
            ("alice", "first", "2026-03-07 10:00:00.123456"),
            ("bob", "second", "2026-03-07 10:00:00.123456"),
        ]
        await storage.save(_message("carol", "third"))
        assert len(_rows(path)) == 2  # still buffered

    # close flushed the rest and finalized meta
    assert len(_rows(path)) == 3
    meta = _meta(path)
    assert "ended_at" in meta
    assert meta["messages"] == "3"
    assert storage.stats == {"messages": 3, "flushes": 2}


@pytest.mark.asyncio
async def test_refuses_existing_file(tmp_path: Path) -> None:
    path = tmp_path / "run.db"
    path.write_bytes(b"not a db")
    with pytest.raises(FileExistsError):
        async with SQLiteStorage(path, room_id=ROOM):
            pass  # pragma: no cover


@pytest.mark.asyncio
async def test_interrupted_run_has_no_ended_at(tmp_path: Path) -> None:
    path = tmp_path / "interrupted.db"
    storage = SQLiteStorage(path, room_id=ROOM, batch_size=1, flush_interval=60.0)
    await storage.__aenter__()  # noqa: PLC2801
    await storage.save(_message())
    # Simulate a killed process: never call close(). Cancel the flush task
    # only to keep the test event loop clean.
    assert storage._flush_task is not None
    storage._flush_task.cancel()

    meta = _meta(path)
    assert meta["room"] == ROOM
    assert "started_at" in meta
    assert "ended_at" not in meta  # interrupted run is visible
    assert len(_rows(path)) == 1  # batch_size=1 committed the row


@pytest.mark.asyncio
async def test_non_pruned_fields_live_in_raw_data(tmp_path: Path) -> None:
    # user_level / color / gift fields are not columns anymore; they must be
    # preserved inside raw_data (pruned columns, zero data loss).
    path = tmp_path / "run.db"
    storage = SQLiteStorage(path, room_id=ROOM, batch_size=1)
    await storage.__aenter__()  # noqa: PLC2801
    await storage.save(_message())
    await storage.close()

    conn = sqlite3.connect(str(path))
    try:
        columns = [r[1] for r in conn.execute("PRAGMA table_info(danmaku)").fetchall()]
        raw = conn.execute("SELECT raw_data FROM danmaku").fetchone()
    finally:
        conn.close()

    assert "user_level" not in columns
    assert "color" not in columns
    assert "gift_id" not in columns
    assert raw is not None
    assert '"txt": "hello"' in raw[0]
    assert '"col": "2"' in raw[0]  # full payload preserved in raw_data
    assert '"level": "5"' in raw[0]


@pytest.mark.asyncio
async def test_raw_data_stored_as_json_text(tmp_path: Path) -> None:
    path = tmp_path / "run.db"
    storage = SQLiteStorage(path, room_id=ROOM, batch_size=1)
    await storage.__aenter__()  # noqa: PLC2801
    await storage.save(_message())
    await storage.close()

    conn = sqlite3.connect(str(path))
    try:
        raw = conn.execute("SELECT raw_data FROM danmaku").fetchone()
    finally:
        conn.close()
    assert raw is not None
    assert '"txt": "hello"' in raw[0]
    assert '"col": "2"' in raw[0]  # full payload preserved


@pytest.mark.asyncio
async def test_unicode_and_nul_bytes_stored_verbatim(tmp_path: Path) -> None:
    path = tmp_path / "run.db"
    message = _message(username="测试", content="包含\x00空字节和emoji🎉")
    storage = SQLiteStorage(path, room_id=ROOM, batch_size=1)
    await storage.__aenter__()  # noqa: PLC2801
    await storage.save(message)
    await storage.close()

    rows = _rows(path)
    assert rows == [("测试", "包含\x00空字节和emoji🎉", "2026-03-07 10:00:00.123456")]
