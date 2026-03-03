"""CLI interface for Douyu Danmu Crawler with async support and pluggable storage.

This module provides a command-line interface for the Douyu Danmu Crawler that supports:
- Multiple storage backends (CSV, console output, PostgreSQL database)
- Asynchronous collection mode (default)
- Configurable room ID, output file, and logging level
- Prune tool for merging and deduplicating CSV files

Usage Examples:
    # Collect danmu from room 6657 to CSV (default)
    python -m dycap

    # Collect from different room
    python -m dycap 123456

    # Use console output instead of CSV
    python -m dycap --storage console

    # Save to PostgreSQL with default connection parameters
    python -m dycap --storage postgres

    # Prune tool: auto-scan and merge CSVs by room_id
    python -m dycap prune

    # Prune tool: merge specific files
    python -m dycap prune file1.csv file2.csv --output merged.csv

CLI Arguments:
    ROOM_ID:        Douyu room ID to connect to (positional, default: 6657)
    --storage:      Storage backend type: "csv", "console", or "postgres" (default: csv)
    --output (-o):  CSV file path for csv storage (default: auto-generated from timestamp)
    --pg-host:      PostgreSQL host (default: localhost)
    --pg-port:      PostgreSQL port (default: 5432)
    --pg-database:  PostgreSQL database name (default: douyu_danmu)
    --pg-user:      PostgreSQL username (default: douyu)
    --pg-password:  PostgreSQL password (default: douyu6657)
    --verbose (-v): Enable debug logging (default: False)

Prune Command:
    python -m dycap prune [FILES...] [-o OUTPUT]
    Merge and deduplicate CSV capture files by room_id.

Exit Codes:
    0: Normal exit (Ctrl+C)
    1: Configuration error or runtime exception
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from dycap.collectors import AsyncCollector, SyncCollector
from dycap.log import logger
from dycap.storage import ConsoleStorage, CSVStorage, PostgreSQLStorage


def _preprocess_argv(argv: list[str]) -> list[str]:
    """Pre-process argv to handle positional room_id before subcommand parsing.

    When a numeric positional argument is provided before any subcommand,
    convert it to --room-id for argparse to handle correctly.

    Example:
        Input:  ['123456', '--storage', 'console']
        Output: ['--room-id', '123456', '--storage', 'console']
    """
    if not argv or argv[0] in ('prune', '-h', '--help', '-v', '--verbose'):
        return argv

    # Check if first arg looks like a room_id (numeric, not a flag)
    try:
        int(argv[0])
        # It's numeric - treat as room_id and convert to named argument
        result = argv.copy()
        result[0] = str(int(result[0]))  # Validate it's still valid
        result.insert(0, '--room-id')
        return result
    except (ValueError, IndexError):
        # Not numeric, leave argv as-is
        return argv

def _validate_args(args: argparse.Namespace) -> None:
    """Validate command-line arguments.

    Args:
        args: Parsed command-line arguments.

    Raises:
        ValueError: If arguments are invalid.
    """
    if args.storage not in ("csv", "console", "postgres"):
        raise ValueError(
            f"Invalid storage type: {args.storage}. Must be 'csv', 'console', or 'postgres'."
        )

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
        # Pass filepath (may be None for auto-generation) and room_id
        return CSVStorage(filepath=args.output, room_id=args.room_id)
    elif args.storage == "console":
        return ConsoleStorage(verbose=args.verbose)
    elif args.storage == "postgres":
        return PostgreSQLStorage(
            room_id=args.room_id,
            host=args.pg_host,
            port=args.pg_port,
            database=args.pg_database,
            user=args.pg_user,
            password=args.pg_password,
        )
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
            collector = AsyncCollector(args.room_id, storage, ws_url=args.ws_url)
            logger.info(
                f"Starting async collection from room {args.room_id} (storage: {args.storage})"
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
            collector = SyncCollector(args.room_id, storage, ws_url=args.ws_url)
            logger.info(
                f"Starting sync collection from room {args.room_id} (storage: {args.storage})"
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
  python -m dycap                           # Default: room 6657, CSV output
  python -m dycap 123456                    # Specific room
  python -m dycap --storage console         # Console output
  python -m dycap 6657 --output chat.csv -v # Verbose with custom file
  python -m dycap prune                     # Merge CSV files by room_id
  python -m dycap prune *.csv -o out.csv    # Merge specific files
""",
    )

    # Create subparsers for different commands
    subparsers = parser.add_subparsers(dest='command', help='Available commands')

    # Default command (capture) - when no subcommand specified
    # We'll add arguments to the main parser for backward compatibility

    parser.add_argument(
        "--room-id",
        type=int,
        dest="room_id",
        default=6657,
        help="Douyu room ID (default: %(default)s)",
    )


    parser.add_argument(
        "--storage",
        type=str,
        choices=["csv", "console", "postgres"],
        default="csv",
        help="Storage backend: csv, console, or postgres (default: %(default)s)",
    )

    parser.add_argument(
        "-o",
        "--output",
        type=str,
        default=None,
        help="CSV file path for csv storage (default: auto-generated from timestamp)",
    )

    parser.add_argument(
        "--pg-host",
        type=str,
        default="localhost",
        help="PostgreSQL host (default: %(default)s)",
    )

    parser.add_argument(
        "--pg-port",
        type=int,
        default=5432,
        help="PostgreSQL port (default: %(default)s)",
    )

    parser.add_argument(
        "--pg-database",
        type=str,
        default="douyu_danmu",
        help="PostgreSQL database name (default: %(default)s)",
    )

    parser.add_argument(
        "--pg-user",
        type=str,
        default="douyu",
        help="PostgreSQL username (default: %(default)s)",
    )

    parser.add_argument(
        "--pg-password",
        type=str,
        default="douyu6657",
        help="PostgreSQL password (default: %(default)s)",
    )

    parser.add_argument(
        "--ws-url",
        type=str,
        default=None,
        help="Manual WebSocket URL override (e.g., wss://trk-58-215-127-75.douyucdn.cn:17053/)",
    )


    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable debug logging",
    )

    # Prune subcommand
    prune_parser = subparsers.add_parser(
        'prune',
        help='Merge and deduplicate CSV files',
        description='Merge and deduplicate CSV capture files by room_id',
    )
    prune_parser.add_argument(
        'files',
        nargs='*',
        help='CSV files to merge (default: auto-scan current directory)',
    )
    prune_parser.add_argument(
        '-o',
        '--output',
        help='Output file path (single room_id mode only)',
    )

    # Parse arguments
    # Pre-process argv to convert positional room_id to --room-id
    processed_argv = _preprocess_argv(sys.argv[1:])
    args = parser.parse_args(processed_argv)


    # Setup logging
    # Loguru is pre-configured in dycap.log module

    try:
        # Validate arguments
        _validate_args(args)

        # Log startup
        if args.command == 'prune':
            # Run prune tool
            from dycap.tools.prune import run_prune
            run_prune(args)
        else:
            # Default: capture mode
            logger.info(
                f"Douyu Danmu Crawler started - "
                f"room_id={args.room_id}, "
                f"storage={args.storage}"
            )

            # Run async collector (sync mode removed)
            asyncio.run(_async_main(args))

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
