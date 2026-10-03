"""dykit-stats - query collected run files."""

from __future__ import annotations

from collections.abc import Callable
from importlib.metadata import version
from typing import Annotated, Literal, cast

from cyclopts import App, Parameter
from rich.console import Console
from rich.table import Table

from ..schema import DEFAULT_RUN_DIR
from .analysis import get
from .analysis import run as run_analysis
from .cluster import ClusterResult
from .db import DataDb
from .rank import RankResult
from .runtime import resolve_runtime
from .search import SearchResult

console: Console = Console()
app: App = App(name="dykit-stats", version=lambda: f"dykit {version('dykit')}")

# ---------------------------------------------------------------------------
# Shared option definitions. rank/cluster/search accept the same filters, so
# they are declared once here instead of being copy-pasted per command.
# ---------------------------------------------------------------------------

RoomOption = Annotated[str, Parameter(name=("-r", "--room"), help="Room ID")]

DataOption = Annotated[
    str | None,
    Parameter(
        name="--data",
        help=f"SQLite run file or directory of run files (default: ./{DEFAULT_RUN_DIR})",
    ),
]

MsgTypeOption = Annotated[str, Parameter(name="--type", help="Message type")]

MsgTypeFilterOption = Annotated[
    str | None,
    Parameter(name="--type", help="Filter by message type (default: every type)"),
]

# `--user` is the historical spelling (search); `--username` matches the other
# commands. Both are accepted everywhere now.
UsernameOption = Annotated[
    str | None,
    Parameter(name=("--username", "--user"), help="Filter by username"),
]

UserIdOption = Annotated[str | None, Parameter(name="--user-id", help="Filter by user_id")]

FromOption = Annotated[
    str | None,
    Parameter(name="--from", help="Start time (YYYY-MM-DD or YYYY-MM-DD HH:MM:SS)"),
]

ToOption = Annotated[
    str | None,
    Parameter(name="--to", help="End time (YYYY-MM-DD or YYYY-MM-DD HH:MM:SS, inclusive)"),
]

LastOption = Annotated[
    int | None,
    Parameter(name="--last", help="Use the last N (most recent) messages"),
]

FirstOption = Annotated[
    int | None,
    Parameter(name="--first", help="Use the first N (earliest) messages"),
]

DaysOption = Annotated[int | None, Parameter(name="--days", help="Limit to recent N days")]


def _run_with_cli_error[T](func: Callable[[], T]) -> T:
    try:
        return func()
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise SystemExit(1) from e


def _analyze(analysis_name: str, room: str, data: str | None, **options: object) -> object:
    """Resolve the room and --data, then run a registered analysis over it.

    Every command goes through the plugin registry, so built-ins and external
    plugins share one code path and a plugin gets the same error handling as
    `rank`. Resolution failures (unknown room, missing path) surface as a CLI
    error with exit code 1, exactly like a failed query does.
    """

    def execute() -> object:
        resolved_room, data_path = resolve_runtime(room, data)
        with DataDb(data_path) as db:
            return run_analysis(get(analysis_name), db, room=resolved_room, **options)

    return _run_with_cli_error(execute)


@app.command
def rank(
    room: RoomOption,
    data: DataOption = None,
    top: Annotated[int, Parameter(name="--top", help="Number of results")] = 10,
    mode: Annotated[
        Literal["user", "content"],
        Parameter(name="--by", help="Rank by user or content"),
    ] = "user",
    msg_type: MsgTypeOption = "chatmsg",
    days: DaysOption = None,
    username: UsernameOption = None,
    user_id: UserIdOption = None,
    from_date: FromOption = None,
    to_date: ToOption = None,
    last: LastOption = None,
    first: FirstOption = None,
) -> None:
    """Rank users or content by frequency.

    Examples:
        dykit-stats rank -r 6657 --top 10
        dykit-stats rank -r 6657 --by content --top 5
        dykit-stats rank -r 6657 --type dgb --top 5
    """
    results = cast(
        "list[RankResult]",
        _analyze(
            "rank",
            room,
            data,
            top=top,
            mode=mode,
            msg_type=msg_type,
            days=days,
            username=username,
            user_id=user_id,
            from_date=from_date,
            to_date=to_date,
            last=last,
            first=first,
        ),
    )

    table = Table(title=f"Top {mode}s in room {room}")
    table.add_column("Rank", justify="right")
    table.add_column(mode.title(), style="cyan")
    table.add_column("Count", justify="right", style="green")

    for r in results:
        table.add_row(str(r.rank), r.value, str(r.count))

    console.print(table)


@app.command
def cluster(
    room: RoomOption,
    data: DataOption = None,
    threshold: Annotated[
        float,
        Parameter(name="--threshold", help="Similarity threshold (0-1)"),
    ] = 0.5,
    limit: Annotated[int, Parameter(name="--limit", help="Source message limit")] = 50,
    msg_type: MsgTypeOption = "chatmsg",
    username: UsernameOption = None,
    user_id: UserIdOption = None,
    from_date: FromOption = None,
    to_date: ToOption = None,
    last: LastOption = None,
    first: FirstOption = None,
    days: DaysOption = None,
) -> None:
    """Cluster similar messages.

    Examples:
        dykit-stats cluster -r 6657 --threshold 0.5
    """
    results = cast(
        "list[ClusterResult]",
        _analyze(
            "cluster",
            room,
            data,
            threshold=threshold,
            msg_type=msg_type,
            limit=limit,
            username=username,
            user_id=user_id,
            from_date=from_date,
            to_date=to_date,
            last=last,
            first=first,
            days=days,
        ),
    )

    console.print(f"[bold]Found {len(results)} clusters[/bold]\n")

    for i, cluster_result in enumerate(results[:10], 1):
        console.print(f"[cyan]Cluster {i}[/cyan] (count: {cluster_result.count})")
        console.print(f"  → {cluster_result.representative}")
        for content, count in cluster_result.similar[:3]:
            if content != cluster_result.representative:
                console.print(f"    {content} ({count})")
        console.print()


@app.command
def search(
    room: RoomOption,
    data: DataOption = None,
    content: Annotated[
        str | None, Parameter(name="--content", help="Search content (LIKE)")
    ] = None,
    username: UsernameOption = None,
    user_id: UserIdOption = None,
    msg_type: MsgTypeFilterOption = None,
    from_time: FromOption = None,
    to_time: ToOption = None,
    last: LastOption = None,
    first: FirstOption = None,
) -> None:
    """Search messages with filters.

    Examples:
        dykit-stats search -r 6657 --content "hello"
        dykit-stats search -r 6657 --username "张三"
    """
    results = cast(
        "list[SearchResult]",
        _analyze(
            "search",
            room,
            data,
            content=content,
            username=username,
            user_id=user_id,
            msg_type=msg_type,
            from_date=from_time,
            to_date=to_time,
            last=last,
            first=first,
        ),
    )

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


def main() -> None:
    """Entry point for the `dykit-stats` command."""
    app()


if __name__ == "__main__":
    main()
