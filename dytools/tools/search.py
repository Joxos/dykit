"""Full-text search for danmaku messages in PostgreSQL database.

This module provides flexible searching of danmaku messages with support
for keyword matching, user filtering, time ranges, and message type filtering.
"""

from __future__ import annotations

from typing import Any

import psycopg
from psycopg import sql


def search(
    dsn: str,
    room_id: str,
    query: str | None = None,
    username: str | None = None,
    user_id: str | None = None,
    msg_type: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    last: int | None = None,
    first: int | None = None,
) -> list[dict[str, Any]]:
    """Search danmaku messages with multiple filtering options.

    Args:
        dsn: PostgreSQL connection string
        room_id: Room ID to search
        query: Keyword to search in content (case-insensitive)
        username: Filter by exact username
        user_id: Filter by exact user_id
        msg_type: Filter by message type (e.g., 'chatmsg', 'dgb')
        from_date: Start date for time range (YYYY-MM-DD format)
        to_date: End date for time range (YYYY-MM-DD format)
        last: Return the last (most recent) N messages (DESC order)
        first: Return the first (earliest) N messages (ASC order)

    Returns:
        List of dicts with keys: timestamp, username, content, user_level,
        user_id, room_id, msg_type

    Raises:
        ValueError: If both last and first are provided
    """
    # Validate mutual exclusivity
    if last is not None and first is not None:
        raise ValueError("Cannot use both 'last' and 'first' parameters")

    # Default to last 100 if neither specified
    if last is None and first is None:
        last = 100

    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            # Build dynamic WHERE clause
            where_clauses: list[sql.SQL] = [sql.SQL("room_id = %s")]
            params: list[Any] = [room_id]

            # Keyword search with ILIKE (case-insensitive)
            if query is not None:
                where_clauses.append(sql.SQL("content ILIKE %s"))
                params.append(f"%{query}%")

            # Username filter
            if username is not None:
                where_clauses.append(sql.SQL("username = %s"))
                params.append(username)

            # User ID filter
            if user_id is not None:
                where_clauses.append(sql.SQL("user_id = %s"))
                params.append(user_id)

            # Message type filter
            if msg_type is not None:
                where_clauses.append(sql.SQL("msg_type = %s"))
                params.append(msg_type)

            # Date range filters
            if from_date is not None:
                where_clauses.append(sql.SQL("timestamp >= %s::timestamp"))
                params.append(from_date)

            if to_date is not None:
                where_clauses.append(sql.SQL("timestamp <= %s::timestamp + INTERVAL '1 day'"))
                params.append(to_date)

            # Build final query with appropriate ordering
            where_clause = sql.SQL(" AND ").join(where_clauses)
            if last is not None:
                query_sql = sql.SQL(
                    """
                    SELECT timestamp, username, content, user_level, user_id, room_id, msg_type
                    FROM danmaku
                    WHERE {where_clause}
                    ORDER BY timestamp DESC
                    LIMIT %s
                    """
                ).format(where_clause=where_clause)
                params.append(last)
            else:  # first is not None
                query_sql = sql.SQL(
                    """
                    SELECT timestamp, username, content, user_level, user_id, room_id, msg_type
                    FROM danmaku
                    WHERE {where_clause}
                    ORDER BY timestamp ASC
                    LIMIT %s
                    """
                ).format(where_clause=where_clause)
                params.append(first)

            cur.execute(query_sql, params)
            results = cur.fetchall()

            return [
                {
                    "timestamp": row[0],
                    "username": row[1],
                    "content": row[2],
                    "user_level": row[3],
                    "user_id": row[4],
                    "room_id": row[5],
                    "msg_type": row[6],
                }
                for row in results
            ]
