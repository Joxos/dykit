from __future__ import annotations

from typing import Any

from dykit.cli.rich_output import out, style_message


def show_user_rank(
    results: list[dict[str, Any]], room: str, msg_type: str, days: int | None
) -> None:
    out(f"\n=== User Ranking (Top {len(results)}) ===")
    out(f"Room: {room}, Type: {msg_type}")
    if days:
        out(f"Time range: last {days} days")
    out(f"\n{'Rank':<6}{'Count':<8}{'Username'}")
    out(f"{'────':<6}{'─────':<8}{'────────────────────'}")
    for rank_num, item in enumerate(results, start=1):
        out(f"{rank_num:<6}{item['count']:<8}{item['username']}")


def show_content_rank(results: list[dict[str, Any]], room: str, days: int | None) -> None:
    out(f"\n=== Repeated Messages (Top {len(results)}) ===")
    out(f"Room: {room}")
    if days:
        out(f"Time range: last {days} days")
    out(f"\n{'Count':<8}{'Content':<50}{'First Seen':<20}{'Last Seen'}")
    out(f"{'─────':<8}{'───────':<50}{'──────────':<20}{'─────────'}")
    for item in results:
        content: Any = item["content"]
        content_str = str(content) if content is not None else ""
        content_preview = content_str[:47] + "..." if len(content_str) > 50 else content_str
        first_seen: Any = item["first_seen"]
        last_seen: Any = item["last_seen"]
        first = (
            first_seen.strftime("%Y-%m-%d %H:%M:%S")
            if hasattr(first_seen, "strftime")
            else str(first_seen)
        )
        last = (
            last_seen.strftime("%Y-%m-%d %H:%M:%S")
            if hasattr(last_seen, "strftime")
            else str(last_seen)
        )
        out(f"{item['count']:<8}{content_preview:<50}{first:<20}{last}")


def show_search_results(
    results: list[dict[str, Any]], room: str, search_str: str, sort_mode: str
) -> None:
    out(f"\n=== Search Results ({len(results)} found) ===")
    out(f"Room: {room}, Filter: {search_str}, Sort: {sort_mode}")
    out("")
    out(f"{'Timestamp':<20}{'Username':<16}{'Content'}")
    out(f"{'─' * 20:<20}{'─' * 16:<16}{'─' * 50}")
    for item in results:
        ts = (
            item["timestamp"].strftime("%Y-%m-%d %H:%M:%S")
            if hasattr(item["timestamp"], "strftime")
            else str(item["timestamp"])[:19]
        )
        username_str = item["username"] or "[unknown]"
        content_str = item["content"] or ""
        content_preview = content_str[:47] + "..." if len(content_str) > 50 else content_str
        msg_type = str(item.get("msg_type") or "chatmsg")
        styled_content = style_message(content_preview, msg_type)
        out(f"{ts:<20}{username_str:<16}{styled_content}")


def show_live_message(username: str | None, level: int, content: str, msg_type: str) -> None:
    username_str = username or "Unknown"
    styled_content = style_message(content, msg_type)
    out(f"[{username_str}] Lv{level}: {styled_content}")


def show_cluster_results(
    multi_clusters: list[list[tuple[str, int]]], threshold: float, total_unique: int
) -> None:
    out(f"\n=== Clusters (threshold={threshold:.2f}, {total_unique} unique msgs) ===")
    out(f"Found {len(multi_clusters)} clusters with 2+ variants\n")
    for idx, clust in enumerate(multi_clusters, start=1):
        total = sum(cnt for _, cnt in clust)
        variants = len(clust)
        out(f"─── Cluster {idx} ({variants} variants, {total} total) ───")
        max_cnt_width = len(str(clust[0][1]))
        for content, cnt in clust:
            display = content if len(content) <= 60 else content[:57] + "..."
            out(f"  [{cnt:>{max_cnt_width}}x] {display}")
        out("")
