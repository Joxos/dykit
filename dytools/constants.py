"""Shared constants for the dytools package."""

from __future__ import annotations

# Minimum packet size: 4+4+2+1+1 (header) + 1 (null terminator) = 13 bytes
MIN_PACKET_SIZE = 13

# Maximum packet size to prevent OOM on malformed packets
MAX_PACKET_SIZE = 65536

# Protocol-internal control messages that should never be filtered by user settings.
# These are used for WebSocket handshake and heartbeat, not for user-facing content.
PROTOCOL_MESSAGE_TYPES: frozenset[str] = frozenset({"loginres", "mrkl", "loginreq", "joingroup"})

# User-facing message types that can be filtered, ranked, or analyzed.
USER_FILTERABLE_TYPES: tuple[str, ...] = (
    "chatmsg",
    "dgb",
    "uenter",
    "anbc",
    "rnewbc",
    "blab",
    "upgrade",
    "unknown",
)
