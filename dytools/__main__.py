"""CLI interface for Douyu Danmu Toolkit with PostgreSQL-first design.

This module provides a Click-based command-line interface for the Douyu Danmu
toolkit. All data operations are PostgreSQL-first, with CSV support via
import/export commands.

Commands:
    collect:   Start async collector and write to PostgreSQL

    rank:      Rank users by message frequency or content by frequency

    prune:     Remove duplicate records from database

    cluster:   Cluster similar messages by semantic similarity
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
import json
import sys
from typing import Any


import click
import psycopg
from psycopg import conninfo as psycopg_conninfo

from dytools.collectors import AsyncCollector
from dytools.log import logger
from dytools.storage import PostgreSQLStorage
from dytools.tools import cluster, prune, rank, search


@click.group()
@click.option(
    "--dsn",
    envvar="DYTOOLS_DSN",
    required=True,
    help="PostgreSQL DSN (or set DYTOOLS_DSN env var)",
)
@click.pass_context
def cli(ctx: click.Context, dsn: str) -> None:
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
def collect(ctx: click.Context, room: str, verbose: bool) -> None:
    """Start async collector and write to PostgreSQL.

    Connects to Douyu live stream room and collects chat messages, gifts,
    and other events in real-time. All data is written to PostgreSQL database.
    Press Ctrl+C to stop gracefully.
    """
    dsn = ctx.obj["dsn"]

    async def run_collector():
        try:
            # Parse DSN to extract connection parameters
            conn_params = psycopg_conninfo.conninfo_to_dict(dsn)
            storage = PostgreSQLStorage(
                room_id=int(room),
                host=conn_params.get("host", "localhost"),
                port=int(conn_params.get("port", 5432)),
                database=conn_params.get("dbname", ""),  # Note: DSN has 'dbname', psycopg expects 'database'
                user=conn_params.get("user", ""),
                password=conn_params.get("password", ""),
            )
            with storage:
                collector = AsyncCollector(int(room), storage)
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

@click.option("-u", "--user", is_flag=True, help="Rank by username (default)")

@click.option("-c", "--content", is_flag=True, help="Rank by message content")
@click.pass_context
def rank_cmd(ctx: click.Context, room: str, top: int, msg_type: str, days: int | None, user: bool, content: bool) -> None:

    """Rank users or messages by frequency.



    Analyzes PostgreSQL database and shows either:

    - Top users by message count (default: --user/-u)

    - Top repeated message content (--content/-c)

    Results are displayed as a formatted table.

    """
    dsn = ctx.obj["dsn"]



    # Validate mutually exclusive flags

    if user and content:

        click.echo("Error: Cannot use both --user and --content", err=True)

        sys.exit(1)



    # Default to user mode if neither specified

    mode = "content" if content else "user"



    try:

        results = rank.rank(dsn, room, top, msg_type, days, mode=mode)



        if not results:

            click.echo(f"No {msg_type} messages found for room {room}")

            return



        # Terminal output

        if mode == "user":

            click.echo(f"\n=== User Ranking (Top {len(results)}) ===")

            click.echo(f"Room: {room}, Type: {msg_type}")

            if days:

                click.echo(f"Time range: last {days} days")

            click.echo(f"\n{'Rank':<6}{'Count':<8}{'Username'}")

            click.echo(f"{'────':<6}{'─────':<8}{'────────────────────'}")



            for rank_num, item in enumerate(results, start=1):

                click.echo(f"{rank_num:<6}{item['count']:<8}{item['username']}")

        else:

            # Content mode

            click.echo(f"\n=== Repeated Messages (Top {len(results)}) ===")

            click.echo(f"Room: {room}")

            if days:

                click.echo(f"Time range: last {days} days")

            click.echo(f"\n{'Count':<8}{'Content':<50}{'First Seen':<20}{'Last Seen'}")

            click.echo(f"{'─────':<8}{'───────':<50}{'──────────':<20}{'─────────'}")



            for item in results:

                content: Any = item["content"]
                content_str = str(content) if content is not None else ""
                content_preview = (
                    content_str[:47] + "..." if len(content_str) > 50 else content_str
                )
                first_seen: Any = item["first_seen"]
                last_seen: Any = item["last_seen"]
                first = first_seen.strftime("%Y-%m-%d %H:%M:%S") if hasattr(first_seen, 'strftime') else str(first_seen)
                last = last_seen.strftime("%Y-%m-%d %H:%M:%S") if hasattr(last_seen, 'strftime') else str(last_seen)
                click.echo(f"{item['count']:<8}{content_preview:<50}{first:<20}{last}")



    except psycopg.Error as e:

        click.echo(f"Error: Database query failed: {e}", err=True)

        sys.exit(1)

@cli.command()
@click.option("-r", "--room", required=True, help="Room ID")
@click.pass_context
def prune_cmd(ctx: click.Context, room: str) -> None:
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
@click.option("--threshold", default=0.6, type=float, help="Similarity threshold (default: 0.6)")
@click.option("--limit", default=1000, type=int, help="Max messages to analyze (default: 1000)")
@click.option("-o", "--output", help="Output CSV file (optional)")
@click.pass_context
def cluster_cmd(ctx: click.Context, room: str, threshold: float, limit: int, output: str | None) -> None:
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


@cli.command()
@click.option("-r", "--room", required=True, help="Room ID")
@click.option("-q", "--query", help="Keyword to search (case-insensitive)")
@click.option("-u", "--user", help="Filter by username")
@click.option("--user-id", help="Filter by user_id")
@click.option("--type", "msg_type", help="Filter by message type")
@click.option("--from", "from_date", help="Start date (YYYY-MM-DD)")
@click.option("--to", "to_date", help="End date (YYYY-MM-DD)")
@click.option("--last", type=int, help="Show last (most recent) N messages")
@click.option("--first", type=int, help="Show first (earliest) N messages")
@click.option("-o", "--output", help="Export to CSV file (optional)")
@click.pass_context
def search_cmd(ctx: click.Context, room: str, query: str | None, user: str | None, user_id: str | None, msg_type: str | None, from_date: str | None, to_date: str | None, last: int | None, first: int | None, output: str | None) -> None:
    """Search danmaku messages with flexible filtering.

    Supports keyword search (ILIKE), username/user_id filtering, message type
    filtering, and time range queries. Use --last for most recent messages or
    --first for earliest messages (mutually exclusive, defaults to --last 100).
    Results can be displayed in terminal or exported to CSV.
    """
    dsn = ctx.obj["dsn"]

    # Validate mutual exclusivity
    if last and first:
        click.echo("Error: Cannot use both --last and --first", err=True)
        sys.exit(1)

    try:
        results = search.search(
            dsn,
            room,
            query=query,
            username=user,
            user_id=user_id,
            msg_type=msg_type,
            from_date=from_date,
            to_date=to_date,
            last=last,
            first=first,
        )

        if not results:
            click.echo(f"No messages found for room {room}")
            return

        # Terminal output
        search_desc = []
        if query:
            search_desc.append(f'query="{query}"')
        if user:
            search_desc.append(f'user="{user}"')
        if user_id:
            search_desc.append(f'user_id="{user_id}"')
        if msg_type:
            search_desc.append(f'type="{msg_type}"')
        search_str = ", ".join(search_desc) if search_desc else "all"

        # Determine sort mode description
        if last:
            sort_mode = f"Last {last}"
        elif first:
            sort_mode = f"First {first}"
        else:
            sort_mode = "Last 100 (default)"

        click.echo(f"\n=== Search Results ({len(results)} found) ===")
        click.echo(f"Room: {room}, Filter: {search_str}, Sort: {sort_mode}")
        click.echo()
        click.echo(f"{'Timestamp':<20}{'Username':<16}{'Content'}")
        click.echo(f"{'─' * 20:<20}{'─' * 16:<16}{'─' * 50}")

        for item in results:
            ts = item["timestamp"].strftime("%Y-%m-%d %H:%M:%S") if hasattr(item["timestamp"], 'strftime') else str(item["timestamp"])[:19]
            username_str = item["username"] or "[unknown]"
            content_str = item["content"] or ""
            content_preview = content_str[:47] + "..." if len(content_str) > 50 else content_str
            click.echo(f"{ts:<20}{username_str:<16}{content_preview}")

        # CSV output
        if output:
            with open(output, "w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["timestamp", "username", "content", "user_level", "user_id", "room_id", "msg_type"])
                for row in results:
                    writer.writerow(
                        [
                            row["timestamp"],
                            row["username"],
                            row["content"],
                            row["user_level"],
                            row["user_id"],
                            row["room_id"],
                            row["msg_type"],
                        ]
                    )
            click.echo(f"\nResults exported to {output}")

    except psycopg.Error as e:
        click.echo(f"Error: Database query failed: {e}", err=True)
        sys.exit(1)


@cli.command("import")
@click.argument("file", type=click.Path(exists=True))
@click.option("-r", "--room", required=True, help="Target room ID for imported data")
@click.pass_context
def import_csv(ctx: click.Context, file: str, room: str) -> None:
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
                        # row[5] = room_id — overridden by CLI --room arg
                        msg_type = row[6]

                        # Parse extra JSON field (column 7, optional)
                        extra_str = row[7] if len(row) > 7 else ""
                        extra: dict[str, str] = {}
                        if extra_str:
                            try:
                                extra = json.loads(extra_str)
                            except (json.JSONDecodeError, ValueError):
                                pass

                        # Map extra fields to dedicated columns
                        gift_id = extra.get("gfid")
                        gfcnt = extra.get("gfcnt")
                        gift_count = int(gfcnt) if gfcnt and str(gfcnt).isdigit() else None
                        gift_name = extra.get("gfn")
                        bl = extra.get("bl")
                        badge_level = int(bl) if bl and str(bl).isdigit() else None
                        badge_name = extra.get("bnn")
                        nl = extra.get("nl")
                        noble_level = int(nl) if nl and str(nl).isdigit() else None
                        avatar_url = extra.get("ic")

                        # Insert into database with all 14 data columns
                        insert_query = """
                            INSERT INTO danmaku (
                                timestamp, room_id, msg_type, user_id, username, content, user_level,
                                gift_id, gift_count, gift_name, badge_level, badge_name, noble_level, avatar_url
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """
                        cur.execute(
                            insert_query,
                            [timestamp, room, msg_type, user_id, username, content, user_level,
                             gift_id, gift_count, gift_name, badge_level, badge_name, noble_level, avatar_url],
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
def export(ctx: click.Context, room: str, output: str) -> None:
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
def init_db(ctx: click.Context) -> None:
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
