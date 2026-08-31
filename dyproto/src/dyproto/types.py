"""Type definitions for Douyu protocol messages."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class MessageType(str, Enum):
    """Douyu message type enumeration.

    These are the recognized message types in the Douyu protocol.
    """

    # User messages
    CHATMSG = "chatmsg"  # Regular chat message
    DGB = "dgb"  # Gift
    UENTER = "uenter"  # User entered
    ANBC = "anbc"  # Noble opened
    RNEWBC = "rnewbc"  # Noble renewed
    BLAB = "blab"  # Badge level up
    UPGRADE = "upgrade"  # User level up


# Mapping from string to MessageType
MSG_TYPE_TO_ENUM: dict[str, MessageType] = {
    "chatmsg": MessageType.CHATMSG,
    "dgb": MessageType.DGB,
    "uenter": MessageType.UENTER,
    "anbc": MessageType.ANBC,
    "rnewbc": MessageType.RNEWBC,
    "blab": MessageType.BLAB,
    "upgrade": MessageType.UPGRADE,
}


@dataclass(frozen=True)
class MessageKindInfo:
    """Static per-message-type metadata (single source of truth).

    All packages derive display labels and icons from ``MESSAGE_KINDS`` so
    that adding a new message type is a one-place change.

    Attributes:
        label_cn: Human-readable Chinese label (CLI help, summaries).
        icon: Emoji icon used in console rendering.
    """

    label_cn: str
    icon: str


UNKNOWN_KIND = MessageKindInfo(label_cn="未知", icon="🔹")


MESSAGE_KINDS: dict[MessageType, MessageKindInfo] = {
    MessageType.CHATMSG: MessageKindInfo(label_cn="弹幕", icon="💬"),
    MessageType.DGB: MessageKindInfo(label_cn="礼物", icon="🎁"),
    MessageType.UENTER: MessageKindInfo(label_cn="进场", icon="🚪"),
    MessageType.ANBC: MessageKindInfo(label_cn="开通贵族", icon="👑"),
    MessageType.RNEWBC: MessageKindInfo(label_cn="续费贵族", icon="♻️"),
    MessageType.BLAB: MessageKindInfo(label_cn="粉丝牌升级", icon="🏷️"),
    MessageType.UPGRADE: MessageKindInfo(label_cn="等级升级", icon="⬆️"),
}
