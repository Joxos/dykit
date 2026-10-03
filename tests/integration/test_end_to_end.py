"""End-to-end smoke tests over real SQLite run files.

Cross-layer: capture writes run files, stats reads them, both CLIs run for
real. No network and no external database are involved.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from dykit.collect.cli import app as capture_app
from dykit.collect.collector import AsyncCollector
from dykit.collect.storage import SQLiteStorage
from dykit.collect.types import DanmuMessage
from dykit.protocol import MessageType
from dykit.stats.cli import app as stats_app

from ..cli_test_runner import CliRunner

ROOM = "6657"


def _message(
    username: str,
    content: str,
    msg_type: MessageType = MessageType.CHATMSG,
    **extra: Any,
) -> DanmuMessage:
    return DanmuMessage(
        timestamp=datetime.now(),
        room_id=ROOM,
        msg_type=msg_type,
        user_id=extra.get("user_id", f"u-{username}"),
        username=username,
        content=content,
        user_level=extra.get("user_level", 1),
        gift_id=extra.get("gift_id"),
        gift_count=extra.get("gift_count"),
        gift_name=extra.get("gift_name"),
        color=extra.get("color"),
        raw_data={"type": msg_type.value, "txt": content},
    )


async def _write_run(path: Path, messages: list[DanmuMessage]) -> None:
    async with SQLiteStorage(path, room_id=ROOM) as storage:
        for message in messages:
            await storage.save(message)


@pytest.fixture
def seeded_dir(tmp_path: Path) -> Path:
    run1 = tmp_path / "6657_20260307_100000.db"
    run2 = tmp_path / "6657_20260308_100000.db"
    asyncio.run(
        _write_run(
            run1,
            [
                _message("Alice", "冲冲冲"),
                _message("Bob", "冲冲冲"),
                _message("Alice", "666"),
                _message(
                    "GiftUser",
                    "送礼",
                    MessageType.DGB,
                    gift_id="g1",
                    gift_count=3,
                    gift_name="火箭",
                ),
            ],
        )
    )
    asyncio.run(
        _write_run(
            run2,
            [
                _message("Alice", "再来一次"),
                _message("Carol", "冲冲冲"),
            ],
        )
    )
    return tmp_path


@pytest.mark.smoke
def test_smoke_stats_single_file(runner: CliRunner, seeded_dir: Path) -> None:
    run_file = seeded_dir / "6657_20260307_100000.db"
    result = runner.invoke(stats_app, ["rank", "--data", str(run_file), "-r", ROOM, "--top", "5"])
    assert result.exit_code == 0, result.output
    assert "Alice" in result.output

    result_search = runner.invoke(
        stats_app, ["search", "--data", str(run_file), "-r", ROOM, "--content", "冲冲冲"]
    )
    assert result_search.exit_code == 0, result_search.output
    assert "Found" in result_search.output

    result_cluster = runner.invoke(
        stats_app,
        ["cluster", "--data", str(run_file), "-r", ROOM, "--limit", "50", "--threshold", "0.5"],
    )
    assert result_cluster.exit_code == 0, result_cluster.output
    assert "clusters" in result_cluster.output


@pytest.mark.smoke
def test_smoke_stats_directory_union(runner: CliRunner, seeded_dir: Path) -> None:
    # Alice appears in both run files (2 + 1 messages).
    result = runner.invoke(stats_app, ["rank", "--data", str(seeded_dir), "-r", ROOM, "--top", "5"])
    assert result.exit_code == 0, result.output
    assert "Alice" in result.output
    assert "Carol" in result.output  # only in the second run file

    result_search = runner.invoke(
        stats_app, ["search", "--data", str(seeded_dir), "-r", ROOM, "--content", "再来一次"]
    )
    assert result_search.exit_code == 0, result_search.output
    assert "再来一次" in result_search.output


class _FakeCollector:
    def __init__(
        self,
        room_id: str,
        storage: Any,
        type_filter: list[str] | None = None,
        type_exclude: list[str] | None = None,
        message_callback: Any | None = None,
        ws_url: str | None = None,
        sink_factory: Any | None = None,
        data_dir: Path | None = None,
    ) -> None:
        self.room_id = room_id
        self.storage = storage
        self.type_filter = type_filter
        self.type_exclude = type_exclude
        self.message_callback = message_callback
        self.rotations = 0

    async def connect(self) -> None:
        message = _message("SmokeCLI", "capture-cli-smoke")
        await self.storage.save(message)
        if self.message_callback is not None:
            self.message_callback(message)

    async def stop(self) -> None:
        return


@pytest.mark.smoke
def test_smoke_capture_cli_sqlite(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("dykit.collect.cli.AsyncCollector", _FakeCollector)
    out = tmp_path / "cli_smoke.db"

    result = runner.invoke(capture_app, ["--storage", "sqlite", "-o", str(out), "-r", ROOM])
    assert result.exit_code == 0, result.output

    import sqlite3

    conn = sqlite3.connect(str(out))
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM danmaku WHERE content = ?", ("capture-cli-smoke",)
        ).fetchone()
        meta = dict(conn.execute("SELECT key, value FROM meta").fetchall())
    finally:
        conn.close()
    assert count is not None
    assert count[0] >= 1
    assert meta["ended_at"] != ""  # cleanly closed run


@pytest.mark.smoke
def test_smoke_capture_cli_csv(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("dykit.collect.cli.AsyncCollector", _FakeCollector)
    output_file = tmp_path / "cli_smoke.csv"

    result = runner.invoke(capture_app, ["--storage", "csv", "-o", str(output_file), "-r", ROOM])
    assert result.exit_code == 0, result.output
    text = output_file.read_text(encoding="utf-8")
    assert "capture-cli-smoke" in text


@pytest.mark.smoke
def test_smoke_capture_cli_console(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("dykit.collect.cli.AsyncCollector", _FakeCollector)

    result = runner.invoke(capture_app, ["--storage", "console", "-r", ROOM])
    assert result.exit_code == 0, result.output
    assert "capture-cli-smoke" in result.output
    assert f"[{ROOM}]" in result.output


@pytest.mark.smoke
def test_smoke_capture_storage_end_to_end(tmp_path: Path) -> None:
    async def run() -> None:
        path = tmp_path / "e2e.db"
        async with SQLiteStorage(path, room_id=ROOM) as storage:
            collector = AsyncCollector(ROOM, storage, type_filter=["chatmsg"])
            assert collector.room_id == ROOM
            assert collector.storage is storage

    asyncio.run(run())
