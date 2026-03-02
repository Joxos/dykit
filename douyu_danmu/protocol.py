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

import struct

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
