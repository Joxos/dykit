"""Frequency ranking analysis for danmu messages.

This module provides frequency ranking functionality for analyzing which
messages appear most often in chat logs. Supports displaying top-N results
in terminal or exporting full rankings to CSV.

Functions:
    run_rank(args) -> None: Main entry point for rank command

CSV Output Format (when -o specified):
    5 columns: rank, count, content, first_user, first_time
    - rank: Ranking position (1-based)
    - count: Number of occurrences
    - content: The message text
    - first_user: Username who first sent this message
    - first_time: Timestamp of first occurrence
"""

from __future__ import annotations

import csv
from pathlib import Path

from dycap.log import logger
from dycap.tools.common import read_chatmsg


def run_rank(args) -> None:
    """Main entry point for rank command.

    Args:
        args: Argparse namespace with:
            - file: CSV file path to analyze
            - top: number of top results to display (default: 50)
            - all: if True, display all unique messages
            - output: optional CSV output file path
    """
    filepath = args.file
    top_n = None if args.all else args.top
    output_path = args.output

    # Read chatmsg rows
    messages = read_chatmsg(filepath)

    if not messages:
        logger.info(f"No chat messages found in {filepath}")
        return

    # Build frequency map with first occurrence tracking
    # Format: {content: {"count": N, "first_user": str, "first_time": str}}
    freq_map = {}
    for msg in messages:
        content = msg["content"]
        if content not in freq_map:
            freq_map[content] = {
                "count": 1,
                "first_user": msg["username"],
                "first_time": msg["timestamp"],
            }
        else:
            freq_map[content]["count"] += 1

    # Sort by frequency descending
    ranked = sorted(freq_map.items(), key=lambda x: x[1]["count"], reverse=True)

    total_messages = len(messages)
    unique_count = len(ranked)

    # Terminal output
    display_count = len(ranked) if top_n is None else min(top_n, len(ranked))
    print(f"\n=== 弹幕频率排名 (Top {display_count} / {unique_count} unique) ===")
    print(f"Total: {total_messages} messages, {unique_count} unique\n")
    print(f"{'Rank':<6}{'Count':<8}{'Message'}")
    print(f"{'────':<6}{'─────':<8}{'───────────────────────────────'}")

    for rank, (content, data) in enumerate(ranked[:display_count], start=1):
        count = data["count"]
        # Truncate long messages for terminal display
        display_content = content if len(content) <= 50 else content[:47] + "..."
        print(f"{rank:<6}{count:<8}{display_content}")

    # File output (CSV)
    if output_path:
        output_file = Path(output_path)
        with open(output_file, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            # Header
            writer.writerow(["rank", "count", "content", "first_user", "first_time"])
            # Data rows
            for rank, (content, data) in enumerate(ranked, start=1):
                writer.writerow(
                    [
                        rank,
                        data["count"],
                        content,
                        data["first_user"],
                        data["first_time"],
                    ]
                )
        logger.info(f"Ranking saved to {output_path} ({len(ranked)} rows)")
