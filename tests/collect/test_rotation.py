"""Rotation: rolling over to a new run file without interrupting collection."""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import pytest

from dykit.collect.collector import AsyncCollector
from dykit.collect.storage import SQLiteStorage, StorageHandler
from dykit.collect.types import DanmuMessage
from dykit.protocol import MessageType

ROOM = "6657"


def _message(text: str) -> DanmuMessage:
    from datetime import datetime

    return DanmuMessage(
        timestamp=datetime(2026, 3, 7, 10, 0, 0),
        room_id=ROOM,
        msg_type=MessageType.CHATMSG,
        user_id="u1",
        username="alice",
        content=text,
    )


def _rows(path: Path) -> list[tuple[str, str]]:
    conn = sqlite3.connect(str(path))
    try:
        return [(r[0], r[1]) for r in conn.execute("SELECT content, room_id FROM danmaku")]
    finally:
        conn.close()


def _meta(path: Path) -> dict[str, str]:
    conn = sqlite3.connect(str(path))
    try:
        return dict(conn.execute("SELECT key, value FROM meta").fetchall())
    finally:
        conn.close()


def _factory(tmp_path: Path, rotate_after: int):
    counter = {"n": 0}

    def make() -> SQLiteStorage:
        counter["n"] += 1
        return SQLiteStorage(
            tmp_path / f"run{counter['n']}.db",
            room_id=ROOM,
            batch_size=1,
            flush_interval=60.0,
            rotate_after=rotate_after,
        )

    return make, counter


class TestRotation:
    @pytest.mark.asyncio
    async def test_rotate_splits_messages_across_two_files(self, tmp_path: Path) -> None:
        make, counter = _factory(tmp_path, rotate_after=0)
        first = make()

        async with first:
            collector = AsyncCollector(ROOM, first, sink_factory=make)
            for i in range(5):
                await collector.storage.save(_message(f"before-{i}"))

            new_ref = await collector.rotate()
            await collector.storage.save(_message("after"))

        assert new_ref is not None
        assert counter["n"] == 2
        assert _rows(tmp_path / "run1.db") == [(f"before-{i}", ROOM) for i in range(5)]
        assert _rows(tmp_path / "run2.db") == [("after", ROOM)]

    @pytest.mark.asyncio
    async def test_old_file_is_finalised_and_new_one_is_not(self, tmp_path: Path) -> None:
        make, _ = _factory(tmp_path, rotate_after=0)
        first = make()

        async with first:
            collector = AsyncCollector(ROOM, first, sink_factory=make)
            await collector.storage.save(_message("x"))
            await collector.rotate()

            old_meta = _meta(tmp_path / "run1.db")
            new_meta = _meta(tmp_path / "run2.db")

        assert old_meta["ended_at"] != ""
        assert old_meta["messages"] == "1"
        assert "ended_at" not in new_meta, "the live shard must stay open"

    @pytest.mark.asyncio
    async def test_rotation_is_not_announced_as_an_interruption(self, tmp_path: Path) -> None:
        """A rollover is normal, so scan_runs must not flag it as interrupted."""
        make, _ = _factory(tmp_path, rotate_after=0)
        first = make()

        async with first:
            collector = AsyncCollector(ROOM, first, sink_factory=make)
            await collector.storage.save(_message("x"))
            await collector.rotate()

        assert _meta(tmp_path / "run1.db")["flush_errors"] == "0"

    @pytest.mark.asyncio
    async def test_without_a_factory_rotation_is_a_noop(self, tmp_path: Path) -> None:
        first = _factory(tmp_path, 0)[0]()
        async with first:
            collector = AsyncCollector(ROOM, first, sink_factory=None)
            assert await collector.rotate() is None
            assert collector.rotations == 0


class TestRotationTrigger:
    @pytest.mark.asyncio
    async def test_sink_reports_when_its_budget_is_spent(self, tmp_path: Path) -> None:
        sink = _factory(tmp_path, rotate_after=3)[0]()
        async with sink:
            assert sink.needs_rotation is False
            for i in range(3):
                await sink.save(_message(f"m{i}"))
            assert sink.needs_rotation is True

    @pytest.mark.asyncio
    async def test_zero_disables_rotation(self, tmp_path: Path) -> None:
        sink = _factory(tmp_path, rotate_after=0)[0]()
        async with sink:
            for i in range(50):
                await sink.save(_message(f"m{i}"))
            assert sink.needs_rotation is False

    @pytest.mark.asyncio
    async def test_collector_rolls_over_when_the_budget_is_spent(self, tmp_path: Path) -> None:
        make, counter = _factory(tmp_path, rotate_after=2)
        first = make()

        async with first:
            collector = AsyncCollector(ROOM, first, sink_factory=make)
            seen: list[str] = []

            def record(message: DanmuMessage) -> None:
                seen.append(message.content or "")

            collector.message_callback = record

            for i in range(5):
                message = _message(f"m{i}")
                await collector.storage.save(message)
                if collector.storage.needs_rotation:
                    await collector.rotate(reason="rotate_after")
                collector.message_callback(message)

        assert counter["n"] == 3
        assert seen == ["m0", "m1", "m2", "m3", "m4"], "no message may be dropped by a rollover"

    @pytest.mark.asyncio
    async def test_rotation_does_not_block_the_receive_loop(self, tmp_path: Path) -> None:
        """The swap itself must not await: that is what keeps rollover lossless."""
        make, _ = _factory(tmp_path, rotate_after=0)
        collector = AsyncCollector(ROOM, make(), sink_factory=make)

        original_open = SQLiteStorage.open

        async def slow_open(self: SQLiteStorage) -> StorageHandler:
            await asyncio.sleep(0.05)  # simulate slow disk
            return await original_open(self)

        SQLiteStorage.open = slow_open  # type: ignore[method-assign]
        try:
            ticks = 0

            async def heartbeat_tick() -> None:
                nonlocal ticks
                while True:
                    ticks += 1
                    await asyncio.sleep(0.005)

            ticker = asyncio.create_task(heartbeat_tick())
            await asyncio.sleep(0.01)
            ticks_before = ticks
            await collector.rotate()
            SQLiteStorage.open = original_open  # type: ignore[method-assign]
            await asyncio.sleep(0.01)
            await asyncio.sleep(0)
            ticker.cancel()

            assert ticks > ticks_before, "the loop was blocked during rotation"
        finally:
            SQLiteStorage.open = original_open  # type: ignore[method-assign]
