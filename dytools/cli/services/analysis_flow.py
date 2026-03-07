from __future__ import annotations

from collections.abc import Callable
from typing import Any


def run_rank(
    rank_module: Any,
    resolve_room_for_query: Callable[[str], str],
    dsn: str,
    room: str,
    top: int,
    msg_type: str,
    days: int | None,
    mode: str,
) -> list[dict[str, Any]]:
    resolved_room = resolve_room_for_query(room)
    return rank_module.rank(dsn, resolved_room, top, msg_type, days, mode=mode)


def run_prune(
    prune_module: Any, resolve_room_for_query: Callable[[str], str], dsn: str, room: str
) -> int:
    resolved_room = resolve_room_for_query(room)
    return prune_module.prune(dsn, resolved_room)


def run_cluster(
    cluster_module: Any,
    resolve_room_for_query: Callable[[str], str],
    dsn: str,
    room: str,
    threshold: float,
    limit: int,
) -> list[list[tuple[str, int]]]:
    resolved_room = resolve_room_for_query(room)
    return cluster_module.cluster(dsn, resolved_room, threshold, "chatmsg", limit)


def run_search(
    search_module: Any,
    resolve_room_for_query: Callable[[str], str],
    dsn: str,
    room: str,
    query: str | None,
    user: str | None,
    user_id: str | None,
    msg_type: str | None,
    from_date: str | None,
    to_date: str | None,
    last: int | None,
    first: int | None,
) -> list[dict[str, Any]]:
    resolved_room = resolve_room_for_query(room)
    return search_module.search(
        dsn,
        resolved_room,
        query=query,
        username=user,
        user_id=user_id,
        msg_type=msg_type,
        from_date=from_date,
        to_date=to_date,
        last=last,
        first=first,
    )


def summarize_search_filter(
    query: str | None,
    user: str | None,
    user_id: str | None,
    msg_type: str | None,
) -> str:
    search_desc: list[str] = []
    if query:
        search_desc.append(f'query="{query}"')
    if user:
        search_desc.append(f'user="{user}"')
    if user_id:
        search_desc.append(f'user_id="{user_id}"')
    if msg_type:
        search_desc.append(f'type="{msg_type}"')
    return ", ".join(search_desc) if search_desc else "all"


def summarize_search_sort(last: int | None, first: int | None) -> str:
    if last:
        return f"Last {last}"
    if first:
        return f"First {first}"
    return "Last 100 (default)"
