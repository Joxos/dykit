"""Turning CLI filter options into SQL.

Every stats query filters the same way - room, message type, user, a time
window, and a first/last window - so the translation from option values to
WHERE clauses lives here once.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from ..schema import format_timestamp

WINDOW_CONFLICT_FIRST_LAST = (
    "Cannot use --last and --first together. Use one window direction only."
)
TIME_CONFLICT_DAYS_RANGE = (
    "Cannot combine --days with --from/--to. Use either relative days or explicit date range."
)

_DATE_FORMAT = "%Y-%m-%d"
_DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def parse_order_limit(last: int | None, first: int | None) -> tuple[str, int | None]:
    """Build ORDER BY/LIMIT SQL (sqlite qmark) for a last/first window."""
    if last is not None and first is not None:
        raise ValueError(WINDOW_CONFLICT_FIRST_LAST)

    if last is not None:
        return "ORDER BY timestamp DESC LIMIT ?", last

    if first is not None:
        return "ORDER BY timestamp ASC LIMIT ?", first

    return "", None


def validate_days_range(days: int | None, from_date: str | None, to_date: str | None) -> None:
    """`--days` (relative) and `--from/--to` (absolute) are mutually exclusive."""
    if days is not None and (from_date is not None or to_date is not None):
        raise ValueError(TIME_CONFLICT_DAYS_RANGE)


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


def parse_from_inclusive(from_value: str) -> datetime:
    """Parse --from; the returned bound is inclusive."""
    parsed, _has_time = _parse_time_filter(from_value, "--from")
    return parsed


def parse_to_exclusive(to_value: str) -> datetime:
    """Parse --to into an exclusive bound.

    `--to` is inclusive for the user: a bare date covers the whole day, and a
    datetime covers that second.
    """
    parsed, has_time = _parse_time_filter(to_value, "--to")
    if has_time:
        return parsed + timedelta(seconds=1)
    return parsed + timedelta(days=1)


def validate_time_window(from_inclusive: datetime, to_exclusive: datetime) -> None:
    if from_inclusive >= to_exclusive:
        raise ValueError("Invalid time window: --from must be earlier than --to")


def _parse_time_filter(value: str, option_name: str) -> tuple[datetime, bool]:
    try:
        return datetime.strptime(value, _DATETIME_FORMAT), True
    except ValueError:
        pass

    try:
        return datetime.strptime(value, _DATE_FORMAT), False
    except ValueError as e:
        raise ValueError(
            f"Invalid {option_name} format: {value!r}. Use 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM:SS'."
        ) from e
