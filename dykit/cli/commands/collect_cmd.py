from __future__ import annotations

import asyncio
import sys

import click
import psycopg
from psycopg import conninfo as psycopg_conninfo

from dykit.cli.common import get_dsn, to_int, to_str
from dykit.cli.options import (
    room_option,
    validate_with_without,
    with_types_option,
    without_types_option,
)
from dykit.log import logger
from dykit.storage import PostgreSQLStorage

AsyncCollector = None


def register(cli: click.Group) -> None:
    @cli.command(name="collect", short_help="Collect danmu messages from a room")
    @room_option()
    @click.option("-v", "--verbose", is_flag=True, help="Enable debug-level logging")
    @with_types_option()
    @without_types_option()
    @click.pass_context
    def collect(
        ctx: click.Context,
        room: str,
        verbose: bool,
        msg_types_include: str | None,
        msg_types_exclude: str | None,
    ) -> None:
        dsn = get_dsn(ctx)
        validate_with_without(msg_types_include, msg_types_exclude)

        type_filter = (
            [t.strip() for t in msg_types_include.split(",")] if msg_types_include else None
        )
        type_exclude = (
            [t.strip() for t in msg_types_exclude.split(",")] if msg_types_exclude else None
        )

        async def run_collector() -> None:
            collector_cls = AsyncCollector
            if collector_cls is None:
                from dykit.collectors import AsyncCollector as collector_cls

            try:
                conn_params = psycopg_conninfo.conninfo_to_dict(dsn)
                storage = await PostgreSQLStorage.create(
                    room_id=room,
                    host=to_str(conn_params.get("host"), "localhost"),
                    port=to_int(conn_params.get("port"), 5432),
                    database=to_str(conn_params.get("dbname"), ""),
                    user=to_str(conn_params.get("user"), ""),
                    password=to_str(conn_params.get("password"), ""),
                )
                async with storage:
                    collector = collector_cls(
                        room,
                        storage,
                        type_filter=type_filter,
                        type_exclude=type_exclude,
                    )
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

    _registered = collect
