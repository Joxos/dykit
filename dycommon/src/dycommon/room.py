from __future__ import annotations

from dysource import resolve_room_id


def resolve_room(room: str) -> str:
    return str(resolve_room_id(room))
