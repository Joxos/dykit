"""Danmu WebSocket server discovery.

Douyu load-balances danmu traffic over a small set of ``danmuproxy`` ports.
The room page usually names the port the room is currently pinned to; when it
does not, the known defaults are used. The collector walks this list in order,
so returning a couple of fallbacks is deliberate - the first entry is only a
hint.
"""

from __future__ import annotations

import logging
import re

from bs4 import BeautifulSoup

from .http import http_get
from .room import resolve_room_id

logger: logging.Logger = logging.getLogger(__name__)

DEFAULT_PORTS: tuple[int, ...] = (8506, 8505, 8502, 8504, 8501, 8508)

_PORT_PATTERN = re.compile(r"danmuproxy\.douyu\.com:(\d+)")


def get_danmu_server(
    room_id: int | str,
    timeout: float = 10.0,
    manual_url: str | None = None,
) -> tuple[list[str], int]:
    """Get candidate danmu WebSocket URLs for a room.

    Args:
        room_id: The Douyu room ID.
        timeout: HTTP request timeout in seconds.
        manual_url: If provided, this URL is returned immediately.

    Returns:
        Tuple of (candidate WebSocket URLs in preference order, resolved room ID).

    Example:
        >>> urls, room_id = get_danmu_server(6657)
        >>> urls[0]
        'wss://danmuproxy.douyu.com:8506/'
    """
    real_room_id = resolve_room_id(room_id, timeout=timeout)

    if manual_url:
        return [manual_url], real_room_id

    return [
        f"wss://danmuproxy.douyu.com:{port}/" for port in _candidate_ports(room_id, timeout)
    ], real_room_id


def _candidate_ports(room_id: int | str, timeout: float) -> tuple[int, ...]:
    """Order the ports to try for this room."""
    try:
        discovered = _discovered_port(room_id, timeout)
    except Exception:
        logger.debug("danmu port discovery failed for %r", room_id, exc_info=True)
        discovered = None

    if discovered is None:
        return DEFAULT_PORTS
    if discovered not in DEFAULT_PORTS:
        # A non-default port means this room sits on its own edge node; the
        # shared defaults are known not to serve it.
        return (discovered,)
    return (discovered, *(port for port in DEFAULT_PORTS if port != discovered))


def _discovered_port(room_id: int | str, timeout: float) -> int | None:
    """Read the danmuproxy port the room page is currently pinned to."""
    response = http_get(f"https://www.douyu.com/{room_id}", timeout)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    for script in soup.find_all("script"):
        if not script.string:
            continue
        match = _PORT_PATTERN.search(script.string)
        if match:
            return int(match.group(1))
    return None
