"""Tests for the stats CLI (rank, cluster, search).

These test the CLI's own job: resolving the room/data path, handing the
options to the right registered analysis, and turning failures into exit
codes. The analyses themselves are covered by ``tests/stats/test_analysis.py``;
running them for real against run files is covered by
``tests/integration``.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from dykit.stats.cli import app

from ..cli_test_runner import CliRunner

PATCH_RUN = "dykit.stats.cli.run_analysis"
FAKE_DATA = "some/path.db"


@pytest.fixture(autouse=True)
def _stub_db(monkeypatch: pytest.MonkeyPatch) -> None:
    """DataDb is exercised elsewhere; here only the plumbing is under test."""
    fake_db = MagicMock()
    fake_db.return_value.__enter__.return_value = fake_db
    monkeypatch.setattr("dykit.stats.cli.DataDb", fake_db)


def _called(mock: MagicMock) -> dict[str, Any]:
    """Pull analysis name + options back out of the run_analysis mock."""
    positional, keywords = mock.call_args
    return {"analysis": positional[0].name, "kwargs": dict(keywords)}


class TestRuntimeResolution:
    def test_room_and_data_are_resolved_before_running(self, runner: CliRunner) -> None:
        with patch(PATCH_RUN, return_value=[]) as mock_run:
            result = runner.invoke(app, ["rank", "--data", FAKE_DATA, "-r", "6657"])

        assert result.exit_code == 0
        assert _called(mock_run) == {
            "analysis": "rank",
            "kwargs": {
                "room": "6657",
                "top": 10,
                "mode": "user",
                "msg_type": "chatmsg",
                "days": None,
                "username": None,
                "user_id": None,
                "from_date": None,
                "to_date": None,
                "last": None,
                "first": None,
            },
        }

    def test_missing_data_path_is_a_cli_error(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from dykit.stats.runtime import resolve_runtime

        monkeypatch.setattr("dykit.stats.cli.resolve_runtime", resolve_runtime)

        with patch(PATCH_RUN, return_value=[]):
            result = runner.invoke(app, ["rank", "--data", "no/such/dir", "-r", "6657"])

        assert result.exit_code == 1
        assert "Data path not found" in result.output

    def test_query_failure_is_a_cli_error(self, runner: CliRunner) -> None:
        with patch(PATCH_RUN, side_effect=sqlite3.Error("db failed")):
            result = runner.invoke(app, ["rank", "--data", FAKE_DATA, "-r", "6657"])

        assert result.exit_code == 1
        assert "Error" in result.output

    def test_unknown_analysis_is_a_cli_error(self, runner: CliRunner) -> None:
        with patch(PATCH_RUN, side_effect=KeyError("nope")):
            result = runner.invoke(app, ["rank", "--data", FAKE_DATA, "-r", "6657"])

        assert result.exit_code == 1


class TestRankCommand:
    def test_defaults(self, runner: CliRunner) -> None:
        with patch(PATCH_RUN, return_value=[]) as mock_run:
            result = runner.invoke(app, ["rank", "--data", FAKE_DATA, "-r", "6657"])

        assert result.exit_code == 0
        assert _called(mock_run)["analysis"] == "rank"

    def test_renders_a_table(self, runner: CliRunner) -> None:
        from dykit.stats.rank import RankResult

        rows = [RankResult(rank=1, value="alice", count=42)]
        with patch(PATCH_RUN, return_value=rows):
            result = runner.invoke(app, ["rank", "--data", FAKE_DATA, "-r", "6657"])

        assert result.exit_code == 0
        assert "alice" in result.output
        assert "42" in result.output

    def test_by_option_is_forwarded(self, runner: CliRunner) -> None:
        with patch(PATCH_RUN, return_value=[]) as mock_run:
            result = runner.invoke(
                app, ["rank", "--data", FAKE_DATA, "-r", "6657", "--by", "content"]
            )

        assert result.exit_code == 0
        assert _called(mock_run)["kwargs"]["mode"] == "content"

    def test_days_is_forwarded(self, runner: CliRunner) -> None:
        with patch(PATCH_RUN, return_value=[]) as mock_run:
            result = runner.invoke(app, ["rank", "--data", FAKE_DATA, "-r", "6657", "--days", "7"])

        assert result.exit_code == 0
        assert _called(mock_run)["kwargs"]["days"] == 7

    def test_last_is_forwarded(self, runner: CliRunner) -> None:
        with patch(PATCH_RUN, return_value=[]) as mock_run:
            result = runner.invoke(app, ["rank", "--data", FAKE_DATA, "-r", "6657", "--last", "10"])

        assert result.exit_code == 0
        assert _called(mock_run)["kwargs"]["last"] == 10

    def test_top_is_forwarded(self, runner: CliRunner) -> None:
        with patch(PATCH_RUN, return_value=[]) as mock_run:
            result = runner.invoke(app, ["rank", "--data", FAKE_DATA, "-r", "6657", "--top", "3"])

        assert result.exit_code == 0
        assert _called(mock_run)["kwargs"]["top"] == 3


class TestClusterCommand:
    def test_defaults(self, runner: CliRunner) -> None:
        with patch(PATCH_RUN, return_value=[]) as mock_run:
            result = runner.invoke(app, ["cluster", "--data", FAKE_DATA, "-r", "6657"])

        assert result.exit_code == 0
        assert _called(mock_run) == {
            "analysis": "cluster",
            "kwargs": {
                "room": "6657",
                "threshold": 0.5,
                "msg_type": "chatmsg",
                "limit": 50,
                "username": None,
                "user_id": None,
                "from_date": None,
                "to_date": None,
                "last": None,
                "first": None,
                "days": None,
            },
        }

    def test_renders_clusters(self, runner: CliRunner) -> None:
        from dykit.stats.cluster import ClusterResult

        rows = [
            ClusterResult(
                representative="hello world",
                count=5,
                similar=[("hello world", 3), ("hello worlds", 2)],
            )
        ]
        with patch(PATCH_RUN, return_value=rows):
            result = runner.invoke(app, ["cluster", "--data", FAKE_DATA, "-r", "6657"])

        assert result.exit_code == 0
        assert "hello world" in result.output

    def test_options_are_forwarded(self, runner: CliRunner) -> None:
        with patch(PATCH_RUN, return_value=[]) as mock_run:
            result = runner.invoke(
                app,
                [
                    "cluster",
                    "--data",
                    FAKE_DATA,
                    "-r",
                    "6657",
                    "--threshold",
                    "0.7",
                    "--limit",
                    "100",
                    "--type",
                    "dgb",
                ],
            )

        assert result.exit_code == 0
        kwargs = _called(mock_run)["kwargs"]
        assert kwargs["threshold"] == 0.7
        assert kwargs["limit"] == 100
        assert kwargs["msg_type"] == "dgb"

    def test_first_is_forwarded(self, runner: CliRunner) -> None:
        with patch(PATCH_RUN, return_value=[]) as mock_run:
            result = runner.invoke(
                app, ["cluster", "--data", FAKE_DATA, "-r", "6657", "--first", "20"]
            )

        assert result.exit_code == 0
        assert _called(mock_run)["kwargs"]["first"] == 20


class TestSearchCommand:
    def test_defaults(self, runner: CliRunner) -> None:
        with patch(PATCH_RUN, return_value=[]) as mock_run:
            result = runner.invoke(app, ["search", "--data", FAKE_DATA, "-r", "6657"])

        assert result.exit_code == 0
        assert _called(mock_run) == {
            "analysis": "search",
            "kwargs": {
                "room": "6657",
                "content": None,
                "username": None,
                "user_id": None,
                "msg_type": None,
                "from_date": None,
                "to_date": None,
                "last": None,
                "first": None,
            },
        }

    def test_renders_rows(self, runner: CliRunner) -> None:
        from dykit.stats.search import SearchResult

        rows = [
            SearchResult(
                timestamp=datetime(2026, 3, 8, 12, 0, 0),
                username="alice",
                content="test message",
                msg_type="chatmsg",
            )
        ]
        with patch(PATCH_RUN, return_value=rows):
            result = runner.invoke(
                app, ["search", "--data", FAKE_DATA, "-r", "6657", "--content", "x"]
            )

        assert result.exit_code == 0
        assert "alice" in result.output
        assert "test message" in result.output

    def test_content_becomes_the_content_option(self, runner: CliRunner) -> None:
        with patch(PATCH_RUN, return_value=[]) as mock_run:
            result = runner.invoke(
                app, ["search", "--data", FAKE_DATA, "-r", "6657", "--content", "y"]
            )

        assert result.exit_code == 0
        assert _called(mock_run)["kwargs"]["content"] == "y"

    def test_filters_are_forwarded(self, runner: CliRunner) -> None:
        with patch(PATCH_RUN, return_value=[]) as mock_run:
            result = runner.invoke(
                app,
                [
                    "search",
                    "--data",
                    FAKE_DATA,
                    "-r",
                    "6657",
                    "--user",
                    "alice",
                    "--user-id",
                    "uid1",
                    "--type",
                    "chatmsg",
                    "--from",
                    "2026-03-01",
                    "--to",
                    "2026-03-07",
                ],
            )

        assert result.exit_code == 0
        kwargs = _called(mock_run)["kwargs"]
        assert kwargs["username"] == "alice"
        assert kwargs["user_id"] == "uid1"
        assert kwargs["msg_type"] == "chatmsg"
        assert kwargs["from_date"] == "2026-03-01"
        assert kwargs["to_date"] == "2026-03-07"

    def test_username_alias(self, runner: CliRunner) -> None:
        """`--username` is the shared spelling; `--user` stays as an alias."""
        with patch(PATCH_RUN, return_value=[]) as mock_run:
            result = runner.invoke(
                app, ["search", "--data", FAKE_DATA, "-r", "6657", "--username", "a"]
            )

        assert result.exit_code == 0
        assert _called(mock_run)["kwargs"]["username"] == "a"

    def test_last_is_forwarded(self, runner: CliRunner) -> None:
        with patch(PATCH_RUN, return_value=[]) as mock_run:
            result = runner.invoke(
                app, ["search", "--data", FAKE_DATA, "-r", "6657", "--last", "12"]
            )

        assert result.exit_code == 0
        assert _called(mock_run)["kwargs"]["last"] == 12


class TestVersionOptions:
    def test_stats_version_option(self, runner: CliRunner) -> None:
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert "dykit" in result.output
