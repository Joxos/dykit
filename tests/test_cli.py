from __future__ import annotations

from datetime import datetime
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import psycopg
import pytest
from click.testing import CliRunner
from dycap.cli import collect
from dystat.cli import cli
from dystat.rank import run_rank

VALID_DSN = "host=localhost dbname=test user=u password=p"
SIMPLE_DSN = "host=x"

PATCH_PG_CREATE = "dycap.cli.PostgreSQLStorageFromDSN.create"
PATCH_ASYNC_COLLECTOR = "dycap.cli.AsyncCollector"
PATCH_RANK = "dystat.cli.run_rank"
PATCH_CLUSTER = "dystat.cli.run_cluster"
PATCH_SEARCH = "dystat.cli.run_search"


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _assert_dycap_missing_dsn(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, args: list[str]
) -> None:
    monkeypatch.delenv("DYKIT_DSN", raising=False)
    monkeypatch.delenv("DYCAP_DSN", raising=False)
    result = runner.invoke(collect, args)
    assert result.exit_code == 1
    assert "DSN required" in result.output


def _assert_dystat_missing_dsn(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, args: list[str]
) -> None:
    monkeypatch.delenv("DYKIT_DSN", raising=False)
    monkeypatch.delenv("DYSTAT_DSN", raising=False)
    result = runner.invoke(cli, args)
    assert result.exit_code == 1
    assert "DSN required" in result.output


class TestMissingDsn:
    @pytest.mark.parametrize(
        "args",
        [
            ["-r", "6657"],
        ],
    )
    def test_dycap_collect_missing_dsn(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch, args: list[str]
    ) -> None:
        _assert_dycap_missing_dsn(runner, monkeypatch, args)

    @pytest.mark.parametrize(
        "args",
        [
            ["rank", "-r", "6657"],
            ["cluster", "-r", "6657"],
            ["search", "-r", "6657"],
        ],
    )
    def test_dystat_missing_dsn(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch, args: list[str]
    ) -> None:
        _assert_dystat_missing_dsn(runner, monkeypatch, args)


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
            [
                "--dsn",
                VALID_DSN,
                "-r",
                "6657",
                "--with",
                "chatmsg",
                "--without",
                "uenter",
            ],
        )
        assert result.exit_code == 1
        assert "Cannot use --with and --without together" in result.output

    def test_collect_happy_path(self, runner: CliRunner) -> None:
        mock_storage = MagicMock()
        mock_storage.__aenter__ = AsyncMock(return_value=mock_storage)
        mock_storage.__aexit__ = AsyncMock(return_value=False)

        mock_collector = MagicMock()
        mock_collector.connect = AsyncMock(return_value=None)

        with patch(PATCH_PG_CREATE, new=AsyncMock(return_value=mock_storage)) as mock_create:
            with patch(PATCH_ASYNC_COLLECTOR, return_value=mock_collector) as mock_collector_cls:
                result = runner.invoke(collect, ["--dsn", VALID_DSN, "-r", "6657"])

        assert result.exit_code == 0
        mock_create.assert_awaited_once()
        mock_collector_cls.assert_called_once_with(
            "6657",
            mock_storage,
            type_filter=None,
            type_exclude=None,
            message_callback=ANY,
        )
        mock_collector.connect.assert_awaited_once()

    def test_collect_with_type_filter(self, runner: CliRunner) -> None:
        mock_storage = MagicMock()
        mock_storage.__aenter__ = AsyncMock(return_value=mock_storage)
        mock_storage.__aexit__ = AsyncMock(return_value=False)

        mock_collector = MagicMock()
        mock_collector.connect = AsyncMock(return_value=None)

        with patch(PATCH_PG_CREATE, new=AsyncMock(return_value=mock_storage)):
            with patch(PATCH_ASYNC_COLLECTOR, return_value=mock_collector) as mock_collector_cls:
                result = runner.invoke(
                    collect,
                    ["--dsn", VALID_DSN, "-r", "6657", "--with", "chatmsg,dgb"],
                )

        assert result.exit_code == 0
        mock_collector_cls.assert_called_once_with(
            "6657",
            mock_storage,
            type_filter=["chatmsg", "dgb"],
            type_exclude=None,
            message_callback=ANY,
        )


class TestRankCommand:
    @patch("dystat.rank.rank", return_value=[])
    @patch("dystat.rank.resolve_room", return_value="6979222")
    def test_run_rank_resolves_room_id(
        self,
        mock_resolve_room: MagicMock,
        mock_rank_impl: MagicMock,
    ) -> None:
        _ = run_rank(room="6657", dsn=SIMPLE_DSN)
        mock_resolve_room.assert_called_once_with("6657")
        mock_rank_impl.assert_called_once_with(
            SIMPLE_DSN,
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
        result = runner.invoke(cli, ["rank", "--dsn", SIMPLE_DSN, "-r", "6657", "--by", "user"])
        assert result.exit_code == 0
        mock_rank.assert_called_once()

    @patch(PATCH_RANK, return_value=[MagicMock(rank=1, value="alice", count=42)])
    def test_rank_user_mode_happy_path(self, mock_rank: MagicMock, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["rank", "--dsn", SIMPLE_DSN, "-r", "6657", "--by", "user"])
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
            SIMPLE_DSN,
        )

    @patch(PATCH_RANK, return_value=[])
    def test_rank_no_results(self, mock_rank: MagicMock, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["rank", "--dsn", SIMPLE_DSN, "-r", "6657"])
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
            SIMPLE_DSN,
        )

    @patch(
        PATCH_RANK,
        return_value=[MagicMock(rank=1, value="spam message", count=5)],
    )
    def test_rank_content_mode_happy_path(self, mock_rank: MagicMock, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["rank", "--dsn", SIMPLE_DSN, "-r", "6657", "--by", "content"])
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
            SIMPLE_DSN,
        )

    @patch(PATCH_RANK, side_effect=psycopg.Error("db failed"))
    def test_rank_database_error(self, mock_rank: MagicMock, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["rank", "--dsn", SIMPLE_DSN, "-r", "6657"])
        assert result.exit_code == 1
        mock_rank.assert_called_once()

    @patch(PATCH_RANK, return_value=[])
    def test_rank_with_days(self, mock_rank: MagicMock, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["rank", "--dsn", SIMPLE_DSN, "-r", "6657", "--days", "7"])
        assert result.exit_code == 0
        mock_rank.assert_called_once_with(
            "6657", 10, "user", "chatmsg", 7, None, None, None, None, None, None, SIMPLE_DSN
        )

    @patch(PATCH_RANK, return_value=[])
    def test_rank_with_last(self, mock_rank: MagicMock, runner: CliRunner) -> None:
        result = runner.invoke(
            cli,
            ["rank", "--dsn", SIMPLE_DSN, "-r", "6657", "--last", "10"],
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
            SIMPLE_DSN,
        )


class TestClusterCommand:
    @patch(PATCH_CLUSTER, return_value=[])
    def test_cluster_no_messages(self, mock_cluster: MagicMock, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["cluster", "--dsn", SIMPLE_DSN, "-r", "6657"])
        assert result.exit_code == 0
        assert "0 clusters" in result.output
        mock_cluster.assert_called_once_with(
            "6657", 0.5, "chatmsg", 50, None, None, None, None, None, None, None, SIMPLE_DSN
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
        result = runner.invoke(cli, ["cluster", "--dsn", SIMPLE_DSN, "-r", "6657"])
        assert result.exit_code == 0
        assert "hello world" in result.output
        mock_cluster.assert_called_once_with(
            "6657", 0.5, "chatmsg", 50, None, None, None, None, None, None, None, SIMPLE_DSN
        )

    @patch(PATCH_CLUSTER, return_value=[])
    def test_cluster_with_options(self, mock_cluster: MagicMock, runner: CliRunner) -> None:
        result = runner.invoke(
            cli,
            [
                "cluster",
                "--dsn",
                SIMPLE_DSN,
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
            "6657", 0.7, "dgb", 100, None, None, None, None, None, None, None, SIMPLE_DSN
        )

    @patch(PATCH_CLUSTER, return_value=[])
    def test_cluster_with_first(self, mock_cluster: MagicMock, runner: CliRunner) -> None:
        result = runner.invoke(
            cli,
            ["cluster", "--dsn", SIMPLE_DSN, "-r", "6657", "--first", "20"],
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
            SIMPLE_DSN,
        )

    @patch(PATCH_CLUSTER, side_effect=psycopg.Error("db failed"))
    def test_cluster_database_error(self, mock_cluster: MagicMock, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["cluster", "--dsn", SIMPLE_DSN, "-r", "6657"])
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
            cli, ["search", "--dsn", SIMPLE_DSN, "-r", "6657", "--content", "test"]
        )
        assert result.exit_code == 0
        assert "alice" in result.output
        assert "test message" in result.output
        mock_search.assert_called_once_with(
            "6657", "test", None, None, None, None, None, None, None, SIMPLE_DSN
        )

    @patch(PATCH_SEARCH, side_effect=psycopg.Error("db failed"))
    def test_search_database_error(self, mock_search: MagicMock, runner: CliRunner) -> None:
        result = runner.invoke(
            cli, ["search", "--dsn", SIMPLE_DSN, "-r", "6657", "--content", "test"]
        )
        assert result.exit_code == 1
        mock_search.assert_called_once()

    @patch(PATCH_SEARCH, return_value=[])
    def test_search_no_results(self, mock_search: MagicMock, runner: CliRunner) -> None:
        result = runner.invoke(
            cli, ["search", "--dsn", SIMPLE_DSN, "-r", "6657", "--content", "xyz"]
        )
        assert result.exit_code == 0
        assert "Found 0 messages" in result.output
        mock_search.assert_called_once_with(
            "6657", "xyz", None, None, None, None, None, None, None, SIMPLE_DSN
        )

    @patch(PATCH_SEARCH, return_value=[])
    def test_search_with_filters(self, mock_search: MagicMock, runner: CliRunner) -> None:
        result = runner.invoke(
            cli,
            [
                "search",
                "--dsn",
                SIMPLE_DSN,
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
            SIMPLE_DSN,
        )

    @patch(PATCH_SEARCH, return_value=[])
    def test_search_with_last(self, mock_search: MagicMock, runner: CliRunner) -> None:
        result = runner.invoke(
            cli,
            ["search", "--dsn", SIMPLE_DSN, "-r", "6657", "--last", "12"],
        )
        assert result.exit_code == 0
        mock_search.assert_called_once_with(
            "6657", None, None, None, None, None, None, 12, None, SIMPLE_DSN
        )


class TestVersionOptions:
    def test_dystat_version_option(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert "dystat" in result.output
