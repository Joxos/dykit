"""Douyu Live Stream Danmu (弹幕) Collector.

A modular, async library for collecting chat messages from Douyu live streams.

Features:
    - Message buffering to prevent UTF-8 truncation
    - Async collectors
    - Pluggable storage handlers
    - Type-safe dataclasses
Basic usage:
    from dykit import DanmuMessage, encode_message, serialize_message

    # Serialize a message to Douyu key-value format
    msg = {"type": "chatmsg", "content": "Hello"}
    serialized = serialize_message(msg)

    # Encode to binary protocol
    encoded = encode_message(serialized)
"""

from __future__ import annotations

from .collectors import AsyncCollector

# Import public API from submodules
from .protocol import (
    CLIENT_MSG_TYPE,
    DOUYU_WS_URL,
    SERVER_MSG_TYPE,
    decode_message,
    deserialize_message,
    encode_message,
    serialize_message,
)
from .storage import ConsoleStorage, CSVStorage, StorageHandler
from .types import DanmuMessage, MessageType

__version__ = "4.0.0"

__all__ = [
    # Version
    "__version__",
    # Protocol functions
    "serialize_message",
    "deserialize_message",
    "encode_message",
    "decode_message",
    # Protocol constants
    "DOUYU_WS_URL",
    "CLIENT_MSG_TYPE",
    "SERVER_MSG_TYPE",
    # Type definitions
    "DanmuMessage",
    "MessageType",
    # Collectors
    "AsyncCollector",
    # Storage
    "StorageHandler",
    "CSVStorage",
    "ConsoleStorage",
]
