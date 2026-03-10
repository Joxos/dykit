from __future__ import annotations

import re

from dyproto import MessageType
from rich.text import Text

from .types import DanmuMessage


def render_message_text(message: DanmuMessage) -> str:
    username = message.username or "Unknown"
    match message.msg_type:
        case MessageType.CHATMSG:
            return f"{username}: {message.content or ''}"

        case MessageType.DGB:
            gift_count = message.gift_count if message.gift_count is not None else 1
            gift_name = message.gift_name or (message.gift_id or "未知礼物")
            return f"{username} 送出了 {gift_count}x {gift_name}"

        case MessageType.UENTER:
            return f"{username} 进入了直播间"

        case MessageType.ANBC:
            noble = message.noble_level or 0
            return f"{username} 开通了{noble}级贵族"

        case MessageType.RNEWBC:
            noble = message.noble_level or 0
            return f"{username} 续费了{noble}级贵族"

        case MessageType.BLAB:
            if message.badge_name and message.badge_level is not None:
                return f"{username} 粉丝牌《{message.badge_name}》升级至{message.badge_level}级"
            return f"{username} 粉丝牌升级"

        case MessageType.UPGRADE:
            if message.user_level is not None:
                return f"{username} 升级到{message.user_level}级"
            return f"{username} 升级"

    return f"{message.msg_type.value}: {message.content or ''}".strip()


_DANMU_COLOR_MAP: dict[str, str] = {
    "1": "white",
    "2": "blue",
    "3": "green",
    "4": "yellow",
    "5": "magenta",
    "6": "cyan",
}


def _style_from_danmu_color(color_value: str | None) -> str:
    if color_value is None:
        return "white"

    value = color_value.strip().lower()
    if not value:
        return "white"

    if value in _DANMU_COLOR_MAP:
        return _DANMU_COLOR_MAP[value]

    if value.startswith("rgb(") and value.endswith(")"):
        match = re.fullmatch(r"rgb\((\d{1,3}),(\d{1,3}),(\d{1,3})\)", value)
        if match is not None:
            r, g, b = (int(group) for group in match.groups())
            if 0 <= r <= 255 and 0 <= g <= 255 and 0 <= b <= 255:
                return f"#{r:02x}{g:02x}{b:02x}"

    normalized_hex = value.removeprefix("0x").removeprefix("#")
    if len(normalized_hex) == 6 and all(ch in "0123456789abcdef" for ch in normalized_hex):
        return f"#{normalized_hex}"

    if value.isdigit():
        color_int = int(value)
        if 0 <= color_int <= 0xFFFFFF:
            return f"#{color_int:06x}"

    return "white"


_TYPE_ICON_MAP: dict[MessageType, str] = {
    MessageType.CHATMSG: "💬",
    MessageType.DGB: "🎁",
    MessageType.UENTER: "🚪",
    MessageType.ANBC: "👑",
    MessageType.RNEWBC: "♻️",
    MessageType.BLAB: "🏷️",
    MessageType.UPGRADE: "⬆️",
}


def _gift_style(message: DanmuMessage) -> str:
    count = message.gift_count or 1
    if count >= 100:
        return "bold reverse"
    if count >= 10:
        return "bold underline"
    return "bold"


def render_console_line(message: DanmuMessage, room_display: str | None = None) -> Text:
    room = room_display or message.room_id
    icon = _TYPE_ICON_MAP.get(message.msg_type, "🔹")
    text = render_message_text(message)

    line = Text()
    line.append(f"[{room}] ", style="dim")
    line.append(f"{icon} ")

    if message.msg_type == MessageType.CHATMSG:
        color_code = None
        if message.raw_data is not None:
            color_code = message.raw_data.get("col")
            if color_code is None:
                color_code = message.raw_data.get("color")
        style = _style_from_danmu_color(None if color_code is None else str(color_code))
        line.append(text, style=style)
        return line

    if message.msg_type == MessageType.UENTER:
        line.append(text, style="dim")
        return line

    if message.msg_type == MessageType.DGB:
        line.append(text, style=_gift_style(message))
        return line

    line.append(text)
    return line
