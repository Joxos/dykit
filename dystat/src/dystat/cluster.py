"""Clustering tool for finding similar danmu messages."""

from __future__ import annotations

from dataclasses import dataclass

import psycopg
from psycopg import sql
from rapidfuzz import fuzz

from .query_filters import build_common_filters, parse_order_limit
from .runtime import resolve_runtime


@dataclass
class ClusterResult:
    """Cluster result item."""

    representative: str
    count: int
    similar: list[tuple[str, int]]


def cluster(
    dsn: str,
    room: str,
    threshold: float = 0.5,
    msg_type: str | None = "chatmsg",
    limit: int = 50,
    username: str | None = None,
    user_id: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    last: int | None = None,
    first: int | None = None,
    days: int | None = None,
) -> list[ClusterResult]:
    """Cluster similar messages using text similarity.

    Args:
        dsn: PostgreSQL connection string.
        room: Room ID to analyze.
        limit: Number of source messages to consider.
        threshold: Similarity threshold (0-1).
        msg_type: Message type to filter.

    Returns:
        List of clusters with representative and similar messages.
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
    where_clauses.extend([sql.SQL("content IS NOT NULL"), sql.SQL("content != ''")])

    if limit_value is not None:
        params.append(limit_value)

    where_sql = sql.SQL(" AND ").join(where_clauses)
    query_sql = sql.SQL(
        """
        WITH filtered AS (
            SELECT *
            FROM danmaku
            WHERE {where_sql}
            {order_limit_sql}
        )
        SELECT content, COUNT(*) as cnt
        FROM filtered
        GROUP BY content
        ORDER BY cnt DESC
        LIMIT %s
        """
    ).format(where_sql=where_sql, order_limit_sql=order_limit_sql)

    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(query_sql, (*params, limit))
            messages = [(row[0], row[1]) for row in cur.fetchall()]

    if not messages:
        return []

    # Greedy clustering
    clusters: list[ClusterResult] = []
    assigned = set()

    for i, (content, count) in enumerate(messages):
        if i in assigned:
            continue

        similar = [(content, count)]
        assigned.add(i)

        for j, (other_content, other_count) in enumerate(messages):
            if j in assigned:
                continue

            ratio = fuzz.ratio(content, other_content) / 100.0
            if ratio >= threshold:
                similar.append((other_content, other_count))
                assigned.add(j)

        clusters.append(
            ClusterResult(
                representative=content,
                count=sum(c for _, c in similar),
                similar=similar,
            )
        )

    return clusters


def run_cluster(
    room: str,
    threshold: float = 0.5,
    msg_type: str | None = "chatmsg",
    limit: int = 50,
    username: str | None = None,
    user_id: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    last: int | None = None,
    first: int | None = None,
    days: int | None = None,
    dsn: str | None = None,
) -> list[ClusterResult]:
    """Run cluster command."""
    resolved_room, resolved_dsn = resolve_runtime(room, dsn)

    return cluster(
        resolved_dsn,
        resolved_room,
        threshold,
        msg_type,
        limit,
        username,
        user_id,
        from_date,
        to_date,
        last,
        first,
        days,
    )
