"""CLI interface for Douyu Danmu Toolkit with PostgreSQL-first design.

This module provides a Click-based command-line interface for the Douyu Danmu
toolkit. All data operations are PostgreSQL-first, with CSV support via
import/export commands.

Commands:
    collect:   Start async collector and write to PostgreSQL
    rank:      Rank users by message frequency
    prune:     Remove duplicate records from database
    compact:   Find most frequent unique messages
    cluster:   Cluster similar messages by semantic similarity
    import:    Batch import CSV to PostgreSQL
    export:    Export PostgreSQL to CSV
    init-db:   Initialize database schema

Global Options:
    --dsn TEXT:  PostgreSQL DSN (required, or set DYTOOLS_DSN env var)

Usage Examples:
    # Start collection
    dytools --dsn postgresql://user:pass@localhost/douyu collect -r 6657

    # Or use environment variable
    export DYTOOLS_DSN="postgresql://user:pass@localhost/douyu"
    dytools collect -r 6657

    # Rank users in room
    dytools rank -r 6657 --top 20

    # Initialize database
    dytools init-db
"""

from __future__ import annotations

import asyncio
import csv
import sys
from datetime import datetime
from pathlib import Path

import click
import psycopg

from dytools.collectors import AsyncCollector
from dytools.log import logger
from dytools.storage import PostgreSQLStorage
from dytools.tools import cluster, compact, prune, rank


@click.group()
@click.option(
    "--dsn",
    envvar="DYTOOLS_DSN",
    required=True,
    help="PostgreSQL DSN (or set DYTOOLS_DSN env var)",
)
@click.pass_context
def cli(ctx, dsn):
    """dytools - Douyu danmu collection and analysis toolkit.

    PostgreSQL-first design for collecting and analyzing Douyu live stream
    chat messages. Use --dsn or DYTOOLS_DSN environment variable for database
    connection.
    """
    ctx.ensure_object(dict)
    ctx.obj["dsn"] = dsn


@cli.command()
@click.option("-r", "--room", required=True, help="Room ID")
@click.option("-v", "--verbose", is_flag=True, help="Enable debug logging")
@click.pass_context
def collect(ctx, room, verbose):
    """Start async collector and write to PostgreSQL.

    Connects to Douyu live stream room and collects chat messages, gifts,
    and other events in real-time. All data is written to PostgreSQL database.
    Press Ctrl+C to stop gracefully.
    """
    dsn = ctx.obj["dsn"]

    async def run_collector():
        try:
            with PostgreSQLStorage(dsn=dsn) as storage:
                collector = AsyncCollector(room, storage)
                logger.info(f"Starting async collection from room {room} (storage: PostgreSQL)")
                try:
                    await collector.connect()
                except KeyboardInterrupt:
                    logger.info("Interrupted by user")
                    await collector.stop()
        except psycopg.Error as e:
            logger.error(f"Database error: {e}")
            sys.exit(1)
        except Exception as e:
            logger.error(f"Error during collection: {e}", exc_info=verbose)
            raise

    try:
        asyncio.run(run_collector())
    except KeyboardInterrupt:
        logger.info("Danmu crawler stopped by user")
        sys.exit(0)


@cli.command()
@click.option("-r", "--room", required=True, help="Room ID")
@click.option("--top", default=10, help="Top N results (default: 10)")
@click.option("--type", "msg_type", default="chatmsg", help="Message type (default: chatmsg)")
@click.option("--days", type=int, help="Days to look back (default: all time)")
@click.pass_context
def rank_cmd(ctx, room, top, msg_type, days):
    """Rank users by message frequency.

    Analyzes PostgreSQL database and shows which users send the most messages
    in the specified room. Results are displayed as a formatted table.
    """
    dsn = ctx.obj["dsn"]

    try:
        results = rank.rank(dsn, room, top, msg_type, days)

        if not results:
            click.echo(f"No {msg_type} messages found for room {room}")
            return

        # Terminal output
        click.echo(f"\n=== User Ranking (Top {len(results)}) ===")
        click.echo(f"Room: {room}, Type: {msg_type}")
        if days:
            click.echo(f"Time range: last {days} days")
        click.echo(f"\n{'Rank':<6}{'Count':<8}{'Username'}")
        click.echo(f"{'────':<6}{'─────':<8}{'────────────────────'}")

        for rank_num, item in enumerate(results, start=1):
            click.echo(f"{rank_num:<6}{item['count']:<8}{item['username']}")

    except psycopg.Error as e:
        click.echo(f"Error: Database query failed: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.option("-r", "--room", required=True, help="Room ID")
@click.pass_context
def prune_cmd(ctx, room):
    """Remove duplicate records from database.

    Identifies and removes duplicate danmaku messages based on
    (timestamp, username, content, user_id) key. Reports number of
    duplicates removed.
    """
    dsn = ctx.obj["dsn"]

    try:
        removed_count = prune.prune(dsn, room)
        click.echo(f"Removed {removed_count} duplicate records from room {room}")

    except psycopg.Error as e:
        click.echo(f"Error: Database operation failed: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.option("-r", "--room", required=True, help="Room ID")
@click.option("--limit", default=10, help="Top N unique messages (default: 10)")
@click.pass_context
def compact_cmd(ctx, room, limit):
    """Find most frequent unique messages.

    Analyzes database and shows the most frequently repeated messages
    in the specified room, along with occurrence counts and timestamps.
    """
    dsn = ctx.obj["dsn"]

    try:
        results = compact.compact(dsn, room, limit)

        if not results:
            click.echo(f"No repeated messages found in room {room}")
            return

        # Terminal output
        click.echo(f"\n=== Repeated Messages (Top {len(results)}) ===")
        click.echo(f"Room: {room}\n")
        click.echo(f"{'Count':<8}{'Content':<50}{'First Seen':<20}{'Last Seen'}")
        click.echo(f"{'─────':<8}{'───────':<50}{'──────────':<20}{'─────────'}")

        for item in results:
            content_preview = (
                item["content"][:47] + "..." if len(item["content"]) > 50 else item["content"]
            )
            first = item["first_seen"].strftime("%Y-%m-%d %H:%M:%S")
            last = item["last_seen"].strftime("%Y-%m-%d %H:%M:%S")
            click.echo(f"{item['count']:<8}{content_preview:<50}{first:<20}{last}")

    except psycopg.Error as e:
        click.echo(f"Error: Database query failed: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.option("-r", "--room", required=True, help="Room ID")
@click.option("--threshold", default=0.6, type=float, help="Similarity threshold (default: 0.6)")
@click.option("--limit", default=1000, type=int, help="Max messages to analyze (default: 1000)")
@click.option("-o", "--output", help="Output CSV file (optional)")
@click.pass_context
def cluster_cmd(ctx, room, threshold, limit, output):
    """Cluster similar messages by semantic similarity.

    Groups similar (but not identical) messages together using text similarity
    algorithms. Useful for identifying spam patterns and coordinated messages.
    """
    dsn = ctx.obj["dsn"]

    try:
        # Query database and cluster
        all_clusters = cluster.cluster(dsn, room, threshold, "chatmsg", limit)

        if not all_clusters:
            click.echo(f"No messages found in room {room}")
            return

        # Calculate total unique messages from all clusters
        total_unique = sum(len(c) for c in all_clusters)

        # Filter clusters with 2+ variants
        multi_clusters = [c for c in all_clusters if len(c) >= 2]

        # Sort by total count
        multi_clusters.sort(key=lambda c: sum(cnt for _, cnt in c), reverse=True)

        if not multi_clusters:
            click.echo(f"No clusters found with threshold {threshold}")
            return

        # Terminal output
        click.echo(f"\n=== Clusters (threshold={threshold:.2f}, {total_unique} unique msgs) ===")
        click.echo(f"Found {len(multi_clusters)} clusters with 2+ variants\n")

        for idx, clust in enumerate(multi_clusters, start=1):
            total = sum(cnt for _, cnt in clust)
            variants = len(clust)
            click.echo(f"─── Cluster {idx} ({variants} variants, {total} total) ───")
            max_cnt_width = len(str(clust[0][1]))
            for content, cnt in clust:
                display = content if len(content) <= 60 else content[:57] + "..."
                click.echo(f"  [{cnt:>{max_cnt_width}}x] {display}")
            click.echo()

        # CSV output
        if output:
            import difflib

            with open(output, "w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["cluster_id", "variant_rank", "count", "content", "similarity"])
                for cluster_id, clust in enumerate(multi_clusters, start=1):
                    top_content = clust[0][0]
                    for variant_rank, (content, count) in enumerate(clust, start=1):
                        if variant_rank == 1:
                            sim = 1.0
                        else:
                            sim = round(
                                difflib.SequenceMatcher(None, top_content, content).ratio(), 6
                            )
                        writer.writerow([cluster_id, variant_rank, count, content, sim])
            click.echo(f"Cluster data saved to {output}")

    except psycopg.Error as e:
        click.echo(f"Error: Database query failed: {e}", err=True)
        sys.exit(1)


@cli.command("import")
@click.argument("file", type=click.Path(exists=True))
@click.option("-r", "--room", required=True, help="Target room ID for imported data")
@click.pass_context
def import_csv(ctx, file, room):
    """Batch import CSV to PostgreSQL.

    Imports danmaku messages from CSV file into PostgreSQL database.
    CSV format: timestamp, username, content, user_level, user_id, room_id, msg_type, extra
    """
    dsn = ctx.obj["dsn"]

    try:
        with psycopg.connect(dsn) as conn:
            with conn.cursor() as cur:
                with open(file, "r", encoding="utf-8") as f:
                    reader = csv.reader(f)
                    header = next(reader, None)

                    if header is None:
                        click.echo("Error: Empty CSV file", err=True)
                        sys.exit(1)

                    count = 0
                    for row in reader:
                        if len(row) < 7:
                            continue

                        timestamp = row[0]
                        username = row[1]
                        content = row[2]
                        user_level = int(row[3]) if row[3] else None
                        user_id = row[4]
                        # Use target room_id from CLI arg (override CSV)
                        msg_type = row[6]

                        # Insert into database
                        insert_query = """
                            INSERT INTO danmaku (
                                timestamp, room_id, msg_type, user_id, username, content, user_level
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """
                        cur.execute(
                            insert_query,
                            [timestamp, room, msg_type, user_id, username, content, user_level],
                        )
                        count += 1

                    conn.commit()
                    click.echo(f"Imported {count} records from {file} to room {room}")

    except psycopg.Error as e:
        click.echo(f"Error: Database import failed: {e}", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.option("-r", "--room", required=True, help="Room ID")
@click.option("-o", "--output", required=True, help="Output CSV file")
@click.pass_context
def export(ctx, room, output):
    """Export PostgreSQL to CSV.

    Exports all danmaku messages for specified room from PostgreSQL to CSV file.
    Output format: timestamp, username, content, user_level, user_id, room_id, msg_type, extra
    """
    dsn = ctx.obj["dsn"]

    try:
        with psycopg.connect(dsn) as conn:
            with conn.cursor() as cur:
                query = """
                    SELECT timestamp, username, content, user_level, user_id, room_id, msg_type
                    FROM danmaku
                    WHERE room_id = %s
                    ORDER BY timestamp
                """
                cur.execute(query, [room])
                results = cur.fetchall()

                if not results:
                    click.echo(f"No data found for room {room}")
                    return

                with open(output, "w", encoding="utf-8", newline="") as f:
                    writer = csv.writer(f)
                    writer.writerow(
                        [
                            "timestamp",
                            "username",
                            "content",
                            "user_level",
                            "user_id",
                            "room_id",
                            "msg_type",
                            "extra",
                        ]
                    )
                    for row in results:
                        # Append empty extra field
                        writer.writerow(list(row) + [""])

                click.echo(f"Exported {len(results)} records from room {room} to {output}")

    except psycopg.Error as e:
        click.echo(f"Error: Database export failed: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.pass_context
def init_db(ctx):
    """Initialize database schema.

    Creates the danmaku table and indexes in PostgreSQL database.
    Safe to run multiple times (uses CREATE TABLE IF NOT EXISTS).
    """
    dsn = ctx.obj["dsn"]

    try:
        with psycopg.connect(dsn) as conn:
            with conn.cursor() as cur:
                # Create unified danmaku table
                create_table_query = """
                    CREATE TABLE IF NOT EXISTS danmaku (
                        id          SERIAL PRIMARY KEY,
                        timestamp   TIMESTAMP NOT NULL,
                        room_id     TEXT NOT NULL,
                        msg_type    TEXT NOT NULL,
                        user_id     TEXT,
                        username    TEXT,
                        content     TEXT,
                        user_level  INTEGER,
                        gift_id     TEXT,
                        gift_count  INTEGER,
                        gift_name   TEXT,
                        badge_level INTEGER,
                        badge_name  TEXT,
                        noble_level INTEGER,
                        avatar_url  TEXT
                    );

                    CREATE INDEX IF NOT EXISTS idx_danmaku_room_time 
                    ON danmaku(room_id, timestamp DESC);

                    CREATE INDEX IF NOT EXISTS idx_danmaku_user_id 
                    ON danmaku(user_id);

                    CREATE INDEX IF NOT EXISTS idx_danmaku_msg_type 
                    ON danmaku(msg_type);
                """
                cur.execute(create_table_query)
                conn.commit()

                click.echo("Database schema initialized successfully")
                click.echo("Table: danmaku")
                click.echo(
                    "Indexes: idx_danmaku_room_time, idx_danmaku_user_id, idx_danmaku_msg_type"
                )

    except psycopg.Error as e:
        click.echo(f"Error: Database initialization failed: {e}", err=True)
        sys.exit(1)


def main() -> None:
    """Main entry point for the CLI."""
    try:
        cli()
    except click.exceptions.MissingParameter as e:
        if "dsn" in str(e).lower():
            click.echo(
                "Error: Database DSN required. Use --dsn or set DYTOOLS_DSN environment variable.",
                err=True,
            )
            sys.exit(1)
        raise


if __name__ == "__main__":
    main()
