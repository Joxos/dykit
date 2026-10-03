"""Douyu wire protocol: encode and decode. Pure - no IO, no network.

Everything here is a function of its arguments, which is why it can be tested
exhaustively without a room and reused without the collector.

Quick start:
    from dykit.protocol import MessageBuffer, encode_message, pack

    data = encode_message({"type@=chatmsg@S"})
    for message in MessageBuffer().add_data(data) or []:
        ...
"""

from __future__ import annotations

from .buffer import MessageBuffer
from .codec import (
    PacketHeader,
    decode_message,
    deserialize_message,
    encode_message,
    serialize_message,
)
from .constants import (
    CLIENT_MSG_TYPE,
    DOUYU_WS_URL,
    MAX_PACKET_SIZE,
    MIN_PACKET_SIZE,
    PACKET_HEADER_SIZE,
    SERVER_MSG_TYPE,
)
from .types import MSG_TYPE_TO_ENUM, MessageType

__all__ = [
    "MessageBuffer",
    "MessageType",
    "MSG_TYPE_TO_ENUM",
    "PacketHeader",
    "encode_message",
    "decode_message",
    "serialize_message",
    "deserialize_message",
    "DOUYU_WS_URL",
    "CLIENT_MSG_TYPE",
    "SERVER_MSG_TYPE",
    "PACKET_HEADER_SIZE",
    "MIN_PACKET_SIZE",
    "MAX_PACKET_SIZE",
]
