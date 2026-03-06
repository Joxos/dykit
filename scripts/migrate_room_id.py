#!/usr/bin/env python3
"""Migrate room_id from compound format (short:real) to real ID only.

This script updates all room_id values in the danmaku table from the old
compound format "SHORT:REAL" (e.g., "6657:6979222") to just the real ID
part (e.g., "6979222").

Usage:
    python scripts/migrate_room_id.py [--dsn DSN] [--dry-run]

Environment:
    DYTOOLS_DSN: PostgreSQL connection string (if --dsn not provided)

Examples:
    # Dry run (show what would be changed)
    python scripts/migrate_room_id.py --dry-run

    # Actually perform migration
    python scripts/migrate_room_id.py

    # With explicit DSN
    python scripts/migrate_room_id.py --dsn "postgresql://user:pass@localhost/db"
"""

from __future__ import annotations

import argparse
import os
import re
import sys

import psycopg

DOC_TEXT = __doc__ or ""


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Migrate room_id from SHORT:REAL format to REAL only",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=DOC_TEXT.split("Usage:", 1)[1] if "Usage:" in DOC_TEXT else "",
    )
    parser.add_argument(
        "--dsn",
        type=str,
        help="PostgreSQL DSN (default: from DYTOOLS_DSN env var)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be changed without modifying data",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show detailed progress information",
    )
    return parser.parse_args()


def get_room_id_stats(conn: psycopg.Connection) -> list[tuple[str, int]]:
    """Get statistics of room_id formats in database.

    Args:
        conn: Database connection.

    Returns:
        List of (room_id, count) tuples ordered by count descending.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT room_id, COUNT(*) as count
            FROM danmaku
            GROUP BY room_id
            ORDER BY count DESC
            """
        )
        return cur.fetchall()


def identify_compound_formats(stats: list[tuple[str, int]]) -> list[tuple[str, str, int]]:
    """Identify room_ids in compound format and extract real ID.

    Args:
        stats: List of (room_id, count) tuples.

    Returns:
        List of (old_format, new_format, count) for compound IDs only.
    """
    compound_pattern = re.compile(r"^(\d+):(\d+)$")
    migrations = []

    for room_id, count in stats:
        match = compound_pattern.match(room_id)
        if match:
            real_id = match.group(2)
            migrations.append((room_id, real_id, count))

    return migrations


def preview_migration(migrations: list[tuple[str, str, int]]) -> None:
    """Print preview of migration changes.

    Args:
        migrations: List of (old_format, new_format, count) tuples.
    """
    if not migrations:
        print("✅ No compound format room_ids found - migration not needed")
        return

    print("\n📋 Migration Preview:")
    print("=" * 70)
    print(f"{'Old Format':<20} {'New Format':<15} {'Records':>10}")
    print("-" * 70)

    total_records = 0
    for old_format, new_format, count in migrations:
        print(f"{old_format:<20} {new_format:<15} {count:>10,}")
        total_records += count

    print("-" * 70)
    print(f"{'TOTAL':<20} {'':<15} {total_records:>10,}")
    print("=" * 70)


def perform_migration(
    conn: psycopg.Connection, migrations: list[tuple[str, str, int]], verbose: bool
) -> int:
    """Execute migration of room_id values.

    Args:
        conn: Database connection.
        migrations: List of (old_format, new_format, count) tuples.
        verbose: Whether to show detailed progress.

    Returns:
        Total number of records updated.
    """
    total_updated = 0

    with conn.cursor() as cur:
        for old_format, new_format, expected_count in migrations:
            if verbose:
                print(f"Migrating {old_format} → {new_format}...", end=" ", flush=True)

            cur.execute(
                "UPDATE danmaku SET room_id = %s WHERE room_id = %s",
                [new_format, old_format],
            )
            updated = cur.rowcount
            total_updated += updated

            if verbose:
                status = "✅" if updated == expected_count else "⚠️"
                print(f"{status} {updated:,} records")

            if updated != expected_count:
                print(
                    f"  WARNING: Expected {expected_count:,} but updated {updated:,}",
                    file=sys.stderr,
                )

    conn.commit()
    return total_updated


def main() -> None:
    """Main entry point."""
    args = parse_args()

    # Get DSN
    dsn = args.dsn or os.environ.get("DYTOOLS_DSN")
    if not dsn:
        print(
            "Error: DSN not provided. Use --dsn flag or set DYTOOLS_DSN environment variable.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Connect to database
    try:
        conn = psycopg.connect(dsn)
    except psycopg.Error as e:
        print(f"Error: Failed to connect to database: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        # Get current statistics
        print("🔍 Analyzing room_id formats in database...")
        stats = get_room_id_stats(conn)

        if args.verbose:
            print(f"\nFound {len(stats)} unique room_id values")

        # Identify compound formats
        migrations = identify_compound_formats(stats)

        # Show preview
        preview_migration(migrations)

        if not migrations:
            return

        # Dry run or actual migration
        if args.dry_run:
            print("\n🔒 DRY RUN - No changes made")
            print("Run without --dry-run to perform migration")
        else:
            print("\n⚙️  Performing migration...")
            total = perform_migration(conn, migrations, args.verbose)
            print(f"\n✅ Migration complete: {total:,} records updated")

            # Verify
            print("\n🔍 Verifying migration...")
            new_stats = get_room_id_stats(conn)
            remaining = identify_compound_formats(new_stats)

            if remaining:
                print(
                    f"⚠️  WARNING: {len(remaining)} compound formats still remain",
                    file=sys.stderr,
                )
            else:
                print("✅ Verification passed: No compound formats remaining")

    except psycopg.Error as e:
        print(f"Error: Database operation failed: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
