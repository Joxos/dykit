"""Clustering analysis for danmu messages — "R&D chains".

Groups similar (but not identical) danmu messages into clusters using greedy
pair-wise comparison with RapidFuzz. Queries message data from PostgreSQL
database. Only clusters with 2+ variants are reported, making them useful for
identifying promotional spam or coordinated copy-paste variants.

Functions:
    cluster(dsn, room_id, threshold, msg_type, limit) -> list: Query DB and cluster

CSV Output Format (when -o specified):
    5 columns: cluster_id, variant_rank, count, content, similarity_to_top
    - cluster_id: 1-based integer cluster identifier
    - variant_rank: 1-based rank within cluster (1 = highest frequency)
    - count: Number of occurrences of this variant
    - content: The message text
    - similarity_to_top: RapidFuzz ratio vs. cluster's top variant (1.0 for top)
"""

from __future__ import annotations

import psycopg
from psycopg import sql
from rapidfuzz import fuzz


def cluster(
    dsn: str,
    room_id: str,
    threshold: float = 0.6,
    msg_type: str | None = "chatmsg",
    limit: int = 1000,
    username: str | None = None,
    user_id: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    last: int | None = None,
    first: int | None = None,
    days: int | None = None,
) -> list[list[tuple[str, int]]]:
    """Cluster similar messages from database.

    Args:
        dsn: PostgreSQL connection string
        room_id: Room ID to query
        threshold: Similarity threshold for clustering (default: 0.6)
        msg_type: Message type to filter (default: 'chatmsg')
        limit: Maximum number of unique messages to consider (default: 1000)

    Returns:
        List of clusters; each cluster is a list of (content, count) tuples
    """
    if last is not None and first is not None:
        raise ValueError("Cannot use --last and --first together. Use one window direction only.")
    if days is not None and (from_date is not None or to_date is not None):
        raise ValueError(
            "Cannot combine --days with --from/--to. Use either relative days or explicit date range."
        )

    where_clauses: list[sql.SQL] = [
        sql.SQL("room_id = %s"),
        sql.SQL("content IS NOT NULL"),
        sql.SQL("content != ''"),
    ]
    params: list[str | int] = [room_id]

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

    order_limit_sql = sql.SQL("")
    if last is not None:
        order_limit_sql = sql.SQL("ORDER BY timestamp DESC LIMIT %s")
        params.append(last)
    elif first is not None:
        order_limit_sql = sql.SQL("ORDER BY timestamp ASC LIMIT %s")
        params.append(first)

    where_sql = sql.SQL(" AND ").join(where_clauses)

    # Query top messages by frequency
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            query = sql.SQL(
                """
                WITH filtered AS (
                    SELECT *
                    FROM danmaku
                    WHERE {where_sql}
                    {order_limit_sql}
                )
                SELECT content, COUNT(*) as count
                FROM filtered
                GROUP BY content
                ORDER BY count DESC
                LIMIT %s
                """
            ).format(where_sql=where_sql, order_limit_sql=order_limit_sql)
            cur.execute(query, (*params, limit))
            top_messages = cur.fetchall()  # Returns list of (content, count) tuples

    if not top_messages:
        return []

    # Use existing clustering algorithm
    return _greedy_cluster(top_messages, threshold)


def _greedy_cluster(
    top_messages: list[tuple[str, int]],
    threshold: float,
) -> list[list[tuple[str, int]]]:
    """Greedy O(n²) clustering of (content, count) pairs.

    For each unassigned message, either assign it to the first cluster whose
    representative (highest-count member) it is sufficiently similar to, or
    start a new cluster.

    Performance optimisation: skip similarity calculation if the length ratio between
    the two strings is more than 3x — they cannot possibly score >= threshold
    for reasonable threshold values, and it avoids wasting CPU on very long /
    very short string pairs.

    Args:
        top_messages: List of (content, count) sorted by count descending.
        threshold: Minimum RapidFuzz ratio to merge two messages.

    Returns:
        List of clusters; each cluster is a list of (content, count) tuples
        sorted by count descending.
    """
    # assigned[i] = cluster_index or -1
    assigned: list[int] = [-1] * len(top_messages)
    clusters: list[list[tuple[str, int]]] = []

    for i, (msg_i, cnt_i) in enumerate(top_messages):
        if assigned[i] != -1:
            continue

        # Start new cluster with this message as seed
        cluster_idx = len(clusters)
        clusters.append([(msg_i, cnt_i)])
        assigned[i] = cluster_idx

        len_i = len(msg_i)

        for j in range(i + 1, len(top_messages)):
            if assigned[j] != -1:
                continue

            msg_j, cnt_j = top_messages[j]
            len_j = len(msg_j)

            # Length-ratio pre-filter avoids expensive similarity calculations.
            if len_i == 0 or len_j == 0:
                continue
            if len_i > 3 * len_j or len_j > 3 * len_i:
                continue

            ratio = fuzz.ratio(msg_i, msg_j) / 100.0
            if ratio >= threshold:
                clusters[cluster_idx].append((msg_j, cnt_j))
                assigned[j] = cluster_idx

    return clusters
