"""Built-in analyses.

``rank``, ``cluster`` and ``search`` are the existing commands expressed
through the plugin protocol, so there is one code path rather than a plugin
API plus a parallel implementation. Each returns the same domain type the CLI
already renders, so demoting them to plugins changed no behaviour.

``latest_unique`` is the first corpus analysis - "what is new in this room" -
and the substrate the rest build on.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass, fields
from typing import Any, cast

from ...schema import parse_timestamp
from ..cluster import group_similar
from ..filters import build_common_filters, parse_order_limit, validate_days_range
from ..rank import RankResult
from ..search import SearchResult
from .base import Analysis, Param, Query


def _options(cls: type[Any], known: dict[str, object], overrides: dict[str, object]) -> Any:
    """Build a typed options dataclass, rejecting unknown names."""
    allowed = {field.name for field in fields(cls)}
    unknown = set(overrides) - allowed
    if unknown:
        raise ValueError(f"unknown option(s): {sorted(unknown)}")
    known.update(overrides)
    return cls(**known)


@dataclass(frozen=True)
class RankOptions:
    room: str
    top: int = 10
    mode: str = "user"
    msg_type: str | None = "chatmsg"
    days: int | None = None
    username: str | None = None
    user_id: str | None = None
    from_date: str | None = None
    to_date: str | None = None
    last: int | None = None
    first: int | None = None


@dataclass(frozen=True)
class RankAnalysis:
    name: str = "rank"
    summary: str = "Rank users or content by frequency."
    params: tuple[Param, ...] = (
        Param("top", "int", 10, "Number of results"),
        Param("mode", "str", "user", "Rank by user or content"),
        Param("msg_type", "str", "chatmsg", "Message type to filter"),
        Param("days", "int", None, "Limit to recent N days"),
        Param("username", "str", None, "Filter by username"),
        Param("user_id", "str", None, "Filter by user_id"),
        Param("from_date", "str", None, "Start time (YYYY-MM-DD or YYYY-MM-DD HH:MM:SS)"),
        Param("to_date", "str", None, "End time (inclusive)"),
        Param("last", "int", None, "Use the last N (most recent) messages"),
        Param("first", "int", None, "Use the first N (earliest) messages"),
    )

    def make_options(self, **overrides: object) -> object:
        room = overrides.pop("room", "")
        return _options(RankOptions, {"room": room}, overrides)

    def build_query(self, options: object) -> Query:
        opts = cast(RankOptions, options)
        validate_days_range(opts.days, opts.from_date, opts.to_date)
        order_limit_sql, limit_value = parse_order_limit(opts.last, opts.first)
        where_clauses, params = build_common_filters(
            room=opts.room,
            msg_type=opts.msg_type,
            username=opts.username,
            user_id=opts.user_id,
            from_date=opts.from_date,
            to_date=opts.to_date,
            days=opts.days,
        )
        group_field = "username" if opts.mode == "user" else "content"
        content_guard = (
            "WHERE content IS NOT NULL AND content != ''" if opts.mode == "content" else ""
        )
        sql = f"""
            WITH filtered AS (
                SELECT * FROM danmaku_all
                WHERE {" AND ".join(where_clauses)}
                {order_limit_sql}
            )
            SELECT {group_field}, COUNT(*) AS cnt
            FROM filtered
            {content_guard}
            GROUP BY {group_field}
            ORDER BY cnt DESC, {group_field}
            LIMIT ?
            """
        values = list(params)
        if limit_value is not None:
            values.append(limit_value)
        values.append(opts.top)
        return Query(sql=sql, params=tuple(values), columns=("value", "cnt"))

    def rows_to_result(self, rows: Iterator[sqlite3.Row], options: object) -> object:
        _ = options
        return [
            RankResult(rank=index + 1, value=row[0], count=row[1]) for index, row in enumerate(rows)
        ]


@dataclass(frozen=True)
class ClusterOptions:
    room: str
    threshold: float = 0.5
    msg_type: str | None = "chatmsg"
    limit: int = 50
    username: str | None = None
    user_id: str | None = None
    from_date: str | None = None
    to_date: str | None = None
    last: int | None = None
    first: int | None = None
    days: int | None = None


@dataclass(frozen=True)
class ClusterAnalysis:
    """Group similar messages.

    The candidate set is chosen and capped in SQL; only the grouping itself
    is Python, because fuzzy similarity has no SQL equivalent. That is exactly
    the case ``rows_to_result`` exists for - one pass, no re-query.
    """

    name: str = "cluster"
    summary: str = "Group similar messages by text similarity."
    params: tuple[Param, ...] = (
        Param("threshold", "float", 0.5, "Similarity threshold (0-1)"),
        Param("limit", "int", 50, "Candidate messages to consider"),
        Param("msg_type", "str", "chatmsg", "Message type to filter"),
        Param("username", "str", None, "Filter by username"),
        Param("user_id", "str", None, "Filter by user_id"),
        Param("from_date", "str", None, "Start time"),
        Param("to_date", "str", None, "End time (inclusive)"),
        Param("last", "int", None, "Use the last N (most recent) messages"),
        Param("first", "int", None, "Use the first N (earliest) messages"),
        Param("days", "int", None, "Limit to recent N days"),
    )

    def make_options(self, **overrides: object) -> object:
        room = overrides.pop("room", "")
        return _options(ClusterOptions, {"room": room}, overrides)

    def build_query(self, options: object) -> Query:
        opts = cast(ClusterOptions, options)
        validate_days_range(opts.days, opts.from_date, opts.to_date)
        order_limit_sql, limit_value = parse_order_limit(opts.last, opts.first)
        where_clauses, params = build_common_filters(
            room=opts.room,
            msg_type=opts.msg_type,
            username=opts.username,
            user_id=opts.user_id,
            from_date=opts.from_date,
            to_date=opts.to_date,
            days=opts.days,
        )
        where_clauses.extend(["content IS NOT NULL", "content != ''"])
        sql = f"""
            WITH filtered AS (
                SELECT * FROM danmaku_all
                WHERE {" AND ".join(where_clauses)}
                {order_limit_sql}
            )
            SELECT content, COUNT(*) AS cnt
            FROM filtered
            GROUP BY content
            ORDER BY cnt DESC, content
            LIMIT ?
            """
        values = list(params)
        if limit_value is not None:
            values.append(limit_value)
        values.append(opts.limit)
        return Query(sql=sql, params=tuple(values), columns=("content", "cnt"))

    def rows_to_result(self, rows: Iterator[sqlite3.Row], options: object) -> object:
        opts = cast(ClusterOptions, options)
        return group_similar([(row[0], row[1]) for row in rows], opts.threshold)


@dataclass(frozen=True)
class SearchOptions:
    room: str
    content: str | None = None
    username: str | None = None
    user_id: str | None = None
    msg_type: str | None = None
    from_date: str | None = None
    to_date: str | None = None
    last: int | None = None
    first: int | None = None


@dataclass(frozen=True)
class SearchAnalysis:
    name: str = "search"
    summary: str = "Search messages with filters."
    params: tuple[Param, ...] = (
        Param("content", "str", None, "Search content (LIKE)"),
        Param("username", "str", None, "Filter by username"),
        Param("user_id", "str", None, "Filter by user_id"),
        Param("msg_type", "str", None, "Filter by message type"),
        Param("from_date", "str", None, "Start time"),
        Param("to_date", "str", None, "End time (inclusive)"),
        Param("last", "int", None, "Use the last N (most recent) messages"),
        Param("first", "int", None, "Use the first N (earliest) messages"),
    )

    def make_options(self, **overrides: object) -> object:
        room = overrides.pop("room", "")
        return _options(SearchOptions, {"room": room}, overrides)

    def build_query(self, options: object) -> Query:
        opts = cast(SearchOptions, options)
        # The default window has to become a real ORDER BY/LIMIT clause, not
        # just a parameter: otherwise the placeholder count and the parameter
        # count disagree and SQLite rejects the query.
        last, first = opts.last, opts.first
        if last is None and first is None:
            last = 100
        order_limit_sql, limit_value = parse_order_limit(last, first)
        where_clauses, params = build_common_filters(
            room=opts.room,
            msg_type=opts.msg_type,
            username=opts.username,
            user_id=opts.user_id,
            from_date=opts.from_date,
            to_date=opts.to_date,
        )
        if opts.content is not None:
            where_clauses.append("content LIKE ?")
            params.append(f"%{opts.content}%")
        sql = f"""
            SELECT timestamp, username, content, msg_type
            FROM danmaku_all
            WHERE {" AND ".join(where_clauses)}
            {order_limit_sql}
            """
        return Query(
            sql=sql,
            params=(*params, limit_value),
            columns=("timestamp", "username", "content", "msg_type"),
        )

    def rows_to_result(self, rows: Iterator[sqlite3.Row], options: object) -> object:
        _ = options
        return [
            SearchResult(
                timestamp=parse_timestamp(row[0]),
                username=row[1],
                content=row[2],
                msg_type=row[3],
            )
            for row in rows
        ]


@dataclass(frozen=True)
class LatestUniqueOptions:
    room: str
    limit: int = 20
    msg_type: str | None = "chatmsg"
    #: Sub-select producing the content already known. Supplied by the caller
    #: to ask "new since run X"; defaults to nothing being known.
    seen_sql: str = "SELECT content FROM danmaku_all WHERE 0"


@dataclass(frozen=True)
class LatestUniqueAnalysis:
    """Newest messages whose content has not been seen in the reference set.

    Uniqueness is decided in SQL (NOT IN against the reference set), so the
    answer never requires pulling the corpus into Python.
    """

    name: str = "latest_unique"
    summary: str = "Newest messages whose content has not appeared before."
    params: tuple[Param, ...] = (
        Param("limit", "int", 20, "How many unseen messages to return"),
        Param("msg_type", "str", "chatmsg", "Message type to consider"),
    )

    def make_options(self, **overrides: object) -> object:
        room = overrides.pop("room", "")
        return _options(LatestUniqueOptions, {"room": room}, overrides)

    def build_query(self, options: object) -> Query:
        opts = cast(LatestUniqueOptions, options)
        msg_type_filter = "fresh.msg_type = ?" if opts.msg_type is not None else "1 = 1"
        sql = f"""
            SELECT timestamp, username, content
            FROM danmaku_all AS fresh
            WHERE {msg_type_filter}
              AND fresh.content IS NOT NULL
              AND fresh.content != ''
              AND fresh.content NOT IN ({opts.seen_sql})
            ORDER BY fresh.id DESC
            LIMIT ?
            """
        params: tuple[object, ...] = ()
        if opts.msg_type is not None:
            params = (opts.msg_type,)
        return Query(
            sql=sql,
            params=(*params, opts.limit),
            columns=("timestamp", "username", "content"),
        )

    def rows_to_result(self, rows: Iterator[sqlite3.Row], options: object) -> object:
        _ = options
        return list(rows)


BUILTINS: tuple[Analysis, ...] = (
    RankAnalysis(),
    ClusterAnalysis(),
    SearchAnalysis(),
    LatestUniqueAnalysis(),
)
