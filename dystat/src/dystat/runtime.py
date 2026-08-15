from __future__ import annotations

from dycommon.env import get_dsn
from dycommon.room import resolve_room


def resolve_runtime(room: str, dsn: str | None) -> tuple[str, str]:
    resolved_dsn = dsn or get_dsn()
    if not resolved_dsn:
        raise ValueError("DSN required. Set DYKIT_DSN or pass --dsn")

    resolved_room = resolve_room(room)
    return resolved_room, resolved_dsn
