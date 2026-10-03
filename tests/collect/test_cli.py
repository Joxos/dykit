"""Tests for the capture CLI."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest

from dykit.collect.cli import app

from ..cli_test_runner import CliRunner

PATCH_ASYNC_COLLECTOR = "dykit.collect.cli.AsyncCollector"


def _meta_of(path: Path) -> dict[str, str]:
    conn = sqlite3.connect(str(path))
    try:
        return dict(conn.execute("SELECT key, value FROM meta").fetchall())
    finally:
        conn.close()


class TestCollectCommand:
    def test_collect_version_option(self, runner: CliRunner) -> None:
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert "dykit" in result.output

    def test_collect_help_shows_human_labels(self, runner: CliRunner) -> None:
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "chatmsg（弹幕）" in result.output
        assert "dgb（礼物）" in result.output

    def test_collect_with_and_without_mutex(self, runner: CliRunner) -> None:
        result = runner.invoke(
            app,
            ["-r", "6657", "--with", "chatmsg", "--without", "uenter"],
        )
        # Usage errors exit 2; runtime failures exit 1.
        assert result.exit_code == 2
        assert "Cannot use --with and --without together" in result.output

    def test_collect_default_sqlite_run_file(
        self, runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        mock_collector = MagicMock()
        mock_collector.connect = AsyncMock(return_value=None)

        with patch(PATCH_ASYNC_COLLECTOR, return_value=mock_collector) as mock_collector_cls:
            result = runner.invoke(app, ["-r", "6657"])

        assert result.exit_code == 0
        dbs = list(tmp_path.glob("dycap-data/*.db"))
        assert len(dbs) == 1
        mock_collector_cls.assert_called_once_with(
            "6657",
            ANY,
            ws_url=None,
            type_filter=None,
            type_exclude=None,
            message_callback=ANY,
            sink_factory=ANY,
            data_dir=ANY,
        )
        meta = _meta_of(dbs[0])
        assert meta["room"] == "6657"
        assert "started_at" in meta
        assert "ended_at" in meta
        assert meta["messages"] == "0"
        assert meta["flush_errors"] == "0"

    def test_collect_custom_output_path(self, runner: CliRunner, tmp_path: Path) -> None:
        mock_collector = MagicMock()
        mock_collector.connect = AsyncMock(return_value=None)
        out = tmp_path / "runs" / "my-run.db"

        with patch(PATCH_ASYNC_COLLECTOR, return_value=mock_collector):
            result = runner.invoke(app, ["-r", "6657", "-o", str(out)])

        assert result.exit_code == 0
        assert out.exists()
        assert _meta_of(out)["room"] == "6657"

    def test_collect_refuses_existing_db(self, runner: CliRunner, tmp_path: Path) -> None:
        out = tmp_path / "exists.db"
        out.write_bytes(b"")

        result = runner.invoke(app, ["-r", "6657", "-o", str(out)])

        assert result.exit_code == 1
        assert "already exists" in result.output

    def test_collect_with_type_filter(self, runner: CliRunner, tmp_path: Path) -> None:
        mock_collector = MagicMock()
        mock_collector.connect = AsyncMock(return_value=None)

        with patch(PATCH_ASYNC_COLLECTOR, return_value=mock_collector) as mock_collector_cls:
            result = runner.invoke(
                app,
                ["-r", "6657", "-o", str(tmp_path / "filter.db"), "--with", "chatmsg,dgb"],
            )

        assert result.exit_code == 0
        mock_collector_cls.assert_called_once_with(
            "6657",
            ANY,
            ws_url=None,
            type_filter=["chatmsg", "dgb"],
            type_exclude=None,
            message_callback=ANY,
            sink_factory=ANY,
            data_dir=ANY,
        )
