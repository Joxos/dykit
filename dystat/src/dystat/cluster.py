"""Clustering tool for finding similar danmu messages."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from rapidfuzz import fuzz

from .db import DataDb
from .query_filters import build_common_filters, parse_order_limit
from .runtime import resolve_runtime


@dataclass
class ClusterResult:
    """Cluster result item."""

    representative: str
    count: int
    similar: list[tuple[str, int]]


def cluster(
    data: Path,
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
        data: SQLite run file or directory of run files.
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
    where_clauses.extend(["content IS NOT NULL", "content != ''"])

    where_sql = " AND ".join(where_clauses)
    params = list(params)
    if limit_value is not None:
        params.append(limit_value)

    query_sql = f"""
        WITH filtered AS (
            SELECT *
            FROM danmaku_all
            WHERE {where_sql}
            {order_limit_sql}
        )
        SELECT content, COUNT(*) AS cnt
        FROM filtered
        GROUP BY content
        ORDER BY cnt DESC
        LIMIT ?
        """

    with DataDb(data) as db:
        rows = db.query(query_sql, (*params, limit))
        messages = [(row[0], row[1]) for row in rows]

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
    data: str | None = None,
) -> list[ClusterResult]:
    """Run cluster command."""
    resolved_room, resolved_data = resolve_runtime(room, data)

    return cluster(
        resolved_data,
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
