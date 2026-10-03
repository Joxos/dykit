"""Tests for the stats CLI (rank, cluster, search)."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from dykit.stats.cli import app

from ..cli_test_runner import CliRunner

PATCH_RANK = "dykit.stats.cli.rank_messages"
PATCH_CLUSTER = "dykit.stats.cli.find_clusters"
PATCH_SEARCH = "dykit.stats.cli.search_messages"

FAKE_DATA = "some/path.db"
RESOLVED_DATA = Path(FAKE_DATA)


def _rank_kwargs(**overrides: object) -> dict[str, object]:
    """Expected rank() keyword call for `rank` with all defaults."""
    kwargs: dict[str, object] = {
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
    }
    kwargs.update(overrides)
    return kwargs


def _cluster_kwargs(**overrides: object) -> dict[str, object]:
    """Expected cluster() keyword call for `cluster` with all defaults."""
    kwargs: dict[str, object] = {
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
    }
    kwargs.update(overrides)
    return kwargs


def _search_kwargs(**overrides: object) -> dict[str, object]:
    """Expected search() keyword call for `search` with all defaults."""
    kwargs: dict[str, object] = {
        "query": None,
        "username": None,
        "user_id": None,
        "msg_type": None,
        "from_date": None,
        "to_date": None,
        "last": None,
        "first": None,
    }
    kwargs.update(overrides)
    return kwargs


def _real_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    """Undo the autouse stub so the real resolve_runtime runs (it checks --data)."""
    from dykit.stats.runtime import resolve_runtime

    monkeypatch.setattr("dykit.stats.cli.resolve_runtime", resolve_runtime)


class TestRuntimeResolution:
    """The CLI resolves the room and the data path before querying."""

    def test_resolves_room_before_querying(self, runner: CliRunner) -> None:
        with (
            patch(PATCH_RANK, return_value=[]) as mock_rank,
            patch("dykit.stats.cli.resolve_runtime", return_value=("6979222", RESOLVED_DATA)),
        ):
            result = runner.invoke(app, ["rank", "--data", FAKE_DATA, "-r", "6657"])

        assert result.exit_code == 0
        mock_rank.assert_called_once_with(RESOLVED_DATA, "6979222", **_rank_kwargs())

    def test_missing_data_path_is_a_cli_error(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _real_runtime(monkeypatch)

        with patch(PATCH_RANK, return_value=[]):
            result = runner.invoke(app, ["rank", "--data", "no/such/dir", "-r", "6657"])

        assert result.exit_code == 1
        assert "Data path not found" in result.output

    def test_query_failure_is_a_cli_error(self, runner: CliRunner) -> None:
        with patch(PATCH_RANK, side_effect=sqlite3.Error("db failed")):
            result = runner.invoke(app, ["rank", "--data", FAKE_DATA, "-r", "6657"])

        assert result.exit_code == 1
        assert "Error" in result.output


class TestRankCommand:
    @patch(PATCH_RANK, return_value=[])
    def test_rank_by_option_happy_path(self, mock_rank: MagicMock, runner: CliRunner) -> None:
        result = runner.invoke(app, ["rank", "--data", FAKE_DATA, "-r", "6657", "--by", "user"])
        assert result.exit_code == 0
        mock_rank.assert_called_once_with(RESOLVED_DATA, "6657", **_rank_kwargs())

    @patch(PATCH_RANK, return_value=[MagicMock(rank=1, value="alice", count=42)])
    def test_rank_user_mode_happy_path(self, mock_rank: MagicMock, runner: CliRunner) -> None:
        result = runner.invoke(app, ["rank", "--data", FAKE_DATA, "-r", "6657", "--by", "user"])
        assert result.exit_code == 0
        assert "alice" in result.output
        assert "42" in result.output
        mock_rank.assert_called_once_with(RESOLVED_DATA, "6657", **_rank_kwargs())

    @patch(PATCH_RANK, return_value=[])
    def test_rank_no_results(self, mock_rank: MagicMock, runner: CliRunner) -> None:
        result = runner.invoke(app, ["rank", "--data", FAKE_DATA, "-r", "6657"])
        assert result.exit_code == 0
        mock_rank.assert_called_once_with(RESOLVED_DATA, "6657", **_rank_kwargs())

    @patch(
        PATCH_RANK,
        return_value=[MagicMock(rank=1, value="spam message", count=5)],
    )
    def test_rank_content_mode_happy_path(self, mock_rank: MagicMock, runner: CliRunner) -> None:
        result = runner.invoke(app, ["rank", "--data", FAKE_DATA, "-r", "6657", "--by", "content"])
        assert result.exit_code == 0
        assert "spam message" in result.output
        assert "5" in result.output
        mock_rank.assert_called_once_with(RESOLVED_DATA, "6657", **_rank_kwargs(mode="content"))

    @patch(PATCH_RANK, return_value=[])
    def test_rank_with_days(self, mock_rank: MagicMock, runner: CliRunner) -> None:
        result = runner.invoke(app, ["rank", "--data", FAKE_DATA, "-r", "6657", "--days", "7"])
        assert result.exit_code == 0
        mock_rank.assert_called_once_with(RESOLVED_DATA, "6657", **_rank_kwargs(days=7))

    @patch(PATCH_RANK, return_value=[])
    def test_rank_with_last(self, mock_rank: MagicMock, runner: CliRunner) -> None:
        result = runner.invoke(app, ["rank", "--data", FAKE_DATA, "-r", "6657", "--last", "10"])
        assert result.exit_code == 0
        mock_rank.assert_called_once_with(RESOLVED_DATA, "6657", **_rank_kwargs(last=10))


class TestClusterCommand:
    @patch(PATCH_CLUSTER, return_value=[])
    def test_cluster_no_messages(self, mock_cluster: MagicMock, runner: CliRunner) -> None:
        result = runner.invoke(app, ["cluster", "--data", FAKE_DATA, "-r", "6657"])
        assert result.exit_code == 0
        assert "0 clusters" in result.output
        mock_cluster.assert_called_once_with(RESOLVED_DATA, "6657", **_cluster_kwargs())

    @patch(
        PATCH_CLUSTER,
        return_value=[
            MagicMock(
                representative="hello world",
                count=5,
                similar=[("hello world", 3), ("hello worlds", 2)],
            )
        ],
    )
    def test_cluster_happy_path(self, mock_cluster: MagicMock, runner: CliRunner) -> None:
        result = runner.invoke(app, ["cluster", "--data", FAKE_DATA, "-r", "6657"])
        assert result.exit_code == 0
        assert "hello world" in result.output
        mock_cluster.assert_called_once_with(RESOLVED_DATA, "6657", **_cluster_kwargs())

    @patch(PATCH_CLUSTER, return_value=[])
    def test_cluster_with_options(self, mock_cluster: MagicMock, runner: CliRunner) -> None:
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
        mock_cluster.assert_called_once_with(
            RESOLVED_DATA, "6657", **_cluster_kwargs(threshold=0.7, limit=100, msg_type="dgb")
        )

    @patch(PATCH_CLUSTER, return_value=[])
    def test_cluster_with_first(self, mock_cluster: MagicMock, runner: CliRunner) -> None:
        result = runner.invoke(app, ["cluster", "--data", FAKE_DATA, "-r", "6657", "--first", "20"])
        assert result.exit_code == 0
        mock_cluster.assert_called_once_with(RESOLVED_DATA, "6657", **_cluster_kwargs(first=20))


class TestSearchCommand:
    @patch(
        PATCH_SEARCH,
        return_value=[
            MagicMock(
                timestamp=datetime(2026, 3, 8, 12, 0, 0),
                username="alice",
                content="test message",
                msg_type="chatmsg",
            )
        ],
    )
    def test_search_happy_path(self, mock_search: MagicMock, runner: CliRunner) -> None:
        result = runner.invoke(app, ["search", "--data", FAKE_DATA, "-r", "6657", "--content", "x"])
        assert result.exit_code == 0
        assert "alice" in result.output
        assert "test message" in result.output
        mock_search.assert_called_once_with(RESOLVED_DATA, "6657", **_search_kwargs(query="x"))

    @patch(PATCH_SEARCH, return_value=[])
    def test_search_no_results(self, mock_search: MagicMock, runner: CliRunner) -> None:
        result = runner.invoke(app, ["search", "--data", FAKE_DATA, "-r", "6657", "--content", "y"])
        assert result.exit_code == 0
        assert "Found 0 messages" in result.output
        mock_search.assert_called_once_with(RESOLVED_DATA, "6657", **_search_kwargs(query="y"))

    @patch(PATCH_SEARCH, return_value=[])
    def test_search_with_filters(self, mock_search: MagicMock, runner: CliRunner) -> None:
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
        mock_search.assert_called_once_with(
            RESOLVED_DATA,
            "6657",
            **_search_kwargs(
                username="alice",
                user_id="uid1",
                msg_type="chatmsg",
                from_date="2026-03-01",
                to_date="2026-03-07",
            ),
        )

    @patch(PATCH_SEARCH, return_value=[])
    def test_search_accepts_username_alias(self, mock_search: MagicMock, runner: CliRunner) -> None:
        """`--username` is the shared spelling; `--user` stays as an alias."""
        result = runner.invoke(
            app, ["search", "--data", FAKE_DATA, "-r", "6657", "--username", "a"]
        )
        assert result.exit_code == 0
        mock_search.assert_called_once_with(RESOLVED_DATA, "6657", **_search_kwargs(username="a"))

    @patch(PATCH_SEARCH, return_value=[])
    def test_search_with_last(self, mock_search: MagicMock, runner: CliRunner) -> None:
        result = runner.invoke(app, ["search", "--data", FAKE_DATA, "-r", "6657", "--last", "12"])
        assert result.exit_code == 0
        mock_search.assert_called_once_with(RESOLVED_DATA, "6657", **_search_kwargs(last=12))


class TestVersionOptions:
    def test_stats_version_option(self, runner: CliRunner) -> None:
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert "dykit" in result.output
