"""dykit-capture - collect danmu from a Douyu room into a run file."""

from __future__ import annotations

import asyncio
import contextlib
import signal
import sys
from collections.abc import Callable
from datetime import datetime
from importlib.metadata import version
from pathlib import Path
from typing import Annotated, Literal

from cyclopts import App, Group, Parameter
from cyclopts.argument import ArgumentCollection
from loguru import logger
from rich.console import Console

from ..protocol import MSG_TYPE_TO_ENUM
from ..schema import DEFAULT_RUN_DIR, default_run_file
from ..source import resolve_room_id
from .collector import AsyncCollector
from .render import MESSAGE_KINDS, render_console_line
from .settings import SETTINGS
from .storage import ConsoleStorage, CSVStorage, SQLiteStorage, StorageHandler
from .types import DanmuMessage

_AVAILABLE_TYPES_HELP = ", ".join(
    f"{key}（{MESSAGE_KINDS[MSG_TYPE_TO_ENUM[key]].label_cn}）"
    for key in sorted(MSG_TYPE_TO_ENUM.keys())
)


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

app: App = App(name="dykit-capture", version=lambda: f"dykit {version('dykit')}")
console: Console = Console()


def _termination_signal_to_keyboardinterrupt(_signum: int, _frame: object) -> None:
    """Fallback (platforms without loop.add_signal_handler support)."""
    raise KeyboardInterrupt


async def _run_collector(
    collector: AsyncCollector,
    shutdown_event: asyncio.Event,
    rotate_event: asyncio.Event,
) -> None:
    """Run the collector until it exits, shutdown is asked for, or SIGHUP.

    SIGINT/SIGTERM are routed through ``shutdown_event`` (via
    ``loop.add_signal_handler``) so shutdown is graceful: the run file always
    gets its meta.ended_at marker, no matter when the signal arrives.

    Shutdown cancels the connect task rather than only clearing a flag, so an
    await stuck in HTTP discovery (up to ~30s of retries) cannot delay exit.
    """
    connect_task = asyncio.create_task(collector.connect())
    shutdown_task = asyncio.create_task(shutdown_event.wait())
    rotate_task = asyncio.create_task(rotate_event.wait())
    pending = {connect_task, shutdown_task, rotate_task}
    shutdown_requested = False
    try:
        while pending:
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            if rotate_task in done:
                print("Rotating to a new run file...")
                await collector.rotate(reason="SIGHUP")
                rotate_task = asyncio.create_task(rotate_event.wait())
                pending.add(rotate_task)
            if shutdown_task in done:
                shutdown_requested = True
                break
            if connect_task in done:
                break
        if shutdown_requested and not connect_task.done():
            print("Shutting down...")
            # Ignore further Ctrl+C/SIGTERM during teardown: a second signal
            # (e.g. an impatient double-press) would interrupt close() and skip
            # the meta.ended_at marker on platforms without loop signal handlers.
            try:
                signal.signal(signal.SIGINT, signal.SIG_IGN)
                signal.signal(signal.SIGTERM, signal.SIG_IGN)
            except ValueError:
                pass
            try:
                await collector.stop()  # cancels connect_task
                with contextlib.suppress(asyncio.CancelledError):
                    await connect_task
            except Exception as exc:  # collector teardown failure after stop
                print(f"collector teardown: {exc}", file=sys.stderr)
    finally:
        for task in (shutdown_task, rotate_task):
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task


def _make_sqlite_sink_factory(
    room: str,
    output: str | None,
    batch_size: int,
    flush_interval: float,
    rotate_after: int,
) -> Callable[[], SQLiteStorage]:
    """Build sinks for a session, naming each rollover after its start time.

    Rollover files are named by their own creation time, so a room's shards
    sort chronologically by filename alone.
    """

    def factory() -> SQLiteStorage:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = output or str(default_run_file(room, stamp))
        return SQLiteStorage(
            path,
            room_id=room,
            batch_size=batch_size,
            flush_interval=flush_interval,
            rotate_after=rotate_after,
        )

    return factory


def _build_storage(
    storage: str,
    output: str | None,
    room: str,
    batch_size: int,
    flush_interval: float,
    rotate_after: int,
) -> tuple[StorageHandler, Callable[[], StorageHandler] | None, str]:
    """Create the first sink plus, when sharding applies, a factory for the next."""
    if storage == "sqlite":
        if output is not None:
            # An explicit path names exactly one file; sharding it would mean
            # inventing names the caller did not ask for.
            first = SQLiteStorage(
                output,
                room_id=room,
                batch_size=batch_size,
                flush_interval=flush_interval,
            )
            return first, None, output
        factory = _make_sqlite_sink_factory(room, None, batch_size, flush_interval, rotate_after)
        first = factory()
        return first, factory, first.run_ref
    if storage == "csv":
        assert output is not None
        return CSVStorage(output), None, output
    return ConsoleStorage(), None, "stdout"


@app.default
async def collect(
    room: Annotated[str, Parameter(name=("-r", "--room"), help="Room ID to collect")],
    ws_url: Annotated[
        str | None,
        Parameter(name="--ws-url", help="Manual WebSocket URL override"),
    ] = SETTINGS.ws_url,
    storage: Annotated[
        Literal["sqlite", "csv", "console"],
        Parameter(
            name="--storage",
            help="Storage backend (sqlite = one .db file per run)",
            group=_CSV_OUTPUT_GROUP,
        ),
    ] = SETTINGS.storage,
    output: Annotated[
        str | None,
        Parameter(
            name=("-o", "--output"),
            help=(
                "Output path: SQLite .db file (sqlite) or CSV file (csv). "
                f"Default: {DEFAULT_RUN_DIR}/<room>_<timestamp>.db"
            ),
            group=_CSV_OUTPUT_GROUP,
        ),
    ] = SETTINGS.output,
    verbose: Annotated[
        bool, Parameter(name=("-v", "--verbose"), help="Enable verbose logging")
    ] = SETTINGS.verbose,
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
    ] = SETTINGS.msg_types_include,
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
    ] = SETTINGS.msg_types_exclude,
    rotate_after: Annotated[
        int,
        Parameter(
            name="--rotate-after",
            help="Roll over to a new run file after this many committed messages (0 = never)",
        ),
    ] = SETTINGS.rotate_after,
    batch_size: Annotated[
        int,
        Parameter(name="--batch-size", help="Messages buffered before an automatic commit"),
    ] = SETTINGS.batch_size,
    flush_interval: Annotated[
        float,
        Parameter(
            name="--flush-interval",
            help=(
                "Max seconds between commits; also the worst-case data loss "
                "if the process is killed"
            ),
        ),
    ] = SETTINGS.flush_interval,
    debug_discovery: Annotated[
        bool,
        Parameter(name="--debug-discovery", help="Log room/server discovery steps"),
    ] = SETTINGS.debug_discovery,
) -> None:
    """Collect danmu messages from a Douyu room into one or more run files."""
    room_display = room
    try:
        resolved_room = str(resolve_room_id(room))
        if resolved_room != room:
            room_display = f"{room}/{resolved_room}"
    except Exception:
        logger.debug("room display resolution failed for {}", room, exc_info=True)
        room_display = room

    if verbose:
        logger.remove()
        logger.add(sys.stderr, level="INFO")
        logger.info("Verbose mode enabled")

    # Graceful shutdown: route SIGINT/SIGTERM through an asyncio event so the
    # run file always gets its meta.ended_at marker. Falls back to raising
    # KeyboardInterrupt on platforms without loop signal handlers.
    #
    # The two signals are registered independently: on Windows
    # add_signal_handler(SIGTERM) raises NotImplementedError, and a shared
    # try/except would leave SIGINT hijacked (event set, nobody consuming it)
    # while use_event_signals stays False - making Ctrl+C unable to exit.
    loop = asyncio.get_running_loop()
    shutdown_event = asyncio.Event()
    rotate_event = asyncio.Event()
    use_event_signals = False
    try:
        loop.add_signal_handler(signal.SIGINT, shutdown_event.set)
        use_event_signals = True
    except NotImplementedError:
        pass
    try:
        loop.add_signal_handler(signal.SIGTERM, shutdown_event.set)
    except NotImplementedError:
        signal.signal(signal.SIGTERM, _termination_signal_to_keyboardinterrupt)
    # SIGHUP rolls over to a new run file without stopping the socket, so
    # sharding and archiving never cost a collection gap.
    hup_installed = False
    if hasattr(signal, "SIGHUP"):
        try:
            loop.add_signal_handler(signal.SIGHUP, rotate_event.set)
            hup_installed = True
        except NotImplementedError:
            pass

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
        if storage == "sqlite" and output is not None and Path(output).exists():
            raise FileExistsError(
                f"Output database already exists: {output} (refusing to overwrite a run file)"
            )
        storage_handler, sink_factory, output_path = _build_storage(
            storage, output, room, batch_size, flush_interval, rotate_after
        )
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
            ws_url=ws_url,
            type_filter=type_filter,
            type_exclude=type_exclude,
            message_callback=message_callback,
            sink_factory=sink_factory,
            data_dir=Path(DEFAULT_RUN_DIR),
        )

        if storage == "sqlite":
            print(f"Output: {output_path}")
            if sink_factory is None:
                print("Sharding: off (explicit --output names a single file)")
            elif rotate_after > 0:
                print(f"Sharding: roll over to a new run file every {rotate_after} messages")
        print(f"Collecting from room {room_display}... Press Ctrl+C to stop.")
        if hup_installed and sink_factory is not None:
            print("Send SIGHUP to roll over to a new run file without stopping.")

        try:
            if use_event_signals:
                await _run_collector(collector, shutdown_event, rotate_event)
            else:
                await collector.connect()
        except KeyboardInterrupt:
            await collector.stop()
            print("Stopped.")
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            raise SystemExit(1) from e
        finally:
            stats = getattr(collector.storage, "stats", None)
            stats_text = ""
            if stats is not None:
                stats_text = (
                    f", committed={stats.get('committed', 0)}, flushes={stats.get('flushes', 0)}"
                )
            shards = f", shards={collector.rotations + 1}" if collector.rotations else ""
            if last_message_at is not None:
                print(
                    "Summary: "
                    f"storage={storage}, messages={message_count}, "
                    f"last_message_at={last_message_at.isoformat(timespec='seconds')}"
                    f"{stats_text}{shards}"
                )
            else:
                print(f"Summary: storage={storage}, messages={message_count}{stats_text}{shards}")


def main() -> None:
    """Entry point for the `dykit-capture` command."""
    app()


if __name__ == "__main__":
    main()
