"""Clustering tool for finding similar danmu messages."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from rapidfuzz import fuzz

from .db import DataDb
from .filters import build_common_filters, parse_order_limit, validate_days_range


@dataclass
class ClusterResult:
    """Cluster result item."""

    representative: str
    count: int
    similar: list[tuple[str, int]]


def group_similar(messages: list[tuple[str, int]], threshold: float) -> list[ClusterResult]:
    """Greedily group ``(content, count)`` pairs by fuzzy text similarity.

    Pure and IO-free: the caller decides what the candidate set is (the SQL in
    :func:`cluster` does), this decides only how the candidates group. Cost is
    quadratic in the number of *unassigned* candidates, which is why the
    candidate set is capped by ``--limit`` in SQL rather than here.
    """
    clusters: list[ClusterResult] = []
    assigned: set[int] = set()

    for i, (content, count) in enumerate(messages):
        if i in assigned:
            continue

        similar = [(content, count)]
        assigned.add(i)

        for j, (other_content, other_count) in enumerate(messages):
            if j in assigned:
                continue

            if fuzz.ratio(content, other_content) / 100.0 >= threshold:
                similar.append((other_content, other_count))
                assigned.add(j)

        clusters.append(
            ClusterResult(
                representative=content,
                count=sum(total for _, total in similar),
                similar=similar,
            )
        )

    return clusters


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
        ORDER BY cnt DESC, content
        LIMIT ?
        """

    with DataDb(data) as db:
        rows = db.query(query_sql, (*params, limit))

    return group_similar([(row[0], row[1]) for row in rows], threshold)
