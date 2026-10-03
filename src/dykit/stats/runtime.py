"""Shared entry-point plumbing for the stats CLI."""

from __future__ import annotations

from pathlib import Path

from ..schema import DEFAULT_RUN_DIR
from ..source import resolve_room_id


def resolve_runtime(room: str, data: str | None) -> tuple[str, Path]:
    """Resolve the room ID and validate the --data path (file or directory)."""
    resolved_room = str(resolve_room_id(room))
    path = Path(data) if data else Path(DEFAULT_RUN_DIR)
    if not path.exists():
        raise ValueError(
            f"Data path not found: {path}. Pass --data <run.db file or directory of run files>."
        )
    return resolved_room, path
