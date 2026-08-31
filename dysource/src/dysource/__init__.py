"""dysource - Douyu source-side resolution (room IDs and danmu servers).

This package resolves Douyu room IDs and discovers danmu WebSocket server
candidates. It is the only package that talks HTTP to douyu.com.

Quick Start:
    from dysource import get_danmu_server, resolve_room_id

    room_id = resolve_room_id("6657")
    urls, real_room_id = get_danmu_server(6657)

Note: all functions are synchronous; wrap them in `asyncio.to_thread`
when called from async code.
"""

from __future__ import annotations

from .discovery import DanmuServer, get_danmu_server, resolve_room_id

__all__ = [
    "resolve_room_id",
    "get_danmu_server",
    "DanmuServer",
]

__version__ = "0.1.0"
