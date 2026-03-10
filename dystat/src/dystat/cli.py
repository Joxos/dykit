"""dystat CLI - Douyu Statistics Tools."""

from __future__ import annotations

from importlib.metadata import version
from typing import Annotated, Literal

from cyclopts import App, Parameter
from dycommon.env import get_dsn
from rich.console import Console
from rich.table import Table

from .cluster import run_cluster
from .rank import run_rank
from .search import run_search

console = Console()
app = App(name="dystat", version=lambda: f"dystat {version('dystat')}")


@app.command
def rank(
    room: Annotated[str, Parameter(name=("-r", "--room"), help="Room ID")],
    dsn: Annotated[
        str | None,
        Parameter(name="--dsn", help="PostgreSQL DSN (or use DYKIT_DSN env)"),
    ] = None,
    top: Annotated[int, Parameter(name="--top", help="Number of results")] = 10,
    mode: Annotated[
        Literal["user", "content"],
        Parameter(name="--by", help="Rank by user or content"),
    ] = "user",
    msg_type: Annotated[str, Parameter(name="--type", help="Message type")] = "chatmsg",
    days: Annotated[int | None, Parameter(name="--days", help="Limit to recent N days")] = None,
    username: Annotated[str | None, Parameter(name="--username", help="Filter by username")] = None,
    user_id: Annotated[str | None, Parameter(name="--user-id", help="Filter by user_id")] = None,
    from_date: Annotated[
        str | None,
        Parameter(name="--from", help="Start time (YYYY-MM-DD or YYYY-MM-DD HH:MM:SS)"),
    ] = None,
    to_date: Annotated[
        str | None,
        Parameter(name="--to", help="End time (YYYY-MM-DD or YYYY-MM-DD HH:MM:SS, inclusive)"),
    ] = None,
    last: Annotated[
        int | None,
        Parameter(name="--last", help="Use the last N (most recent) messages"),
    ] = None,
    first: Annotated[
        int | None,
        Parameter(name="--first", help="Use the first N (earliest) messages"),
    ] = None,
) -> None:
    """Rank users or content by frequency.

    Examples:
        dystat rank -r 6657 --top 10
        dystat rank -r 6657 --by content --top 5
        dystat rank -r 6657 --type dgb --top 5
    """
    dsn = dsn or get_dsn("DYSTAT_DSN")
    if not dsn:
        console.print("[red]Error: DSN required. Set DYKIT_DSN or use --dsn[/red]")
        raise SystemExit(1)

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
        raise SystemExit(1) from e

    # Display table
    table = Table(title=f"Top {mode}s in room {room}")
    table.add_column("Rank", justify="right")
    table.add_column(mode.title(), style="cyan")
    table.add_column("Count", justify="right", style="green")

    for r in results:
        table.add_row(str(r.rank), r.value, str(r.count))

    console.print(table)


@app.command
def cluster(
    room: Annotated[str, Parameter(name=("-r", "--room"), help="Room ID")],
    dsn: Annotated[
        str | None,
        Parameter(name="--dsn", help="PostgreSQL DSN (or use DYKIT_DSN env)"),
    ] = None,
    threshold: Annotated[
        float,
        Parameter(name="--threshold", help="Similarity threshold (0-1)"),
    ] = 0.5,
    limit: Annotated[int, Parameter(name="--limit", help="Source message limit")] = 50,
    msg_type: Annotated[str, Parameter(name="--type", help="Message type")] = "chatmsg",
    username: Annotated[str | None, Parameter(name="--username", help="Filter by username")] = None,
    user_id: Annotated[str | None, Parameter(name="--user-id", help="Filter by user_id")] = None,
    from_date: Annotated[
        str | None,
        Parameter(name="--from", help="Start time (YYYY-MM-DD or YYYY-MM-DD HH:MM:SS)"),
    ] = None,
    to_date: Annotated[
        str | None,
        Parameter(name="--to", help="End time (YYYY-MM-DD or YYYY-MM-DD HH:MM:SS, inclusive)"),
    ] = None,
    last: Annotated[
        int | None,
        Parameter(name="--last", help="Use the last N (most recent) messages"),
    ] = None,
    first: Annotated[
        int | None,
        Parameter(name="--first", help="Use the first N (earliest) messages"),
    ] = None,
    days: Annotated[int | None, Parameter(name="--days", help="Limit to recent N days")] = None,
) -> None:
    """Cluster similar messages.

    Examples:
        dystat cluster -r 6657 --threshold 0.5
    """
    dsn = dsn or get_dsn("DYSTAT_DSN")
    if not dsn:
        console.print("[red]Error: DSN required. Set DYKIT_DSN or use --dsn[/red]")
        raise SystemExit(1)

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
        raise SystemExit(1) from e

    console.print(f"[bold]Found {len(results)} clusters[/bold]\n")

    for i, cluster in enumerate(results[:10], 1):
        console.print(f"[cyan]Cluster {i}[/cyan] (count: {cluster.count})")
        console.print(f"  → {cluster.representative}")
        for content, count in cluster.similar[:3]:
            if content != cluster.representative:
                console.print(f"    {content} ({count})")
        console.print()


@app.command
def search(
    room: Annotated[str, Parameter(name=("-r", "--room"), help="Room ID")],
    dsn: Annotated[
        str | None,
        Parameter(name="--dsn", help="PostgreSQL DSN (or use DYKIT_DSN env)"),
    ] = None,
    content: Annotated[
        str | None, Parameter(name="--content", help="Search content (ILIKE)")
    ] = None,
    username: Annotated[str | None, Parameter(name="--user", help="Filter by username")] = None,
    user_id: Annotated[str | None, Parameter(name="--user-id", help="Filter by user ID")] = None,
    msg_type: Annotated[str | None, Parameter(name="--type", help="Filter by message type")] = None,
    from_time: Annotated[str | None, Parameter(name="--from", help="From timestamp (ISO)")] = None,
    to_time: Annotated[str | None, Parameter(name="--to", help="To timestamp (ISO)")] = None,
    last: Annotated[
        int | None,
        Parameter(name="--last", help="Use the last N (most recent) messages"),
    ] = None,
    first: Annotated[
        int | None,
        Parameter(name="--first", help="Use the first N (earliest) messages"),
    ] = None,
) -> None:
    """Search messages with filters.

    Examples:
        dystat search -r 6657 --content "hello"
        dystat search -r 6657 --user "张三"
    """
    dsn = dsn or get_dsn("DYSTAT_DSN")
    if not dsn:
        console.print("[red]Error: DSN required. Set DYKIT_DSN or use --dsn[/red]")
        raise SystemExit(1)

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
        raise SystemExit(1) from e

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


def cli() -> None:
    """Douyu Statistics Tools - analyze danmu data."""
    app()


def _click_compat_main(*, args: list[str] | tuple[str, ...] | None = None, **_: object) -> None:
    tokens = list(args) if args is not None else None
    app(tokens)


cli.name = "dystat"  # type: ignore[attr-defined]
cli.main = _click_compat_main  # type: ignore[attr-defined]


if __name__ == "__main__":
    cli()
