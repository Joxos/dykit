"""Unit tests for dystat SQLite data access (single file + directory union)."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from dycommon.time_rules import WINDOW_CONFLICT_FIRST_LAST
from dycommon.timestamps import format_timestamp, parse_timestamp
from dystat.db import DataDb
from dystat.query_filters import build_common_filters, parse_order_limit

DDL = """
CREATE TABLE danmaku (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp            TEXT NOT NULL,
    room_id              TEXT NOT NULL,
    msg_type             TEXT NOT NULL,
    user_id              TEXT,
    username             TEXT,
    user_level           INTEGER,
    avatar_url           TEXT,
    color                TEXT,
    content              TEXT,
    badge_level          INTEGER,
    badge_name           TEXT,
    badge_room_id        TEXT,
    gift_id              TEXT,
    gift_count           INTEGER,
    gift_name            TEXT,
    gift_hits            INTEGER,
    gift_receiver_uid    TEXT,
    gift_receiver_name   TEXT,
    noble_level          INTEGER,
    client_type          TEXT,
    raw_data             TEXT
);
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def _create_run_file(path: Path, rows: list[tuple]) -> None:
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript(DDL)
        conn.executemany(
            "INSERT INTO danmaku (timestamp, room_id, msg_type, username, content) "
            "VALUES (?, ?, ?, ?, ?)",
            rows,
        )
        conn.commit()
    finally:
        conn.close()


def _ts(day: int) -> str:
    return format_timestamp(datetime(2026, 3, day, 10, 0, 0))


class TestDataDbFileMode:
    def test_query_single_file(self, tmp_path: Path) -> None:
        file = tmp_path / "run.db"
        _create_run_file(file, [(_ts(1), "6657", "chatmsg", "alice", "hi")] * 3)

        with DataDb(file) as db:
            assert db.query("SELECT COUNT(*) FROM danmaku_all")[0][0] == 3
            rows = db.query(
                "SELECT username FROM danmaku_all WHERE room_id = ?", ("6657",)
            )
            assert len(rows) == 3

    def test_invalid_path_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="neither file nor directory"):
            DataDb(tmp_path / "missing.db")


class TestDataDbDirectoryMode:
    def test_union_across_run_files(self, tmp_path: Path) -> None:
        run1 = tmp_path / "6657_a.db"
        run2 = tmp_path / "6657_b.db"
        _create_run_file(run1, [(_ts(1), "6657", "chatmsg", "alice", "one")])
        _create_run_file(run2, [(_ts(2), "6657", "chatmsg", "bob", "two")] * 2)

        with DataDb(tmp_path) as db:
            assert db.query("SELECT COUNT(*) FROM danmaku_all")[0][0] == 3
            rows = db.query(
                "SELECT username, COUNT(*) FROM danmaku_all "
                "WHERE room_id = ? GROUP BY username ORDER BY 2 DESC",
                ("6657",),
            )
            assert [(r[0], r[1]) for r in rows] == [("bob", 2), ("alice", 1)]

    def test_empty_directory_yields_zero_rows(self, tmp_path: Path) -> None:
        with DataDb(tmp_path) as db:
            assert db.query("SELECT COUNT(*) FROM danmaku_all")[0][0] == 0

    def test_ignores_non_db_files(self, tmp_path: Path) -> None:
        (tmp_path / "notes.txt").write_text("not a run file")
        _create_run_file(tmp_path / "6657_c.db", [(_ts(3), "6657", "chatmsg", "carol", "three")])
        with DataDb(tmp_path) as db:
            assert db.query("SELECT COUNT(*) FROM danmaku_all")[0][0] == 1


class TestSchemaCompat:
    def test_extra_columns_in_file_are_ignored(self, tmp_path: Path) -> None:
        # Forward compatibility: the union view selects named columns, so a
        # file with additional columns (e.g. produced by a future format)
        # stays readable.
        conn = sqlite3.connect(str(tmp_path / "future.db"))
        conn.executescript(DDL.replace("raw_data             TEXT", "raw_data             TEXT, extra TEXT"))
        conn.execute(
            "INSERT INTO danmaku (timestamp, room_id, msg_type, username, content, raw_data, extra) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (_ts(1), "6657", "chatmsg", "alice", "hi", '{"type": "chatmsg"}', "x"),
        )
        conn.commit()
        conn.close()

        with DataDb(tmp_path / "future.db") as db:
            assert db.query("SELECT COUNT(*) FROM danmaku_all")[0][0] == 1
            rows = db.query(
                "SELECT username, content FROM danmaku_all WHERE room_id = ?", ("6657",)
            )
            assert rows == [("alice", "hi")]


class TestQueryFilters:
    def test_order_limit_last_first_conflict(self) -> None:
        with pytest.raises(ValueError, match=WINDOW_CONFLICT_FIRST_LAST):
            parse_order_limit(last=10, first=5)

    def test_order_limit_last(self) -> None:
        sql, value = parse_order_limit(last=10, first=None)
        assert "LIMIT ?" in sql
        assert value == 10

    def test_common_filters_basic(self) -> None:
        where, params = build_common_filters(
            room="6657", msg_type="chatmsg", username="alice", user_id=None,
            from_date=None, to_date=None,
        )
        assert where == ["room_id = ?", "msg_type = ?", "username = ?"]
        assert params == ["6657", "chatmsg", "alice"]

    def test_common_filters_time_window(self) -> None:
        where, params = build_common_filters(
            room="6657", msg_type=None, username=None, user_id=None,
            from_date="2026-03-01", to_date="2026-03-07",
        )
        assert "timestamp >= ?" in where
        assert "timestamp < ?" in where
        # parse_to_exclusive adds one day to a date-only --to
        assert params[1] == format_timestamp(datetime(2026, 3, 1))
        assert params[2] == format_timestamp(datetime(2026, 3, 8))

    def test_common_filters_days(self) -> None:
        where, params = build_common_filters(
            room="6657", msg_type=None, username=None, user_id=None,
            from_date=None, to_date=None, days=3,
        )
        assert where == ["room_id = ?", "timestamp >= ?"]
        # Tolerance: build_common_filters computes now() internally.
        cutoff = parse_timestamp(params[1])
        assert abs((datetime.now() - timedelta(days=3) - cutoff).total_seconds()) < 5
