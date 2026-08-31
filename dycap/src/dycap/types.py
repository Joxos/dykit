"""Type definitions for dycap."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

# Re-export MessageType from dyproto for convenience
from dyproto import MessageType


@dataclass(frozen=True)
class DanmuMessage:
    """Represents a parsed Douyu danmu message.

    This is the canonical message type used throughout dycap for storage
    and analysis. It contains all common fields from various message types.

    Attributes:
        timestamp: Time the message was received.
        room_id: The room ID this message belongs to.
        msg_type: Type of the message (chatmsg, gift, etc.).
        user_id: User's unique ID.
        username: User's display name.
        content: Message content (for chat messages).
        user_level: User's level in the streamer's room.
        gift_id: Gift ID (for gift messages).
        gift_count: Gift count (for gift messages).
        gift_name: Gift name (for gift messages).
        badge_level: Fan badge level.
        badge_name: Fan badge name.
        noble_level: Noble level (0 = not a noble).
        avatar_url: User's avatar URL.
        color: Danmu color (chat messages, raw ``col``/``color`` value).
        raw_data: Original raw message dictionary (full payload, no loss).
    """

    timestamp: datetime
    room_id: str
    msg_type: MessageType
    user_id: str | None = None
    username: str | None = None
    content: str | None = None
    user_level: int | None = None
    gift_id: str | None = None
    gift_count: int | None = None
    gift_name: str | None = None
    badge_level: int | None = None
    badge_name: str | None = None
    noble_level: int | None = None
    avatar_url: str | None = None
    color: str | None = None
    raw_data: dict[str, Any] | None = None
