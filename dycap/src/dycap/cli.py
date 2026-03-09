"""dycap CLI - Douyu Live Stream Collector."""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime

import click
from dycommon.env import get_dsn

from .collector import MSG_TYPE_LABELS, MSG_TYPE_TO_ENUM, AsyncCollector
from .render import render_message_text
from .storage import ConsoleStorage, CSVStorage, PostgreSQLStorageFromDSN
from .types import DanmuMessage


@click.command()
@click.option("-r", "--room", required=True, help="Room ID to collect")
@click.option("--dsn", help="PostgreSQL DSN (or use DYKIT_DSN env)")
@click.option(
    "--storage",
    type=click.Choice(["postgres", "csv", "console"]),
    default="postgres",
    help="Storage backend",
)
@click.option("-o", "--output", help="Output file (for csv storage)")
@click.option("-v", "--verbose", is_flag=True, help="Enable verbose logging")
@click.option(
    "--with",
    "msg_types_include",
    default=None,
    help=(
        "Filter to only these message types (comma-separated). "
        "Available: "
        + ", ".join(
            f"{key}（{MSG_TYPE_LABELS.get(key, key)}）" for key in sorted(MSG_TYPE_TO_ENUM.keys())
        )
        + ". "
        "Example: --with chatmsg,dgb,uenter"
    ),
)
@click.option(
    "--without",
    "msg_types_exclude",
    default=None,
    help=(
        "Filter out these message types (comma-separated). "
        "Available: "
        + ", ".join(
            f"{key}（{MSG_TYPE_LABELS.get(key, key)}）" for key in sorted(MSG_TYPE_TO_ENUM.keys())
        )
        + ". "
        "Example: --without uenter"
    ),
)
def collect(
    room: str,
    dsn: str | None,
    storage: str,
    output: str | None,
    verbose: bool,
    msg_types_include: str | None,
    msg_types_exclude: str | None,
) -> None:
    """Collect danmu messages from a Douyu room.

    Examples:
        dycap collect -r 6657
        dycap collect -r 6657 --dsn postgresql://user:pass@localhost/douyu
        dycap collect -r 6657 --storage csv -o output.csv
    """
    # Get DSN
    dsn = dsn or get_dsn()
    if storage == "postgres" and not dsn:
        click.echo(
            "Error: DSN required for postgres storage. Use --dsn or set DYKIT_DSN.", err=True
        )
        sys.exit(1)

    if msg_types_include is not None and msg_types_exclude is not None:
        click.echo("Error: Cannot use --with and --without together", err=True)
        sys.exit(1)

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

    def on_message(message: DanmuMessage) -> None:
        nonlocal message_count, last_message_at
        message_count += 1
        last_message_at = message.timestamp

        if storage != "console":
            click.echo(f"[{message.room_id}] {render_message_text(message)}")

    async def run() -> None:
        # Create storage
        if storage == "postgres":
            assert dsn is not None
            storage_handler = await PostgreSQLStorageFromDSN.create(room_id=room, dsn=dsn)
        elif storage == "csv":
            if not output:
                click.echo("Error: --output required for csv storage.", err=True)
                sys.exit(1)
            storage_handler = CSVStorage(output)
        else:
            storage_handler = ConsoleStorage()

        # Run collector
        async with storage_handler:
            collector = AsyncCollector(
                room,
                storage_handler,
                type_filter=type_filter,
                type_exclude=type_exclude,
                message_callback=on_message,
            )

            click.echo(f"Collecting from room {room}... Press Ctrl+C to stop.")

            try:
                await collector.connect()
            except KeyboardInterrupt:
                await collector.stop()
                click.echo("Stopped.")
            except Exception as e:
                click.echo(f"Error: {e}", err=True)
                sys.exit(1)
            finally:
                if last_message_at is not None:
                    click.echo(
                        "Summary: "
                        f"storage={storage}, messages={message_count}, "
                        f"last_message_at={last_message_at.isoformat(timespec='seconds')}"
                    )
                else:
                    click.echo(f"Summary: storage={storage}, messages={message_count}")

    asyncio.run(run())


if __name__ == "__main__":
    collect()
