from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import psycopg
import pytest
from dycap.schema import SCHEMA_STATEMENTS
from dycap.storage.postgres import PostgreSQLStorageFromDSN
from dycap.types import DanmuMessage

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
def seeded_smoke_db(smoke_dsn: str) -> str:
    setup_sql = "CREATE SCHEMA IF NOT EXISTS smoke;" + "".join(SCHEMA_STATEMENTS)

    truncate_sql = """
    TRUNCATE TABLE danmaku RESTART IDENTITY;
    TRUNCATE TABLE danmaku_dead_letter RESTART IDENTITY;
    TRUNCATE TABLE collection_sessions RESTART IDENTITY;
    """

    with psycopg.connect(smoke_dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(setup_sql)
            cur.execute(truncate_sql)
        conn.commit()

    return smoke_dsn


@pytest.mark.smoke
@pytest.mark.asyncio
async def test_postgres_storage_quarantines_bad_raw_data(
    seeded_smoke_db: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bad_records_path = tmp_path / "bad-records.ndjson"
    monkeypatch.setenv("DYCAP_BAD_RECORDS_PATH", str(bad_records_path))

    storage = await PostgreSQLStorageFromDSN.create(room_id="6657", dsn=seeded_smoke_db)
    good_message = DanmuMessage(
        timestamp=datetime.now(),
        room_id="6657",
        msg_type=MessageType.CHATMSG,
        user_id="u4001",
        username="GoodRow",
        content="good-after-bad",
        user_level=1,
        raw_data={"type": "chatmsg", "txt": "good-after-bad"},
    )
    bad_message = DanmuMessage(
        timestamp=datetime.now(),
        room_id="6657",
        msg_type=MessageType.DGB,
        user_id="u4002",
        username="BadRow",
        content=None,
        user_level=2,
        gift_id="g1",
        gift_count=1,
        gift_name="粉丝荧光棒",
        raw_data={"type": "dgb", "mss": "bad\x00value", "pma": "723113883"},
    )

    async with storage:
        await storage.save(good_message)
        await storage.save(bad_message)

    with psycopg.connect(seeded_smoke_db) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM danmaku WHERE room_id = %s AND content = %s",
                ("6657", "good-after-bad"),
            )
            good_count_row = cur.fetchone()
            cur.execute(
                "SELECT COUNT(*) FROM danmaku_dead_letter WHERE room_id = %s AND username = %s",
                ("6657", "BadRow"),
            )
            dead_letter_count_row = cur.fetchone()

    assert good_count_row is not None
    assert dead_letter_count_row is not None
    assert good_count_row[0] >= 1
    assert dead_letter_count_row[0] == 0
    assert not bad_records_path.exists()


@pytest.mark.smoke
@pytest.mark.asyncio
async def test_postgres_storage_sanitizes_nul_bytes_before_insert(
    seeded_smoke_db: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bad_records_path = tmp_path / "bad-records.ndjson"
    monkeypatch.setenv("DYCAP_BAD_RECORDS_PATH", str(bad_records_path))

    storage = await PostgreSQLStorageFromDSN.create(room_id="6657", dsn=seeded_smoke_db)
    message = DanmuMessage(
        timestamp=datetime.now(),
        room_id="6657",
        msg_type=MessageType.CHATMSG,
        user_id="u4003",
        username="NullCleaner",
        content="nul\x00message",
        user_level=1,
        raw_data={"type": "chatmsg", "txt": "nul\x00message"},
    )

    async with storage:
        await storage.save(message)

    with psycopg.connect(seeded_smoke_db) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT content, raw_data->>'txt' FROM danmaku WHERE room_id = %s AND username = %s ORDER BY id DESC LIMIT 1",
                ("6657", "NullCleaner"),
            )
            row = cur.fetchone()

    assert row is not None
    assert row[0] == "nulmessage"
    assert row[1] == "nulmessage"
    assert not bad_records_path.exists()
