"""Ranking tool for danmu data."""

from __future__ import annotations

from dataclasses import dataclass

import psycopg
from psycopg import sql

from .query_filters import build_common_filters, parse_order_limit
from .runtime import resolve_runtime


@dataclass
class RankResult:
    """Rank result item."""

    rank: int
    value: str  # username or content
    count: int


def rank(
    dsn: str,
    room: str,
    top: int = 10,
    mode: str = "user",
    msg_type: str | None = "chatmsg",
    days: int | None = None,
    username: str | None = None,
    user_id: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    last: int | None = None,
    first: int | None = None,
) -> list[RankResult]:
    """Rank users or content by frequency.

    Args:
        dsn: PostgreSQL connection string.
        room: Room ID to query.
        top: Number of top results.
        mode: "user" or "content".
        msg_type: Message type to filter.
        days: Optional limit to recent N days.

    Returns:
        List of RankResult sorted by count descending.
    """
    if days is not None and (from_date is not None or to_date is not None):
        raise ValueError(
            "Cannot combine --days with --from/--to. Use either relative days or explicit date range."
        )

    order_limit_sql, limit_value = parse_order_limit(last, first)

    where_clauses, params = build_common_filters(
        room=room,
        msg_type=msg_type,
        username=username,
        user_id=user_id,
        from_date=from_date,
        to_date=to_date,
        days=days,
    )

    where_sql = sql.SQL(" AND ").join(where_clauses)
    if limit_value is not None:
        params.append(limit_value)

    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            group_field = "username" if mode == "user" else "content"
            query_sql = sql.SQL(
                """
                WITH filtered AS (
                    SELECT *
                    FROM danmaku
                    WHERE {where_sql}
                    {order_limit_sql}
                )
                SELECT {group_field}, COUNT(*) as cnt
                FROM filtered
                {content_guard}
                GROUP BY {group_field}
                ORDER BY cnt DESC
                LIMIT %s
                """
            ).format(
                where_sql=where_sql,
                order_limit_sql=order_limit_sql,
                group_field=sql.SQL(group_field),
                content_guard=sql.SQL("WHERE content IS NOT NULL AND content != ''")
                if mode == "content"
                else sql.SQL(""),
            )
            cur.execute(query_sql, (*params, top))
            results = cur.fetchall()

    return [RankResult(rank=i + 1, value=row[0], count=row[1]) for i, row in enumerate(results)]


def run_rank(
    room: str,
    top: int = 10,
    mode: str = "user",
    msg_type: str | None = "chatmsg",
    days: int | None = None,
    username: str | None = None,
    user_id: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    last: int | None = None,
    first: int | None = None,
    dsn: str | None = None,
) -> list[RankResult]:
    """Run rank command with CLI defaults."""
    resolved_room, resolved_dsn = resolve_runtime(room, dsn)

    return rank(
        resolved_dsn,
        resolved_room,
        top,
        mode,
        msg_type,
        days,
        username,
        user_id,
        from_date,
        to_date,
        last,
        first,
    )
