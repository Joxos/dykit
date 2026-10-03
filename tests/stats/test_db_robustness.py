"""Guarantees the reader owes a real data directory.

Each of these was a way ``dykit-stats`` used to fail outright.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from dykit.schema import SCHEMA_SQL
from dykit.stats.db import MAX_ATTACHED, DataDb

ROOM = "6657"


def _seed(path: Path, rows: list[tuple[str, str]]) -> None:
    conn = sqlite3.connect(str(path))
    conn.executescript(SCHEMA_SQL)
    conn.executemany(
        "INSERT INTO danmaku (timestamp, room_id, msg_type, content) VALUES (?,?,?,?)",
        [(ts, ROOM, "chatmsg", c) for ts, c in rows],
    )
    conn.commit()
    conn.close()


def _dir_with(tmp_path: Path, count: int) -> Path:
    directory = tmp_path / "dycap-data"
    directory.mkdir(exist_ok=True)
    for i in range(count):
        _seed(directory / f"{ROOM}_{i}.db", [(f"2026-03-07 10:00:0{i}.000000", f"msg-{i}")])
    return directory


class TestAttachCeiling:
    def test_more_than_ten_files_still_works(self, tmp_path: Path) -> None:
        """SQLite caps ATTACH at ten; a month of run files must not break analysis."""
        directory = _dir_with(tmp_path, 25)

        with DataDb(directory) as db:
            assert len(db.files) == 25
            assert db.query("SELECT COUNT(*) FROM danmaku_all")[0][0] == 25

    def test_large_directory_matches_a_small_one(self, tmp_path: Path) -> None:
        """The >10 materialisation path must give identical results to the view."""
        directory = _dir_with(tmp_path, 14)
        same = tmp_path / "same"
        same.mkdir()
        for i in range(14):
            _seed(same / f"{ROOM}_{i}.db", [(f"2026-03-07 10:00:0{i}.000000", f"msg-{i}")])

        sql = "SELECT content FROM danmaku_all ORDER BY content"
        with DataDb(directory) as big, DataDb(same) as small:
            assert [tuple(r) for r in big.query(sql)] == [tuple(r) for r in small.query(sql)]

        assert len(DataDb(directory).files) == 14

    def test_global_aggregation_is_exact(self, tmp_path: Path) -> None:
        """Per-file merging would break a LIMIT meant to apply corpus-wide."""
        directory = tmp_path / "dycap-data"
        directory.mkdir()
        # File i holds i+1 copies of `shared-{i}`. The corpus-wide top two are
        # therefore shared-13 and shared-12, which are not top rows inside any
        # single ten-file batch.
        for i in range(12):
            path = directory / f"{ROOM}_{i}.db"
            _seed(path, [])
            conn = sqlite3.connect(str(path))
            for j in range(i + 1):
                conn.execute(
                    "INSERT INTO danmaku (timestamp, room_id, msg_type, content) VALUES (?,?,?,?)",
                    (f"2026-03-07 11:00:{j:02d}.000000", ROOM, "chatmsg", f"shared-{i}"),
                )
            conn.commit()
            conn.close()

        with DataDb(directory) as db:
            rows = db.query(
                "SELECT content, COUNT(*) AS n FROM danmaku_all"
                " GROUP BY content ORDER BY n DESC, content LIMIT 2"
            )

        assert [r[0] for r in rows] == ["shared-11", "shared-10"]
        assert rows[0][1] == 12, "the count must span every file, not one batch"


class TestBadFiles:
    def test_a_corrupt_file_is_skipped_not_fatal(self, tmp_path: Path) -> None:
        directory = _dir_with(tmp_path, 3)
        (directory / "notes.db").write_bytes(b"not a database")
        (directory / "empty.db").write_bytes(b"")

        with DataDb(directory) as db:
            assert db.query("SELECT COUNT(*) FROM danmaku_all")[0][0] == 3
            assert len(db.skipped_files) == 2

    def test_an_unrelated_sqlite_file_is_skipped(self, tmp_path: Path) -> None:
        """A valid SQLite file that is not a run file must not poison the query."""
        directory = _dir_with(tmp_path, 2)
        other = sqlite3.connect(str(directory / "scratch.db"))
        other.execute("CREATE TABLE notes(x)")
        other.commit()
        other.close()

        with DataDb(directory) as db:
            assert db.query("SELECT COUNT(*) FROM danmaku_all")[0][0] == 2
            assert [p.name for p in db.skipped_files] == ["scratch.db"]

    def test_all_files_bad_is_an_empty_result_not_a_crash(self, tmp_path: Path) -> None:
        directory = tmp_path / "dycap-data"
        directory.mkdir()
        (directory / "junk.db").write_bytes(b"nope")

        with DataDb(directory) as db:
            assert db.query("SELECT COUNT(*) FROM danmaku_all")[0][0] == 0
            assert db.skipped_files


class TestSchemaAdaptivity:
    def test_a_file_missing_a_new_column_is_still_readable(self, tmp_path: Path) -> None:
        """Old run files must survive a schema addition."""
        path = tmp_path / "old.db"
        conn = sqlite3.connect(str(path))
        conn.executescript(
            "CREATE TABLE danmaku (id INTEGER PRIMARY KEY, timestamp TEXT NOT NULL,"
            " room_id TEXT NOT NULL, msg_type TEXT NOT NULL, content TEXT);"
        )
        conn.execute(
            "INSERT INTO danmaku (timestamp, room_id, msg_type, content) VALUES (?,?,?,?)",
            ("2026-03-07 10:00:00.000000", ROOM, "chatmsg", "legacy"),
        )
        conn.commit()
        conn.close()

        with DataDb(path) as db:
            row = db.query("SELECT content, username FROM danmaku_all")[0]

        assert row[0] == "legacy"
        assert row[1] is None, "absent columns project as NULL, not as an error"

    def test_missing_path_is_still_an_error(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="neither file nor directory"):
            DataDb(tmp_path / "nope")


class TestResourceHandling:
    def test_failed_construction_does_not_leak_the_connection(self, tmp_path: Path) -> None:
        """Pointing --data at a file that is not a run file must not lock it.

        The constructor opens the connection before it can discover the file
        has no danmaku table, and ``with DataDb(...)`` never binds when the
        constructor raises - so the constructor itself has to clean up.
        """
        path = tmp_path / "not_a_run.db"
        conn = sqlite3.connect(str(path))
        conn.execute("CREATE TABLE notes(x)")
        conn.execute("INSERT INTO notes VALUES (1)")
        conn.commit()
        conn.close()

        with pytest.raises(sqlite3.OperationalError, match="danmaku"):
            DataDb(path)

        # A leaked handle keeps the file open on Windows.
        path.replace(tmp_path / "renamed.db")
        assert (tmp_path / "renamed.db").exists()

    def test_close_is_idempotent(self, tmp_path: Path) -> None:
        db = DataDb(_dir_with(tmp_path, 1))
        db.close()
        db.close()
        with pytest.raises(RuntimeError, match="closed"):
            db.query("SELECT 1")


class TestReadOnlyAccess:
    def test_analysis_cannot_write_to_a_run_file(self, tmp_path: Path) -> None:
        """The guarantee that matters: reading never mutates the run."""
        directory = _dir_with(tmp_path, 2)
        run = directory / f"{ROOM}_0.db"
        conn = sqlite3.connect(":memory:", uri=True)
        conn.execute("ATTACH DATABASE ? AS r0", (f"file:{run.as_posix()}?mode=ro",))
        try:
            with pytest.raises(sqlite3.OperationalError, match="readonly"):
                conn.execute(
                    "INSERT INTO r0.danmaku (timestamp, room_id, msg_type, content) VALUES (?,?,?,?)",
                    ("2026-03-07 12:00:00.000000", ROOM, "chatmsg", "injected"),
                )
            conn.commit()
        finally:
            conn.close()

        with DataDb(directory) as db:
            contents = [r[0] for r in db.query("SELECT content FROM danmaku_all ORDER BY content")]

        assert "injected" not in contents

    def test_the_run_files_are_left_byte_identical(self, tmp_path: Path) -> None:
        """Reading must not touch a run's bytes."""
        directory = _dir_with(tmp_path, 3)
        before = {path.name: path.read_bytes() for path in sorted(directory.glob("*.db"))}

        with DataDb(directory) as db:
            db.query("SELECT COUNT(*) FROM danmaku_all")

        for path in sorted(directory.glob("*.db")):
            assert path.read_bytes() == before[path.name], f"{path.name} was modified"


def test_max_attached_matches_sqlite() -> None:
    assert MAX_ATTACHED == 10
