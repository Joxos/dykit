"""SQL-based frequency ranking for danmu messages.



This module provides SQL frequency ranking to analyze which users

send the most messages in a room, or which message content appears

most frequently.

"""

from __future__ import annotations

import csv
from typing import Any, Literal

import psycopg
from psycopg import sql

from dykit.log import logger


def rank(
    dsn: str,
    room_id: str,
    top: int = 10,
    msg_type: str | None = "chatmsg",
    days: int | None = None,
    mode: Literal["user", "content"] = "user",
    username: str | None = None,
    user_id: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    last: int | None = None,
    first: int | None = None,
) -> list[dict[str, int | str]]:
    """Get top N ranked items by frequency from database.



    Supports two modes:

    - mode='user': Rank users by message count (default)

    - mode='content': Rank repeated message content by occurrence



    Args:

        dsn: PostgreSQL connection string

        room_id: Room ID to query

        top: Number of top results to return

        msg_type: Message type to filter (default: 'chatmsg')

        days: Optional number of days to look back (None = all time)

        mode: 'user' (default) or 'content'



    Returns:

        List of dicts with keys: 'username', 'count' (user mode)

        or 'content', 'count', 'first_seen', 'last_seen' (content mode)

    """
    if last is not None and first is not None:
        raise ValueError("Cannot use --last and --first together. Use one window direction only.")
    if days is not None and (from_date is not None or to_date is not None):
        raise ValueError(
            "Cannot combine --days with --from/--to. Use either relative days or explicit date range."
        )

    where_clauses: list[sql.SQL] = [sql.SQL("room_id = %s")]
    params: list[Any] = [room_id]

    if msg_type is not None:
        where_clauses.append(sql.SQL("msg_type = %s"))
        params.append(msg_type)
    if username is not None:
        where_clauses.append(sql.SQL("username = %s"))
        params.append(username)
    if user_id is not None:
        where_clauses.append(sql.SQL("user_id = %s"))
        params.append(user_id)
    if from_date is not None:
        where_clauses.append(sql.SQL("timestamp >= %s::timestamp"))
        params.append(from_date)
    if to_date is not None:
        where_clauses.append(sql.SQL("timestamp <= %s::timestamp + INTERVAL '1 day'"))
        params.append(to_date)
    if days is not None:
        where_clauses.append(sql.SQL("timestamp >= NOW() - INTERVAL '%s days'"))
        params.append(days)

    where_sql = sql.SQL(" AND ").join(where_clauses)
    order_limit_sql = sql.SQL("")
    if last is not None:
        order_limit_sql = sql.SQL("ORDER BY timestamp DESC LIMIT %s")
        params.append(last)
    elif first is not None:
        order_limit_sql = sql.SQL("ORDER BY timestamp ASC LIMIT %s")
        params.append(first)

    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            if mode == "content":
                query = sql.SQL(
                    """
                    WITH filtered AS (
                        SELECT *
                        FROM danmaku
                        WHERE {where_sql}
                        {order_limit_sql}
                    )
                    SELECT content, COUNT(*) AS count, MIN(timestamp) AS first_seen, MAX(timestamp) AS last_seen
                    FROM filtered
                    WHERE content IS NOT NULL AND content != ''
                    GROUP BY content
                    HAVING COUNT(*) > 1
                    ORDER BY count DESC
                    LIMIT %s
                    """
                ).format(where_sql=where_sql, order_limit_sql=order_limit_sql)
                cur.execute(query, (*params, top))
                results = cur.fetchall()
                return [
                    {"content": row[0], "count": row[1], "first_seen": row[2], "last_seen": row[3]}
                    for row in results
                ]

            query = sql.SQL(
                """
                WITH filtered AS (
                    SELECT *
                    FROM danmaku
                    WHERE {where_sql}
                    {order_limit_sql}
                )
                SELECT username, COUNT(*) as count
                FROM filtered
                GROUP BY username
                ORDER BY count DESC
                LIMIT %s
                """
            ).format(where_sql=where_sql, order_limit_sql=order_limit_sql)
            cur.execute(query, (*params, top))
            results = cur.fetchall()
            return [{"username": row[0], "count": row[1]} for row in results]


def export_rank(
    results: list[dict[str, Any]], mode: Literal["user", "content"], output: str
) -> None:
    with open(output, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        if mode == "user":
            writer.writerow(["rank", "username", "count"])
            for idx, row in enumerate(results, start=1):
                writer.writerow([idx, row.get("username"), row.get("count")])
        else:
            writer.writerow(["rank", "content", "count", "first_seen", "last_seen"])
            for idx, row in enumerate(results, start=1):
                writer.writerow(
                    [
                        idx,
                        row.get("content"),
                        row.get("count"),
                        row.get("first_seen"),
                        row.get("last_seen"),
                    ]
                )


def run_rank(args: Any) -> None:
    """CLI entry point for rank command.

    Args:
        args: Argparse namespace with dsn, room, top, msg_type, days
    """
    dsn = args.dsn
    room_id = args.room
    top = args.top
    msg_type = getattr(args, "msg_type", "chatmsg")
    days = getattr(args, "days", None)

    results = rank(dsn, room_id, top, msg_type, days)

    if not results:
        logger.info(f"No messages found for room {room_id}")
        return

    # Terminal output
    print(f"\n=== User Ranking (Top {len(results)}) ===")
    print(f"Room: {room_id}, Type: {msg_type}\n")
    print(f"{'Rank':<6}{'Count':<8}{'Username'}")
    print(f"{'────':<6}{'─────':<8}{'────────────────────'}")

    for rank_num, item in enumerate(results, start=1):
        print(f"{rank_num:<6}{item['count']:<8}{item['username']}")
