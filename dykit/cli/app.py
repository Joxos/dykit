from __future__ import annotations

import click

from dykit.cli.commands import analysis_cmd, collect_cmd, initdb_cmd, io_cmd, service_cmd
from dykit.cli.options import dsn_option


@click.group()
@dsn_option()
@click.pass_context
def cli(ctx: click.Context, dsn: str | None) -> None:
    ctx.ensure_object(dict)
    ctx.obj["dsn"] = dsn


collect_cmd.register(cli)
analysis_cmd.register(cli)
io_cmd.register(cli)
initdb_cmd.register(cli)
service_cmd.register(cli)
