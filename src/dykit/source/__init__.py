"""Douyu source-side resolution: room IDs and danmu WebSocket endpoints.

This is the only part of dykit that talks HTTP to douyu.com.

    from dykit.source import get_danmu_server, resolve_room_id

    room_id = resolve_room_id("longzhu")
    urls, real_room_id = get_danmu_server(room_id)

All functions are synchronous; wrap them in ``asyncio.to_thread`` when called
from async code.
"""

from __future__ import annotations

from .room import resolve_room_id
from .server import get_danmu_server

__all__ = [
    "get_danmu_server",
    "resolve_room_id",
]
