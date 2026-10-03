"""UTF-8 safe message buffer for streaming packet reassembly.

Incoming WebSocket data can hold several protocol packets at once, or half of
one; this buffer yields only the complete ones and keeps the rest until the
next read.
"""

from __future__ import annotations

from .codec import decode_message, deserialize_message, parse_packet_length
from .constants import MAX_PACKET_SIZE, MIN_PACKET_SIZE


class MessageBuffer:
    """Accumulate raw bytes and yield complete protocol messages.

    Handles:
    - Multiple packets in one WebSocket frame
    - Incomplete packets (wait for more data)
    - UTF-8 multi-byte sequence splitting across frames

    Example:
        buffer = MessageBuffer()
        buffer.add_data(raw_bytes)
        for msg_dict in buffer.get_messages():
            process(msg_dict)
    """

    def __init__(self) -> None:
        self._buffer = bytearray()

    def add_data(self, data: bytes) -> None:
        """Add raw bytes to the buffer.

        Args:
            data: Raw bytes received from WebSocket.
        """
        self._buffer.extend(data)

    def get_messages(self) -> list[dict[str, str]]:
        """Extract all complete messages from buffer.

        Returns:
            List of deserialized message dictionaries.
            Incomplete packets remain in buffer for next call.
        """
        messages: list[dict[str, str]] = []

        while True:
            # Need at least 4 bytes to get packet length
            if len(self._buffer) < 4:
                break

            # Parse packet length from first 4 bytes
            packet_length = parse_packet_length(bytes(self._buffer))
            if packet_length is None:
                break

            # Calculate total packet size (length field + length value)
            total_size = packet_length + 4

            # Sanity check
            if total_size < MIN_PACKET_SIZE or total_size > MAX_PACKET_SIZE:
                # Invalid length, clear buffer to avoid infinite loop
                self._buffer.clear()
                break

            # Wait for complete packet
            if len(self._buffer) < total_size:
                break

            # Extract and decode packet
            packet_data = bytes(self._buffer[:total_size])
            self._buffer = self._buffer[total_size:]

            # Decode binary to string
            msg_str = decode_message(packet_data)
            if msg_str is None:
                continue

            # Deserialize to dict
            msg_dict = deserialize_message(msg_str)
            if msg_dict:
                messages.append(msg_dict)

        return messages

    def clear(self) -> None:
        """Clear the buffer."""
        self._buffer.clear()

    def __len__(self) -> int:
        """Return current buffer size."""
        return len(self._buffer)
