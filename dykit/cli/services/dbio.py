from __future__ import annotations

import csv
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

ConnectCallable = Callable[[str], Any]


CREATE_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS danmaku (
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

    CREATE INDEX IF NOT EXISTS idx_danmaku_room_time
    ON danmaku(room_id, timestamp DESC);

    CREATE INDEX IF NOT EXISTS idx_danmaku_user_id
    ON danmaku(user_id);

    CREATE INDEX IF NOT EXISTS idx_danmaku_msg_type
    ON danmaku(msg_type);
"""


def import_csv_to_db(connect: ConnectCallable, dsn: str, file: str, room: str) -> int:
    conn = connect(dsn)
    with conn as conn:
        with conn.cursor() as cur:
            with open(file, "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                header = next(reader, None)

                if header is None:
                    raise ValueError("Empty CSV file")

                count = 0
                for row in reader:
                    if len(row) < 7:
                        continue

                    timestamp = row[0]
                    username = row[1]
                    content = row[2]
                    user_level = int(row[3]) if row[3] else None
                    user_id = row[4]
                    msg_type = row[6]

                    extra_str = row[7] if len(row) > 7 else ""
                    extra: dict[str, str] = {}
                    if extra_str:
                        try:
                            extra = json.loads(extra_str)
                        except (json.JSONDecodeError, ValueError):
                            pass

                    gift_id = extra.get("gfid")
                    gfcnt = extra.get("gfcnt")
                    gift_count = int(gfcnt) if gfcnt and str(gfcnt).isdigit() else None
                    gift_name = extra.get("gfn")
                    bl = extra.get("bl")
                    badge_level = int(bl) if bl and str(bl).isdigit() else None
                    badge_name = extra.get("bnn")
                    nl = extra.get("nl")
                    noble_level = int(nl) if nl and str(nl).isdigit() else None
                    avatar_url = extra.get("ic")

                    insert_query = """
                        INSERT INTO danmaku (
                            timestamp, room_id, msg_type, user_id, username, content, user_level,
                            gift_id, gift_count, gift_name, badge_level, badge_name, noble_level, avatar_url, raw_data
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """
                    cur.execute(
                        insert_query,
                        [
                            timestamp,
                            room,
                            msg_type,
                            user_id,
                            username,
                            content,
                            user_level,
                            gift_id,
                            gift_count,
                            gift_name,
                            badge_level,
                            badge_name,
                            noble_level,
                            avatar_url,
                            None,
                        ],
                    )
                    count += 1

                conn.commit()
                return count


def export_room_to_csv(
    connect: ConnectCallable, dsn: str, resolved_room: str, output_path: str
) -> int:
    conn = connect(dsn)
    with conn as conn:
        with conn.cursor() as cur:
            query = """
                SELECT timestamp, username, content, user_level, user_id, room_id, msg_type
                FROM danmaku
                WHERE room_id = %s
                ORDER BY timestamp
            """
            cur.execute(query, [resolved_room])
            results = cur.fetchall()

            if not results:
                return 0

            with open(output_path, "w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(
                    [
                        "timestamp",
                        "username",
                        "content",
                        "user_level",
                        "user_id",
                        "room_id",
                        "msg_type",
                        "extra",
                    ]
                )
                for row in results:
                    writer.writerow(list(row) + [""])

            return len(results)


def init_database_schema(connect: ConnectCallable, dsn: str) -> None:
    conn = connect(dsn)
    with conn as conn:
        with conn.cursor() as cur:
            cur.execute(CREATE_TABLE_SQL)
            conn.commit()


def export_search_results_to_csv(results: list[dict[str, object]], output_path: str) -> None:
    path = Path(output_path)
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "timestamp",
                "username",
                "content",
                "user_level",
                "user_id",
                "room_id",
                "msg_type",
            ]
        )
        for row in results:
            writer.writerow(
                [
                    row["timestamp"],
                    row["username"],
                    row["content"],
                    row["user_level"],
                    row["user_id"],
                    row["room_id"],
                    row["msg_type"],
                ]
            )


def export_clusters_to_csv(clusters: list[list[tuple[str, int]]], output_path: str) -> None:
    from rapidfuzz import fuzz

    with open(output_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["cluster_id", "variant_rank", "count", "content", "similarity"])
        for cluster_id, clust in enumerate(clusters, start=1):
            top_content = clust[0][0]
            for variant_rank, (content, count) in enumerate(clust, start=1):
                if variant_rank == 1:
                    sim = 1.0
                else:
                    sim = round(fuzz.ratio(top_content, content) / 100.0, 6)
                writer.writerow([cluster_id, variant_rank, count, content, sim])
