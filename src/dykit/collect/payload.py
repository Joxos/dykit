"""Douyu payload -> :class:`DanmuMessage` mapping.

Pure, synchronous, zero IO: every function here takes a decoded payload dict
and returns a value. The collector owns the WebSocket lifecycle; this module
owns the shape of a message. Keeping the two apart makes the mapping testable
without a live room (see ``tests/collect/test_payload.py``).
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from ..protocol import MSG_TYPE_TO_ENUM, MessageType
from .types import DanmuMessage

CHATMSG = "chatmsg"
LOGIN_RESPONSE = "loginres"

_STRIP = r"^\s+|\s+$"
_GIFT_MESSAGE_TYPES = frozenset({MessageType.DGB, MessageType.ANBC, MessageType.RNEWBC})


def resolve_message_type(msg_type: str) -> MessageType | None:
    """Map a raw Douyu type string to the type we persist, or None.

    ``None`` means "not collected": either Douyu does not model the type, or
    it is the chat message (handled by :func:`build_chat_message`).
    """
    enum_value = MSG_TYPE_TO_ENUM.get(msg_type)
    if enum_value is None or enum_value == MessageType.CHATMSG:
        return None
    return enum_value


def should_skip(
    msg_type: str, type_filter: list[str] | None, type_exclude: list[str] | None
) -> bool:
    """Apply the --with/--without filters to one raw message type."""
    if type_filter and msg_type not in type_filter:
        return True
    return bool(type_exclude and msg_type in type_exclude)


def build_chat_message(
    msg_dict: dict[str, str],
    real_room_id: int,
    timestamp: datetime,
) -> DanmuMessage:
    """Build a chat message.

    Chat payloads always carry a user and content, so missing values fall back
    to ``Unknown``/empty rather than None.
    """
    nickname = _strip(msg_dict.get("nn", "Unknown"))
    level = msg_dict.get("level", "0")
    badge_level = msg_dict.get("bl", "")

    return DanmuMessage(
        timestamp=timestamp,
        room_id=str(real_room_id),
        msg_type=MessageType.CHATMSG,
        user_id=msg_dict.get("uid", "0"),
        username=nickname,
        content=_strip(msg_dict.get("txt", "")),
        user_level=int(level) if level.isdigit() else 0,
        color=msg_dict.get("col") or msg_dict.get("color"),
        client_type=msg_dict.get("ct"),
        avatar_url=msg_dict.get("ic"),
        badge_level=int(badge_level) if badge_level.isdigit() else None,
        badge_name=msg_dict.get("bnn"),
        badge_room_id=msg_dict.get("brid"),
        raw_data=msg_dict,
    )


def build_structured_message(
    msg_dict: dict[str, str],
    msg_type: MessageType,
    real_room_id: int,
    timestamp: datetime,
) -> DanmuMessage:
    """Build a gift / enter / badge / noble message."""
    nickname = _strip(msg_dict.get("nn", ""))
    level = msg_dict.get("level", "0")
    uid = msg_dict.get("uid", "0")
    badge_level = msg_dict.get("bl", "")

    fields: dict[str, Any] = {
        "timestamp": timestamp,
        "room_id": str(real_room_id),
        "msg_type": msg_type,
        "user_id": uid or None,
        "username": nickname or None,
        "user_level": int(level) if level.isdigit() else None,
        "color": msg_dict.get("col") or msg_dict.get("color"),
        "client_type": msg_dict.get("ct"),
        "avatar_url": msg_dict.get("ic") or msg_dict.get("av"),
        "badge_level": int(badge_level) if badge_level.isdigit() else None,
        "badge_name": msg_dict.get("bnn"),
        "badge_room_id": msg_dict.get("brid"),
        "raw_data": msg_dict,
    }

    if msg_type in _GIFT_MESSAGE_TYPES:
        fields.update(_gift_fields(msg_dict))

    return DanmuMessage(**fields)


def _gift_fields(msg_dict: dict[str, str]) -> dict[str, Any]:
    """Extract gift/noble fields shared by dgb, anbc and rnewbc payloads."""
    gift_count = msg_dict.get("gfcnt", "")
    gift_hits = msg_dict.get("hits", "")
    return {
        "gift_id": msg_dict.get("gfid"),
        "gift_count": int(gift_count) if gift_count.isdigit() else None,
        "gift_name": msg_dict.get("gfn") or msg_dict.get("gftype"),
        "gift_hits": int(gift_hits) if gift_hits.isdigit() else None,
        "gift_receiver_uid": msg_dict.get("receive_uid"),
        "gift_receiver_name": msg_dict.get("receive_nn"),
        "noble_level": int(msg_dict.get("nl", "0")) or None,
    }


def _strip(value: str) -> str:
    return re.sub(_STRIP, "", value)
