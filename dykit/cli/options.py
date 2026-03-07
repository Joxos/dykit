from __future__ import annotations

from typing import Any

import click

from dykit.cli.common import TYPES_HELP


def dsn_option() -> Any:
    return click.option(
        "--dsn",
        envvar="DYTOOLS_DSN",
        required=False,
        help="PostgreSQL DSN (or set DYTOOLS_DSN env var)",
    )


def room_option(help_text: str = "Room ID") -> Any:
    return click.option("-r", "--room", required=True, help=help_text)


def with_types_option(example: str = "--with chatmsg,dgb,uenter") -> Any:
    return click.option(
        "--with",
        "msg_types_include",
        default=None,
        help=(
            "Include only these message types (comma-separated). "
            f"Available: {TYPES_HELP}. "
            f"Example: {example}"
        ),
    )


def without_types_option() -> Any:
    return click.option(
        "--without",
        "msg_types_exclude",
        default=None,
        help=(
            "Exclude these message types (comma-separated). "
            f"Available: {TYPES_HELP}. "
            "Example: --without uenter"
        ),
    )


def search_from_option() -> Any:
    return click.option("--from", "from_date", help="Start date (YYYY-MM-DD)")


def search_to_option() -> Any:
    return click.option("--to", "to_date", help="End date (YYYY-MM-DD)")


def search_last_option() -> Any:
    return click.option("--last", type=int, help="Show last (most recent) N messages")


def search_first_option() -> Any:
    return click.option("--first", type=int, help="Show first (earliest) N messages")


def username_option(short: bool = False) -> Any:
    if short:
        return click.option("--user", "username", help="Filter by username")
    return click.option("--username", help="Filter by username")


def user_id_option() -> Any:
    return click.option("--user-id", help="Filter by user_id")


def msg_type_option(default: str | None = None) -> Any:
    if default is None:
        return click.option(
            "--type",
            "msg_type",
            help="Filter by message type (chatmsg, loginres, loginreq, joingroup, mrkl, dgb, uenter, anbc, rnewbc, blab, upgrade, unknown)",
        )
    return click.option(
        "--type",
        "msg_type",
        default=default,
        help=f"Filter by message type (default: {default})",
    )


def output_option(help_text: str = "Output CSV file (optional)", required: bool = False) -> Any:
    return click.option("-o", "--output", help=help_text, required=required)


def validate_with_without(msg_types_include: str | None, msg_types_exclude: str | None) -> None:
    from dykit.cli.common import ensure_mutually_exclusive

    ensure_mutually_exclusive(
        msg_types_include,
        msg_types_exclude,
        "Cannot use --with and --without together. Use only one of them.",
    )


def validate_last_first(last: int | None, first: int | None) -> None:
    from dykit.cli.common import ensure_mutually_exclusive

    ensure_mutually_exclusive(
        last,
        first,
        "Cannot use --last and --first together. Use one window direction only.",
    )
