"""SQLite data access: one run file, or a directory of run files.

Both modes expose the same ``danmaku_all`` relation, so command SQL never
changes between them. Three things make directory mode survive a real data
directory rather than only a clean test fixture:

- **Column-adaptive projection.** The expected columns come from
  ``dykit.schema``; the ones a given file actually has come from
  ``PRAGMA table_info``. Missing ones are projected as ``NULL AS <name>``, so
  a run file written by an older version stays readable after the schema
  gains a column (and extra columns are ignored, as always).
- **Bounded ATTACH.** SQLite allows at most ten attached databases, so large
  directories are drained into a temp table in batches. The temp table is
  SQLite-managed (not Python memory) and carries the source indexes, so peak
  memory stays proportional to one file, not to the corpus.
- **Read-only access.** Every file is attached with ``file:...?mode=ro``, so
  SQLite rejects any write - analysis can never mutate a run, even one a
  collector is still appending to. (SQLite still creates ``-wal``/``-shm``
  sidecars for WAL-mode databases; that is required to read a WAL database and
  does not modify the run itself.)
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Sequence
from pathlib import Path
from types import TracebackType

from ..schema import DANMAKU_VIEW_COLUMNS, columns_sql

#: SQLite's compiled-in ceiling on ATTACHed databases.
MAX_ATTACHED = 10

_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS temp.idx_all_room_ts ON danmaku_all(room_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS temp.idx_all_msg_type ON danmaku_all(msg_type);
"""


def _projection_for(conn: sqlite3.Connection, schema: str) -> str:
    """Column list for the run table in `schema`, filling NULLs for absent columns."""
    available = {row[1] for row in conn.execute(f"PRAGMA {schema}.table_info(danmaku)")}
    if not available:
        raise sqlite3.OperationalError(f"no danmaku table in schema {schema!r}")
    return columns_sql(
        [name if name in available else f"NULL AS {name}" for name in DANMAKU_VIEW_COLUMNS]
    )


class DataDb:
    """Read-only wrapper over one SQLite run file or a directory of run files."""

    def __init__(self, path: Path) -> None:
        self.files: list[Path] = []
        self.skipped_files: list[Path] = []
        self._conn: sqlite3.Connection | None = None

        try:
            self._open(path)
        except BaseException:
            # `with DataDb(...)` never binds when the constructor raises, so
            # nothing else would ever close this connection.
            if self._conn is not None:
                self._conn.close()
                self._conn = None
            raise

    def _open(self, path: Path) -> None:
        if path.is_file():
            self.files = [path]
            conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
            # Assign before building the view: if the view creation fails the
            # constructor's handler must already be able to close this.
            self._conn = conn
            conn.execute(
                f"CREATE TEMP VIEW danmaku_all AS SELECT {_projection_for(conn, 'main')}"
                " FROM main.danmaku"
            )
            return
        if not path.is_dir():
            raise ValueError(f"Data path is neither file nor directory: {path}")

        self._conn = sqlite3.connect(":memory:", uri=True)
        # uri=True is what lets ATTACH take `file:...?mode=ro`, so analysing a
        # run never creates -wal/-shm files or takes a write lock on a file a
        # collector may still be appending to.
        # Keep the temp table on disk rather than in RAM: the corpus can be far
        # larger than memory.
        self._conn.execute("PRAGMA temp_store=FILE")

        candidates = sorted(p for p in path.glob("*.db") if p.is_file())
        readable: list[Path] = []
        for file in candidates:
            if self._is_readable(file):
                readable.append(file)
            else:
                self.skipped_files.append(file)
        self.files = readable

        if not self.files:
            self._create_empty_view()
            return

        if len(self.files) <= MAX_ATTACHED:
            self._create_union_view()
        else:
            self._materialise()

    @staticmethod
    def _is_readable(path: Path) -> bool:
        """Can this file be opened and does it actually hold run data?

        Directory mode skips whatever fails here instead of letting one stray
        ``.db`` take down every command.
        """
        try:
            probe = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        except sqlite3.Error:
            return False
        try:
            probe.execute("SELECT 1 FROM main.danmaku LIMIT 1").fetchall()
        except sqlite3.Error:
            return False
        finally:
            probe.close()
        return True

    def _conn_or_raise(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("DataDb is closed")
        return self._conn

    def _create_empty_view(self) -> None:
        null_row = ", ".join(f"NULL AS {name}" for name in DANMAKU_VIEW_COLUMNS)
        self._conn_or_raise().execute(
            "CREATE TEMP VIEW danmaku_all AS "
            f"SELECT {columns_sql(DANMAKU_VIEW_COLUMNS)} FROM (SELECT {null_row} WHERE 0)"
        )

    def _create_union_view(self) -> None:
        conn = self._conn_or_raise()
        parts: list[str] = []
        for index, file in enumerate(self.files):
            alias = f"run_{index}"
            conn.execute(f"ATTACH DATABASE ? AS {alias}", (f"file:{file.as_posix()}?mode=ro",))
            projection = _projection_for(conn, alias)
            parts.append(f"SELECT {projection} FROM {alias}.danmaku")
        conn.execute("CREATE TEMP VIEW danmaku_all AS " + " UNION ALL ".join(parts))

    def _materialise(self) -> None:
        """Drain every file into one temp table, ten at a time.

        Needed because ATTACH is capped at ten databases, and because it keeps
        arbitrary SQL (aggregates, window functions, subqueries) correct: the
        alternative - querying each file separately and merging in Python -
        silently breaks anything whose LIMIT is meant to apply globally.
        """
        conn = self._conn_or_raise()
        conn.execute(f"CREATE TEMP TABLE danmaku_all ({columns_sql(_table_ddl_columns())})")

        for start in range(0, len(self.files), MAX_ATTACHED):
            batch = self.files[start : start + MAX_ATTACHED]
            attached: list[str] = []
            for index, file in enumerate(batch):
                alias = f"run_{index}"
                conn.execute(f"ATTACH DATABASE ? AS {alias}", (f"file:{file.as_posix()}?mode=ro",))
                attached.append(alias)
                projection = _projection_for(conn, alias)
                # Close the cursor explicitly: SQLite refuses to DETACH a
                # database that still has a prepared statement open on it, and
                # a discarded cursor is not guaranteed to be finalised in time.
                cursor = conn.execute(
                    f"INSERT INTO temp.danmaku_all SELECT {projection} FROM {alias}.danmaku"
                )
                cursor.close()
            conn.commit()
            for alias in attached:
                conn.execute(f"DETACH DATABASE {alias}")

        conn.executescript(_INDEX_SQL)

    def query(self, sql: str, params: Sequence[object] = ()) -> list[sqlite3.Row]:
        """Execute a SELECT against the union view and return all rows."""
        conn = self._conn_or_raise()
        cursor = conn.execute(sql, params)
        return cursor.fetchall()

    def query_each(self, sql: str, params: Sequence[object] = ()) -> Iterable[sqlite3.Row]:
        """Stream a SELECT instead of materialising it, for large results."""
        return self._conn_or_raise().execute(sql, params)

    def close(self) -> None:
        """Close the underlying connection(s). Idempotent."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> DataDb:
        return self

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc_val: BaseException | None,
        _exc_tb: TracebackType | None,
    ) -> None:
        self.close()


def _table_ddl_columns() -> list[str]:
    from ..schema import DANMAKU_SCHEMA

    return [column.definition() for column in DANMAKU_SCHEMA if column.name in DANMAKU_VIEW_COLUMNS]
