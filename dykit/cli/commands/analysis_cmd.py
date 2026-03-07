from __future__ import annotations

import sys
from typing import Literal

import click
import psycopg

from dykit.cli.common import get_dsn, resolve_room_for_query
from dykit.cli.formatters import (
    show_cluster_results,
    show_content_rank,
    show_search_results,
    show_user_rank,
)
from dykit.cli.options import (
    msg_type_option,
    output_option,
    room_option,
    search_first_option,
    search_from_option,
    search_last_option,
    search_to_option,
    user_id_option,
    username_option,
    validate_last_first,
)
from dykit.cli.rich_output import err, out
from dykit.cli.services.analysis_flow import (
    run_cluster,
    run_prune,
    run_rank,
    run_search,
    summarize_search_filter,
    summarize_search_sort,
)
from dykit.cli.services.dbio import export_clusters_to_csv, export_search_results_to_csv
from dykit.tools import cluster, prune, rank, search
from dykit.tools import rank as rank_tool


def _validate_rank_and_cluster_filter_window(
    days: int | None,
    from_date: str | None,
    to_date: str | None,
) -> None:
    if days is not None and (from_date is not None or to_date is not None):
        err(
            "Error: Cannot combine --days with --from/--to. Use either relative days or explicit date range."
        )
        sys.exit(1)


def register(cli: click.Group) -> None:
    @cli.command(name="rank", short_help="Show ranking statistics")
    @room_option()
    @click.option("--top", default=10, help="Show top N results")
    @msg_type_option(default="chatmsg")
    @click.option("--days", type=int, help="Filter to messages from the last N days")
    @click.option(
        "--by",
        "mode",
        type=click.Choice(["user", "content"]),
        default="user",
        show_default=True,
        help="Choose ranking dimension",
    )
    @username_option(short=True)
    @user_id_option()
    @search_from_option()
    @search_to_option()
    @search_last_option()
    @search_first_option()
    @output_option(help_text="Write rank results to CSV")
    @click.pass_context
    def _rank_cmd(
        ctx: click.Context,
        room: str,
        top: int,
        msg_type: str,
        days: int | None,
        mode: str,
        username: str | None,
        user_id: str | None,
        from_date: str | None,
        to_date: str | None,
        last: int | None,
        first: int | None,
        output: str | None,
    ) -> None:
        dsn = get_dsn(ctx)
        mode_value: Literal["user", "content"] = "content" if mode == "content" else "user"
        validate_last_first(last, first)
        _validate_rank_and_cluster_filter_window(days, from_date, to_date)
        try:
            results = run_rank(
                rank,
                resolve_room_for_query,
                dsn,
                room,
                top,
                msg_type,
                days,
                mode_value,
                username,
                user_id,
                from_date,
                to_date,
                last,
                first,
            )
            if not results:
                out(f"No {msg_type} messages found for room {room}")
                return
            if mode_value == "user":
                show_user_rank(results, room, msg_type, days)
            else:
                show_content_rank(results, room, days)
            if output:
                rank_tool.export_rank(results, mode=mode_value, output=output)
                out(f"\nResults exported to {output}")
        except psycopg.Error as e:
            err(f"Error: Database query failed: {e}")
            sys.exit(1)
        except ValueError as e:
            err(f"Error: {e}")
            sys.exit(1)

    @cli.command(name="prune", short_help="Remove duplicate records")
    @room_option()
    @click.pass_context
    def _prune_cmd(ctx: click.Context, room: str) -> None:
        dsn = get_dsn(ctx)
        try:
            removed_count = run_prune(prune, resolve_room_for_query, dsn, room)
            out(f"Removed {removed_count} duplicate records from room {room}")
        except psycopg.Error as e:
            err(f"Error: Database operation failed: {e}")
            sys.exit(1)

    @cli.command(name="cluster", short_help="Cluster similar chat messages")
    @room_option()
    @click.option("--threshold", default=0.6, type=float, help="Set similarity threshold")
    @click.option("--limit", default=1000, type=int, help="Limit source messages before clustering")
    @msg_type_option(default="chatmsg")
    @username_option(short=True)
    @user_id_option()
    @search_from_option()
    @search_to_option()
    @search_last_option()
    @search_first_option()
    @click.option("--days", type=int, help="Filter to messages from the last N days")
    @output_option()
    @click.pass_context
    def _cluster_cmd(
        ctx: click.Context,
        room: str,
        threshold: float,
        limit: int,
        msg_type: str,
        username: str | None,
        user_id: str | None,
        from_date: str | None,
        to_date: str | None,
        last: int | None,
        first: int | None,
        days: int | None,
        output: str | None,
    ) -> None:
        dsn = get_dsn(ctx)
        validate_last_first(last, first)
        _validate_rank_and_cluster_filter_window(days, from_date, to_date)
        try:
            all_clusters = run_cluster(
                cluster,
                resolve_room_for_query,
                dsn,
                room,
                threshold,
                limit,
                msg_type,
                username,
                user_id,
                from_date,
                to_date,
                last,
                first,
                days,
            )
            if not all_clusters:
                out(f"No messages found in room {room}")
                return

            total_unique = sum(len(c) for c in all_clusters)
            multi_clusters = [c for c in all_clusters if len(c) >= 2]
            multi_clusters.sort(key=lambda c: sum(cnt for _, cnt in c), reverse=True)

            if not multi_clusters:
                out(f"No clusters found with threshold {threshold}")
                return

            show_cluster_results(multi_clusters, threshold, total_unique)
            if output:
                export_clusters_to_csv(multi_clusters, output)
                out(f"Cluster data saved to {output}")
        except psycopg.Error as e:
            err(f"Error: Database query failed: {e}")
            sys.exit(1)
        except ValueError as e:
            err(f"Error: {e}")
            sys.exit(1)

    @cli.command(name="search", short_help="Search messages with filters")
    @room_option()
    @click.option("-q", "--query", help="Keyword to search (case-insensitive)")
    @click.option("-u", "--user", "username", help="Filter by username")
    @user_id_option()
    @msg_type_option()
    @search_from_option()
    @search_to_option()
    @search_last_option()
    @search_first_option()
    @output_option(help_text="Export to CSV file (optional)")
    @click.pass_context
    def _search_cmd(
        ctx: click.Context,
        room: str,
        query: str | None,
        username: str | None,
        user_id: str | None,
        msg_type: str | None,
        from_date: str | None,
        to_date: str | None,
        last: int | None,
        first: int | None,
        output: str | None,
    ) -> None:
        dsn = get_dsn(ctx)
        validate_last_first(last, first)

        try:
            results = run_search(
                search,
                resolve_room_for_query,
                dsn,
                room,
                query,
                username,
                user_id,
                msg_type,
                from_date,
                to_date,
                last,
                first,
            )
            if not results:
                out(f"No messages found for room {room}")
                return

            search_str = summarize_search_filter(query, username, user_id, msg_type)
            sort_mode = summarize_search_sort(last, first)

            show_search_results(results, room, search_str, sort_mode)

            if output:
                export_search_results_to_csv(results, output)
                out(f"\nResults exported to {output}")
        except psycopg.Error as e:
            err(f"Error: Database query failed: {e}")
            sys.exit(1)

    _registered = (_rank_cmd, _prune_cmd, _cluster_cmd, _search_cmd)
