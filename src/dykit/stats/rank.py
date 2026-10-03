"""Rank users or content by frequency."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .db import DataDb
from .filters import build_common_filters, parse_order_limit, validate_days_range


@dataclass
class RankResult:
    """Rank result item."""

    rank: int
    value: str  # username or content
    count: int


def rank(
    data: Path,
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
        data: SQLite run file or directory of run files.
        room: Room ID to query.
        top: Number of top results.
        mode: "user" or "content".
        msg_type: Message type to filter.
        days: Optional limit to recent N days.

    Returns:
        List of RankResult sorted by count descending.
    """
    validate_days_range(days, from_date, to_date)

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

    where_sql = " AND ".join(where_clauses)
    params = list(params)
    if limit_value is not None:
        params.append(limit_value)

    group_field = "username" if mode == "user" else "content"
    content_guard = "WHERE content IS NOT NULL AND content != ''" if mode == "content" else ""

    query_sql = f"""
        WITH filtered AS (
            SELECT *
            FROM danmaku_all
            WHERE {where_sql}
            {order_limit_sql}
        )
        SELECT {group_field}, COUNT(*) AS cnt
        FROM filtered
        {content_guard}
        GROUP BY {group_field}
        ORDER BY cnt DESC, {group_field}
        LIMIT ?
        """

    with DataDb(data) as db:
        rows = db.query(query_sql, (*params, top))

    return [RankResult(rank=i + 1, value=row[0], count=row[1]) for i, row in enumerate(rows)]
