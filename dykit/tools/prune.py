"""Tool for deduplicating danmaku records in PostgreSQL database.

This tool provides functionality to:
- Connect to PostgreSQL database via DSN
- Identify duplicate danmaku records based on (room_id, timestamp, user_id, content)
- Remove duplicates while keeping the most recent record (MAX id)
- Support efficient SQL-based deduplication using CTE and window functions

Usage:
    python -m dykit prune --dsn "postgresql://..." --room 6657
"""

from __future__ import annotations

from typing import Any

import psycopg

from dykit.log import logger


def run_prune(args: Any) -> None:
    """CLI entry point for prune command.

    Args:
        args: Argparse namespace with:
            - dsn: PostgreSQL connection string
            - room: room_id to deduplicate
    """
    dsn = args.dsn
    room_id = args.room

    deleted_count = prune(dsn, room_id)

    logger.info(f"Deleted {deleted_count} duplicate records from room {room_id}")


def prune(dsn: str, room_id: str) -> int:
    """Remove duplicate danmaku records from database.

    Args:
        dsn: PostgreSQL connection string
        room_id: Room ID to deduplicate

    Returns:
        Number of duplicate rows deleted
    """
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            query = """
                WITH dupes AS (
                    SELECT id,
                           ROW_NUMBER() OVER (
                               PARTITION BY room_id, timestamp, user_id, content
                               ORDER BY id DESC
                           ) AS rn
                    FROM danmaku
                    WHERE room_id = %s
                )
                DELETE FROM danmaku WHERE id IN (SELECT id FROM dupes WHERE rn > 1)
                RETURNING id
            """
            cur.execute(query, (room_id,))
            deleted_ids = cur.fetchall()
            conn.commit()

    return len(deleted_ids)
