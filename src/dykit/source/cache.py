"""Persistent cache of discovered danmu endpoints.

Restarting a collector means establishing a new WebSocket, and the slow part is
not the socket - it is discovery. ``resolve_room_id`` can walk three HTML/JSON
sources and ``get_danmu_server`` scrapes the room page again, each with its own
timeout and retry: worst case seconds, against ~100-300ms for a socket
handshake.

Writing the last successful result lets a starting collector connect
immediately and refresh in the background, which is what keeps a redeploy's
collection gap down to the handshake.

The cache is a hint, never a source of truth: a stale or unreadable cache just
means falling back to live discovery.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

logger: logging.Logger = logging.getLogger(__name__)

CACHE_VERSION = 1


@dataclass(frozen=True)
class EndpointCache:
    """Last known good endpoints for one room."""

    urls: tuple[str, ...]
    real_room_id: int
    version: int = CACHE_VERSION

    def to_json(self) -> str:
        return json.dumps(
            {"version": self.version, "urls": list(self.urls), "real_room_id": self.real_room_id}
        )

    @classmethod
    def from_json(cls, raw: str) -> EndpointCache | None:
        try:
            data: Any = json.loads(raw)
            if data.get("version") != CACHE_VERSION:
                return None
            urls: object = data["urls"]
            if not isinstance(urls, list) or not urls:
                return None
            known_urls: tuple[str, ...] = tuple(str(url) for url in cast("list[Any]", urls))
            return cls(urls=known_urls, real_room_id=int(data["real_room_id"]))
        except (ValueError, KeyError, TypeError):
            return None

    @property
    def is_usable(self) -> bool:
        return bool(self.urls) and self.real_room_id > 0


def cache_path(data_dir: Path, room_id: str) -> Path:
    """Where the cache for `room_id` lives (inside the data directory)."""
    return data_dir / ".endpoints" / f"{room_id}.json"


def load(data_dir: Path, room_id: str) -> EndpointCache | None:
    """Read the cached endpoints, or None if absent/unreadable/garbage."""
    path = cache_path(data_dir, room_id)
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    cache = EndpointCache.from_json(raw)
    if cache is None or not cache.is_usable:
        logger.debug("ignoring unusable endpoint cache at %s", path)
    return cache


def store(data_dir: Path, room_id: str, urls: list[str], real_room_id: int) -> None:
    """Record the endpoints a successful discovery just produced."""
    if not urls or real_room_id <= 0:
        return
    path = cache_path(data_dir, room_id)
    cache = EndpointCache(urls=tuple(urls), real_room_id=real_room_id)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(cache.to_json(), encoding="utf-8")
    except OSError as exc:  # a cache miss only costs us a slower start
        logger.debug("could not write endpoint cache %s: %s", path, exc)
