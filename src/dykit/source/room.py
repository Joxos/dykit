"""Room ID resolution.

Douyu accepts both numeric room IDs and vanity names ("longzhu"); this module
turns either into the numeric ID the danmu protocol needs. Several sources are
tried in order of reliability, and a failure in one is logged and falls
through to the next rather than aborting the whole lookup.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable

from .http import http_get

logger: logging.Logger = logging.getLogger(__name__)

# Numeric IDs below this are ambiguous with vanity names, so they are resolved
# over HTTP instead of trusted as-is.
NUMERIC_ID_THRESHOLD = 100000

_MOBILE_RID_PATTERN = re.compile(r'"rid":(\d{1,8})')
_DESKTOP_ROOM_ID_PATTERN = re.compile(r'room_id["\s]*[:=]["\s]*([0-9]{5,10})')


class RoomResolutionError(ValueError):
    """A room name could not be resolved to a numeric Douyu room ID."""


def resolve_room_id(room_id: int | str, timeout: float = 10.0) -> int:
    """Resolve a room ID from any accepted format to the numeric room ID.

    Attempts, in order: the betard API, the m.douyu.com page, then the
    www.douyu.com page. Falls back to interpreting the input as numeric.

    Args:
        room_id: The Douyu room ID (numeric or vanity format).
        timeout: HTTP request timeout in seconds.

    Returns:
        The resolved room ID as an integer.

    Example:
        >>> resolve_room_id(6657)
        6657
        >>> resolve_room_id("longzhu")
        6657
    """
    if isinstance(room_id, int) and room_id > NUMERIC_ID_THRESHOLD:
        return room_id

    room_str = str(room_id).strip()
    strategies: tuple[Callable[[], int | None], ...] = (
        lambda: _from_betard_api(room_str, timeout),
        lambda: _from_mobile_page(room_str, timeout),
        lambda: _from_desktop_page(room_str, timeout),
    )

    for strategy in strategies:
        try:
            resolved = strategy()
        except Exception:
            logger.debug("room resolution step failed for %r", room_str, exc_info=True)
            continue
        if resolved is not None:
            return resolved

    if room_str.isdigit():
        return int(room_str)
    # A vanity name no source could resolve. Say so plainly - the raw int()
    # failure would reach the user as "invalid literal for int()".
    raise RoomResolutionError(
        f"Could not resolve room {room_str!r} to a numeric room ID. "
        "Check the room name, or pass the numeric room ID directly."
    )


def _from_betard_api(room_str: str, timeout: float) -> int | None:
    """Primary source: the betard JSON endpoint."""
    response = http_get(f"https://www.douyu.com/betard/{room_str}", timeout)
    response.raise_for_status()
    resolved = response.json().get("room", {}).get("room_id")
    return int(resolved) if resolved else None


def _from_mobile_page(room_str: str, timeout: float) -> int | None:
    """Secondary source: the m.douyu.com page embeds the real rid."""
    response = http_get(f"https://m.douyu.com/{room_str}", timeout)
    response.raise_for_status()
    match = _MOBILE_RID_PATTERN.search(response.text)
    return int(match.group(1)) if match else None


def _from_desktop_page(room_str: str, timeout: float) -> int | None:
    """Last resort: scrape room_id out of the desktop page."""
    response = http_get(f"https://www.douyu.com/{room_str}", timeout)
    response.raise_for_status()
    match = _DESKTOP_ROOM_ID_PATTERN.search(response.text)
    return int(match.group(1)) if match else None
