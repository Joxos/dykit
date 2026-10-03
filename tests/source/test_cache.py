"""The endpoint cache that makes a restart fast.

Worst case live discovery is seconds (three HTML/JSON sources plus a room-page
scrape, each with its own timeout and retry); the WebSocket handshake is
~100-300ms. Caching the last good result lets a starting collector connect
without waiting, which is what keeps a redeploy's gap near the handshake.
"""

from __future__ import annotations

from pathlib import Path

from dykit.source.cache import EndpointCache, cache_path, load, store

ROOM = "6657"
URL = "wss://danmuproxy.douyu.com:8506/"


class TestRoundTrip:
    def test_store_then_load(self, tmp_path: Path) -> None:
        store(tmp_path, ROOM, [URL], 6657)

        cache = load(tmp_path, ROOM)

        assert cache is not None
        assert cache.urls == (URL,)
        assert cache.real_room_id == 6657
        assert cache.is_usable

    def test_cache_lives_in_the_data_directory(self, tmp_path: Path) -> None:
        store(tmp_path, ROOM, [URL], 6657)

        path = cache_path(tmp_path, ROOM)
        assert path.parent == tmp_path / ".endpoints"
        assert path.exists()

    def test_rooms_do_not_share_a_cache(self, tmp_path: Path) -> None:
        store(tmp_path, "111", [URL], 111)
        store(tmp_path, "222", ["wss://other/"], 222)

        assert load(tmp_path, "111").real_room_id == 111  # type: ignore[union-attr]
        assert load(tmp_path, "222").urls == ("wss://other/",)  # type: ignore[union-attr]


class TestMissingAndBroken:
    def test_absent_cache_is_not_an_error(self, tmp_path: Path) -> None:
        assert load(tmp_path, ROOM) is None

    def test_empty_discovery_is_not_cached(self, tmp_path: Path) -> None:
        store(tmp_path, ROOM, [], 0)

        assert load(tmp_path, ROOM) is None

    def test_garbage_is_ignored(self, tmp_path: Path) -> None:
        path = cache_path(tmp_path, ROOM)
        path.parent.mkdir(parents=True)
        path.write_text("not json at all", encoding="utf-8")

        assert load(tmp_path, ROOM) is None

    def test_wrong_version_is_ignored(self, tmp_path: Path) -> None:
        path = cache_path(tmp_path, ROOM)
        path.parent.mkdir(parents=True)
        path.write_text(
            f'{{"version": 999, "urls": ["{URL}"], "real_room_id": 1}}', encoding="utf-8"
        )

        assert load(tmp_path, ROOM) is None

    def test_empty_url_list_is_ignored(self, tmp_path: Path) -> None:
        path = cache_path(tmp_path, ROOM)
        path.parent.mkdir(parents=True)
        path.write_text('{"version": 1, "urls": [], "real_room_id": 1}', encoding="utf-8")

        assert load(tmp_path, ROOM) is None

    def test_non_list_urls_is_ignored(self, tmp_path: Path) -> None:
        path = cache_path(tmp_path, ROOM)
        path.parent.mkdir(parents=True)
        path.write_text('{"version": 1, "urls": "nope", "real_room_id": 1}', encoding="utf-8")

        assert load(tmp_path, ROOM) is None

    def test_unwritable_directory_does_not_raise(self, tmp_path: Path) -> None:
        """A cache miss at worst costs a slower start; it must never crash."""
        blocker = tmp_path / "blocker"
        blocker.write_text("i am a file, not a directory", encoding="utf-8")

        store(blocker, ROOM, [URL], 6657)  # must not raise
        assert load(blocker, ROOM) is None


class TestCollectorWarmStart:
    def test_cached_endpoints_are_adopted_without_waiting(self) -> None:
        """The behavioural point: a restart does not block on discovery."""
        import asyncio
        import tempfile
        import threading
        import time
        from typing import Any

        from dykit.collect.collector import AsyncCollector
        from dykit.collect.storage import SQLiteStorage

        class _Stub(SQLiteStorage):
            def __init__(self) -> None:
                super().__init__("unused.db", room_id=ROOM)

            async def __aenter__(self) -> _Stub:
                return self

            async def close(self) -> None:
                return None

        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            store(data_dir, ROOM, [URL], 6657)

            release = threading.Event()

            def slow_discovery(*args: Any, **kwargs: Any) -> tuple[list[str], int]:
                _ = (args, kwargs)
                release.wait(3)
                return [], 0

            import dykit.collect.collector as module

            original = module.get_danmu_server
            module.get_danmu_server = slow_discovery  # type: ignore[assignment]
            loop = asyncio.new_event_loop()
            try:
                collector = AsyncCollector(ROOM, _Stub(), data_dir=data_dir)
                started = time.perf_counter()
                loop.run_until_complete(collector.refresh_candidates())
                elapsed = time.perf_counter() - started
                # Release the uninterruptible worker before teardown: the
                # executor's shutdown would otherwise dominate the timing.
                release.set()
                for pending in asyncio.all_tasks(loop):
                    pending.cancel()
            finally:
                release.set()
                loop.close()
                module.get_danmu_server = original  # type: ignore[assignment]

            assert elapsed < 1.0, f"warm start still waited {elapsed:.2f}s on discovery"
            assert collector.real_room_id == 6657
            assert collector.candidate_urls == [URL]


def test_cache_is_usable_only_when_complete() -> None:
    assert EndpointCache(urls=(URL,), real_room_id=1).is_usable
    assert not EndpointCache(urls=(), real_room_id=1).is_usable
    assert not EndpointCache(urls=(URL,), real_room_id=0).is_usable
