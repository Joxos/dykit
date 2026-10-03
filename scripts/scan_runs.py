"""Scan dycap run files for interrupted runs.

A run file is "interrupted" when its meta table lacks ``ended_at`` and the
run started long enough ago that it cannot be an active collection anymore
(killed process, power loss). Actively running files are never flagged.

Also reports the data directory's disk usage (for retention planning).

Usage:
    uv run python scripts/scan_runs.py [--data DIR] [--min-age-minutes N]

Exit codes:
    0 - no interrupted runs
    1 - interrupted runs found
    2 - data dir missing
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from datetime import datetime, timedelta
from itertools import pairwise
from pathlib import Path

from dykit.schema import parse_timestamp

DEFAULT_DATA_DIR = "dycap-data"
DEFAULT_MIN_AGE_MINUTES = 60
#: Rotation hands over in milliseconds; anything above a minute of silence
#: between consecutive runs is a real coverage gap worth reporting.
DEFAULT_MAX_GAP_SECONDS = 60.0


def read_meta(db_file: Path) -> dict[str, str] | None:
    """Run metadata, or None when the file is not a readable run file."""
    try:
        conn = sqlite3.connect(f"file:{db_file.as_posix()}?mode=ro", uri=True)
    except sqlite3.Error:
        return None
    try:
        return dict(conn.execute("SELECT key, value FROM meta").fetchall())
    except sqlite3.Error:
        return None
    finally:
        conn.close()


def _parse(rows: dict[str, str], key: str) -> datetime | None:
    value = rows.get(key)
    if not value:
        return None
    try:
        return parse_timestamp(value)
    except ValueError:
        return None


def find_gaps(data_dir: Path, max_gap: timedelta) -> list[dict[str, str]]:
    """Find collection gaps between consecutive runs of the same room.

    Every run file records when it started and ended. Rotation closes one file
    and opens the next, so a handover shows up as `next.started_at` later than
    `previous.ended_at`. With a single writer and an atomic sink swap that gap
    should be milliseconds; anything larger is a real interruption in coverage
    (a deploy, a crash) and is worth an audit trail rather than a silent
    assumption.
    """
    gaps: list[dict[str, str]] = []
    by_room: dict[str, list[tuple[datetime, datetime | None, Path]]] = {}

    for db_file in sorted(data_dir.glob("*.db")):
        rows = read_meta(db_file)
        if rows is None:
            continue
        started = _parse(rows, "started_at")
        if started is None:
            continue
        room = rows.get("room", "?")
        by_room.setdefault(room, []).append((started, _parse(rows, "ended_at"), db_file))

    for room, runs in by_room.items():
        runs.sort(key=lambda item: item[0])
        for (_, ended, previous), (next_started, _, next_file) in pairwise(runs):
            if ended is None:
                continue  # still running: no boundary to measure
            gap = next_started - ended
            if gap > max_gap:
                gaps.append(
                    {
                        "room": room,
                        "previous": previous.name,
                        "next": next_file.name,
                        "seconds": f"{gap.total_seconds():.1f}",
                    }
                )
    return gaps


def scan(data_dir: Path, min_age: timedelta) -> list[dict[str, str]]:
    """Return run files whose meta lacks ended_at and that stopped being written.

    Active runs are detected by file mtime (they are written every few
    seconds), not by start time - a run may legitimately last many hours.
    """
    interrupted: list[dict[str, str]] = []
    cutoff = datetime.now() - min_age

    for db_file in sorted(data_dir.glob("*.db")):
        # A freshly written file is an active run, however old it is.
        try:
            mtime = datetime.fromtimestamp(db_file.stat().st_mtime)
        except OSError:
            continue
        if mtime > cutoff:
            continue

        rows = read_meta(db_file)
        if rows is None:
            continue  # not a run file; skip silently

        if "ended_at" in rows:
            continue

        started = _parse(rows, "started_at")
        if started is None:
            continue  # no start info; cannot judge

        interrupted.append(
            {
                "file": db_file.name,
                "room": rows.get("room", "?"),
                "started_at": rows.get("started_at", "?"),
                "messages": rows.get("messages", "?"),
            }
        )

    return interrupted


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data",
        default=DEFAULT_DATA_DIR,
        help=f"run files directory (default: {DEFAULT_DATA_DIR})",
    )
    parser.add_argument(
        "--min-age-minutes",
        type=int,
        default=DEFAULT_MIN_AGE_MINUTES,
        help="ignore runs started within this many minutes (default: 60)",
    )
    parser.add_argument(
        "--max-gap-seconds",
        type=float,
        default=DEFAULT_MAX_GAP_SECONDS,
        help=(
            "report a GAP when consecutive runs of a room are further apart than "
            f"this (default: {DEFAULT_MAX_GAP_SECONDS:.0f})"
        ),
    )
    args = parser.parse_args()

    data_dir = Path(args.data)
    if not data_dir.is_dir():
        print(f"data dir not found: {data_dir}", file=sys.stderr)
        return 2

    interrupted = scan(data_dir, timedelta(minutes=args.min_age_minutes))

    for run in interrupted:
        print(
            f"INTERRUPTED {run['file']}: room={run['room']} "
            f"started={run['started_at']} messages={run['messages']}"
        )
    print(f"scan: {len(interrupted)} interrupted run(s) in {data_dir}")

    gaps = find_gaps(data_dir, timedelta(seconds=args.max_gap_seconds))
    for gap in gaps:
        print(f"GAP {gap['room']}: {gap['seconds']}s between {gap['previous']} and {gap['next']}")
    if gaps:
        print(f"scan: {len(gaps)} coverage gap(s) above {args.max_gap_seconds:.0f}s")

    usage = shutil.disk_usage(data_dir)
    percent = usage.used / usage.total * 100
    print(f"disk: {percent:.1f}% used, {usage.free / (1024**3):.1f} GiB free")

    return 1 if interrupted else 0


if __name__ == "__main__":
    sys.exit(main())
