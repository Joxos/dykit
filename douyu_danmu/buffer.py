"""Message Buffer for UTF-8 Safe Packet Parsing.

This module solves a critical UTF-8 truncation bug that occurs when multi-byte
UTF-8 characters are split across WebSocket packet boundaries.

The Problem:
------------
Chinese characters like "你" are encoded as 3 bytes in UTF-8: [0xE4, 0xBD, 0xA0]

When WebSocket delivers data in chunks, a multi-byte character can be split:
    Packet 1: "...type@=chatmsg/txt@=你|" ends with [0xE4, 0xBD]
    Packet 2: Starts with [0xA0, ...]

If we decode each packet independently, Packet 1 triggers UnicodeDecodeError
because [0xE4, 0xBD] is an incomplete UTF-8 sequence. Using errors="ignore"
silently drops the character, resulting in data loss.

The Solution:
-------------
MessageBuffer accumulates raw bytes until a complete Douyu protocol packet
is received, then decodes the entire packet as UTF-8. This ensures multi-byte
characters are never split during decoding.

Packet Format (from protocol.py):
    - Bytes 0-3:   packet_length (little-endian uint32)
    - Bytes 4-7:   packet_length (duplicate)
    - Bytes 8-9:   msg_type (690 for server messages)
    - Byte 10:     encrypt flag (0 = no encryption)
    - Byte 11:     reserved (0)
    - Bytes 12+:   message body (UTF-8 key-value pairs)
    - Last byte:   null terminator (\\x00)

Note: packet_length = len(body) + 8, so total_size = packet_length + 4

Example Usage:
--------------
    buffer = MessageBuffer()

    def on_websocket_message(ws, data: bytes):
        buffer.add_data(data)
        for message_dict in buffer.get_messages():
            # message_dict: {"type": "chatmsg", "txt": "你好", ...}
            handle_danmu(message_dict)
"""

from __future__ import annotations

import struct

from .log import logger
from .protocol import deserialize_message

# Minimum packet size: 4+4+2+1+1 (header) + 1 (null terminator) = 13 bytes
MIN_PACKET_SIZE = 13


class MessageBuffer:
    """Buffer for accumulating and parsing Douyu protocol packets safely.

    This class prevents UTF-8 truncation by buffering incoming bytes until
    a complete protocol packet is received, then decoding the entire packet.

    Attributes:
        _buffer: Internal byte buffer accumulating incomplete packets.
    """

    def __init__(self) -> None:
        """Initialize an empty message buffer."""
        self._buffer = bytearray()

    def add_data(self, data: bytes) -> None:
        """Append incoming bytes to the internal buffer.

        Args:
            data: Raw bytes received from WebSocket.
        """
        self._buffer.extend(data)

    def get_messages(self) -> list[dict[str, str]]:
        """Extract and parse all complete messages from the buffer.

        This method:
        1. Checks if buffer has enough bytes for a complete packet
        2. Parses the packet header to get exact packet length
        3. Waits until buffer contains the full packet
        4. Decodes UTF-8 safely (complete packet guaranteed)
        5. Deserializes into key-value dictionary
        6. Removes processed bytes from buffer
        7. Repeats for multiple packets in the same buffer

        Returns:
            List of deserialized message dictionaries.
            Empty list if no complete packets available.

        Example:
            >>> buffer.add_data(packet_bytes)
            >>> messages = buffer.get_messages()
            >>> for msg in messages:
            ...     print(msg["type"], msg.get("txt", ""))
        """
        messages: list[dict[str, str]] = []

        while len(self._buffer) >= 4:  # Need at least packet_length field
            # Parse packet length from first 4 bytes
            packet_length = struct.unpack("<I", self._buffer[0:4])[0]
            total_size = 4 + packet_length  # Total bytes needed

            # Check if we have the complete packet
            if len(self._buffer) < total_size:
                # Incomplete packet - wait for more data
                break

            # Sanity check: packet must be at least MIN_PACKET_SIZE
            if total_size < MIN_PACKET_SIZE:
                logger.warning(
                    f"Invalid packet length {packet_length} (total={total_size}), "
                    f"expected at least {MIN_PACKET_SIZE}. Discarding buffer."
                )
                self._buffer.clear()
                break

            # Extract complete packet
            packet = bytes(self._buffer[:total_size])

            # Remove processed packet from buffer
            del self._buffer[:total_size]

            # Decode and parse the packet
            message_dict = self._decode_packet(packet)
            if message_dict is not None:
                messages.append(message_dict)

        return messages

    def _decode_packet(self, packet: bytes) -> dict[str, str] | None:
        """Decode a complete Douyu protocol packet into a message dictionary.

        Args:
            packet: Complete binary packet (including header).

        Returns:
            Deserialized message dictionary, or None if decode fails.
        """
        if len(packet) < MIN_PACKET_SIZE:
            return None

        # Skip header (12 bytes: 4+4+2+1+1)
        # Extract message body (from byte 12 onwards)
        body = packet[12:]

        # Remove null terminator if present
        if body.endswith(b"\x00"):
            body = body[:-1]

        # Decode UTF-8 (safe because we have complete packet)
        try:
            message_str = body.decode("utf-8")
        except UnicodeDecodeError as e:
            logger.warning(
                f"UTF-8 decode failed for complete packet (len={len(body)}): {e}. "
                f"First 50 bytes: {body[:50]}"
            )
            return None

        # Deserialize Douyu key-value format
        try:
            return deserialize_message(message_str)
        except Exception as e:
            logger.warning(
                f"Failed to deserialize message: {e}. Message: {message_str[:100]}"
            )
            return None
