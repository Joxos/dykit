"""CLI interface for Douyu Danmu Crawler with async support and pluggable storage.

This module provides a command-line interface for the Douyu Danmu Crawler that supports:
- Multiple storage backends (CSV, console output)
- Synchronous and asynchronous collection modes
- Configurable room ID, output file, and logging level

Usage Examples:
    # Collect danmu from room 6657 to CSV (default)
    python -m douyu_danmu

    # Collect from different room
    python -m douyu_danmu --room-id 123456

    # Use console output instead of CSV
    python -m douyu_danmu --storage console

    # Async mode with CSV output
    python -m douyu_danmu --async --output custom.csv

    # All options combined
    python -m douyu_danmu --room-id 123456 --storage csv --output danmu.csv --async -v

CLI Arguments:
    --room-id (-r):     Douyu room ID to connect to (default: 6657)
    --storage:          Storage backend type: "csv" or "console" (default: csv)
    --output (-o):      CSV file path for csv storage (default: danmu.csv)
    --async:            Use async collector instead of sync (default: False)
    --verbose (-v):     Enable debug logging (default: False)

Exit Codes:
    0: Normal exit (Ctrl+C)
    1: Configuration error or runtime exception
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from douyu_danmu.collectors import AsyncCollector, SyncCollector
from douyu_danmu.log import logger
from douyu_danmu.storage import ConsoleStorage, CSVStorage


def _validate_args(args: argparse.Namespace) -> None:
    """Validate command-line arguments.

    Args:
        args: Parsed command-line arguments.

    Raises:
        ValueError: If arguments are invalid.
    """
    if args.storage not in ("csv", "console"):
        raise ValueError(
            f"Invalid storage type: {args.storage}. Must be 'csv' or 'console'."
        )

    if args.storage == "csv" and not args.output:
        raise ValueError("--output is required when using csv storage.")

    if args.room_id <= 0:
        raise ValueError(f"Room ID must be positive, got {args.room_id}.")


def _create_storage(args: argparse.Namespace):
    """Create and return the appropriate storage handler.

    Args:
        args: Parsed command-line arguments.

    Returns:
        StorageHandler: The appropriate storage handler instance.

    Raises:
        ValueError: If storage type is invalid.
    """
    if args.storage == "csv":
        return CSVStorage(args.output)
    elif args.storage == "console":
        return ConsoleStorage(verbose=args.verbose)
    else:
        raise ValueError(f"Unknown storage type: {args.storage}")


async def _async_main(args: argparse.Namespace) -> None:
    """Main async entry point for async collector mode.

    Args:
        args: Parsed command-line arguments.
    """
    storage = _create_storage(args)
    try:
        with storage:
            collector = AsyncCollector(args.room_id, storage)
            logger.info(
                f"Starting async collection from room {args.room_id} "
                f"(storage: {args.storage})"
            )
            try:
                await collector.connect()
            except KeyboardInterrupt:
                logger.info("Interrupted by user")
                await collector.stop()
    except Exception as e:
        logger.error(f"Error during collection: {e}", exc_info=args.verbose)
        raise


def _sync_main(args: argparse.Namespace) -> None:
    """Main sync entry point for sync collector mode.

    Args:
        args: Parsed command-line arguments.
    """
    storage = _create_storage(args)
    try:
        with storage:
            collector = SyncCollector(args.room_id, storage)
            logger.info(
                f"Starting sync collection from room {args.room_id} "
                f"(storage: {args.storage})"
            )
            try:
                collector.connect()
            except KeyboardInterrupt:
                logger.info("Interrupted by user")
                collector.stop()
    except Exception as e:
        logger.error(f"Error during collection: {e}", exc_info=args.verbose)
        raise


def main() -> None:
    """Main entry point for the CLI."""
    parser = argparse.ArgumentParser(
        description="Douyu live stream danmu (chat message) crawler",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  python -m douyu_danmu                           # Default: room 6657, CSV output
  python -m douyu_danmu --room-id 123456          # Specific room
  python -m douyu_danmu --storage console         # Console output
  python -m douyu_danmu --async                   # Async mode
  python -m douyu_danmu -r 6657 -o chat.csv -v    # Verbose with custom file
""",
    )

    parser.add_argument(
        "-r",
        "--room-id",
        type=int,
        default=6657,
        help="Douyu room ID (default: %(default)s)",
    )

    parser.add_argument(
        "--storage",
        type=str,
        choices=["csv", "console"],
        default="csv",
        help="Storage backend: csv or console (default: %(default)s)",
    )

    parser.add_argument(
        "-o",
        "--output",
        type=str,
        default="danmu.csv",
        help="CSV file path for csv storage (default: %(default)s)",
    )

    parser.add_argument(
        "--async",
        dest="async_mode",
        action="store_true",
        help="Use async collector instead of sync",
    )

    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable debug logging",
    )

    # Parse arguments
    args = parser.parse_args()

    # Setup logging
    # Loguru is pre-configured in douyu_danmu.log module

    try:
        # Validate arguments
        _validate_args(args)

        # Log startup
        logger.info(
            f"Douyu Danmu Crawler started - "
            f"room_id={args.room_id}, "
            f"storage={args.storage}, "
            f"async={args.async_mode}"
        )

        # Run appropriate collector
        if args.async_mode:
            asyncio.run(_async_main(args))
        else:
            _sync_main(args)

    except KeyboardInterrupt:
        logger.info("Danmu crawler stopped by user")
        sys.exit(0)
    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
