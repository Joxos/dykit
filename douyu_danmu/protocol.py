"""Douyu Live Stream Protocol Encoding and Decoding.

This module handles the binary protocol for communicating with Douyu's danmu
(chat message) servers. It provides functions to serialize/deserialize messages
using Douyu's key-value format and encode/decode them into the binary protocol.

Protocol Format:
    The Douyu protocol uses a binary packet format with little-endian encoding:
    - 4 bytes: packet length (little-endian)
    - 4 bytes: packet length (duplicate)
    - 2 bytes: message type (689=client, 690=server)
    - 1 byte: encrypt flag (0=no encryption)
    - 1 byte: reserved (0)
    - N bytes: message body (UTF-8 encoded key-value pairs)
    - 1 byte: null terminator (\\x00)

Key-Value Serialization:
    Messages are serialized as: key1@=value1/key2@=value2/
    Escaping rules:
        @ -> @A
        / -> @S
"""

from __future__ import annotations

import re
import struct

import httpx
from bs4 import BeautifulSoup

from .log import logger

# Douyu WebSocket server URL (use wss:// port 8506)
DOUYU_WS_URL = "wss://danmuproxy.douyu.com:8506/"

# Message types for Douyu protocol
CLIENT_MSG_TYPE = 689  # Client -> Server
SERVER_MSG_TYPE = 690  # Server -> Client


def serialize_message(msg_dict: dict[str, str | int]) -> str:
    """Serialize a message dictionary to Douyu key-value format.

    Format: key1@=value1/key2@=value2/
    Escaping: @ -> @A, / -> @S

    Args:
        msg_dict: Dictionary containing message key-value pairs.

    Returns:
        Serialized message string in Douyu format.
    """
    result = []
    for key, value in msg_dict.items():
        # Escape @ and / in key and value
        key_escaped = str(key).replace("@", "@A").replace("/", "@S")
        value_escaped = str(value).replace("@", "@A").replace("/", "@S")
        result.append(f"{key_escaped}@={value_escaped}/")
    return "".join(result)


def deserialize_message(msg_str: str) -> dict[str, str]:
    """Deserialize Douyu key-value format to a dictionary.

    Format: key1@=value1/key2@=value2/
    Unescaping: @A -> @, @S -> /

    Args:
        msg_str: Serialized message string in Douyu format.

    Returns:
        Dictionary with deserialized key-value pairs.
    """
    result: dict[str, str] = {}
    # Remove trailing / and split by /
    parts = msg_str.rstrip("/").split("/")
    for part in parts:
        if "@=" in part:
            key, value = part.split("@=", 1)
            # Unescape @A and @S
            key_unescaped = key.replace("@S", "/").replace("@A", "@")
            value_unescaped = value.replace("@S", "/").replace("@A", "@")
            result[key_unescaped] = value_unescaped
    return result


def encode_message(msg_str: str) -> bytes:
    """Encode a message string into Douyu binary protocol format.

    Format:
        - 4 bytes: packet length (little-endian)
        - 4 bytes: packet length (duplicate)
        - 2 bytes: message type (689 for client)
        - 1 byte: encrypt (0 = no encryption)
        - 1 byte: reserved (0)
        - N bytes: message body
        - 1 byte: null terminator (\\0)

    Args:
        msg_str: Message string to encode.

    Returns:
        Binary packet ready to send over WebSocket.
    """
    # Message body with null terminator
    body = msg_str.encode("utf-8") + b"\x00"

    # Calculate packet length (header + body)
    # Header is 12 bytes: 4+4+2+1+1
    packet_length = len(body) + 8  # 8 = 2+1+1+body length (excluding first 4 bytes)

    # Build packet
    packet = struct.pack("<I", packet_length)  # 4 bytes: length
    packet += struct.pack("<I", packet_length)  # 4 bytes: length (duplicate)
    packet += struct.pack("<H", CLIENT_MSG_TYPE)  # 2 bytes: msg type
    packet += struct.pack("<B", 0)  # 1 byte: encrypt
    packet += struct.pack("<B", 0)  # 1 byte: reserved
    packet += body

    return packet


def decode_message(data: bytes) -> str | None:
    """Decode Douyu binary protocol message.

    Args:
        data: Binary data received from WebSocket.

    Returns:
        Message string (without null terminator), or None if decode fails.
    """
    if len(data) < 12:
        return None

    # Parse packet header (kept for protocol documentation)
    _ = struct.unpack("<I", data[0:4])  # packet_length
    _ = struct.unpack("<H", data[8:10])  # msg_type

    # Skip header (12 bytes: 4+4+2+1+1)
    # Extract message body (until null terminator)
    body = data[12:]

    # Remove null terminator
    if body.endswith(b"\x00"):
        body = body[:-1]

    try:
        return body.decode("utf-8")
    except UnicodeDecodeError:
        # Retry with error handling for incomplete multi-byte sequences
        try:
            return body.decode("utf-8", errors="ignore")
        except Exception:
            logger.warning(f"Failed to decode message (len={len(body)}): {body[:50]}")
            return None


def resolve_room_id(room_id: int | str, timeout: float = 10.0) -> int:
    """Resolve room ID from various formats to actual room ID number.

    Attempts multiple resolution methods to find the actual room ID.
    Handles both numeric IDs and vanity/shorthand formats that redirect
    to the true room ID through the Douyu API and website.

    Args:
        room_id: The Douyu room ID (numeric or vanity format).
        timeout: HTTP request timeout in seconds (default: 10.0).

    Returns:
        The resolved room ID as an integer. Returns int(room_id) if all
        resolution methods fail.
    """
    # Immediately return if already an integer that's large enough
    if isinstance(room_id, int) and room_id > 100000:
        return room_id

    room_id_str = str(room_id).strip()
    headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}

    # Method 1: Try betard API (primary method)
    try:
        url = f"https://www.douyu.com/betard/{room_id_str}"
        logger.info(f"Attempting betard API resolution for room {room_id_str}...")
        response = httpx.get(url, headers=headers, timeout=timeout, follow_redirects=True)
        response.raise_for_status()
        data = response.json()
        resolved_id = data.get("room", {}).get("room_id")
        if resolved_id:
            logger.info(f"Resolved {room_id_str} -> {resolved_id} via betard API")
            return int(resolved_id)
    except Exception as e:
        logger.debug(f"betard API resolution failed: {e}")

    # Method 2: Try m.douyu.com HTML (secondary method)
    try:
        url = f"https://m.douyu.com/{room_id_str}"
        logger.info(f"Attempting m.douyu.com HTML resolution for room {room_id_str}...")
        response = httpx.get(url, headers=headers, timeout=timeout, follow_redirects=True)
        response.raise_for_status()
        match = re.search(r'"rid":(\d{1,8})', response.text)
        if match:
            resolved_id = match.group(1)
            logger.info(f"Resolved {room_id_str} -> {resolved_id} via m.douyu.com")
            return int(resolved_id)
    except Exception as e:
        logger.debug(f"m.douyu.com HTML resolution failed: {e}")

    # Method 3: Try www.douyu.com HTML (tertiary method)
    try:
        url = f"https://www.douyu.com/{room_id_str}"
        logger.info(f"Attempting www.douyu.com HTML resolution for room {room_id_str}...")
        response = httpx.get(url, headers=headers, timeout=timeout, follow_redirects=True)
        response.raise_for_status()
        match = re.search(r'room_id["\\s]*[:=]["\\s]*([0-9]{5,10})', response.text)
        if match:
            resolved_id = match.group(1)
            logger.info(f"Resolved {room_id_str} -> {resolved_id} via www.douyu.com")
            return int(resolved_id)
    except Exception as e:
        logger.debug(f"www.douyu.com HTML resolution failed: {e}")

    # Fallback: Return the integer value of the provided room_id
    logger.warning(f"Could not resolve room {room_id_str}, returning as-is")
    return int(room_id_str)


def get_danmu_server(
    room_id: int | str, timeout: float = 10.0, manual_url: str | None = None
) -> tuple[list[str], int]:
    """Get danmu WebSocket server URLs for a given room.

    Attempts to extract the real danmu server configuration from the room page.
    Returns a list of candidate URLs to try, ordered by likelihood of success.

    Args:
        room_id: The Douyu room ID.
        timeout: HTTP request timeout in seconds.
        manual_url: If provided, returns this URL immediately without discovery.

    Returns:
        tuple[list[str], int]: A tuple containing:
            - List of WebSocket URLs to try, e.g.:
              ['wss://danmuproxy.douyu.com:8505/', 'wss://danmuproxy.douyu.com:8506/', ...]
            - The resolved real room ID as an integer.
    """
    # Resolve the real room ID first
    real_room_id = resolve_room_id(room_id, timeout=timeout)

    # If manual_url is provided, use it directly
    if manual_url:
        logger.info(f"Using manual WebSocket URL: {manual_url}")
        return [manual_url], real_room_id

    # Common danmu proxy ports (8505 and 8506 are most common)
    default_ports = [8506, 8505, 8502, 8504, 8501, 8508]
    discovered_port = None

    try:
        # Fetch room page HTML
        url = f"https://www.douyu.com/{room_id}"
        headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}

        logger.info(f"Fetching danmu server config for room {room_id}...")
        response = httpx.get(url, headers=headers, timeout=timeout, follow_redirects=True)
        response.raise_for_status()

        # Parse HTML to find danmu server config
        soup = BeautifulSoup(response.text, "html.parser")

        # Method 1: Look for danmuproxy URL patterns in <script> tags
        scripts = soup.find_all("script")
        for script in scripts:
            if not script.string:
                continue

            # Try to extract port from patterns like danmuproxy.douyu.com:8502
            port_match = re.search(r"danmuproxy\.douyu\.com:(\d+)", script.string)
            if port_match:
                discovered_port = int(port_match.group(1))
                logger.info(f"Discovered danmu port from HTML: {discovered_port}")
                break

            # Try JSON parsing for embedded config objects
            if "$ROOM" in script.string or "room" in script.string.lower():
                # Look for port-like numbers near danmu/websocket keywords
                port_pattern = re.search(
                    r'["\'](?:danmu_?port|ws_?port)["\']\s*[:=]\s*(\d+)',
                    script.string,
                    re.IGNORECASE,
                )
                if port_pattern:
                    discovered_port = int(port_pattern.group(1))
                    logger.info(f"Discovered danmu port from config: {discovered_port}")
                    break

        if not discovered_port:
            logger.warning(f"Could not find danmu server config for room {room_id}")

    except httpx.HTTPError as e:
        logger.warning(f"HTTP error fetching room {room_id}: {e}")
    except Exception as e:
        logger.warning(f"Error discovering danmu server for room {room_id}: {e}")

    # Build candidate URL list
    candidate_urls = []

    # If we discovered a specific port, try it first
    if discovered_port and discovered_port not in default_ports:
        candidate_urls.append(f"wss://danmuproxy.douyu.com:{discovered_port}/")
    elif discovered_port:
        # Discovered port is in default list, prioritize it
        default_ports.remove(discovered_port)
        default_ports.insert(0, discovered_port)

    # Add all default ports
    for port in default_ports:
        candidate_urls.append(f"wss://danmuproxy.douyu.com:{port}/")

    logger.info(f"Candidate servers: {candidate_urls[:3]}... ({len(candidate_urls)} total)")
    return candidate_urls, real_room_id
