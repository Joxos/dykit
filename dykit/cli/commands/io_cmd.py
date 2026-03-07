from __future__ import annotations

import sys

import click
import psycopg

from dykit.cli.common import get_dsn, resolve_room_for_query
from dykit.cli.options import output_option, room_option
from dykit.cli.rich_output import err, out
from dykit.cli.services.dbio import export_room_to_csv, import_csv_to_db


def register(cli: click.Group) -> None:
    @cli.command("import", short_help="Import CSV data into database")
    @click.argument("file", type=click.Path(exists=True))
    @room_option(help_text="Target room ID")
    @click.pass_context
    def _import_csv(ctx: click.Context, file: str, room: str) -> None:
        dsn = get_dsn(ctx)
        try:
            count = import_csv_to_db(psycopg.connect, dsn, file, room)
            out(f"Imported {count} records from {file} to room {room}")
        except ValueError as e:
            err(f"Error: {e}")
            sys.exit(1)
        except psycopg.Error as e:
            err(f"Error: Database import failed: {e}")
            sys.exit(1)
        except Exception as e:
            err(f"Error: {e}")
            sys.exit(1)

    @cli.command(name="export", short_help="Export room data to CSV")
    @room_option()
    @output_option(help_text="Output CSV file", required=True)
    @click.pass_context
    def _export(ctx: click.Context, room: str, output: str) -> None:
        dsn = get_dsn(ctx)
        try:
            resolved_room = resolve_room_for_query(room)
            count = export_room_to_csv(psycopg.connect, dsn, resolved_room, output)
            if not count:
                out(f"No data found for room {room}")
                return
            out(f"Exported {count} records from room {room} to {output}")
        except psycopg.Error as e:
            err(f"Error: Database export failed: {e}")
            sys.exit(1)

    _registered = (_import_csv, _export)
