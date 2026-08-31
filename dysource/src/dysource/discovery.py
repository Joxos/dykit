"""Room discovery for Douyu.

This module provides functions to resolve room IDs and discover danmu servers.

Requires extra dependencies: httpx, beautifulsoup4, tenacity
"""

from __future__ import annotations

import re
from typing import TypedDict

import httpx
from bs4 import BeautifulSoup
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

# Constants for discovery
DEFAULT_PORTS = [8506, 8505, 8502, 8504, 8501, 8508]

RETRY_ATTEMPTS_HTTP = 3
RETRY_BACKOFF_HTTP_MIN_SECONDS = 1
RETRY_BACKOFF_HTTP_MAX_SECONDS = 10
RETRY_BACKOFF_HTTP_MULTIPLIER = 2


class DanmuServer(TypedDict):
    """Danmu server configuration."""

    url: str
    port: int


@retry(
    retry=retry_if_exception_type(httpx.HTTPError),
    stop=stop_after_attempt(RETRY_ATTEMPTS_HTTP),
    wait=wait_exponential(
        multiplier=RETRY_BACKOFF_HTTP_MULTIPLIER,
        min=RETRY_BACKOFF_HTTP_MIN_SECONDS,
        max=RETRY_BACKOFF_HTTP_MAX_SECONDS,
    ),
    reraise=True,
)
def _http_get(url: str, headers: dict[str, str], timeout: float) -> httpx.Response:
    """Issue GET request with retry."""
    return httpx.get(url, headers=headers, timeout=timeout, follow_redirects=True)


def resolve_room_id(room_id: int | str, timeout: float = 10.0) -> int:
    """Resolve room ID from various formats to actual room ID number.

    Attempts multiple resolution methods:
    1. betard API (primary)
    2. m.douyu.com HTML (secondary)
    3. www.douyu.com HTML (tertiary)

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
    # Already a valid numeric ID
    if isinstance(room_id, int) and room_id > 100000:
        return room_id

    room_id_str = str(room_id).strip()
    headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}

    # Method 1: Try betard API
    try:
        url = f"https://www.douyu.com/betard/{room_id_str}"
        response = _http_get(url, headers, timeout)
        response.raise_for_status()
        data = response.json()
        resolved_id = data.get("room", {}).get("room_id")
        if resolved_id:
            return int(resolved_id)
    except Exception:
        pass

    # Method 2: Try m.douyu.com HTML
    try:
        url = f"https://m.douyu.com/{room_id_str}"
        response = _http_get(url, headers, timeout)
        response.raise_for_status()
        match = re.search(r'"rid":(\d{1,8})', response.text)
        if match:
            return int(match.group(1))
    except Exception:
        pass

    # Method 3: Try www.douyu.com HTML
    try:
        url = f"https://www.douyu.com/{room_id_str}"
        response = _http_get(url, headers, timeout)
        response.raise_for_status()
        match = re.search(r'room_id["\\s]*[:=]["\\s]*([0-9]{5,10})', response.text)
        if match:
            return int(match.group(1))
    except Exception:
        pass

    # Fallback
    return int(room_id_str)


def get_danmu_server(
    room_id: int | str,
    timeout: float = 10.0,
    manual_url: str | None = None,
) -> tuple[list[str], int]:
    """Get danmu WebSocket server URLs for a given room.

    Args:
        room_id: The Douyu room ID.
        timeout: HTTP request timeout in seconds.
        manual_url: If provided, returns this URL immediately.

    Returns:
        Tuple of (list of WebSocket URLs, resolved room ID).

    Example:
        >>> urls, room_id = get_danmu_server(6657)
        >>> urls
        ['wss://danmuproxy.douyu.com:8506/', ...]
        >>> room_id
        6657
    """
    # Resolve the real room ID first
    real_room_id = resolve_room_id(room_id, timeout=timeout)

    # Manual URL override
    if manual_url:
        return [manual_url], real_room_id

    # Discover danmu port from room page
    discovered_port: int | None = None

    try:
        url = f"https://www.douyu.com/{room_id}"
        headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}
        response = _http_get(url, headers, timeout)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        scripts = soup.find_all("script")

        for script in scripts:
            if not script.string:
                continue

            # Try to find danmuproxy port
            port_match = re.search(r"danmuproxy\.douyu\.com:(\d+)", script.string)
            if port_match:
                discovered_port = int(port_match.group(1))
                break

    except Exception:
        pass

    # Build candidate URL list
    candidate_urls: list[str] = []
    ports: list[int] = []

    if discovered_port and discovered_port not in DEFAULT_PORTS:
        candidate_urls.append(f"wss://danmuproxy.douyu.com:{discovered_port}/")
    elif discovered_port:
        ports = [discovered_port] + [p for p in DEFAULT_PORTS if p != discovered_port]
    else:
        ports = DEFAULT_PORTS.copy()

    for port in ports:
        candidate_urls.append(f"wss://danmuproxy.douyu.com:{port}/")

    return candidate_urls, real_room_id


__all__ = [
    "resolve_room_id",
    "get_danmu_server",
    "DanmuServer",
]
