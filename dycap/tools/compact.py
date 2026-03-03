"""Compact tool for CSV slimming by deduplicating chatmsg and filtering non-chatmsg rows.

This module provides functionality to:
1. Deduplicate chatmsg rows and track occurrence counts
2. Optionally keep/filter uenter, dgb, and other message types
3. Simplify extra fields for non-chatmsg types (unless --keep-extra)
4. Output a compacted CSV with 9 columns (original 8 + count column)

Output format: timestamp, username, content, user_level, user_id, room_id, msg_type, extra, count
"""

import csv
import json
from pathlib import Path

from dycap.log import logger


def run_compact(args):
    """Entry point for compact command.

    Args:
        args: Namespace from argparse with:
            - file: Path to input CSV file
            - output: Optional output path (default: {input}_compact.csv)
            - keep_uenter: Keep uenter rows (default: False)
            - keep_dgb: Keep dgb rows (default: False)
            - keep_extra: Keep full extra field (default: False, simplify for dgb)
    """
    input_path = Path(args.file)

    if not input_path.exists():
        logger.error(f"Input file not found: {input_path}")
        return

    # Determine output path
    if args.output:
        output_path = Path(args.output)
    else:
        output_path = input_path.parent / f"{input_path.stem}_compact.csv"

    # Read and process CSV
    original_stats = {"chatmsg": 0, "uenter": 0, "dgb": 0, "other": 0}
    compact_stats = {"chatmsg": 0, "uenter": 0, "dgb": 0, "other": 0}

    # Deduplication storage: {key: {"count": N, "row": [...]}}
    chatmsg_dedup = {}
    other_rows = []  # For non-chatmsg rows

    header = None

    # Read input CSV
    with open(input_path, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader, None)

        if header is None:
            logger.error(f"Empty CSV file: {input_path}")
            return

        for row in reader:
            if len(row) < 8:
                continue  # Skip invalid rows (need at least 8 columns)

            timestamp, username, content, user_level, user_id, room_id, msg_type, extra = row[:8]

            # Count original message types
            if msg_type == "chatmsg":
                original_stats["chatmsg"] += 1
            elif msg_type == "uenter":
                original_stats["uenter"] += 1
            elif msg_type == "dgb":
                original_stats["dgb"] += 1
            else:
                original_stats["other"] += 1

            # Process chatmsg: deduplicate and count
            # Process chatmsg: deduplicate by content only, count occurrences
            if msg_type == "chatmsg":
                # Dedup key: content only — identical messages from any user merge together
                # This produces count=2694 for '主播同款顶级耳机！' etc.
                key = content

                if key in chatmsg_dedup:
                    chatmsg_dedup[key]["count"] += 1
                else:
                    chatmsg_dedup[key] = {
                        "count": 1,
                        "row": [
                            timestamp,
                            username,
                            content,
                            user_level,
                            user_id,
                            room_id,
                            msg_type,
                            extra,
                        ],
                    }

            # Process uenter: optionally keep
            elif msg_type == "uenter":
                if args.keep_uenter:
                    # Simplify extra unless --keep-extra
                    if not args.keep_extra:
                        extra = ""  # Strip extra field
                    other_rows.append(
                        [
                            timestamp,
                            username,
                            content,
                            user_level,
                            user_id,
                            room_id,
                            msg_type,
                            extra,
                        ]
                    )

            # Process dgb: optionally keep
            elif msg_type == "dgb":
                if args.keep_dgb:
                    # Simplify extra to only gfn/gfcnt unless --keep-extra
                    if not args.keep_extra and extra:
                        try:
                            extra_dict = json.loads(extra)
                            simplified = {}
                            if "gfn" in extra_dict:
                                simplified["gfn"] = extra_dict["gfn"]
                            if "gfcnt" in extra_dict:
                                simplified["gfcnt"] = extra_dict["gfcnt"]
                            extra = json.dumps(simplified, ensure_ascii=False)
                        except (json.JSONDecodeError, TypeError):
                            extra = ""  # If JSON parsing fails, clear it
                    other_rows.append(
                        [
                            timestamp,
                            username,
                            content,
                            user_level,
                            user_id,
                            room_id,
                            msg_type,
                            extra,
                        ]
                    )

            # Process other types: follow uenter/dgb logic (discard by default)
            else:
                # Other types follow same rules as uenter
                if args.keep_uenter:  # Piggyback on uenter flag
                    if not args.keep_extra:
                        extra = ""
                    other_rows.append(
                        [
                            timestamp,
                            username,
                            content,
                            user_level,
                            user_id,
                            room_id,
                            msg_type,
                            extra,
                        ]
                    )

    # Prepare output rows
    output_rows = []

    # Add chatmsg rows with count
    for dedup_data in chatmsg_dedup.values():
        row = dedup_data["row"] + [str(dedup_data["count"])]
        output_rows.append(row)
        compact_stats["chatmsg"] += 1

    # Add other rows with empty count
    for row in other_rows:
        msg_type = row[6]
        if msg_type == "uenter":
            compact_stats["uenter"] += 1
        elif msg_type == "dgb":
            compact_stats["dgb"] += 1
        else:
            compact_stats["other"] += 1

        output_rows.append(row + [""])  # Empty count for non-chatmsg

    # Sort by timestamp (column 0)
    output_rows.sort(key=lambda r: r[0])

    # Write output CSV
    output_header = header + ["count"]  # Add count column
    with open(output_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(output_header)
        writer.writerows(output_rows)

    # Calculate file sizes
    input_size_kb = input_path.stat().st_size / 1024
    output_size_kb = output_path.stat().st_size / 1024

    # Calculate totals
    original_total = sum(original_stats.values())
    compact_total = sum(compact_stats.values())

    # Calculate savings
    rows_saved_pct = 0.0 if original_total == 0 else (1 - compact_total / original_total) * 100
    size_saved_pct = 0.0 if input_size_kb == 0 else (1 - output_size_kb / input_size_kb) * 100

    # Print summary
    print("=== Compact Summary ===")
    print(f"Input:  {input_path.name}")
    print(f"Output: {output_path.name}")
    print()
    print(f"Original: {original_total} rows, {input_size_kb:.0f} KB")
    print(f"Compact:  {compact_total} rows, {output_size_kb:.0f} KB")
    print(f"Savings:  {rows_saved_pct:.1f}% rows removed, {size_saved_pct:.1f}% size reduced")
    print()
    print("Breakdown:")
    print(
        f"  chatmsg: {original_stats['chatmsg']} → {compact_stats['chatmsg']} (deduped, count in 'count' column)"
    )

    if compact_stats["uenter"] == 0:
        print(f"  uenter:  {original_stats['uenter']} → 0 (stripped, use --keep-uenter to retain)")
    else:
        print(
            f"  uenter:  {original_stats['uenter']} → {compact_stats['uenter']} (kept with --keep-uenter)"
        )

    if compact_stats["dgb"] == 0:
        print(f"  dgb:     {original_stats['dgb']} → 0 (stripped, use --keep-dgb to retain)")
    else:
        print(f"  dgb:     {original_stats['dgb']} → {compact_stats['dgb']} (kept with --keep-dgb)")

    if original_stats["other"] > 0:
        if compact_stats["other"] == 0:
            print(f"  other:   {original_stats['other']} → 0 (stripped)")
        else:
            print(f"  other:   {original_stats['other']} → {compact_stats['other']} (kept)")
