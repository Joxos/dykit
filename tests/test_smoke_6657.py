from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import psycopg
import pytest
from click.testing import CliRunner
from dycap.cli import collect
from dycap.collector import AsyncCollector
from dycap.storage import ConsoleStorage, CSVStorage, PostgreSQLStorageFromDSN
from dycap.types import DanmuMessage
from dystat.cli import cli

from dyproto import MessageType


def _with_search_path(dsn: str, search_path: str) -> str:
    parts = urlsplit(dsn)
    query_items = dict(parse_qsl(parts.query, keep_blank_values=True))
    query_items["options"] = f"-csearch_path={search_path}"
    new_query = urlencode(query_items)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, new_query, parts.fragment))


@pytest.fixture
def smoke_dsn() -> str:
    base_dsn = os.environ.get("DYKIT_DSN")
    if not base_dsn:
        pytest.skip("DYKIT_DSN is not set; skip real-db smoke tests")
    return _with_search_path(base_dsn, "smoke,public")


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def seeded_smoke_db(smoke_dsn: str) -> str:
    # New packages use room_id strings directly — no resolution needed.
    room_id = "6657"

    setup_sql = """
    CREATE SCHEMA IF NOT EXISTS smoke;

    CREATE TABLE IF NOT EXISTS smoke.danmaku (
        id          SERIAL PRIMARY KEY,
        timestamp   TIMESTAMP NOT NULL,
        room_id     TEXT NOT NULL,
        msg_type    TEXT NOT NULL,
        user_id     TEXT,
        username    TEXT,
        content     TEXT,
        user_level  INTEGER,
        gift_id     TEXT,
        gift_count  INTEGER,
        gift_name   TEXT,
        badge_level INTEGER,
        badge_name  TEXT,
        noble_level INTEGER,
        avatar_url  TEXT,
        raw_data    JSONB
    );

    CREATE INDEX IF NOT EXISTS idx_smoke_danmaku_room_time
    ON smoke.danmaku(room_id, timestamp DESC);

    CREATE INDEX IF NOT EXISTS idx_smoke_danmaku_user_id
    ON smoke.danmaku(user_id);

    CREATE INDEX IF NOT EXISTS idx_smoke_danmaku_msg_type
    ON smoke.danmaku(msg_type);

    TRUNCATE TABLE smoke.danmaku;
    """

    seed_rows = [
        (
            "2026-03-07 10:00:00",
            room_id,
            "chatmsg",
            "u1001",
            "Alice",
            "冲冲冲",
            12,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
        ),
        (
            "2026-03-07 10:00:05",
            room_id,
            "chatmsg",
            "u1002",
            "Bob",
            "冲冲冲",
            8,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
        ),
        (
            "2026-03-07 10:00:10",
            room_id,
            "chatmsg",
            "u1001",
            "Alice",
            "666",
            12,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
        ),
        (
            "2026-03-07 10:00:10",
            room_id,
            "chatmsg",
            "u1001",
            "Alice",
            "666",
            12,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
        ),
        (
            "2026-03-07 10:00:15",
            room_id,
            "dgb",
            "u2001",
            "GiftUser",
            "送礼",
            18,
            "g1",
            3,
            "火箭",
            None,
            None,
            None,
            None,
        ),
    ]

    insert_sql = """
    INSERT INTO smoke.danmaku (
        timestamp, room_id, msg_type, user_id, username, content, user_level,
        gift_id, gift_count, gift_name, badge_level, badge_name, noble_level, avatar_url, raw_data
    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """

    with psycopg.connect(smoke_dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(setup_sql)
            for row in seed_rows:
                cur.execute(insert_sql, [*row, None])
        conn.commit()

    return smoke_dsn


@pytest.mark.smoke
def test_smoke_6657_commands(runner: CliRunner, seeded_smoke_db: str) -> None:
    # rank — Alice sent the most messages
    result_rank = runner.invoke(cli, ["rank", "--dsn", seeded_smoke_db, "-r", "6657", "--top", "5"])
    assert result_rank.exit_code == 0, result_rank.output
    assert "Alice" in result_rank.output

    # search — find messages containing "冲冲冲"
    result_search = runner.invoke(
        cli, ["search", "--dsn", seeded_smoke_db, "-r", "6657", "--content", "冲冲冲"]
    )
    assert result_search.exit_code == 0, result_search.output
    assert "Found" in result_search.output

    # cluster — should complete without error
    result_cluster = runner.invoke(
        cli,
        ["cluster", "--dsn", seeded_smoke_db, "-r", "6657", "--limit", "50", "--threshold", "0.5"],
    )
    assert result_cluster.exit_code == 0, result_cluster.output
    assert "clusters" in result_cluster.output

    # prune — should remove the duplicate "666" record for Alice
    result_prune = runner.invoke(cli, ["prune", "--dsn", seeded_smoke_db, "-r", "6657"])
    assert result_prune.exit_code == 0, result_prune.output
    assert "Removed" in result_prune.output


@pytest.mark.smoke
@pytest.mark.asyncio
async def test_smoke_dycap_postgres_storage(seeded_smoke_db: str) -> None:
    storage = await PostgreSQLStorageFromDSN.create(room_id="6657", dsn=seeded_smoke_db)
    message = DanmuMessage(
        timestamp=datetime.now(),
        room_id="6657",
        msg_type=MessageType.CHATMSG,
        user_id="u3001",
        username="SmokeCollector",
        content="dycap-postgres-smoke",
        user_level=1,
        raw_data={"type": "chatmsg", "txt": "dycap-postgres-smoke"},
    )

    async with storage:
        await storage.save(message)

    with psycopg.connect(seeded_smoke_db) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM danmaku WHERE room_id = %s AND content = %s",
                ("6657", "dycap-postgres-smoke"),
            )
            row = cur.fetchone()
    assert row is not None
    count = row[0]
    assert count >= 1


@pytest.mark.smoke
@pytest.mark.asyncio
async def test_smoke_dycap_csv_storage(tmp_path: Path) -> None:
    output_file = tmp_path / "smoke.csv"
    storage = CSVStorage(output_file)
    message = DanmuMessage(
        timestamp=datetime.now(),
        room_id="6657",
        msg_type=MessageType.CHATMSG,
        user_id="u3002",
        username="SmokeCSV",
        content="dycap-csv-smoke",
        user_level=1,
        raw_data={"type": "chatmsg", "txt": "dycap-csv-smoke"},
    )

    async with storage:
        await storage.save(message)

    text = output_file.read_text(encoding="utf-8")
    assert "dycap-csv-smoke" in text


@pytest.mark.smoke
@pytest.mark.asyncio
async def test_smoke_dycap_console_storage(capsys: pytest.CaptureFixture[str]) -> None:
    storage = ConsoleStorage()
    message = DanmuMessage(
        timestamp=datetime.now(),
        room_id="6657",
        msg_type=MessageType.CHATMSG,
        user_id="u3003",
        username="SmokeConsole",
        content="dycap-console-smoke",
        user_level=1,
        raw_data={"type": "chatmsg", "txt": "dycap-console-smoke"},
    )

    async with storage:
        await storage.save(message)

    captured = capsys.readouterr()
    assert "dycap-console-smoke" in captured.out


@pytest.mark.smoke
@pytest.mark.asyncio
async def test_smoke_dycap_async_collector_instantiation(seeded_smoke_db: str) -> None:
    storage = await PostgreSQLStorageFromDSN.create(room_id="6657", dsn=seeded_smoke_db)
    try:
        collector = AsyncCollector("6657", storage)
        assert collector.room_id == "6657"
        assert collector.storage is storage
    finally:
        await storage.close()


class _FakeCollector:
    def __init__(
        self,
        room_id: str,
        storage: Any,
        type_filter: list[str] | None = None,
        type_exclude: list[str] | None = None,
        message_callback: Any | None = None,
    ) -> None:
        self.room_id = room_id
        self.storage = storage
        self.type_filter = type_filter
        self.type_exclude = type_exclude
        self.message_callback = message_callback

    async def connect(self) -> None:
        message = DanmuMessage(
            timestamp=datetime.now(),
            room_id=self.room_id,
            msg_type=MessageType.CHATMSG,
            user_id="u3999",
            username="SmokeCLI",
            content="dycap-cli-smoke",
            user_level=1,
            raw_data={"type": "chatmsg", "txt": "dycap-cli-smoke"},
        )
        await self.storage.save(message)
        if self.message_callback is not None:
            self.message_callback(message)

    async def stop(self) -> None:
        return


@pytest.mark.smoke
def test_smoke_dycap_cli_postgres(
    runner: CliRunner,
    seeded_smoke_db: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("dycap.cli.AsyncCollector", _FakeCollector)

    result = runner.invoke(
        collect, ["--storage", "postgres", "--dsn", seeded_smoke_db, "-r", "6657"]
    )
    assert result.exit_code == 0, result.output

    with psycopg.connect(seeded_smoke_db) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM danmaku WHERE room_id = %s AND content = %s",
                ("6657", "dycap-cli-smoke"),
            )
            row = cur.fetchone()
    assert row is not None
    assert row[0] >= 1


@pytest.mark.smoke
def test_smoke_dycap_cli_csv(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("dycap.cli.AsyncCollector", _FakeCollector)
    output_file = tmp_path / "cli_smoke.csv"

    result = runner.invoke(
        collect,
        ["--storage", "csv", "-o", str(output_file), "-r", "6657"],
    )
    assert result.exit_code == 0, result.output
    text = output_file.read_text(encoding="utf-8")
    assert "dycap-cli-smoke" in text


@pytest.mark.smoke
def test_smoke_dycap_cli_console(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("dycap.cli.AsyncCollector", _FakeCollector)

    result = runner.invoke(collect, ["--storage", "console", "-r", "6657"])
    assert result.exit_code == 0, result.output
    assert "dycap-cli-smoke" in result.output
    assert "[6657]" in result.output


@pytest.mark.smoke
def test_smoke_dycap_cli_csv_always_shows_output(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("dycap.cli.AsyncCollector", _FakeCollector)
    output_file = tmp_path / "cli_smoke_output.csv"

    result = runner.invoke(
        collect,
        ["--storage", "csv", "-o", str(output_file), "-r", "6657"],
    )
    assert result.exit_code == 0, result.output
    assert "Collecting from room 6657" in result.output
    assert "dycap-cli-smoke" in result.output
    assert "Summary:" in result.output
