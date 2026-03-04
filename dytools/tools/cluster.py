"""Clustering analysis for danmu messages — "R&D chains".

Groups similar (but not identical) danmu messages into clusters using greedy
pair-wise comparison with difflib.SequenceMatcher. Queries message data from
PostgreSQL database. Only clusters with 2+ variants are reported, making them
useful for identifying promotional spam or coordinated copy-paste variants.

Functions:
    cluster(dsn, room_id, threshold, msg_type, limit) -> list: Query DB and cluster
    run_cluster(args) -> None: Main entry point for cluster command

CSV Output Format (when -o specified):
    5 columns: cluster_id, variant_rank, count, content, similarity_to_top
    - cluster_id: 1-based integer cluster identifier
    - variant_rank: 1-based rank within cluster (1 = highest frequency)
    - count: Number of occurrences of this variant
    - content: The message text
    - similarity_to_top: SequenceMatcher ratio vs. cluster's top variant (1.0 for top)
"""

from __future__ import annotations

import difflib

import psycopg

from dytools.log import logger


def cluster(
    dsn: str,
    room_id: str,
    threshold: float = 0.6,
    msg_type: str = "chatmsg",
    limit: int = 1000,
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
    # Query top messages by frequency
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            query = """
                SELECT content, COUNT(*) as count
                FROM danmaku
                WHERE room_id = %s AND msg_type = %s AND content IS NOT NULL AND content != ''
                GROUP BY content
                ORDER BY count DESC
                LIMIT %s
            """
            cur.execute(query, (room_id, msg_type, limit))
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

    Performance optimisation: skip SequenceMatcher if the length ratio between
    the two strings is more than 3x — they cannot possibly score >= threshold
    for reasonable threshold values, and it avoids wasting CPU on very long /
    very short string pairs.

    Args:
        top_messages: List of (content, count) sorted by count descending.
        threshold: Minimum SequenceMatcher ratio to merge two messages.

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

            # Length-ratio pre-filter (avoids slow SequenceMatcher calls)
            if len_i == 0 or len_j == 0:
                continue
            if len_i > 3 * len_j or len_j > 3 * len_i:
                continue

            ratio = difflib.SequenceMatcher(None, msg_i, msg_j).ratio()
            if ratio >= threshold:
                clusters[cluster_idx].append((msg_j, cnt_j))
                assigned[j] = cluster_idx

    return clusters


def run_cluster(args) -> None:
    """Main entry point for cluster command.
    
    Args:
        args: Argparse namespace with:
            - dsn: PostgreSQL connection string
            - room: Room ID to query
            - threshold: similarity threshold (default: 0.6)
            - msg_type: message type to filter (default: 'chatmsg')
            - limit: max number of unique messages to consider (default: 1000)
            - output: optional CSV output file path
    """
    dsn = args.dsn
    room_id = args.room
    threshold: float = getattr(args, 'threshold', 0.6)
    msg_type: str = getattr(args, 'msg_type', 'chatmsg')
    limit: int = getattr(args, 'limit', 1000)
    output_path: str | None = getattr(args, 'output', None)
    
    # ── Query database and cluster ───────────────────────────────────────────
    all_clusters = cluster(dsn, room_id, threshold, msg_type, limit)
    
    if not all_clusters:
        logger.info(f"No messages found for room {room_id}")
        return
    
    # Calculate total unique messages from all clusters
    total_unique = sum(len(c) for c in all_clusters)

    # ── Filter: only clusters with 2+ variants ────────────────────────────────
    multi_clusters = [c for c in all_clusters if len(c) >= 2]

    # ── Sort clusters by total occurrence count descending ────────────────────
    def cluster_total(cluster: list[tuple[str, int]]) -> int:
        return sum(cnt for _, cnt in cluster)

    multi_clusters.sort(key=cluster_total, reverse=True)

    # ── Terminal output ────────────────────────────────────────────────────────
    top_label = f"{total_unique} unique msgs"
    print(
        f"\n=== 弹幕研发链聚类 (threshold={threshold:.2f}, {top_label} unique msgs) ===\n"
        f"Found {len(multi_clusters)} clusters with 2+ variants\n"
    )

    for idx, cluster in enumerate(multi_clusters, start=1):
        total = cluster_total(cluster)
        variants = len(cluster)
        print(f"─── Cluster {idx} ({variants} variants, {total} total) ───")
        max_cnt_width = len(str(cluster[0][1]))  # widest count for alignment
        for content, cnt in cluster:
            print(f"  [{cnt:>{max_cnt_width}}x] {content}")
        print()

    # ── CSV output ─────────────────────────────────────────────────────────────
    if output_path:
        with open(output_path, "w", encoding="utf-8", newline="") as f:
            import csv
            writer = csv.writer(f)
            writer.writerow(["cluster_id", "variant_rank", "count", "content", "similarity_to_top"])
            for cluster_id, cluster in enumerate(multi_clusters, start=1):
                top_content = cluster[0][0]
                for variant_rank, (content, count) in enumerate(cluster, start=1):
                    if variant_rank == 1:
                        sim = 1.0
                    else:
                        sim = round(difflib.SequenceMatcher(None, top_content, content).ratio(), 6)
                    writer.writerow([cluster_id, variant_rank, count, content, sim])
        logger.info(f"Cluster CSV saved to {output_path}")
