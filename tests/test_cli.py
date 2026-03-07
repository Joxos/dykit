from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import psycopg
import pytest
from click.testing import CliRunner

from dytools.cli import cli

VALID_DSN = "host=localhost dbname=test user=u password=p"
SIMPLE_DSN = "host=x"

PATCH_RESOLVE_ROOM_ANALYSIS = "dytools.cli.commands.analysis_cmd.resolve_room_for_query"
PATCH_RESOLVE_ROOM_IO = "dytools.cli.commands.io_cmd.resolve_room_for_query"
PATCH_PG_CREATE = "dytools.cli.commands.collect_cmd.PostgreSQLStorage.create"
PATCH_ASYNC_COLLECTOR = "dytools.cli.commands.collect_cmd.AsyncCollector"
PATCH_RANK = "dytools.cli.commands.analysis_cmd.rank.rank"
PATCH_PRUNE = "dytools.cli.commands.analysis_cmd.prune.prune"
PATCH_CLUSTER = "dytools.cli.commands.analysis_cmd.cluster.cluster"
PATCH_SEARCH = "dytools.cli.commands.analysis_cmd.search.search"
PATCH_CONNECT = "dytools.cli.commands.io_cmd.psycopg.connect"


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def tmp_csv(tmp_path: Path) -> Path:
    csv_file = tmp_path / "test.csv"
    with open(csv_file, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            ["timestamp", "username", "content", "user_level", "user_id", "room_id", "msg_type"]
        )
        writer.writerow(
            ["2024-01-01 12:00:00", "testuser", "hello", "5", "uid123", "12345", "chatmsg"]
        )
    return csv_file


def _make_psycopg_mock(
    fetchall_return: list[tuple[object, ...]] | None = None,
) -> tuple[MagicMock, MagicMock]:
    mock_cursor = MagicMock()
    mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
    mock_cursor.__exit__ = MagicMock(return_value=False)
    if fetchall_return is not None:
        mock_cursor.fetchall.return_value = fetchall_return

    mock_conn = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_conn.cursor.return_value = mock_cursor
    return mock_conn, mock_cursor


def _assert_missing_dsn(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, args: list[str]
) -> None:
    monkeypatch.delenv("DYTOOLS_DSN", raising=False)
    result = runner.invoke(cli, args)
    assert result.exit_code == 1
    assert "Missing --dsn" in result.output or "DYTOOLS_DSN" in result.output


class TestMissingDsn:
    @pytest.mark.parametrize(
        "args",
        [
            ["collect", "-r", "6657"],
            ["rank", "-r", "6657"],
            ["prune", "-r", "6657"],
            ["cluster", "-r", "6657"],
            ["search", "-r", "6657"],
            ["init-db"],
        ],
    )
    def test_missing_dsn_common_commands(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch, args: list[str]
    ) -> None:
        _assert_missing_dsn(runner, monkeypatch, args)

    def test_import_missing_dsn(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_csv: Path
    ) -> None:
        _assert_missing_dsn(runner, monkeypatch, ["import", str(tmp_csv), "-r", "6657"])

    def test_export_missing_dsn(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        output_file = tmp_path / "out.csv"
        _assert_missing_dsn(runner, monkeypatch, ["export", "-r", "6657", "-o", str(output_file)])


class TestCollectCommand:
    def test_collect_with_and_without_mutex(self, runner: CliRunner) -> None:
        result = runner.invoke(
            cli,
            [
                "--dsn",
                VALID_DSN,
                "collect",
                "-r",
                "6657",
                "--with",
                "chatmsg",
                "--without",
                "uenter",
            ],
        )
        assert result.exit_code == 1
        assert "Cannot use both" in result.output

    def test_collect_happy_path(self, runner: CliRunner) -> None:
        mock_storage = MagicMock()
        mock_storage.__aenter__ = AsyncMock(return_value=mock_storage)
        mock_storage.__aexit__ = AsyncMock(return_value=False)

        mock_collector = MagicMock()
        mock_collector.connect = AsyncMock(return_value=None)

        with patch(PATCH_PG_CREATE, new=AsyncMock(return_value=mock_storage)) as mock_create:
            with patch(PATCH_ASYNC_COLLECTOR, return_value=mock_collector) as mock_collector_cls:
                result = runner.invoke(cli, ["--dsn", VALID_DSN, "collect", "-r", "6657"])

        assert result.exit_code == 0
        mock_create.assert_awaited_once()
        mock_collector_cls.assert_called_once_with(
            "6657", mock_storage, type_filter=None, type_exclude=None
        )
        mock_collector.connect.assert_awaited_once()


class TestRankCommand:
    @patch(PATCH_RESOLVE_ROOM_ANALYSIS, return_value="12345")
    def test_rank_user_and_content_mutex(self, mock_resolve: MagicMock, runner: CliRunner) -> None:
        result = runner.invoke(
            cli, ["--dsn", SIMPLE_DSN, "rank", "-r", "6657", "--user", "--content"]
        )
        assert result.exit_code == 1
        assert "Cannot use both" in result.output

    @patch(PATCH_RESOLVE_ROOM_ANALYSIS, return_value="12345")
    @patch(PATCH_RANK, return_value=[{"username": "alice", "count": 42}])
    def test_rank_user_mode_happy_path(
        self, mock_rank: MagicMock, mock_resolve: MagicMock, runner: CliRunner
    ) -> None:
        result = runner.invoke(cli, ["--dsn", SIMPLE_DSN, "rank", "-r", "6657", "--user"])
        assert result.exit_code == 0
        assert "alice" in result.output
        assert "42" in result.output
        mock_resolve.assert_called_once_with("6657")
        mock_rank.assert_called_once_with(SIMPLE_DSN, "12345", 10, "chatmsg", None, mode="user")

    @patch(PATCH_RESOLVE_ROOM_ANALYSIS, return_value="12345")
    @patch(PATCH_RANK, return_value=[])
    def test_rank_no_results(
        self, mock_rank: MagicMock, mock_resolve: MagicMock, runner: CliRunner
    ) -> None:
        result = runner.invoke(cli, ["--dsn", SIMPLE_DSN, "rank", "-r", "6657"])
        assert result.exit_code == 0
        assert "messages found" in result.output
        mock_resolve.assert_called_once_with("6657")
        mock_rank.assert_called_once_with(SIMPLE_DSN, "12345", 10, "chatmsg", None, mode="user")

    @patch(PATCH_RESOLVE_ROOM_ANALYSIS, return_value="12345")
    @patch(
        PATCH_RANK,
        return_value=[
            {
                "content": "spam message",
                "count": 5,
                "first_seen": datetime(2024, 1, 1),
                "last_seen": datetime(2024, 1, 2),
            }
        ],
    )
    def test_rank_content_mode_happy_path(
        self, mock_rank: MagicMock, mock_resolve: MagicMock, runner: CliRunner
    ) -> None:
        result = runner.invoke(cli, ["--dsn", SIMPLE_DSN, "rank", "-r", "6657", "--content"])
        assert result.exit_code == 0
        assert "spam message" in result.output
        assert "5" in result.output
        mock_resolve.assert_called_once_with("6657")
        mock_rank.assert_called_once_with(SIMPLE_DSN, "12345", 10, "chatmsg", None, mode="content")

    @patch(PATCH_RESOLVE_ROOM_ANALYSIS, return_value="12345")
    @patch(PATCH_RANK, side_effect=psycopg.Error("db failed"))
    def test_rank_database_error(
        self, mock_rank: MagicMock, mock_resolve: MagicMock, runner: CliRunner
    ) -> None:
        result = runner.invoke(cli, ["--dsn", SIMPLE_DSN, "rank", "-r", "6657"])
        assert result.exit_code == 1
        assert "Database query failed" in result.output
        mock_resolve.assert_called_once_with("6657")
        mock_rank.assert_called_once()


class TestPruneCommand:
    @patch(PATCH_RESOLVE_ROOM_ANALYSIS, return_value="12345")
    @patch(PATCH_PRUNE, return_value=3)
    def test_prune_happy_path(
        self, mock_prune: MagicMock, mock_resolve: MagicMock, runner: CliRunner
    ) -> None:
        result = runner.invoke(cli, ["--dsn", SIMPLE_DSN, "prune", "-r", "6657"])
        assert result.exit_code == 0
        assert "3" in result.output
        assert "duplicate" in result.output
        mock_resolve.assert_called_once_with("6657")
        mock_prune.assert_called_once_with(SIMPLE_DSN, "12345")


class TestClusterCommand:
    @patch(PATCH_RESOLVE_ROOM_ANALYSIS, return_value="12345")
    @patch(PATCH_CLUSTER, return_value=[])
    def test_cluster_no_messages(
        self, mock_cluster: MagicMock, mock_resolve: MagicMock, runner: CliRunner
    ) -> None:
        result = runner.invoke(cli, ["--dsn", SIMPLE_DSN, "cluster", "-r", "6657"])
        assert result.exit_code == 0
        assert "No messages found" in result.output
        mock_resolve.assert_called_once_with("6657")
        mock_cluster.assert_called_once_with(SIMPLE_DSN, "12345", 0.6, "chatmsg", 1000)

    @patch(PATCH_RESOLVE_ROOM_ANALYSIS, return_value="12345")
    @patch(PATCH_CLUSTER, return_value=[[("hello world", 5), ("hello worlds", 3)]])
    def test_cluster_happy_path(
        self, mock_cluster: MagicMock, mock_resolve: MagicMock, runner: CliRunner
    ) -> None:
        result = runner.invoke(cli, ["--dsn", SIMPLE_DSN, "cluster", "-r", "6657"])
        assert result.exit_code == 0
        assert "hello world" in result.output
        mock_resolve.assert_called_once_with("6657")
        mock_cluster.assert_called_once_with(SIMPLE_DSN, "12345", 0.6, "chatmsg", 1000)


class TestSearchCommand:
    @patch(PATCH_RESOLVE_ROOM_ANALYSIS, return_value="12345")
    def test_search_last_and_first_mutex(self, mock_resolve: MagicMock, runner: CliRunner) -> None:
        result = runner.invoke(
            cli,
            ["--dsn", SIMPLE_DSN, "search", "-r", "6657", "--last", "10", "--first", "10"],
        )
        assert result.exit_code == 1
        assert "Cannot use both" in result.output

    @patch(PATCH_RESOLVE_ROOM_ANALYSIS, return_value="12345")
    @patch(
        PATCH_SEARCH,
        return_value=[
            {
                "timestamp": datetime(2024, 1, 1, 12, 0, 0),
                "username": "alice",
                "content": "test message",
                "user_level": 5,
                "user_id": "uid123",
                "room_id": "12345",
                "msg_type": "chatmsg",
            }
        ],
    )
    def test_search_happy_path(
        self, mock_search: MagicMock, mock_resolve: MagicMock, runner: CliRunner
    ) -> None:
        result = runner.invoke(cli, ["--dsn", SIMPLE_DSN, "search", "-r", "6657", "-q", "test"])
        assert result.exit_code == 0
        assert "alice" in result.output
        assert "test message" in result.output
        mock_resolve.assert_called_once_with("6657")
        mock_search.assert_called_once_with(
            SIMPLE_DSN,
            "12345",
            query="test",
            username=None,
            user_id=None,
            msg_type=None,
            from_date=None,
            to_date=None,
            last=None,
            first=None,
        )

    @patch(PATCH_RESOLVE_ROOM_ANALYSIS, return_value="12345")
    @patch(PATCH_SEARCH, return_value=[])
    def test_search_no_results(
        self, mock_search: MagicMock, mock_resolve: MagicMock, runner: CliRunner
    ) -> None:
        result = runner.invoke(cli, ["--dsn", SIMPLE_DSN, "search", "-r", "6657", "-q", "xyz"])
        assert result.exit_code == 0
        assert "No messages found" in result.output
        mock_resolve.assert_called_once_with("6657")
        mock_search.assert_called_once_with(
            SIMPLE_DSN,
            "12345",
            query="xyz",
            username=None,
            user_id=None,
            msg_type=None,
            from_date=None,
            to_date=None,
            last=None,
            first=None,
        )

    @patch(PATCH_RESOLVE_ROOM_ANALYSIS, return_value="12345")
    @patch(PATCH_SEARCH, side_effect=psycopg.Error("db failed"))
    def test_search_database_error(
        self, mock_search: MagicMock, mock_resolve: MagicMock, runner: CliRunner
    ) -> None:
        result = runner.invoke(cli, ["--dsn", SIMPLE_DSN, "search", "-r", "6657", "-q", "test"])
        assert result.exit_code == 1
        assert "Database query failed" in result.output
        mock_resolve.assert_called_once_with("6657")
        mock_search.assert_called_once()


class TestImportCommand:
    @patch(PATCH_CONNECT)
    def test_import_happy_path(
        self, mock_connect: MagicMock, runner: CliRunner, tmp_csv: Path
    ) -> None:
        mock_conn, mock_cursor = _make_psycopg_mock()
        mock_connect.return_value = mock_conn

        result = runner.invoke(cli, ["--dsn", SIMPLE_DSN, "import", str(tmp_csv), "-r", "6657"])

        assert result.exit_code == 0
        assert "Imported 1 records" in result.output
        mock_connect.assert_called_once_with(SIMPLE_DSN)
        assert mock_cursor.execute.call_count == 1
        mock_conn.commit.assert_called_once()

    @patch(PATCH_CONNECT)
    def test_import_empty_csv(
        self, mock_connect: MagicMock, runner: CliRunner, tmp_path: Path
    ) -> None:
        mock_conn, _ = _make_psycopg_mock()
        mock_connect.return_value = mock_conn
        empty_csv = tmp_path / "empty.csv"
        empty_csv.write_text("", encoding="utf-8")

        result = runner.invoke(cli, ["--dsn", SIMPLE_DSN, "import", str(empty_csv), "-r", "6657"])

        assert result.exit_code == 1
        assert "Empty CSV file" in result.output
        mock_connect.assert_called_once_with(SIMPLE_DSN)

    @patch(PATCH_CONNECT, side_effect=psycopg.Error("db failed"))
    def test_import_database_error(
        self, mock_connect: MagicMock, runner: CliRunner, tmp_csv: Path
    ) -> None:
        result = runner.invoke(cli, ["--dsn", SIMPLE_DSN, "import", str(tmp_csv), "-r", "6657"])

        assert result.exit_code == 1
        assert "Database import failed" in result.output
        mock_connect.assert_called_once_with(SIMPLE_DSN)


class TestExportCommand:
    @patch(PATCH_RESOLVE_ROOM_IO, return_value="12345")
    @patch(PATCH_CONNECT)
    def test_export_no_data(
        self, mock_connect: MagicMock, mock_resolve: MagicMock, runner: CliRunner, tmp_path: Path
    ) -> None:
        mock_conn, mock_cursor = _make_psycopg_mock(fetchall_return=[])
        mock_connect.return_value = mock_conn
        output_file = tmp_path / "out.csv"

        result = runner.invoke(
            cli,
            ["--dsn", SIMPLE_DSN, "export", "-r", "6657", "-o", str(output_file)],
        )

        assert result.exit_code == 0
        assert "No data found" in result.output
        mock_resolve.assert_called_once_with("6657")
        mock_connect.assert_called_once_with(SIMPLE_DSN)
        mock_cursor.execute.assert_called_once()
        assert not output_file.exists()

    @patch(PATCH_RESOLVE_ROOM_IO, return_value="12345")
    @patch(PATCH_CONNECT)
    def test_export_happy_path(
        self, mock_connect: MagicMock, mock_resolve: MagicMock, runner: CliRunner, tmp_path: Path
    ) -> None:
        mock_row = (
            datetime(2024, 1, 1, 12, 0, 0),
            "alice",
            "hello",
            5,
            "uid123",
            "12345",
            "chatmsg",
        )
        mock_conn, mock_cursor = _make_psycopg_mock(fetchall_return=[mock_row])
        mock_connect.return_value = mock_conn
        output_file = tmp_path / "out.csv"

        result = runner.invoke(
            cli,
            ["--dsn", SIMPLE_DSN, "export", "-r", "6657", "-o", str(output_file)],
        )

        assert result.exit_code == 0
        assert "Exported 1 records" in result.output
        mock_resolve.assert_called_once_with("6657")
        mock_connect.assert_called_once_with(SIMPLE_DSN)
        mock_cursor.execute.assert_called_once()

        with open(output_file, encoding="utf-8", newline="") as f:
            rows = list(csv.reader(f))
        assert len(rows) == 2
        assert rows[0] == [
            "timestamp",
            "username",
            "content",
            "user_level",
            "user_id",
            "room_id",
            "msg_type",
            "extra",
        ]
        assert rows[1][1] == "alice"
        assert rows[1][2] == "hello"

    @patch(PATCH_RESOLVE_ROOM_IO, return_value="12345")
    @patch(PATCH_CONNECT, side_effect=psycopg.Error("db failed"))
    def test_export_database_error(
        self, mock_connect: MagicMock, mock_resolve: MagicMock, runner: CliRunner, tmp_path: Path
    ) -> None:
        output_file = tmp_path / "out.csv"
        result = runner.invoke(
            cli,
            ["--dsn", SIMPLE_DSN, "export", "-r", "6657", "-o", str(output_file)],
        )

        assert result.exit_code == 1
        assert "Database export failed" in result.output
        mock_resolve.assert_called_once_with("6657")
        mock_connect.assert_called_once_with(SIMPLE_DSN)

    @patch(PATCH_RESOLVE_ROOM_IO, return_value="12345")
    @patch(PATCH_CONNECT)
    @patch("builtins.open", side_effect=OSError("disk full"))
    def test_export_file_write_failure(
        self,
        mock_open: MagicMock,
        mock_connect: MagicMock,
        mock_resolve: MagicMock,
        runner: CliRunner,
        tmp_path: Path,
    ) -> None:
        _ = mock_resolve
        mock_row = (
            datetime(2024, 1, 1, 12, 0, 0),
            "alice",
            "hello",
            5,
            "uid123",
            "12345",
            "chatmsg",
        )
        mock_conn, mock_cursor = _make_psycopg_mock(fetchall_return=[mock_row])
        mock_connect.return_value = mock_conn
        output_file = tmp_path / "out.csv"

        result = runner.invoke(
            cli,
            ["--dsn", SIMPLE_DSN, "export", "-r", "6657", "-o", str(output_file)],
        )

        assert result.exit_code == 1
        assert isinstance(result.exception, OSError)
        assert "disk full" in str(result.exception)
        mock_resolve.assert_called_once_with("6657")
        mock_connect.assert_called_once_with(SIMPLE_DSN)
        mock_cursor.execute.assert_called_once()
        mock_open.assert_called_once()


class TestInitDbCommand:
    @patch(PATCH_CONNECT)
    def test_init_db_happy_path(self, mock_connect: MagicMock, runner: CliRunner) -> None:
        mock_conn, mock_cursor = _make_psycopg_mock()
        mock_connect.return_value = mock_conn

        result = runner.invoke(cli, ["--dsn", SIMPLE_DSN, "init-db"])

        assert result.exit_code == 0
        assert "initialized successfully" in result.output
        mock_connect.assert_called_once_with(SIMPLE_DSN)
        mock_cursor.execute.assert_called_once()
        mock_conn.commit.assert_called_once()
