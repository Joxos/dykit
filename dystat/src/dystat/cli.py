"""dystat CLI - Douyu Statistics Tools."""

from __future__ import annotations

import sys
from importlib.metadata import version

import click
from dycommon.env import get_dsn
from rich.console import Console
from rich.table import Table

from .cluster import run_cluster
from .prune import run_prune
from .rank import run_rank
from .search import run_search

console = Console()


@click.command()
@click.option("-r", "--room", required=True, help="Room ID")
@click.option("--dsn", help="PostgreSQL DSN (or use DYKIT_DSN env)")
@click.option("--top", default=10, help="Number of results")
@click.option(
    "--by",
    "mode",
    type=click.Choice(["user", "content"]),
    default="user",
    help="Rank by user or content",
)
@click.option("--type", "msg_type", default="chatmsg", help="Message type")
@click.option("--days", type=int, help="Limit to recent N days")
@click.option("--username", help="Filter by username")
@click.option("--user-id", help="Filter by user_id")
@click.option("--from", "from_date", help="Start time (YYYY-MM-DD or YYYY-MM-DD HH:MM:SS)")
@click.option("--to", "to_date", help="End time (YYYY-MM-DD or YYYY-MM-DD HH:MM:SS, inclusive)")
@click.option("--last", type=int, help="Use the last N (most recent) messages")
@click.option("--first", type=int, help="Use the first N (earliest) messages")
def rank(
    room: str,
    dsn: str | None,
    top: int,
    mode: str,
    msg_type: str,
    days: int | None,
    username: str | None,
    user_id: str | None,
    from_date: str | None,
    to_date: str | None,
    last: int | None,
    first: int | None,
) -> None:
    """Rank users or content by frequency.

    Examples:
        dystat rank -r 6657 --top 10
        dystat rank -r 6657 --by content --top 5
        dystat rank -r 6657 --type dgb --top 5
    """
    dsn = dsn or get_dsn()
    if not dsn:
        console.print("[red]Error: DSN required. Set DYKIT_DSN or use --dsn[/red]")
        sys.exit(1)

    try:
        results = run_rank(
            room,
            top,
            mode,
            msg_type,
            days,
            username,
            user_id,
            from_date,
            to_date,
            last,
            first,
            dsn,
        )
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)

    # Display table
    table = Table(title=f"Top {mode}s in room {room}")
    table.add_column("Rank", justify="right")
    table.add_column(mode.title(), style="cyan")
    table.add_column("Count", justify="right", style="green")

    for r in results:
        table.add_row(str(r.rank), r.value, str(r.count))

    console.print(table)


@click.command()
@click.option("-r", "--room", required=True, help="Room ID")
@click.option("--dsn", help="PostgreSQL DSN (or use DYKIT_DSN env)")
@click.option("--threshold", default=0.5, help="Similarity threshold (0-1)")
@click.option("--limit", default=50, help="Source message limit")
@click.option("--type", "msg_type", default="chatmsg", help="Message type")
@click.option("--username", help="Filter by username")
@click.option("--user-id", help="Filter by user_id")
@click.option("--from", "from_date", help="Start time (YYYY-MM-DD or YYYY-MM-DD HH:MM:SS)")
@click.option("--to", "to_date", help="End time (YYYY-MM-DD or YYYY-MM-DD HH:MM:SS, inclusive)")
@click.option("--last", type=int, help="Use the last N (most recent) messages")
@click.option("--first", type=int, help="Use the first N (earliest) messages")
@click.option("--days", type=int, help="Limit to recent N days")
def cluster(
    room: str,
    dsn: str | None,
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
) -> None:
    """Cluster similar messages.

    Examples:
        dystat cluster -r 6657 --threshold 0.5
    """
    dsn = dsn or get_dsn()
    if not dsn:
        console.print("[red]Error: DSN required. Set DYKIT_DSN or use --dsn[/red]")
        sys.exit(1)

    try:
        results = run_cluster(
            room,
            threshold,
            msg_type,
            limit,
            username,
            user_id,
            from_date,
            to_date,
            last,
            first,
            days,
            dsn,
        )
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)

    console.print(f"[bold]Found {len(results)} clusters[/bold]\n")

    for i, cluster in enumerate(results[:10], 1):
        console.print(f"[cyan]Cluster {i}[/cyan] (count: {cluster.count})")
        console.print(f"  → {cluster.representative}")
        for content, count in cluster.similar[:3]:
            if content != cluster.representative:
                console.print(f"    {content} ({count})")
        console.print()


@click.command()
@click.option("-r", "--room", required=True, help="Room ID")
@click.option("--dsn", help="PostgreSQL DSN (or use DYKIT_DSN env)")
@click.option("--content", help="Search content (ILIKE)")
@click.option("--user", "username", help="Filter by username")
@click.option("--user-id", help="Filter by user ID")
@click.option("--type", "msg_type", help="Filter by message type")
@click.option("--from", "from_time", help="From timestamp (ISO)")
@click.option("--to", "to_time", help="To timestamp (ISO)")
@click.option("--last", type=int, help="Use the last N (most recent) messages")
@click.option("--first", type=int, help="Use the first N (earliest) messages")
def search(
    room: str,
    dsn: str | None,
    content: str | None,
    username: str | None,
    user_id: str | None,
    msg_type: str | None,
    from_time: str | None,
    to_time: str | None,
    last: int | None,
    first: int | None,
) -> None:
    """Search messages with filters.

    Examples:
        dystat search -r 6657 --content "hello"
        dystat search -r 6657 --user "张三"
    """
    dsn = dsn or get_dsn()
    if not dsn:
        console.print("[red]Error: DSN required. Set DYKIT_DSN or use --dsn[/red]")
        sys.exit(1)

    try:
        results = run_search(
            room,
            content,
            username,
            user_id,
            msg_type,
            from_time,
            to_time,
            last,
            first,
            dsn,
        )
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)

    console.print(f"[bold]Found {len(results)} messages[/bold]\n")

    table = Table()
    table.add_column("Time", style="dim")
    table.add_column("User")
    table.add_column("Content")

    for r in results:
        table.add_row(
            r.timestamp.strftime("%H:%M:%S"),
            r.username or "-",
            r.content or "-",
        )

    console.print(table)


@click.command()
@click.option("-r", "--room", required=True, help="Room ID")
@click.option("--dsn", help="PostgreSQL DSN (or use DYKIT_DSN env)")
def prune(room: str, dsn: str | None) -> None:
    """Remove duplicate messages.

    Examples:
        dystat prune -r 6657
    """
    dsn = dsn or get_dsn()
    if not dsn:
        console.print("[red]Error: DSN required. Set DYKIT_DSN or use --dsn[/red]")
        sys.exit(1)

    try:
        deleted = run_prune(room, dsn)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)

    console.print(f"[green]Removed {deleted} duplicate records[/green]")


# Main group
@click.group()
@click.version_option(version=version("dystat"), prog_name="dystat")
def cli() -> None:
    """Douyu Statistics Tools - analyze danmu data."""
    pass


cli.add_command(rank)
cli.add_command(cluster)
cli.add_command(search)
cli.add_command(prune)


if __name__ == "__main__":
    cli()
