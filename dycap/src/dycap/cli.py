"""dycap CLI - Douyu Live Stream Collector."""

from __future__ import annotations

import asyncio
import signal
import sys
from datetime import datetime
from importlib.metadata import version
from pathlib import Path
from typing import Annotated, Literal

from cyclopts import App, Group, Parameter
from cyclopts.argument import ArgumentCollection
from dycommon.room import resolve_room
from dyproto import MESSAGE_KINDS, MSG_TYPE_TO_ENUM
from loguru import logger
from rich.console import Console

from .collector import AsyncCollector
from .render import render_console_line
from .storage import ConsoleStorage, CSVStorage, SQLiteStorage
from .types import DanmuMessage

DEFAULT_DATA_DIR = "dycap-data"

_AVAILABLE_TYPES_HELP = ", ".join(
    f"{key}（{MESSAGE_KINDS[MSG_TYPE_TO_ENUM[key]].label_cn}）"
    for key in sorted(MSG_TYPE_TO_ENUM.keys())
)


def _default_db_path(room: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return str(Path(DEFAULT_DATA_DIR) / f"{room}_{stamp}.db")


def _validate_with_without(arguments: ArgumentCollection) -> None:
    include_given = False
    exclude_given = False
    for argument in arguments:
        if argument.field_info.name == "msg_types_include":
            include_given = argument.has_tokens
        elif argument.field_info.name == "msg_types_exclude":
            exclude_given = argument.has_tokens
    if include_given and exclude_given:
        raise ValueError("Cannot use --with and --without together")


def _validate_csv_output(arguments: ArgumentCollection) -> None:
    storage_value = "sqlite"
    output_given = False
    for argument in arguments:
        if argument.field_info.name == "storage" and argument.value is not None:
            storage_value = str(argument.value)
        elif argument.field_info.name == "output":
            output_given = argument.has_tokens
    if storage_value == "csv" and not output_given:
        raise ValueError("--output required")


_WITH_WITHOUT_GROUP = Group(show=False, validator=_validate_with_without)
_CSV_OUTPUT_GROUP = Group(show=False, validator=_validate_csv_output)

app = App(name="dycap", version=lambda: f"dycap {version('dycap')}")
console = Console()


def _termination_signal_to_keyboardinterrupt(signum: int, _frame: object) -> None:
    """Fallback (platforms without loop.add_signal_handler support)."""
    raise KeyboardInterrupt


async def _run_collector(collector: AsyncCollector, shutdown_event: asyncio.Event) -> None:
    """Run the collector until it exits or shutdown is requested.

    SIGINT/SIGTERM are routed through ``shutdown_event`` (via
    ``loop.add_signal_handler``) so shutdown is graceful: the run file always
    gets its meta.ended_at marker, no matter when the signal arrives.
    """
    connect_task = asyncio.create_task(collector.connect())
    shutdown_task = asyncio.create_task(shutdown_event.wait())
    done, _pending = await asyncio.wait(
        {connect_task, shutdown_task}, return_when=asyncio.FIRST_COMPLETED
    )
    if shutdown_task in done and not connect_task.done():
        try:
            await collector.stop()
            await connect_task
        except asyncio.CancelledError:
            pass
        except Exception as exc:  # collector teardown failure after stop
            print(f"collector teardown: {exc}", file=sys.stderr)


@app.default
async def collect(
    room: Annotated[str, Parameter(name=("-r", "--room"), help="Room ID to collect")],
    storage: Annotated[
        Literal["sqlite", "csv", "console"],
        Parameter(
            name="--storage",
            help="Storage backend (default: sqlite - one .db file per run)",
            group=_CSV_OUTPUT_GROUP,
        ),
    ] = "sqlite",
    output: Annotated[
        str | None,
        Parameter(
            name=("-o", "--output"),
            help=(
                "Output path: SQLite .db file (sqlite) or CSV file (csv). "
                f"Default: {DEFAULT_DATA_DIR}/<room>_<timestamp>.db"
            ),
            group=_CSV_OUTPUT_GROUP,
        ),
    ] = None,
    verbose: Annotated[
        bool, Parameter(name=("-v", "--verbose"), help="Enable verbose logging")
    ] = False,
    msg_types_include: Annotated[
        str | None,
        Parameter(
            name="--with",
            help=(
                "Filter to only these message types (comma-separated). "
                f"Available: {_AVAILABLE_TYPES_HELP}. "
                "Example: --with chatmsg,dgb,uenter"
            ),
            group=_WITH_WITHOUT_GROUP,
        ),
    ] = None,
    msg_types_exclude: Annotated[
        str | None,
        Parameter(
            name="--without",
            help=(
                "Filter out these message types (comma-separated). "
                f"Available: {_AVAILABLE_TYPES_HELP}. "
                "Example: --without uenter"
            ),
            group=_WITH_WITHOUT_GROUP,
        ),
    ] = None,
) -> None:
    """Collect danmu messages from a Douyu room into a run file."""
    room_display = room
    try:
        resolved_room = resolve_room(room)
        if resolved_room != room:
            room_display = f"{room}/{resolved_room}"
    except Exception:
        room_display = room

    if verbose:
        logger.remove()
        logger.add(sys.stderr, level="INFO")
        logger.info("Verbose mode enabled")

    # Graceful shutdown: route SIGINT/SIGTERM through an asyncio event so the
    # run file always gets its meta.ended_at marker. Falls back to raising
    # KeyboardInterrupt on platforms without loop signal handlers.
    loop = asyncio.get_running_loop()
    shutdown_event = asyncio.Event()
    use_event_signals = False
    try:
        loop.add_signal_handler(signal.SIGINT, shutdown_event.set)
        loop.add_signal_handler(signal.SIGTERM, shutdown_event.set)
        use_event_signals = True
    except NotImplementedError:
        signal.signal(signal.SIGTERM, _termination_signal_to_keyboardinterrupt)

    type_filter = (
        [token.strip() for token in msg_types_include.split(",") if token.strip()]
        if msg_types_include
        else None
    )
    type_exclude = (
        [token.strip() for token in msg_types_exclude.split(",") if token.strip()]
        if msg_types_exclude
        else None
    )

    output_path = ""
    try:
        match storage:
            case "sqlite":
                output_path = output or _default_db_path(room)
                if Path(output_path).exists():
                    raise FileExistsError(
                        f"Output database already exists: {output_path} "
                        "(refusing to overwrite a run file)"
                    )
                storage_handler = SQLiteStorage(output_path, room_id=room)
            case "csv":
                assert output is not None
                storage_handler = CSVStorage(output)
            case _:
                storage_handler = ConsoleStorage()
    except (FileExistsError, OSError) as e:
        print(f"Error: {e}", file=sys.stderr)
        raise SystemExit(1) from e

    message_count = 0
    last_message_at: datetime | None = None

    def message_callback(message: DanmuMessage) -> None:
        nonlocal message_count, last_message_at
        message_count += 1
        last_message_at = message.timestamp

        if storage != "console":
            console.print(render_console_line(message, room_display=room_display))

    async with storage_handler:
        collector = AsyncCollector(
            room,
            storage_handler,
            type_filter=type_filter,
            type_exclude=type_exclude,
            message_callback=message_callback,
        )

        if storage == "sqlite":
            print(f"Output: {output_path}")
        print(f"Collecting from room {room_display}... Press Ctrl+C to stop.")

        try:
            if use_event_signals:
                await _run_collector(collector, shutdown_event)
            else:
                await collector.connect()
        except KeyboardInterrupt:
            await collector.stop()
            print("Stopped.")
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            raise SystemExit(1) from e
        finally:
            stats = getattr(storage_handler, "stats", None)
            stats_text = ""
            if stats is not None:
                stats_text = f", flushes={stats.get('flushes', 0)}"
            if last_message_at is not None:
                print(
                    "Summary: "
                    f"storage={storage}, messages={message_count}, "
                    f"last_message_at={last_message_at.isoformat(timespec='seconds')}"
                    f"{stats_text}"
                )
            else:
                print(f"Summary: storage={storage}, messages={message_count}{stats_text}")


def main() -> None:
    app()


def _click_compat_main(*, args: list[str] | tuple[str, ...] | None = None, **_: object) -> None:
    tokens = list(args) if args is not None else None
    app(tokens)


collect.name = "collect"  # type: ignore[attr-defined]
collect.main = _click_compat_main  # type: ignore[attr-defined]


if __name__ == "__main__":
    main()
