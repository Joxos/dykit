"""Unit tests for the interrupted-run scanner."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from dycommon.timestamps import format_timestamp

from scripts.scan_runs import scan


def _make_run_file(path: Path, *, ended: bool, started_minutes_ago: int) -> None:
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        """
    )
    started = datetime.now() - timedelta(minutes=started_minutes_ago)
    conn.execute("INSERT INTO meta (key, value) VALUES (?, ?)", ("room", "6657"))
    conn.execute("INSERT INTO meta (key, value) VALUES (?, ?)", ("started_at", format_timestamp(started)))
    conn.execute("INSERT INTO meta (key, value) VALUES (?, ?)", ("messages", "123"))
    if ended:
        conn.execute("INSERT INTO meta (key, value) VALUES (?, ?)", ("ended_at", format_timestamp(started + timedelta(minutes=30))))
    conn.commit()
    conn.close()


def test_completed_runs_are_not_interrupted(tmp_path: Path) -> None:
    _make_run_file(tmp_path / "6657_ok.db", ended=True, started_minutes_ago=600)
    assert scan(tmp_path, timedelta(minutes=60)) == []


def test_recent_run_without_ended_at_is_active_not_interrupted(tmp_path: Path) -> None:
    _make_run_file(tmp_path / "6657_active.db", ended=False, started_minutes_ago=5)
    assert scan(tmp_path, timedelta(minutes=60)) == []


def test_old_run_without_ended_at_is_interrupted(tmp_path: Path) -> None:
    _make_run_file(tmp_path / "6657_crash.db", ended=False, started_minutes_ago=300)
    result = scan(tmp_path, timedelta(minutes=60))
    assert len(result) == 1
    assert result[0]["file"] == "6657_crash.db"
    assert result[0]["room"] == "6657"
    assert result[0]["messages"] == "123"


def test_mixed_directory(tmp_path: Path) -> None:
    _make_run_file(tmp_path / "a.db", ended=True, started_minutes_ago=600)
    _make_run_file(tmp_path / "b.db", ended=False, started_minutes_ago=5)
    _make_run_file(tmp_path / "c.db", ended=False, started_minutes_ago=300)
    result = scan(tmp_path, timedelta(minutes=60))
    assert [r["file"] for r in result] == ["c.db"]


def test_non_run_files_are_skipped(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("not a db")
    assert scan(tmp_path, timedelta(minutes=60)) == []
