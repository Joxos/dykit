"""The analysis plugin layer.

Two properties matter and are asserted here:

* **The work is pushed into SQL.** An analysis returns a Query; it never
  pulls the corpus into Python to aggregate it there. The `latest_unique`
  tests check the uniqueness predicate lives in the SQL, not the post-pass.
* **Plugins are pluggable.** A third-party analysis registers and runs through
  the same path as a built-in.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import pytest

from dykit.schema import SCHEMA_SQL
from dykit.stats.analysis import Param, Query, available, get, register, reset, run
from dykit.stats.cluster import ClusterResult
from dykit.stats.db import DataDb
from dykit.stats.rank import RankResult

ROOM = "6657"


def _seed(path: Path, rows: list[tuple[str, str, str]]) -> None:
    """rows: (timestamp, username, content)"""
    conn = sqlite3.connect(str(path))
    conn.executescript(SCHEMA_SQL)
    conn.executemany(
        "INSERT INTO danmaku (timestamp, room_id, msg_type, username, content) VALUES (?,?,?,?,?)",
        [(ts, ROOM, "chatmsg", user, content) for ts, user, content in rows],
    )
    conn.commit()
    conn.close()


@pytest.fixture
def seeded(tmp_path: Path) -> Path:
    _seed(
        tmp_path / "run.db",
        [
            ("2026-03-07 10:00:00.000000", "alice", "hello"),
            ("2026-03-07 10:01:00.000000", "bob", "world"),
            ("2026-03-07 10:02:00.000000", "alice", "hello"),
            ("2026-03-07 10:03:00.000000", "carol", "fresh"),
        ],
    )
    return tmp_path / "run.db"


class TestRegistry:
    def test_builtins_are_available(self) -> None:
        assert "rank" in available()
        assert "search" in available()
        assert "latest_unique" in available()

    def test_unknown_name_lists_what_is_available(self) -> None:
        with pytest.raises(KeyError, match="available"):
            get("no-such-analysis")

    def test_duplicate_registration_is_refused(self) -> None:
        analysis = get("rank")
        with pytest.raises(ValueError, match="already registered"):
            register(analysis)

    def test_replace_allows_an_override(self) -> None:
        original = get("rank")
        try:

            @dataclass(frozen=True)
            class _Override:
                name: str = "rank"
                summary: str = "overridden"
                params: tuple[Param, ...] = ()

                def make_options(self, **overrides: object) -> object:
                    _ = overrides
                    return object()

                def build_query(self, options: object) -> Query:
                    _ = options
                    return Query(sql="SELECT 1", columns=("n",))

                def rows_to_result(self, rows: Iterator[sqlite3.Row], options: object) -> object:
                    _ = options
                    return list(rows)

            register(_Override(), replace=True)
            assert get("rank").summary == "overridden"
        finally:
            register(original, replace=True)

    def test_a_broken_plugin_does_not_break_the_cli(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import dykit.stats.analysis.registry as registry_module

        def exploding(_group: str) -> object:
            raise RuntimeError("entry points unavailable")

        monkeypatch.setattr(registry_module, "entry_points", exploding)
        reset()
        registry_module.load_entry_points()  # must not raise

    def test_plugins_load_from_entry_points(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import dykit.stats.analysis.registry as registry_module

        @dataclass(frozen=True)
        class _Plugin:
            name: str = "from_entry_point"
            summary: str = "loaded externally"
            params: tuple[Param, ...] = ()

            def make_options(self, **overrides: object) -> object:
                _ = overrides
                return object()

            def build_query(self, options: object) -> Query:
                _ = options
                return Query(sql="SELECT 1", columns=("n",))

            def rows_to_result(self, rows: Iterator[sqlite3.Row], options: object) -> object:
                _ = options
                return list(rows)

        class _Entry:
            name = "external"

            @staticmethod
            def load() -> type[_Plugin]:
                return _Plugin

        def fake_entry_points(group: str) -> list[_Entry]:
            assert group == registry_module.ENTRY_POINT_GROUP
            return [_Entry()]

        monkeypatch.setattr(registry_module, "entry_points", fake_entry_points)
        reset()
        try:
            registry_module.load_entry_points()
            assert get("from_entry_point").summary == "loaded externally"
        finally:
            registry_module.reset()
            reset()


class TestRankThroughThePlugin:
    def test_returns_exactly_what_the_library_function_returns(self, seeded: Path) -> None:
        """The strongest form of "one code path": identical output, not similar."""
        from dykit.stats.rank import rank

        with DataDb(seeded) as db:
            plugin_result = cast("list[RankResult]", run(get("rank"), db, room=ROOM, mode="user"))
        expected = rank(seeded, ROOM, mode="user")

        assert plugin_result == expected
        assert [(r.rank, r.value, r.count) for r in plugin_result] == [
            (1, "alice", 2),
            (2, "bob", 1),
            (3, "carol", 1),
        ]

    def test_window_options_reach_sql(self, seeded: Path) -> None:
        with DataDb(seeded) as db:
            result = cast("list[RankResult]", run(get("rank"), db, room=ROOM, top=1))

        assert [(r.value, r.count) for r in result] == [("alice", 2)]

    def test_conflicting_days_and_range_is_rejected(self, seeded: Path) -> None:
        with DataDb(seeded) as db, pytest.raises(ValueError, match="--days"):
            run(get("rank"), db, room=ROOM, days=3, from_date="2026-03-01")

    def test_unknown_option_is_rejected(self, seeded: Path) -> None:
        with DataDb(seeded) as db, pytest.raises(ValueError, match="unknown option"):
            run(get("rank"), db, room=ROOM, nonsense=1)


class TestClusterThroughThePlugin:
    """Clustering is the case where a Python pass is genuinely needed."""

    def test_returns_exactly_what_the_library_function_returns(self, seeded: Path) -> None:
        from dykit.stats.cluster import cluster

        with DataDb(seeded) as db:
            plugin_result = cast(
                "list[ClusterResult]", run(get("cluster"), db, room=ROOM, threshold=0.5)
            )
        expected = cluster(seeded, ROOM, threshold=0.5)

        assert plugin_result == expected
        # The two identical "hello" rows are grouped by SQL COUNT(*), so the
        # representative carries count 2 before any fuzzy pass runs; the rest
        # tie at 1 and are ordered by content.
        assert [c.representative for c in plugin_result] == ["hello", "fresh", "world"]
        assert plugin_result[0].count == 2

    def test_candidates_are_capped_in_sql(self, seeded: Path) -> None:
        """The expensive part must not run over the whole corpus."""
        options = get("cluster").make_options(room=ROOM, limit=7)
        query = get("cluster").build_query(options)

        assert "LIMIT ?" in query.sql
        assert query.params[-1] == 7

    def test_threshold_reaches_the_grouping_pass(self, seeded: Path) -> None:
        """Threshold is not applied in SQL (no SQL equivalent), so it must be threaded."""
        from dykit.stats.cluster import cluster

        for threshold in (0.0, 0.5, 0.99):
            with DataDb(seeded) as db:
                plugin_result = cast(
                    "list[ClusterResult]",
                    run(get("cluster"), db, room=ROOM, threshold=threshold),
                )
            assert plugin_result == cluster(seeded, ROOM, threshold=threshold)

    def test_cluster_is_a_registered_analysis(self) -> None:
        assert "cluster" in available()


class TestLatestUnique:
    def test_reports_unseen_content_newest_first(self, tmp_path: Path) -> None:
        _seed(
            tmp_path / "run.db",
            [
                ("2026-03-07 10:00:00.000000", "alice", "old"),
                ("2026-03-07 10:01:00.000000", "bob", "brand new"),
            ],
        )

        with DataDb(tmp_path / "run.db") as db:
            result = run(
                get("latest_unique"),
                db,
                room=ROOM,
                seen_sql="SELECT 'old'",
            )

        contents = [row[2] for row in cast("list[sqlite3.Row]", result)]
        assert contents == ["brand new"]

    def test_uniqueness_is_decided_in_sql(self, tmp_path: Path) -> None:
        """The predicate must be in the query, not in a Python post-pass."""
        _seed(tmp_path / "run.db", [("2026-03-07 10:00:00.000000", "a", "x")])
        query = get("latest_unique").build_query(_options(room=ROOM))

        assert "NOT IN" in query.sql
        assert "ORDER BY fresh.id DESC" in query.sql

    def test_content_is_required_to_be_present(self, tmp_path: Path) -> None:
        """A gift message has no content; it must not count as unique text."""
        _seed(tmp_path / "run.db", [])
        conn = sqlite3.connect(str(tmp_path / "run.db"))
        conn.execute(
            "INSERT INTO danmaku (timestamp, room_id, msg_type, content) VALUES (?,?,?,?)",
            ("2026-03-07 10:00:00.000000", ROOM, "dgb", None),
        )
        conn.commit()
        conn.close()

        with DataDb(tmp_path / "run.db") as db:
            result = run(get("latest_unique"), db, room=ROOM)

        assert result == []


def _options(**kwargs: object) -> object:
    """Build typed options without repeating the internal cast in tests."""
    return get("latest_unique").make_options(**kwargs)


class TestContract:
    def test_every_builtin_declares_its_options(self) -> None:
        for name in available():
            analysis = get(name)
            assert analysis.summary, f"{name} has no summary"
            for param in analysis.params:
                assert param.flag.startswith("--")
                assert param.help, f"{name}.{param.name} has no help"

    def test_run_executes_exactly_one_query(self, seeded: Path) -> None:
        """An analysis may stream its result, but it must not re-query."""
        calls: list[str] = []

        class _CountingDb:
            def query(self, sql: str, params: object) -> list[sqlite3.Row]:
                calls.append(sql)
                return []

        run(get("rank"), _CountingDb(), room=ROOM)

        assert len(calls) == 1
