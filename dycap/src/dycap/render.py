from __future__ import annotations

from dyproto import MessageType

from .types import DanmuMessage


def render_message_text(message: DanmuMessage) -> str:
    username = message.username or "Unknown"
    if message.msg_type == MessageType.CHATMSG:
        return f"{username}: {message.content or ''}"

    if message.msg_type == MessageType.DGB:
        gift_count = message.gift_count if message.gift_count is not None else 1
        gift_name = message.gift_name or (message.gift_id or "未知礼物")
        return f"{username} 送出了 {gift_count}x {gift_name}"

    if message.msg_type == MessageType.UENTER:
        return f"{username} 进入了直播间"

    if message.msg_type == MessageType.ANBC:
        noble = message.noble_level or 0
        return f"{username} 开通了{noble}级贵族"

    if message.msg_type == MessageType.RNEWBC:
        noble = message.noble_level or 0
        return f"{username} 续费了{noble}级贵族"

    if message.msg_type == MessageType.BLAB:
        if message.badge_name and message.badge_level is not None:
            return f"{username} 粉丝牌《{message.badge_name}》升级至{message.badge_level}级"
        return f"{username} 粉丝牌升级"

    if message.msg_type == MessageType.UPGRADE:
        if message.user_level is not None:
            return f"{username} 升级到{message.user_level}级"
        return f"{username} 升级"

    return f"{message.msg_type.value}: {message.content or ''}".strip()
