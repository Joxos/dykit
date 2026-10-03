"""Built-in analyses.

``rank`` and ``search`` are the existing commands expressed through the plugin
protocol, so there is one code path rather than a plugin API plus a parallel
implementation. ``latest_unique`` is the first corpus analysis - "what is new
in this room" - which is the substrate the rest build on.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass, fields
from typing import cast

from ..filters import build_common_filters, parse_order_limit, validate_days_range
from .base import Analysis, Param, Query


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
        values: dict[str, object] = {"room": overrides.pop("room", "")}
        known = {f.name for f in fields(RankOptions)}
        unknown = set(overrides) - known
        if unknown:
            raise ValueError(f"unknown option(s) for rank: {sorted(unknown)}")
        values.update(overrides)
        return RankOptions(**values)  # type: ignore[arg-type]

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
        return [(index + 1, row[0], row[1]) for index, row in enumerate(rows)]


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
        values: dict[str, object] = {"room": overrides.pop("room", "")}
        values.update(overrides)
        return SearchOptions(**values)  # type: ignore[arg-type]

    def build_query(self, options: object) -> Query:
        opts = cast(SearchOptions, options)
        limit_value = opts.last if opts.last is not None else opts.first
        if limit_value is None:
            limit_value = 100
        order_limit_sql, _ = parse_order_limit(opts.last, opts.first)
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
        return list(rows)


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
    answer does not require pulling the corpus into Python.
    """

    name: str = "latest_unique"
    summary: str = "Newest messages whose content has not appeared before."
    params: tuple[Param, ...] = (
        Param("limit", "int", 20, "How many unseen messages to return"),
        Param("msg_type", "str", "chatmsg", "Message type to consider"),
    )

    def make_options(self, **overrides: object) -> object:
        values: dict[str, object] = {"room": overrides.pop("room", "")}
        values.update(overrides)
        return LatestUniqueOptions(**values)  # type: ignore[arg-type]

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
    SearchAnalysis(),
    LatestUniqueAnalysis(),
)
