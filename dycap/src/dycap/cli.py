"""dycap CLI - Douyu Live Stream Collector."""

from __future__ import annotations

import sys
from datetime import datetime
from importlib.metadata import version
from typing import Annotated, Literal

from cyclopts import App, Group, Parameter
from cyclopts.argument import ArgumentCollection
from dycommon.env import get_dsn
from loguru import logger

from .collector import MSG_TYPE_LABELS, MSG_TYPE_TO_ENUM, AsyncCollector
from .render import render_message_text
from .storage import ConsoleStorage, CSVStorage, PostgreSQLStorageFromDSN
from .types import DanmuMessage


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
    storage_value = "postgres"
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


@app.default
async def collect(
    room: Annotated[str, Parameter(name=("-r", "--room"), help="Room ID to collect")],
    dsn: Annotated[
        str | None,
        Parameter(name="--dsn", help="PostgreSQL DSN (or use DYKIT_DSN/DYCAP_DSN env)"),
    ] = None,
    storage: Annotated[
        Literal["postgres", "csv", "console"],
        Parameter(name="--storage", help="Storage backend", group=_CSV_OUTPUT_GROUP),
    ] = "postgres",
    output: Annotated[
        str | None,
        Parameter(
            name=("-o", "--output"), help="Output file (for csv storage)", group=_CSV_OUTPUT_GROUP
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
                "Available: "
                + ", ".join(
                    f"{key}（{MSG_TYPE_LABELS.get(key, key)}）"
                    for key in sorted(MSG_TYPE_TO_ENUM.keys())
                )
                + ". "
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
                "Available: "
                + ", ".join(
                    f"{key}（{MSG_TYPE_LABELS.get(key, key)}）"
                    for key in sorted(MSG_TYPE_TO_ENUM.keys())
                )
                + ". "
                "Example: --without uenter"
            ),
            group=_WITH_WITHOUT_GROUP,
        ),
    ] = None,
) -> None:
    """Collect danmu messages from a Douyu room."""
    dsn = dsn or get_dsn("DYCAP_DSN")

    if verbose:
        logger.remove()
        logger.add(sys.stderr, level="INFO")
        logger.info("Verbose mode enabled")

    if storage == "postgres" and not dsn:
        print(
            "Error: DSN required for postgres storage. Use --dsn or set DYKIT_DSN/DYCAP_DSN.",
            file=sys.stderr,
        )
        raise SystemExit(1)

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

    message_count = 0
    last_message_at: datetime | None = None

    def message_callback(message: DanmuMessage) -> None:
        nonlocal message_count, last_message_at
        message_count += 1
        last_message_at = message.timestamp

        if storage != "console":
            print(f"[{message.room_id}] {render_message_text(message)}")

    match storage:
        case "postgres":
            assert dsn is not None
            storage_handler = await PostgreSQLStorageFromDSN.create(room_id=room, dsn=dsn)
        case "csv":
            assert output is not None
            storage_handler = CSVStorage(output)
        case _:
            storage_handler = ConsoleStorage()

    async with storage_handler:
        collector = AsyncCollector(
            room,
            storage_handler,
            type_filter=type_filter,
            type_exclude=type_exclude,
            message_callback=message_callback,
        )

        print(f"Collecting from room {room}... Press Ctrl+C to stop.")

        try:
            await collector.connect()
        except KeyboardInterrupt:
            await collector.stop()
            print("Stopped.")
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            raise SystemExit(1) from e
        finally:
            if last_message_at is not None:
                print(
                    "Summary: "
                    f"storage={storage}, messages={message_count}, "
                    f"last_message_at={last_message_at.isoformat(timespec='seconds')}"
                )
            else:
                print(f"Summary: storage={storage}, messages={message_count}")


def main() -> None:
    app()


def _click_compat_main(*, args: list[str] | tuple[str, ...] | None = None, **_: object) -> None:
    tokens = list(args) if args is not None else None
    app(tokens)


collect.name = "collect"  # type: ignore[attr-defined]
collect.main = _click_compat_main  # type: ignore[attr-defined]


if __name__ == "__main__":
    main()
