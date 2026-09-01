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
from pathlib import Path

from dycommon.timestamps import parse_timestamp

DEFAULT_DATA_DIR = "dycap-data"
DEFAULT_MIN_AGE_MINUTES = 60


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

        try:
            conn = sqlite3.connect(str(db_file))
            rows = dict(conn.execute("SELECT key, value FROM meta").fetchall())
            conn.close()
        except sqlite3.Error:
            continue  # not a run file; skip silently

        if "ended_at" in rows:
            continue

        started: datetime | None = None
        if "started_at" in rows:
            try:
                started = parse_timestamp(rows["started_at"])
            except ValueError:
                started = None
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
    parser.add_argument("--data", default=DEFAULT_DATA_DIR, help=f"run files directory (default: {DEFAULT_DATA_DIR})")
    parser.add_argument(
        "--min-age-minutes",
        type=int,
        default=DEFAULT_MIN_AGE_MINUTES,
        help="ignore runs started within this many minutes (default: 60)",
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

    usage = shutil.disk_usage(data_dir)
    percent = usage.used / usage.total * 100
    print(f"disk: {percent:.1f}% used, {usage.free / (1024**3):.1f} GiB free")

    return 1 if interrupted else 0


if __name__ == "__main__":
    sys.exit(main())
