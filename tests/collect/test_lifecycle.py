"""The lifecycle guarantees the state machine is supposed to provide.

The regression these guard: `stop()` used to only clear a flag, so an await
stuck in HTTP room discovery (up to ~30s of tenacity retries) kept Ctrl+C
waiting for it to finish.

The blocking doubles below are *synchronous* on purpose - that is what
``asyncio.to_thread`` is handed, and a real HTTP call is equally uninterruptible.
They release on a ``threading.Event`` so the test can let the worker thread go
instead of leaving it parked for an hour.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Callable, Iterator
from typing import Any

import pytest

from dykit.collect.collector import AsyncCollector, CaptureState
from dykit.collect.storage import SQLiteStorage
from dykit.collect.types import DanmuMessage
from dykit.protocol import MessageType

ROOM = "6657"

BlockingDiscovery = Callable[..., tuple[list[str], int]]


class _StubStorage(SQLiteStorage):
    def __init__(self) -> None:
        super().__init__("unused.db", room_id=ROOM)

    async def __aenter__(self) -> _StubStorage:
        return self

    async def close(self) -> None:
        return None

    @property
    def run_ref(self) -> str:
        return "stub"


def _collector() -> AsyncCollector:
    return AsyncCollector(ROOM, _StubStorage())


@pytest.fixture
def release() -> Iterator[threading.Event]:
    """Unblocks the fake HTTP worker once the assertions are done."""
    event = threading.Event()
    yield event
    event.set()


def _blocking_discovery(
    release: threading.Event,
    entered: threading.Event,
    on_enter: Callable[[], None] = lambda: None,
) -> BlockingDiscovery:
    def discovery(*args: Any, **kwargs: Any) -> tuple[list[str], int]:
        _ = (args, kwargs)
        on_enter()
        entered.set()
        release.wait(3)
        return [], 0

    return discovery


def _install(monkeypatch: pytest.MonkeyPatch, stub: BlockingDiscovery) -> None:
    monkeypatch.setattr("dykit.collect.collector.get_danmu_server", stub, raising=True)


class TestStopIsAnInterrupt:
    @pytest.mark.asyncio
    async def test_stop_cancels_a_connect_stuck_in_discovery(
        self, monkeypatch: pytest.MonkeyPatch, release: threading.Event
    ) -> None:
        """The whole point: a slow discovery must not hold up shutdown."""
        collector = _collector()
        entered = threading.Event()
        _install(monkeypatch, _blocking_discovery(release, entered))

        connect_task = asyncio.create_task(collector.connect())
        await asyncio.to_thread(entered.wait, 5)

        started = time.perf_counter()
        await collector.stop()
        with pytest.raises(asyncio.CancelledError):
            await connect_task
        elapsed = time.perf_counter() - started

        assert elapsed < 1.0, f"stop() took {elapsed:.2f}s; the await was not interruptible"

    @pytest.mark.asyncio
    async def test_stop_is_safe_before_connect(self) -> None:
        await _collector().stop()  # must not raise

    @pytest.mark.asyncio
    async def test_stop_is_idempotent(self) -> None:
        collector = _collector()
        await collector.stop()
        await collector.stop()

    @pytest.mark.asyncio
    async def test_connect_twice_is_refused(
        self, monkeypatch: pytest.MonkeyPatch, release: threading.Event
    ) -> None:
        collector = _collector()
        entered = threading.Event()
        _install(monkeypatch, _blocking_discovery(release, entered))

        task = asyncio.create_task(collector.connect())
        await asyncio.to_thread(entered.wait, 5)

        with pytest.raises(RuntimeError, match="already running"):
            await collector.connect()

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


class TestStateMachine:
    def test_starts_idle(self) -> None:
        assert _collector().state is CaptureState.IDLE

    @pytest.mark.asyncio
    async def test_enters_discovery_and_ends_stopped(
        self, monkeypatch: pytest.MonkeyPatch, release: threading.Event
    ) -> None:
        collector = _collector()
        seen: list[CaptureState] = []
        entered = threading.Event()
        _install(
            monkeypatch,
            _blocking_discovery(release, entered, on_enter=lambda: seen.append(collector.state)),
        )

        task = asyncio.create_task(collector.connect())
        await asyncio.to_thread(entered.wait, 5)
        assert seen == [CaptureState.DISCOVERING]

        await collector.stop()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert collector.state is CaptureState.STOPPED

    @pytest.mark.asyncio
    async def test_cancel_passes_through(
        self, monkeypatch: pytest.MonkeyPatch, release: threading.Event
    ) -> None:
        """Cancellation must stay visible to the caller, not be swallowed."""
        collector = _collector()
        entered = threading.Event()
        _install(monkeypatch, _blocking_discovery(release, entered))

        task = asyncio.create_task(collector.connect())
        await asyncio.to_thread(entered.wait, 5)
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task
        assert collector.state is CaptureState.STOPPED


class TestStateMachineDoesNotChangeDelivery:
    @pytest.mark.asyncio
    async def test_a_decoded_payload_still_becomes_a_saved_message(self) -> None:
        """A guard on the refactor: routing must be unchanged."""
        collector = _collector()
        received: list[DanmuMessage] = []

        def record(message: DanmuMessage) -> None:
            received.append(message)

        collector.message_callback = record
        await collector._handle_message(  # pyright: ignore[reportPrivateUsage]
            "chatmsg", {"type": "chatmsg", "txt": "hello", "nn": "alice"}
        )

        assert [m.content for m in received] == ["hello"]
        assert received[0].msg_type is MessageType.CHATMSG

    @pytest.mark.asyncio
    async def test_unknown_types_are_not_saved(self) -> None:
        collector = _collector()
        received: list[DanmuMessage] = []
        collector.message_callback = received.append

        await collector._handle_message(  # pyright: ignore[reportPrivateUsage]
            "some_new_douyu_type", {"type": "x"}
        )
        assert received == []
