from __future__ import annotations

from pathlib import Path

from dycommon.room import resolve_room

DEFAULT_DATA_DIR = "dycap-data"


def resolve_runtime(room: str, data: str | None) -> tuple[str, Path]:
    """Resolve the room ID and validate the --data path (file or directory)."""
    resolved_room = resolve_room(room)
    path = Path(data) if data else Path(DEFAULT_DATA_DIR)
    if not path.exists():
        raise ValueError(
            f"Data path not found: {path}. Pass --data <run.db file or directory of run files>."
        )
    return resolved_room, path
