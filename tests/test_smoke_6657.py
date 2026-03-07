from __future__ import annotations

import csv
import os
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import psycopg
import pytest
from click.testing import CliRunner

from dykit.cli import cli
from dykit.cli.common import resolve_room_for_query


def _with_search_path(dsn: str, search_path: str) -> str:
    parts = urlsplit(dsn)
    query_items = dict(parse_qsl(parts.query, keep_blank_values=True))
    query_items["options"] = f"-csearch_path={search_path}"
    new_query = urlencode(query_items)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, new_query, parts.fragment))


@pytest.fixture
def smoke_dsn() -> str:
    base_dsn = os.environ.get("DYTOOLS_DSN")
    if not base_dsn:
        pytest.skip("DYTOOLS_DSN is not set; skip real-db smoke tests")
    return _with_search_path(base_dsn, "smoke,public")


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def seeded_smoke_db(smoke_dsn: str) -> str:
    resolved_room = resolve_room_for_query("6657")

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
            resolved_room,
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
            resolved_room,
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
            resolved_room,
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
            resolved_room,
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
            resolved_room,
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
def test_smoke_6657_commands(runner: CliRunner, seeded_smoke_db: str, tmp_path: Path) -> None:
    export_before = tmp_path / "smoke_6657_before.csv"
    export_after = tmp_path / "smoke_6657_after.csv"
    import_file = tmp_path / "import_one.csv"

    with open(import_file, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            ["timestamp", "username", "content", "user_level", "user_id", "room_id", "msg_type"]
        )
        writer.writerow(
            ["2026-03-07 10:01:00", "SmokeUser", "new msg", "9", "u9001", "6657", "chatmsg"]
        )

    result_init = runner.invoke(cli, ["--dsn", seeded_smoke_db, "init-db"])
    assert result_init.exit_code == 0
    assert "initialized successfully" in result_init.output

    result_rank = runner.invoke(cli, ["--dsn", seeded_smoke_db, "rank", "-r", "6657", "--top", "5"])
    assert result_rank.exit_code == 0
    assert "User Ranking" in result_rank.output
    assert "Alice" in result_rank.output

    result_search = runner.invoke(
        cli,
        ["--dsn", seeded_smoke_db, "search", "-r", "6657", "--last", "5"],
    )
    assert result_search.exit_code == 0
    assert "Search Results" in result_search.output

    result_cluster = runner.invoke(
        cli,
        ["--dsn", seeded_smoke_db, "cluster", "-r", "6657", "--limit", "50", "--threshold", "0.5"],
    )
    assert result_cluster.exit_code == 0

    result_export_before = runner.invoke(
        cli,
        ["--dsn", seeded_smoke_db, "export", "-r", "6657", "-o", str(export_before)],
    )
    assert result_export_before.exit_code == 0
    assert export_before.exists()

    result_prune = runner.invoke(cli, ["--dsn", seeded_smoke_db, "prune", "-r", "6657"])
    assert result_prune.exit_code == 0
    assert "Removed" in result_prune.output

    result_export_after = runner.invoke(
        cli,
        ["--dsn", seeded_smoke_db, "export", "-r", "6657", "-o", str(export_after)],
    )
    assert result_export_after.exit_code == 0
    assert export_after.exists()

    with open(export_before, encoding="utf-8", newline="") as f:
        before_rows = list(csv.reader(f))
    with open(export_after, encoding="utf-8", newline="") as f:
        after_rows = list(csv.reader(f))
    assert len(before_rows) > len(after_rows)

    result_import = runner.invoke(
        cli,
        ["--dsn", seeded_smoke_db, "import", str(import_file), "-r", "6657"],
    )
    assert result_import.exit_code == 0
    assert "Imported 1 records" in result_import.output

    result_collect_validation = runner.invoke(
        cli,
        [
            "--dsn",
            seeded_smoke_db,
            "collect",
            "-r",
            "6657",
            "--with",
            "chatmsg",
            "--without",
            "dgb",
        ],
    )
    assert result_collect_validation.exit_code == 1
    assert "Cannot use --with and --without together" in result_collect_validation.output

    result_service_help = runner.invoke(cli, ["service", "--help"])
    assert result_service_help.exit_code == 0
    assert "Commands:" in result_service_help.output
