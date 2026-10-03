"""Cross-layer contract: what capture writes, stats must be able to read.

The column list has a single source of truth (``dykit.schema``), but three
things still have to agree: the DDL capture executes, the column set it
INSERTs, and the columns stats projects. These tests pin that agreement so a
schema change fails here with a clear message instead of at query time.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from dykit.collect.storage.sqlite import ROW_COLUMNS
from dykit.schema import (
    DANMAKU_SCHEMA,
    DANMAKU_VIEW_COLUMNS,
    DANMAKU_WRITE_COLUMNS,
    SCHEMA_SQL,
)
from dykit.stats.db import DataDb


def _table_columns(ddl: str) -> set[str]:
    conn = sqlite3.connect(":memory:")
    try:
        conn.executescript(ddl)
        return {row[1] for row in conn.execute("PRAGMA table_info(danmaku)")}
    finally:
        conn.close()


def test_ddl_declares_every_view_column() -> None:
    """SCHEMA_SQL must actually create the columns stats selects."""
    assert set(DANMAKU_VIEW_COLUMNS) <= _table_columns(SCHEMA_SQL)


def test_view_exposes_arrival_order() -> None:
    """`id` is written by SQLite but read by analyses ("newest first")."""
    assert "id" in DANMAKU_VIEW_COLUMNS
    assert "id" not in DANMAKU_WRITE_COLUMNS


def test_write_columns_match_the_storage_insert() -> None:
    """The writer must not store a column the reader ignores, or vice versa."""
    assert set(ROW_COLUMNS) == set(DANMAKU_WRITE_COLUMNS)


def test_schema_registry_covers_the_table() -> None:
    """The view is exactly the declared schema, in the declared order."""
    assert tuple(column.name for column in DANMAKU_SCHEMA) == DANMAKU_VIEW_COLUMNS


def test_stats_reads_a_run_file_written_by_capture(tmp_path: Path) -> None:
    """End-to-end: DDL from capture, rows from capture, query through stats."""
    run_file = tmp_path / "run.db"
    conn = sqlite3.connect(str(run_file))
    try:
        conn.executescript(SCHEMA_SQL)
        conn.execute(
            "INSERT INTO danmaku (timestamp, room_id, msg_type, username, content) "
            "VALUES (?, ?, ?, ?, ?)",
            ("2026-03-07 10:00:00.000000", "6657", "chatmsg", "alice", "hi"),
        )
        conn.commit()
    finally:
        conn.close()

    with DataDb(run_file) as db:
        rows = db.query("SELECT username, content FROM danmaku_all WHERE room_id = ?", ("6657",))

    assert rows == [("alice", "hi")]
