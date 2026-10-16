"""Rotation: rolling over to a new run file without interrupting collection."""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime
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
    async def test_aclose_finalises_the_live_shard_not_the_first(self, tmp_path: Path) -> None:
        """Regression: closing the *first* sink leaves the live one unfinished.

        Found against a live room: after a rollover the last shard had no
        `ended_at` and no `messages`, so scan_runs reported a clean shutdown as
        an interrupted run and the tail buffer was never flushed.
        """
        make, _ = _factory(tmp_path, rotate_after=0)
        first = make()

        async with first:
            collector = AsyncCollector(ROOM, first, sink_factory=make)
            await collector.storage.save(_message("before"))
            await collector.rotate()
            await collector.storage.save(_message("after"))

            await collector.aclose()

        old_meta = _meta(tmp_path / "run1.db")
        new_meta = _meta(tmp_path / "run2.db")

        assert old_meta["ended_at"] != "", "the rotated-away shard is finalised by rotate()"
        assert new_meta["ended_at"] != "", "the live shard must be finalised by aclose()"
        assert new_meta["messages"] == "1"
        assert new_meta["flush_errors"] == "0"

    @pytest.mark.asyncio
    async def test_aclose_is_safe_without_rotation(self, tmp_path: Path) -> None:
        make, _ = _factory(tmp_path, rotate_after=0)
        first = make()

        async with first:
            collector = AsyncCollector(ROOM, first, sink_factory=make)
            await collector.storage.save(_message("only"))
            await collector.aclose()
            await collector.aclose()  # idempotent

        assert _meta(tmp_path / "run1.db")["ended_at"] != ""

    @pytest.mark.asyncio
    async def test_without_a_factory_rotation_is_a_noop(self, tmp_path: Path) -> None:
        first = _factory(tmp_path, 0)[0]()
        async with first:
            collector = AsyncCollector(ROOM, first, sink_factory=None)
            assert await collector.rotate() is None
            assert collector.rotations == 0

    @pytest.mark.asyncio
    async def test_a_failed_rollover_keeps_collecting_in_the_current_file(
        self, tmp_path: Path
    ) -> None:
        """Regression: an unopenable next shard must not end the capture.

        The name collision case (two rollovers inside one second) surfaced this
        against a live room: `rotate()` raised, the exception escaped the run
        loop, and the collector died - costing a restart gap rather than just a
        delayed rollover.
        """
        make, counter = _factory(tmp_path, rotate_after=0)
        first = make()

        def broken_factory() -> SQLiteStorage:
            counter["n"] += 1
            raise FileExistsError("Output database already exists: collision.db")

        async with first:
            collector = AsyncCollector(ROOM, first, sink_factory=broken_factory)
            await collector.storage.save(_message("before"))

            assert await collector.rotate() is None, "a failed rollover reports no new file"
            assert collector.rotations == 0

            # the old sink is still live and still accepting messages
            await collector.storage.save(_message("after"))

        assert _rows(tmp_path / "run1.db") == [("before", ROOM), ("after", ROOM)]
        assert _meta(tmp_path / "run1.db")["ended_at"] != ""

    @pytest.mark.asyncio
    async def test_a_failed_rollover_does_not_lose_the_next_message(self, tmp_path: Path) -> None:
        """The failure path must leave the swap untouched, not half-applied."""
        first = _factory(tmp_path, rotate_after=0)[0]()

        async with first:
            collector = AsyncCollector(
                ROOM, first, sink_factory=lambda: SQLiteStorage(tmp_path / "never.db")
            )
            await collector.storage.save(_message("a"))

            original_open = SQLiteStorage.open

            async def failing_open(self: SQLiteStorage) -> StorageHandler:
                raise OSError("disk full")

            SQLiteStorage.open = failing_open  # type: ignore[method-assign]
            try:
                assert await collector.rotate() is None
            finally:
                SQLiteStorage.open = original_open  # type: ignore[method-assign]

            await collector.storage.save(_message("b"))

        assert _rows(tmp_path / "run1.db") == [("a", ROOM), ("b", ROOM)]
        assert not (tmp_path / "never.db").exists()


class TestShardNaming:
    def test_two_rollovers_in_the_same_second_get_distinct_names(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Regression: second-granularity names collided on a fast rollover.

        The factory froze `datetime.now()` at whole seconds, so a second
        rollover in the same second picked the same filename and the
        immutability guard rejected it.
        """
        from dykit.collect import cli as capture_cli

        # Freeze the clock so both rollovers would otherwise pick one name.
        class _FrozenDatetime(datetime):
            @classmethod
            def now(cls, tz=None):  # type: ignore[no-untyped-def]
                return cls(2026, 10, 16, 10, 0, 0)

        monkeypatch.setattr(capture_cli, "datetime", _FrozenDatetime)
        monkeypatch.setattr(capture_cli, "DEFAULT_RUN_DIR", str(tmp_path))

        factory = capture_cli._make_sqlite_sink_factory(ROOM, None, 1, 60.0, 0)  # pyright: ignore[reportPrivateUsage]

        first = factory()
        first_path = Path(first.run_ref)
        first_path.touch()  # stand in for the file the first rollover created

        second = factory()
        second_path = Path(second.run_ref)

        assert first_path != second_path, "a taken shard name must be bumped"
        assert second_path.name.startswith(f"{ROOM}_")
        assert not second_path.exists()


class TestSighupRotation:
    """`_run_collector` drives rollover from a level-triggered event."""

    @pytest.mark.asyncio
    async def test_one_hup_rolls_over_once(self, tmp_path: Path) -> None:
        """Regression: a set-but-never-cleared event spun the loop.

        Found by rehearsing SIGHUP against a live room: `rotate_event` was
        never cleared, so re-waiting on it returned immediately and the
        collector rolled over on *every* loop iteration - ~1390 empty shards
        from two HUP signals.
        """
        from dykit.collect import cli as capture_cli

        make, counter = _factory(tmp_path, rotate_after=0)
        first = make()
        shutdown_event = asyncio.Event()
        rotate_event = asyncio.Event()

        async def fire_shutdown() -> None:
            await asyncio.sleep(0.05)
            shutdown_event.set()

        async with first:
            collector = AsyncCollector(ROOM, first, sink_factory=make)
            rotate_event.set()  # the HUP arrives before the loop starts

            await asyncio.gather(
                capture_cli._run_collector(  # pyright: ignore[reportPrivateUsage]
                    collector, shutdown_event, rotate_event
                ),
                fire_shutdown(),
            )

        assert counter["n"] == 2, f"one HUP must roll over exactly once, got {counter['n'] - 1}"
        assert collector.rotations == 1

    @pytest.mark.asyncio
    async def test_two_hups_roll_over_twice(self, tmp_path: Path) -> None:
        from dykit.collect import cli as capture_cli

        make, counter = _factory(tmp_path, rotate_after=0)
        first = make()
        shutdown_event = asyncio.Event()
        rotate_event = asyncio.Event()

        async def fire() -> None:
            await asyncio.sleep(0.02)
            rotate_event.set()
            await asyncio.sleep(0.05)
            rotate_event.set()
            await asyncio.sleep(0.05)
            shutdown_event.set()

        async with first:
            collector = AsyncCollector(ROOM, first, sink_factory=make)
            await asyncio.gather(
                capture_cli._run_collector(  # pyright: ignore[reportPrivateUsage]
                    collector, shutdown_event, rotate_event
                ),
                fire(),
            )

        assert collector.rotations == 2
        assert counter["n"] == 3


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
