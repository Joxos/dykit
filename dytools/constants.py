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
# Each entry is (type_name, human_readable_description).
USER_FILTERABLE_TYPES_DESCRIBED: tuple[tuple[str, str], ...] = (
    ("chatmsg", "弹幕"),
    ("dgb", "礼物"),
    ("uenter", "进场"),
    ("anbc", "开通贵族"),
    ("rnewbc", "续费贵族"),
    ("blab", "粉丝牌升级"),
    ("upgrade", "用户升级"),
)

USER_FILTERABLE_TYPES: tuple[str, ...] = tuple(t for t, _ in USER_FILTERABLE_TYPES_DESCRIBED)
