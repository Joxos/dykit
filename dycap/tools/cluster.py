"""Clustering analysis for danmu messages — "R&D chains".

Groups similar (but not identical) danmu messages into clusters using greedy
pair-wise comparison with difflib.SequenceMatcher.  Only clusters with 2+
variants are reported, making them useful for identifying promotional spam or
coordinated copy-paste variants.

Functions:
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

import csv
import difflib
from collections import Counter
from pathlib import Path

from dycap.log import logger
from dycap.tools.common import read_chatmsg


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
            - file: CSV file path to analyze
            - top: number of top unique messages to consider (default: 500)
            - all: if True, consider all unique messages
            - threshold: similarity threshold (default: 0.6)
            - output: optional CSV output file path
    """
    filepath = args.file
    threshold: float = args.threshold
    top_n: int | None = None if args.all else args.top
    output_path: str | None = args.output

    # ── Read messages ─────────────────────────────────────────────────────────
    messages = read_chatmsg(filepath)
    if not messages:
        logger.info(f"No chat messages found in {filepath}")
        return

    # ── Preprocessing: count frequencies ──────────────────────────────────────
    counter: Counter[str] = Counter(msg["content"] for msg in messages)

    # Take the top-N unique messages by frequency
    if top_n is not None:
        top_messages: list[tuple[str, int]] = counter.most_common(top_n)
    else:
        top_messages = counter.most_common()

    total_unique = len(top_messages)

    # ── Greedy clustering ──────────────────────────────────────────────────────
    all_clusters = _greedy_cluster(top_messages, threshold)

    # ── Filter: only clusters with 2+ variants ────────────────────────────────
    multi_clusters = [c for c in all_clusters if len(c) >= 2]

    # ── Sort clusters by total occurrence count descending ────────────────────
    def cluster_total(cluster: list[tuple[str, int]]) -> int:
        return sum(cnt for _, cnt in cluster)

    multi_clusters.sort(key=cluster_total, reverse=True)

    # ── Terminal output ────────────────────────────────────────────────────────
    top_label = f"top {total_unique}" if top_n is None else f"top {top_n}"
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
        out = Path(output_path)
        with open(out, "w", encoding="utf-8", newline="") as f:
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
        logger.info(f"Cluster CSV saved to {out}")
