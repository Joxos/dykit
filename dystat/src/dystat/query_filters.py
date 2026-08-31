from __future__ import annotations

from datetime import datetime, timedelta

from dycommon.time_rules import WINDOW_CONFLICT_FIRST_LAST
from dycommon.timestamps import format_timestamp

from .time_filters import parse_from_inclusive, parse_to_exclusive, validate_time_window


def parse_order_limit(last: int | None, first: int | None) -> tuple[str, int | None]:
    """Build ORDER BY/LIMIT SQL (sqlite qmark) for a last/first window."""
    if last is not None and first is not None:
        raise ValueError(WINDOW_CONFLICT_FIRST_LAST)

    if last is not None:
        return "ORDER BY timestamp DESC LIMIT ?", last

    if first is not None:
        return "ORDER BY timestamp ASC LIMIT ?", first

    return "", None


def build_common_filters(
    *,
    room: str,
    msg_type: str | None,
    username: str | None,
    user_id: str | None,
    from_date: str | None,
    to_date: str | None,
    days: int | None = None,
) -> tuple[list[str], list[object]]:
    """Build WHERE clauses and qmark params shared by rank/cluster/search."""
    parsed_from = parse_from_inclusive(from_date) if from_date is not None else None
    parsed_to = parse_to_exclusive(to_date) if to_date is not None else None

    if parsed_from is not None and parsed_to is not None:
        validate_time_window(parsed_from, parsed_to)

    where_clauses: list[str] = ["room_id = ?"]
    params: list[object] = [room]

    if msg_type is not None:
        where_clauses.append("msg_type = ?")
        params.append(msg_type)
    if username is not None:
        where_clauses.append("username = ?")
        params.append(username)
    if user_id is not None:
        where_clauses.append("user_id = ?")
        params.append(user_id)
    if parsed_from is not None:
        where_clauses.append("timestamp >= ?")
        params.append(format_timestamp(parsed_from))
    if parsed_to is not None:
        where_clauses.append("timestamp < ?")
        params.append(format_timestamp(parsed_to))
    if days is not None:
        where_clauses.append("timestamp >= ?")
        params.append(format_timestamp(datetime.now() - timedelta(days=days)))

    return where_clauses, params
