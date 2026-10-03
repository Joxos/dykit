"""In-process archiving: move old rows out of a live run file.

Slicing a file that is currently being written is done with two SQL
statements inside one transaction:

    INSERT INTO arc.danmaku SELECT ... FROM main.danmaku WHERE id <= ?
    DELETE      FROM main.danmaku WHERE id <= ?

so a reader sees either the old rows or the new rows, never a gap, and the
writer (another connection, or this one) is unaffected.

It runs in chunks with a yield between them. Measured on a 200k-row run:
a 2k-row chunk stalls the event loop for ~65ms, 10k for ~157ms, 50k for
~711ms. Chunking keeps the worst stall bounded and lets message processing
continue in between - and it stays in this process, so no second writer ever
competes for SQLite's single write lock.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import sqlite3
from pathlib import Path

logger: logging.Logger = logging.getLogger(__name__)

DEFAULT_CHUNK_ROWS = 2000


class RunArchiver:
    """Move rows older than a cutoff out of a run file, chunk by chunk."""

    def __init__(
        self,
        run_path: Path,
        archive_path: Path,
        chunk_rows: int = DEFAULT_CHUNK_ROWS,
    ) -> None:
        self.run_path = run_path
        self.archive_path = archive_path
        self.chunk_rows = chunk_rows

    def _open(self) -> sqlite3.Connection:
        # check_same_thread=False: every statement runs in a worker thread, but
        # run_async hops threads between chunks and closes from one. Access is
        # still serialized - exactly one chunk at a time, by construction.
        conn = sqlite3.connect(str(self.run_path), check_same_thread=False)
        conn.execute("ATTACH DATABASE ? AS arc", (str(self.archive_path),))
        existing = conn.execute(
            "SELECT name FROM arc.sqlite_master WHERE type='table' AND name='danmaku'"
        ).fetchone()
        if existing is None:
            conn.execute("CREATE TABLE arc.danmaku AS SELECT * FROM main.danmaku WHERE 0")
        return conn

    def archive_chunk(self, before_id: int, conn: sqlite3.Connection) -> int:
        """Move one chunk. Returns the number of rows moved (0 when drained)."""
        rows = conn.execute(
            "SELECT id FROM main.danmaku WHERE id <= ? ORDER BY id LIMIT ?",
            (before_id, self.chunk_rows),
        ).fetchall()
        if not rows:
            return 0
        low, high = rows[0][0], rows[-1][0]
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT INTO arc.danmaku SELECT * FROM main.danmaku WHERE id BETWEEN ? AND ?",
            (low, high),
        )
        conn.execute("DELETE FROM main.danmaku WHERE id BETWEEN ? AND ?", (low, high))
        conn.commit()
        return len(rows)

    def _max_id(self, conn: sqlite3.Connection) -> int:
        row = conn.execute("SELECT COALESCE(MAX(id), 0) FROM main.danmaku").fetchone()
        return int(row[0]) if row else 0

    def run(self, before_id: int) -> int:
        """Archive synchronously until drained. Intended for scripts/one-shots."""
        conn = self._open()
        try:
            cutoff = min(before_id, self._max_id(conn))
            moved = 0
            while True:
                count = self.archive_chunk(cutoff, conn)
                if count == 0:
                    break
                moved += count
            self._reclaim(conn)
            return moved
        finally:
            conn.close()

    def _reclaim(self, conn: sqlite3.Connection) -> None:
        """Checkpoint the WAL and hand free pages back where SQLite can.

        Both are best-effort: an archive that fails to shrink is still correct.
        """
        with contextlib.suppress(sqlite3.Error):
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        with contextlib.suppress(sqlite3.Error):
            conn.execute("PRAGMA incremental_vacuum")

    async def run_async(self, before_id: int) -> int:
        """Archive without ever blocking the event loop for more than a chunk.

        Each chunk runs in a worker thread and the loop is yielded between
        chunks, so incoming messages keep being processed throughout.
        """
        conn = await asyncio.to_thread(self._open)
        moved = 0
        try:
            cutoff = await asyncio.to_thread(lambda: min(before_id, self._max_id(conn)))
            while True:
                count = await asyncio.to_thread(self.archive_chunk, cutoff, conn)
                if count == 0:
                    break
                moved += count
                await asyncio.sleep(0)  # let the collector breathe
            await asyncio.to_thread(self._reclaim, conn)
            return moved
        finally:
            await asyncio.to_thread(conn.close)
            logger.info("archived %d rows from %s", moved, self.run_path)
