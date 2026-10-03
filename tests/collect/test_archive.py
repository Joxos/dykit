"""Archiving old rows out of a live run file, and gap detection between runs."""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from dykit.collect.archive import RunArchiver
from dykit.schema import SCHEMA_SQL, format_timestamp
from scripts.scan_runs import find_gaps, read_meta, scan

ROOM = "6657"


def _seed_run(path: Path, contents: list[str]) -> None:
    conn = sqlite3.connect(str(path))
    conn.executescript(SCHEMA_SQL)
    conn.executemany(
        "INSERT INTO danmaku (timestamp, room_id, msg_type, content) VALUES (?,?,?,?)",
        [
            (f"2026-03-07 10:00:{i % 60:02d}.000000", ROOM, "chatmsg", c)
            for i, c in enumerate(contents)
        ],
    )
    conn.commit()
    conn.close()


def _contents(path: Path) -> list[str]:
    conn = sqlite3.connect(str(path))
    try:
        return [r[0] for r in conn.execute("SELECT content FROM danmaku ORDER BY id")]
    finally:
        conn.close()


class TestArchiver:
    def test_moves_old_rows_and_keeps_new_ones(self, tmp_path: Path) -> None:
        run = tmp_path / "run.db"
        archive = tmp_path / "run-old.db"
        _seed_run(run, [f"m{i}" for i in range(20)])

        conn = sqlite3.connect(str(run))
        try:
            cutoff = conn.execute("SELECT MIN(id) + 9 FROM danmaku").fetchone()[0]
        finally:
            conn.close()

        moved = RunArchiver(run, archive, chunk_rows=4).run(cutoff)

        assert moved == 10
        assert _contents(run) == [f"m{i}" for i in range(10, 20)]
        assert _contents(archive) == [f"m{i}" for i in range(10)]

    def test_no_rows_is_a_noop(self, tmp_path: Path) -> None:
        run = tmp_path / "run.db"
        _seed_run(run, ["a", "b"])
        archive = tmp_path / "run-old.db"

        assert RunArchiver(run, archive).run(0) == 0
        assert _contents(run) == ["a", "b"]

    def test_repeated_runs_are_idempotent(self, tmp_path: Path) -> None:
        run = tmp_path / "run.db"
        archive = tmp_path / "run-old.db"
        _seed_run(run, ["a", "b", "c"])
        archiver = RunArchiver(run, archive, chunk_rows=1)
        conn = sqlite3.connect(str(run))
        try:
            cutoff = conn.execute("SELECT MAX(id) FROM danmaku").fetchone()[0]
        finally:
            conn.close()

        assert archiver.run(cutoff) == 3
        assert archiver.run(cutoff) == 0
        assert _contents(archive) == ["a", "b", "c"]

    def test_appending_to_a_kept_row_is_impossible(self, tmp_path: Path) -> None:
        """Rows are removed by id range, so a later append never reappears."""
        run = tmp_path / "run.db"
        archive = tmp_path / "run-old.db"
        _seed_run(run, ["a", "b", "c"])

        conn = sqlite3.connect(str(run))
        try:
            cutoff = conn.execute("SELECT MIN(id) FROM danmaku").fetchone()[0]
        finally:
            conn.close()
        RunArchiver(run, archive).run(cutoff)

        conn = sqlite3.connect(str(run))
        conn.execute(
            "INSERT INTO danmaku (timestamp, room_id, msg_type, content) VALUES (?,?,?,?)",
            ("2026-03-07 11:00:00.000000", ROOM, "chatmsg", "d"),
        )
        conn.commit()
        conn.close()

        assert _contents(run) == ["b", "c", "d"]
        assert _contents(archive) == ["a"]


class TestArchiverDoesNotBlockTheLoop:
    @pytest.mark.asyncio
    async def test_the_loop_keeps_running_while_archiving(self, tmp_path: Path) -> None:
        """Chunking exists so a big archive cannot stall message processing."""
        run = tmp_path / "run.db"
        archive = tmp_path / "run-old.db"
        _seed_run(run, [f"m{i}" for i in range(4000)])

        conn = sqlite3.connect(str(run))
        try:
            cutoff = conn.execute("SELECT MAX(id) FROM danmaku").fetchone()[0]
        finally:
            conn.close()

        ticks = 0

        async def ticker() -> None:
            nonlocal ticks
            while True:
                ticks += 1
                await asyncio.sleep(0)

        task = asyncio.create_task(ticker())
        moved = await RunArchiver(run, archive, chunk_rows=100).run_async(cutoff)
        await asyncio.sleep(0)
        task.cancel()

        assert moved == 4000
        assert ticks > 0, "the event loop was blocked for the whole archive"


class TestGapDetection:
    def _run(self, path: Path, room: str, started: str, ended: str | None) -> None:
        conn = sqlite3.connect(str(path))
        conn.executescript(SCHEMA_SQL)
        conn.execute("INSERT INTO meta VALUES ('room', ?)", (room,))
        conn.execute("INSERT INTO meta VALUES ('started_at', ?)", (started,))
        if ended is not None:
            conn.execute("INSERT INTO meta VALUES ('ended_at', ?)", (ended,))
        conn.commit()
        conn.close()

    def test_normal_rotation_is_not_a_gap(self, tmp_path: Path) -> None:
        self._run(
            tmp_path / "a.db", ROOM, "2026-03-07 10:00:00.000000", "2026-03-07 10:30:00.000000"
        )
        self._run(tmp_path / "b.db", ROOM, "2026-03-07 10:30:00.050000", None)

        assert find_gaps(tmp_path, timedelta(seconds=60)) == []

    def test_a_deploy_gap_is_reported(self, tmp_path: Path) -> None:
        self._run(
            tmp_path / "a.db", ROOM, "2026-03-07 10:00:00.000000", "2026-03-07 10:30:00.000000"
        )
        self._run(tmp_path / "b.db", ROOM, "2026-03-07 10:32:00.000000", None)

        gaps = find_gaps(tmp_path, timedelta(seconds=60))

        assert len(gaps) == 1
        assert gaps[0]["room"] == ROOM
        assert gaps[0]["previous"] == "a.db"
        assert gaps[0]["seconds"] == "120.0"

    def test_a_running_predecessor_is_not_a_gap(self, tmp_path: Path) -> None:
        """The newest file has no ended_at; there is no boundary to measure."""
        self._run(tmp_path / "a.db", ROOM, "2026-03-07 10:00:00.000000", None)

        assert find_gaps(tmp_path, timedelta(seconds=1)) == []

    def test_rooms_are_judged_independently(self, tmp_path: Path) -> None:
        self._run(
            tmp_path / "a.db", "111", "2026-03-07 10:00:00.000000", "2026-03-07 10:30:00.000000"
        )
        self._run(tmp_path / "b.db", "111", "2026-03-07 10:32:00.000000", None)
        self._run(
            tmp_path / "c.db", "222", "2026-03-07 09:00:00.000000", "2026-03-07 09:30:00.000000"
        )
        self._run(tmp_path / "d.db", "222", "2026-03-07 09:30:00.100000", None)

        gaps = find_gaps(tmp_path, timedelta(seconds=60))

        assert [gap["room"] for gap in gaps] == ["111"]

    def test_non_run_files_are_ignored(self, tmp_path: Path) -> None:
        (tmp_path / "notes.db").write_bytes(b"not a database")

        assert find_gaps(tmp_path, timedelta(seconds=1)) == []


def test_read_meta_reports_none_for_junk(tmp_path: Path) -> None:
    path = tmp_path / "junk.db"
    path.write_bytes(b"nope")
    assert read_meta(path) is None


def test_scan_still_finds_interrupted_runs(tmp_path: Path) -> None:
    """The GAP check must not have broken the original INTERRUPTED scan."""
    run = tmp_path / "old.db"
    _seed_run(run, ["a"])
    conn = sqlite3.connect(str(run))
    conn.execute("INSERT INTO meta VALUES ('room', '6657')")
    conn.execute(
        "INSERT INTO meta VALUES ('started_at', ?)",
        (format_timestamp(datetime.now() - timedelta(hours=5)),),
    )
    conn.commit()
    conn.close()
    import os

    old = (datetime.now() - timedelta(hours=5)).timestamp()
    os.utime(run, (old, old))

    assert [row["file"] for row in scan(tmp_path, timedelta(minutes=60))] == ["old.db"]
