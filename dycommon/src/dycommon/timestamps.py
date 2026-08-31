"""Shared timestamp formatting for SQLite run files.

The danmaku timestamp is stored as fixed-width ISO-like text
(``%Y-%m-%d %H:%M:%S.%f``, always 6-digit microseconds) so that TEXT
comparisons are lexicographically equivalent to chronological order.
Writer (dycap) and readers (dystat) must use the same format.
"""

from __future__ import annotations

from datetime import datetime

TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S.%f"


def format_timestamp(dt: datetime) -> str:
    """Format a datetime as fixed-width storage text."""
    return dt.strftime(TIMESTAMP_FORMAT)


def parse_timestamp(value: str) -> datetime:
    """Parse storage text back to a datetime."""
    return datetime.strptime(value, TIMESTAMP_FORMAT)
