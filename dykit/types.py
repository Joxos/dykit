"""Type definitions for Douyu danmu messages.

This module provides data classes and enums for representing danmu messages
in the Douyu streaming protocol. The DanmuMessage dataclass serves as a
strongly-typed container for all message data, supporting both protocol
parsing and CSV serialization.

Enums:
    MessageType: Enumeration of protocol message types (chatmsg, loginres, etc.)

Classes:
    DanmuMessage: Frozen dataclass representing a single danmu message with
        timestamp, user info, content, and raw protocol data.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional


class MessageType(Enum):
    """Enumeration of Douyu protocol message types.

    Attributes:
        CHATMSG: Regular chat/danmu message (弹幕消息)
        LOGINRES: Login response from server (登录响应)
        LOGINREQ: Login request to server (登录请求)
        JOINGROUP: Join room/group message (加入房间)
        MRKL: Heartbeat/keep-alive message (心跳消息)
        DGB: Gift/reward message (礼物消息)
        UENTER: User enter room message (用户进场)
        ANBC: Open noble/VIP message (开通贵族)
        RNEWBC: Renew noble/VIP message (续费贵族)
        BLAB: Fan badge level up message (粉丝牌升级)
        UPGRADE: User level up message (用户升级)
        UNKNOWN: Unknown or unrecognized message type (未知类型)
    """

    CHATMSG = "chatmsg"
    LOGINRES = "loginres"
    LOGINREQ = "loginreq"
    JOINGROUP = "joingroup"
    MRKL = "mrkl"
    DGB = "dgb"
    UENTER = "uenter"
    ANBC = "anbc"
    RNEWBC = "rnewbc"
    BLAB = "blab"
    UPGRADE = "upgrade"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class DanmuMessage:
    """Immutable data class representing a Douyu danmu message.

    This class encapsulates all information about a single danmu message,
    including sender details, message content, and raw protocol data.

    Attributes:
        timestamp: ISO 8601 formatted timestamp of message reception.
        username: Nickname of the message sender (可能为None).
        content: The actual danmu/chat message content (可能为None).
        user_level: User level/rank in the channel (0 for unknown).
        user_id: Unique identifier for the message sender (可能为None).
        room_id: ID of the streaming room/channel (可能为None).
        msg_type: Type of protocol message (from MessageType enum).
        raw_data: Complete raw message data as dict for debugging.
        gift_id: Gift ID for dgb messages (optional).
        gift_count: Gift count for dgb messages (optional).
        gift_name: Gift name for dgb messages (optional).
        badge_level: Badge level for uenter/blab messages (optional).
        badge_name: Badge name for uenter/blab messages (optional).
        noble_level: Noble level for anbc/rnewbc messages (optional).
        avatar_url: Avatar URL for uenter messages (optional).
    """

    timestamp: datetime
    username: str | None
    content: str | None
    user_level: int
    user_id: str | None
    room_id: str | None
    msg_type: MessageType
    raw_data: dict[str, str]
    gift_id: Optional[str] = None
    gift_count: Optional[int] = None
    gift_name: Optional[str] = None
    badge_level: Optional[int] = None
    badge_name: Optional[str] = None
    noble_level: Optional[int] = None
    avatar_url: Optional[str] = None

    def to_dict(self) -> dict[str, str | int | None]:
        """Convert message to dictionary suitable for CSV writing.

        Returns a flat dictionary with all fields converted to serializable
        types (str, int, None). Datetime is converted to ISO 8601 string.

        Returns:
            Dictionary with keys: timestamp, username, content, user_level,
            user_id, room_id, msg_type, extra. All values are strings, ints,
            None, or dict.

        Example:
            >>> msg = DanmuMessage(...)
            >>> row = msg.to_dict()
            >>> csv_writer.writerow([row["timestamp"], row["username"], ...])
        """
        return {
            "timestamp": self.timestamp.isoformat(),
            "username": self.username,
            "content": self.content,
            "user_level": self.user_level,
            "user_id": self.user_id,
            "room_id": self.room_id,
            "msg_type": self.msg_type.value,
            "gift_id": self.gift_id,
            "gift_count": self.gift_count,
            "gift_name": self.gift_name,
            "badge_level": self.badge_level,
            "badge_name": self.badge_name,
            "noble_level": self.noble_level,
            "avatar_url": self.avatar_url,
        }
