"""dyproto - Douyu Live Stream Protocol.

A minimal, type-safe library for encoding and decoding Douyu danmu (chat) protocol.

Quick Start:
    from dyproto import pack, unpack, MessageBuffer

    # Encode a message to bytes
    data = pack({"type": "chatmsg", "content": "Hello"})

    # Decode bytes to message
    msg = unpack(data)  # {"type": "chatmsg", "content": "Hello"}

    # For streaming, use MessageBuffer
    buffer = MessageBuffer()
    buffer.add_data(raw_bytes)
    for msg in buffer.get_messages():
        process(msg)

For room discovery (see the `dysource` package):
    from dysource import resolve_room_id, get_danmu_server
"""

from __future__ import annotations

from .buffer import MessageBuffer
from .protocol import (
    PacketHeader,
    decode_message,
    deserialize_message,
    encode_message,
    serialize_message,
)
from .types import MESSAGE_KINDS, MSG_TYPE_TO_ENUM, UNKNOWN_KIND, MessageKindInfo, MessageType

# Convenience functions
__all__ = [
    # Version
    "__version__",
    # Core functions
    "pack",
    "unpack",
    "encode_message",
    "decode_message",
    "serialize_message",
    "deserialize_message",
    # Buffer
    "MessageBuffer",
    # Types
    "MessageType",
    "MessageKindInfo",
    "MSG_TYPE_TO_ENUM",
    "MESSAGE_KINDS",
    "UNKNOWN_KIND",
    "PacketHeader",
    # Constants
    "DOUYU_WS_URL",
    "CLIENT_MSG_TYPE",
    "SERVER_MSG_TYPE",
    "PACKET_HEADER_SIZE",
    "MIN_PACKET_SIZE",
    "MAX_PACKET_SIZE",
]

__version__ = "0.1.0"

# Import constants
from .constants import (
    CLIENT_MSG_TYPE,
    DOUYU_WS_URL,
    MAX_PACKET_SIZE,
    MIN_PACKET_SIZE,
    PACKET_HEADER_SIZE,
    SERVER_MSG_TYPE,
)

# Convenience wrappers
from .protocol import decode_message as unpack
from .protocol import encode_message as pack
