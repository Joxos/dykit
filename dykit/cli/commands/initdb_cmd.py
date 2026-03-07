from __future__ import annotations

import sys

import click
import psycopg

from dykit.cli.common import get_dsn
from dykit.cli.rich_output import err, out
from dykit.cli.services.dbio import init_database_schema


def register(cli: click.Group) -> None:
    @cli.command(name="init-db", short_help="Initialize database schema")
    @click.pass_context
    def _init_db(ctx: click.Context) -> None:
        dsn = get_dsn(ctx)
        try:
            init_database_schema(psycopg.connect, dsn)
            out("Database schema initialized successfully")
            out("Table: danmaku")
            out("Indexes: idx_danmaku_room_time, idx_danmaku_user_id, idx_danmaku_msg_type")
        except psycopg.Error as e:
            err(f"Error: Database initialization failed: {e}")
            sys.exit(1)

    _registered = _init_db
