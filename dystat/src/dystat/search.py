"""Search tool for finding danmu messages."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from dycommon.timestamps import parse_timestamp

from .db import DataDb
from .query_filters import build_common_filters, parse_order_limit
from .runtime import resolve_runtime


@dataclass
class SearchResult:
    """Search result item."""

    timestamp: datetime
    username: str | None
    content: str | None
    msg_type: str


def search(
    data: Path,
    room: str,
    query: str | None = None,
    username: str | None = None,
    user_id: str | None = None,
    msg_type: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    last: int | None = None,
    first: int | None = None,
) -> list[SearchResult]:
    """Search danmu messages with filters.

    Args:
        data: SQLite run file or directory of run files.
        room: Room ID to search.
        query: Filter by content (LIKE).
        username: Filter by username.
        user_id: Filter by user ID.
        msg_type: Filter by message type.
        from_date: Filter from timestamp.
        to_date: Filter to timestamp.
        last: Return the last (most recent) N messages.
        first: Return the first (earliest) N messages.

    Returns:
        List of matching messages.
    """
    if last is None and first is None:
        last = 100

    order_limit_sql, limit_value = parse_order_limit(last, first)

    where_clauses, params = build_common_filters(
        room=room,
        msg_type=msg_type,
        username=username,
        user_id=user_id,
        from_date=from_date,
        to_date=to_date,
    )

    if query is not None:
        where_clauses.append("content LIKE ?")
        params.append(f"%{query}%")

    where_sql = " AND ".join(where_clauses)
    query_sql = f"""
        SELECT timestamp, username, content, msg_type
        FROM danmaku_all
        WHERE {where_sql}
        {order_limit_sql}
        """
    if limit_value is None:
        raise ValueError("Invalid limit value")
    params = [*params, limit_value]

    with DataDb(data) as db:
        rows = db.query(query_sql, params)

    return [
        SearchResult(
            timestamp=parse_timestamp(row[0]),
            username=row[1],
            content=row[2],
            msg_type=row[3],
        )
        for row in rows
    ]


def run_search(
    room: str,
    query: str | None = None,
    username: str | None = None,
    user_id: str | None = None,
    msg_type: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    last: int | None = None,
    first: int | None = None,
    data: str | None = None,
) -> list[SearchResult]:
    """Run search command."""
    resolved_room, resolved_data = resolve_runtime(room, data)

    return search(
        resolved_data,
        resolved_room,
        query,
        username,
        user_id,
        msg_type,
        from_date,
        to_date,
        last,
        first,
    )
