from __future__ import annotations

import shutil

import click

from dykit.cli.common import fail, get_dsn_or
from dykit.cli.options import (
    validate_with_without,
    with_types_option,
    without_types_option,
)
from dykit.cli.rich_output import out
from dykit.service import ServiceManager


def register(cli: click.Group) -> None:
    @cli.group(name="service", short_help="Manage systemd user services")
    @click.pass_context
    def service(ctx: click.Context) -> None:
        _ = ctx
        if click.get_current_context().resilient_parsing:
            return
        if not shutil.which("systemctl"):
            out(
                "[bold red]systemd user services not available. Ensure systemd is installed and running.[/bold red]"
            )
            raise SystemExit(1)

    @service.command(name="create", short_help="Create a user service")
    @click.argument("spec")
    @click.option("--dsn", envvar="DYTOOLS_DSN", help="PostgreSQL DSN (or DYTOOLS_DSN env var)")
    @with_types_option(example="--with chatmsg,dgb")
    @without_types_option()
    @click.option("-v", "--verbose", is_flag=True, help="Enable debug logging")
    @click.pass_context
    def _create_service(
        ctx: click.Context,
        spec: str,
        dsn: str | None,
        msg_types_include: str | None,
        msg_types_exclude: str | None,
        verbose: bool,
    ) -> None:
        validate_with_without(msg_types_include, msg_types_exclude)

        resolved_dsn = get_dsn_or(ctx, dsn)
        sm = ServiceManager()
        try:
            sm.create(
                spec,
                resolved_dsn,
                with_types=msg_types_include,
                without_types=msg_types_exclude,
                verbose=verbose,
            )
        except ValueError as e:
            fail(str(e))
        except RuntimeError as e:
            fail(str(e))

    @service.command(name="list", short_help="List managed services")
    def _list_services() -> None:
        sm = ServiceManager()
        services = sm.list()

        if not services:
            out("No dykit services found.")
            return

        out(f"{'NAME':<30} {'STATUS':<12} {'ROOM_ID':<10}")
        out("-" * 54)
        for svc in services:
            out(f"{svc['name']:<30} {svc['status']:<12} {svc['room_id']:<10}")

    @service.command(name="start", short_help="Start a service")
    @click.argument("service_name")
    def _start_service(service_name: str) -> None:
        sm = ServiceManager()
        try:
            sm.start(service_name)
        except RuntimeError as e:
            fail(str(e))

    @service.command(name="stop", short_help="Stop a service")
    @click.argument("service_name")
    def _stop_service(service_name: str) -> None:
        sm = ServiceManager()
        try:
            sm.stop(service_name)
        except RuntimeError as e:
            fail(str(e))

    @service.command(name="restart", short_help="Restart a service")
    @click.argument("service_name")
    def _restart_service(service_name: str) -> None:
        sm = ServiceManager()
        try:
            sm.restart(service_name)
        except RuntimeError as e:
            fail(str(e))

    @service.command(name="reload", short_help="Reload service config")
    @click.argument("service_name")
    def _reload_service(service_name: str) -> None:
        sm = ServiceManager()
        try:
            sm.reload(service_name)
        except RuntimeError as e:
            fail(str(e))

    @service.command(name="status", short_help="Show service status")
    @click.argument("service_name")
    def _status_service(service_name: str) -> None:
        sm = ServiceManager()
        try:
            output = sm.status(service_name)
            out(output)
        except RuntimeError as e:
            fail(str(e))

    @service.command(name="logs", short_help="Show service logs")
    @click.argument("service_name")
    @click.option("-n", "--lines", type=int, default=50, help="Show the last N log lines")
    def _logs_service(service_name: str, lines: int) -> None:
        sm = ServiceManager()
        try:
            output = sm.logs(service_name, lines)
            out(output)
        except RuntimeError as e:
            fail(str(e))

    @service.command(name="where", short_help="Show unit file path")
    @click.argument("service_name")
    def _where_service(service_name: str) -> None:
        sm = ServiceManager()
        try:
            path = sm.where(service_name)
            out(path)
        except FileNotFoundError as e:
            fail(str(e))

    @service.command(name="edit", short_help="Edit unit file")
    @click.argument("service_name")
    def _edit_service(service_name: str) -> None:
        sm = ServiceManager()
        try:
            sm.edit(service_name)
        except FileNotFoundError as e:
            fail(str(e))
        except RuntimeError as e:
            fail(str(e))

    @service.command(name="remove", short_help="Remove a service")
    @click.argument("service_name")
    def _remove_service(service_name: str) -> None:
        sm = ServiceManager()
        try:
            sm.remove(service_name)
        except FileNotFoundError as e:
            fail(str(e))
        except RuntimeError as e:
            fail(str(e))

    _registered = (
        _create_service,
        _list_services,
        _start_service,
        _stop_service,
        _restart_service,
        _reload_service,
        _status_service,
        _logs_service,
        _where_service,
        _edit_service,
        _remove_service,
    )
