from __future__ import annotations

import sqlite3
from datetime import datetime
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest
from dycap.cli import collect
from dystat.cli import cli
from dystat.rank import run_rank

from .cli_test_runner import CliRunner

PATCH_ASYNC_COLLECTOR = "dycap.cli.AsyncCollector"
PATCH_RANK = "dystat.cli.run_rank"
PATCH_CLUSTER = "dystat.cli.run_cluster"
PATCH_SEARCH = "dystat.cli.run_search"

FAKE_DATA = "some/path.db"


@pytest.fixture(autouse=True)
def _no_network_room(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep room resolution deterministic in CLI tests (no network)."""
    monkeypatch.setattr("dycap.cli.resolve_room", lambda room: room)
    monkeypatch.setattr("dystat.runtime.resolve_room", lambda room: room)


def _meta_of(path) -> dict[str, str]:
    conn = sqlite3.connect(str(path))
    try:
        return dict(conn.execute("SELECT key, value FROM meta").fetchall())
    finally:
        conn.close()


class TestCollectCommand:
    def test_collect_version_option(self, runner: CliRunner) -> None:
        result = runner.invoke(collect, ["--version"])
        assert result.exit_code == 0
        assert "dycap" in result.output

    def test_collect_help_shows_human_labels(self, runner: CliRunner) -> None:
        result = runner.invoke(collect, ["--help"])
        assert result.exit_code == 0
        assert "chatmsg（弹幕）" in result.output
        assert "dgb（礼物）" in result.output

    def test_collect_with_and_without_mutex(self, runner: CliRunner) -> None:
        result = runner.invoke(
            collect,
            ["-r", "6657", "--with", "chatmsg", "--without", "uenter"],
        )
        assert result.exit_code == 1
        assert "Cannot use --with and --without together" in result.output

    def test_collect_default_sqlite_run_file(
        self, runner: CliRunner, tmp_path: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        mock_collector = MagicMock()
        mock_collector.connect = AsyncMock(return_value=None)

        with patch(PATCH_ASYNC_COLLECTOR, return_value=mock_collector) as mock_collector_cls:
            result = runner.invoke(collect, ["-r", "6657"])

        assert result.exit_code == 0
        dbs = list(tmp_path.glob("dycap-data/*.db"))
        assert len(dbs) == 1
        mock_collector_cls.assert_called_once_with(
            "6657",
            ANY,
            type_filter=None,
            type_exclude=None,
            message_callback=ANY,
        )
        meta = _meta_of(dbs[0])
        assert meta["room"] == "6657"
        assert "started_at" in meta
        assert "ended_at" in meta
        assert meta["messages"] == "0"

    def test_collect_custom_output_path(
        self, runner: CliRunner, tmp_path: pytest.TempPathFactory
    ) -> None:
        mock_collector = MagicMock()
        mock_collector.connect = AsyncMock(return_value=None)
        out = tmp_path / "runs" / "my-run.db"

        with patch(PATCH_ASYNC_COLLECTOR, return_value=mock_collector):
            result = runner.invoke(collect, ["-r", "6657", "-o", str(out)])

        assert result.exit_code == 0
        assert out.exists()
        assert _meta_of(out)["room"] == "6657"

    def test_collect_refuses_existing_db(
        self, runner: CliRunner, tmp_path: pytest.TempPathFactory
    ) -> None:
        out = tmp_path / "exists.db"
        out.write_bytes(b"")

        result = runner.invoke(collect, ["-r", "6657", "-o", str(out)])

        assert result.exit_code == 1
        assert "already exists" in result.output

    def test_collect_with_type_filter(
        self, runner: CliRunner, tmp_path: pytest.TempPathFactory
    ) -> None:
        mock_collector = MagicMock()
        mock_collector.connect = AsyncMock(return_value=None)

        with patch(PATCH_ASYNC_COLLECTOR, return_value=mock_collector) as mock_collector_cls:
            result = runner.invoke(
                collect,
                ["-r", "6657", "-o", str(tmp_path / "filter.db"), "--with", "chatmsg,dgb"],
            )

        assert result.exit_code == 0
        mock_collector_cls.assert_called_once_with(
            "6657",
            ANY,
            type_filter=["chatmsg", "dgb"],
            type_exclude=None,
            message_callback=ANY,
        )


class TestRankCommand:
    @patch("dystat.rank.rank", return_value=[])
    @patch("dystat.runtime.resolve_room", return_value="6979222")
    def test_run_rank_resolves_room_id(
        self,
        mock_resolve_room: MagicMock,
        mock_rank_impl: MagicMock,
        tmp_path: pytest.TempPathFactory,
    ) -> None:
        data_file = tmp_path / "runs.db"
        data_file.write_bytes(b"")
        _ = run_rank(room="6657", data=str(data_file))
        mock_resolve_room.assert_called_once_with("6657")
        mock_rank_impl.assert_called_once_with(
            data_file,
            "6979222",
            10,
            "user",
            "chatmsg",
            None,
            None,
            None,
            None,
            None,
            None,
            None,
        )

    @patch(PATCH_RANK, return_value=[])
    def test_rank_by_option_happy_path(self, mock_rank: MagicMock, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["rank", "--data", FAKE_DATA, "-r", "6657", "--by", "user"])
        assert result.exit_code == 0
        mock_rank.assert_called_once()

    @patch(PATCH_RANK, return_value=[MagicMock(rank=1, value="alice", count=42)])
    def test_rank_user_mode_happy_path(self, mock_rank: MagicMock, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["rank", "--data", FAKE_DATA, "-r", "6657", "--by", "user"])
        assert result.exit_code == 0
        assert "alice" in result.output
        assert "42" in result.output
        mock_rank.assert_called_once_with(
            "6657",
            10,
            "user",
            "chatmsg",
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            FAKE_DATA,
        )

    @patch(PATCH_RANK, return_value=[])
    def test_rank_no_results(self, mock_rank: MagicMock, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["rank", "--data", FAKE_DATA, "-r", "6657"])
        assert result.exit_code == 0
        mock_rank.assert_called_once_with(
            "6657",
            10,
            "user",
            "chatmsg",
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            FAKE_DATA,
        )

    @patch(
        PATCH_RANK,
        return_value=[MagicMock(rank=1, value="spam message", count=5)],
    )
    def test_rank_content_mode_happy_path(self, mock_rank: MagicMock, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["rank", "--data", FAKE_DATA, "-r", "6657", "--by", "content"])
        assert result.exit_code == 0
        assert "spam message" in result.output
        assert "5" in result.output
        mock_rank.assert_called_once_with(
            "6657",
            10,
            "content",
            "chatmsg",
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            FAKE_DATA,
        )

    @patch(PATCH_RANK, side_effect=sqlite3.Error("db failed"))
    def test_rank_database_error(self, mock_rank: MagicMock, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["rank", "--data", FAKE_DATA, "-r", "6657"])
        assert result.exit_code == 1
        mock_rank.assert_called_once()

    @patch(PATCH_RANK, return_value=[])
    def test_rank_with_days(self, mock_rank: MagicMock, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["rank", "--data", FAKE_DATA, "-r", "6657", "--days", "7"])
        assert result.exit_code == 0
        mock_rank.assert_called_once_with(
            "6657", 10, "user", "chatmsg", 7, None, None, None, None, None, None, FAKE_DATA
        )

    @patch(PATCH_RANK, return_value=[])
    def test_rank_with_last(self, mock_rank: MagicMock, runner: CliRunner) -> None:
        result = runner.invoke(
            cli,
            ["rank", "--data", FAKE_DATA, "-r", "6657", "--last", "10"],
        )
        assert result.exit_code == 0
        mock_rank.assert_called_once_with(
            "6657",
            10,
            "user",
            "chatmsg",
            None,
            None,
            None,
            None,
            None,
            10,
            None,
            FAKE_DATA,
        )

    def test_rank_missing_data_path(self, runner: CliRunner) -> None:
        with patch("dystat.runtime.resolve_room", return_value="6979222"):
            result = runner.invoke(cli, ["rank", "--data", "no/such/dir", "-r", "6657"])
        assert result.exit_code == 1
        assert "Data path not found" in result.output


class TestClusterCommand:
    @patch(PATCH_CLUSTER, return_value=[])
    def test_cluster_no_messages(self, mock_cluster: MagicMock, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["cluster", "--data", FAKE_DATA, "-r", "6657"])
        assert result.exit_code == 0
        assert "0 clusters" in result.output
        mock_cluster.assert_called_once_with(
            "6657", 0.5, "chatmsg", 50, None, None, None, None, None, None, None, FAKE_DATA
        )

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
        result = runner.invoke(cli, ["cluster", "--data", FAKE_DATA, "-r", "6657"])
        assert result.exit_code == 0
        assert "hello world" in result.output
        mock_cluster.assert_called_once_with(
            "6657", 0.5, "chatmsg", 50, None, None, None, None, None, None, None, FAKE_DATA
        )

    @patch(PATCH_CLUSTER, return_value=[])
    def test_cluster_with_options(self, mock_cluster: MagicMock, runner: CliRunner) -> None:
        result = runner.invoke(
            cli,
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
            "6657", 0.7, "dgb", 100, None, None, None, None, None, None, None, FAKE_DATA
        )

    @patch(PATCH_CLUSTER, return_value=[])
    def test_cluster_with_first(self, mock_cluster: MagicMock, runner: CliRunner) -> None:
        result = runner.invoke(
            cli,
            ["cluster", "--data", FAKE_DATA, "-r", "6657", "--first", "20"],
        )
        assert result.exit_code == 0
        mock_cluster.assert_called_once_with(
            "6657",
            0.5,
            "chatmsg",
            50,
            None,
            None,
            None,
            None,
            None,
            20,
            None,
            FAKE_DATA,
        )

    @patch(PATCH_CLUSTER, side_effect=sqlite3.Error("db failed"))
    def test_cluster_database_error(self, mock_cluster: MagicMock, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["cluster", "--data", FAKE_DATA, "-r", "6657"])
        assert result.exit_code == 1
        mock_cluster.assert_called_once()


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
        result = runner.invoke(
            cli, ["search", "--data", FAKE_DATA, "-r", "6657", "--content", "test"]
        )
        assert result.exit_code == 0
        assert "alice" in result.output
        assert "test message" in result.output
        mock_search.assert_called_once_with(
            "6657", "test", None, None, None, None, None, None, None, FAKE_DATA
        )

    @patch(PATCH_SEARCH, side_effect=sqlite3.Error("db failed"))
    def test_search_database_error(self, mock_search: MagicMock, runner: CliRunner) -> None:
        result = runner.invoke(
            cli, ["search", "--data", FAKE_DATA, "-r", "6657", "--content", "test"]
        )
        assert result.exit_code == 1
        mock_search.assert_called_once()

    @patch(PATCH_SEARCH, return_value=[])
    def test_search_no_results(self, mock_search: MagicMock, runner: CliRunner) -> None:
        result = runner.invoke(
            cli, ["search", "--data", FAKE_DATA, "-r", "6657", "--content", "xyz"]
        )
        assert result.exit_code == 0
        assert "Found 0 messages" in result.output
        mock_search.assert_called_once_with(
            "6657", "xyz", None, None, None, None, None, None, None, FAKE_DATA
        )

    @patch(PATCH_SEARCH, return_value=[])
    def test_search_with_filters(self, mock_search: MagicMock, runner: CliRunner) -> None:
        result = runner.invoke(
            cli,
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
            "6657",
            None,
            "alice",
            "uid1",
            "chatmsg",
            "2026-03-01",
            "2026-03-07",
            None,
            None,
            FAKE_DATA,
        )

    @patch(PATCH_SEARCH, return_value=[])
    def test_search_with_last(self, mock_search: MagicMock, runner: CliRunner) -> None:
        result = runner.invoke(
            cli,
            ["search", "--data", FAKE_DATA, "-r", "6657", "--last", "12"],
        )
        assert result.exit_code == 0
        mock_search.assert_called_once_with(
            "6657", None, None, None, None, None, None, 12, None, FAKE_DATA
        )


class TestVersionOptions:
    def test_dystat_version_option(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert "dystat" in result.output
