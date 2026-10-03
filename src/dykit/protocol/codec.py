"""Douyu wire protocol: header, key-value body, binary packets.

Pure functions - no IO, no state.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from construct import Int8ul, Int16ul, Int32ul

from .constants import (
    CLIENT_MSG_TYPE,
    MAX_PACKET_SIZE,
    MIN_PACKET_SIZE,
    PACKET_HEADER_SIZE,
)

# ============================================================
# Low-level byte parsing (using struct for zero-dep option)
# ============================================================


def _parse_uint(data: bytes, construct_int: object, width_bits: int) -> int:
    parser = getattr(construct_int, "parse", None)
    if not callable(parser):
        raise RuntimeError(f"construct Int{width_bits}ul parser is unavailable")
    parsed = parser(data)
    if isinstance(parsed, int):
        return parsed
    raise RuntimeError(f"construct Int{width_bits}ul parser returned non-integer value")


def _build_uint(value: int, construct_int: object, width_bits: int) -> bytes:
    builder = getattr(construct_int, "build", None)
    if not callable(builder):
        raise RuntimeError(f"construct Int{width_bits}ul builder is unavailable")
    built = builder(value)
    if isinstance(built, bytes):
        return built
    if isinstance(built, bytearray):
        return bytes(built)
    raise RuntimeError(f"construct Int{width_bits}ul builder returned non-bytes value")


# ============================================================
# Packet Header
# ============================================================


@dataclass(frozen=True)
class PacketHeader:
    """Douyu packet header fields."""

    packet_length: int
    packet_length_dup: int
    msg_type: int
    encrypt_flag: int
    reserved: int


def parse_packet_length(data: bytes) -> int | None:
    """Parse packet length from first 4 bytes."""
    if len(data) < 4:
        return None
    return _parse_uint(data[0:4], Int32ul, 32)


def parse_packet_header(data: bytes) -> PacketHeader | None:
    """Parse full 12-byte packet header."""
    if len(data) < PACKET_HEADER_SIZE:
        return None
    return PacketHeader(
        packet_length=_parse_uint(data[0:4], Int32ul, 32),
        packet_length_dup=_parse_uint(data[4:8], Int32ul, 32),
        msg_type=_parse_uint(data[8:10], Int16ul, 16),
        encrypt_flag=_parse_uint(data[10:11], Int8ul, 8),
        reserved=_parse_uint(data[11:12], Int8ul, 8),
    )


def build_packet_header(header: PacketHeader) -> bytes:
    """Build binary packet header from fields."""
    return b"".join(
        (
            _build_uint(header.packet_length, Int32ul, 32),
            _build_uint(header.packet_length_dup, Int32ul, 32),
            _build_uint(header.msg_type, Int16ul, 16),
            _build_uint(header.encrypt_flag, Int8ul, 8),
            _build_uint(header.reserved, Int8ul, 8),
        )
    )


# ============================================================
# Key-Value Serialization
# ============================================================


def serialize_message(msg_dict: Mapping[str, object]) -> str:
    """Serialize message dict to Douyu key-value format.

    Format: key1@=value1/key2@=value2/
    Escaping: @ -> @A, / -> @S

    Keys and values are stringified, so any value type is accepted.

    Args:
        msg_dict: Mapping containing message key-value pairs.

    Returns:
        Serialized message string in Douyu format.
    """
    result: list[str] = []
    for key, value in msg_dict.items():
        key_escaped = str(key).replace("@", "@A").replace("/", "@S")
        value_escaped = str(value).replace("@", "@A").replace("/", "@S")
        result.append(f"{key_escaped}@={value_escaped}/")
    return "".join(result)


def deserialize_message(msg_str: str) -> dict[str, str]:
    """Deserialize Douyu key-value format to dict.

    Format: key1@=value1/key2@=value2/
    Unescaping: @A -> @, @S -> /

    Args:
        msg_str: Serialized message string in Douyu format.

    Returns:
        Dictionary with deserialized key-value pairs.
    """
    result: dict[str, str] = {}
    parts = msg_str.rstrip("/").split("/")
    for part in parts:
        if "@=" in part:
            key, value = part.split("@=", 1)
            key_unescaped = key.replace("@S", "/").replace("@A", "@")
            value_unescaped = value.replace("@S", "/").replace("@A", "@")
            result[key_unescaped] = value_unescaped
    return result


# ============================================================
# Binary Packet Encoding/Decoding
# ============================================================


def encode_message(msg_str: str) -> bytes:
    """Encode message string to Douyu binary protocol.

    Packet format:
        - 4 bytes: packet length (little-endian)
        - 4 bytes: packet length (duplicate)
        - 2 bytes: message type (689 for client)
        - 1 byte: encrypt (0 = no encryption)
        - 1 byte: reserved (0)
        - N bytes: message body
        - 1 byte: null terminator

    Args:
        msg_str: Message string to encode.

    Returns:
        Binary packet ready to send over WebSocket.
    """
    body = msg_str.encode("utf-8") + b"\x00"
    packet_length = len(body) + 8

    header = build_packet_header(
        PacketHeader(
            packet_length=packet_length,
            packet_length_dup=packet_length,
            msg_type=CLIENT_MSG_TYPE,
            encrypt_flag=0,
            reserved=0,
        )
    )
    return header + body


def decode_message(data: bytes) -> str | None:
    """Decode Douyu binary protocol message.

    Args:
        data: Binary data received from WebSocket.

    Returns:
        Message string (without null terminator), or None if decode fails.
    """
    if len(data) < PACKET_HEADER_SIZE:
        return None

    header = parse_packet_header(data[0:PACKET_HEADER_SIZE])
    if header is None:
        return None

    packet_length = int(header.packet_length)
    if packet_length != int(header.packet_length_dup):
        return None

    total_size = packet_length + 4
    if total_size < MIN_PACKET_SIZE or total_size > MAX_PACKET_SIZE:
        return None

    if len(data) < total_size:
        return None

    body = data[PACKET_HEADER_SIZE:total_size]

    if body.endswith(b"\x00"):
        body = body[:-1]

    try:
        return body.decode("utf-8")
    except UnicodeDecodeError:
        try:
            return body.decode("utf-8", errors="ignore")
        except Exception:
            return None
