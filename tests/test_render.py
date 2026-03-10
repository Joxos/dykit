from __future__ import annotations

from datetime import datetime

from dycap.render import render_console_line
from dycap.types import DanmuMessage, MessageType


def _chat_message(*, col: str | None) -> DanmuMessage:
    raw_data = {"type": "chatmsg", "txt": "hello"}
    if col is not None:
        raw_data["col"] = col
    return DanmuMessage(
        timestamp=datetime(2026, 3, 10, 12, 0, 0),
        room_id="6657",
        msg_type=MessageType.CHATMSG,
        username="Alice",
        content="hello",
        raw_data=raw_data,
    )


def test_render_console_line_chatmsg_uses_named_palette_color() -> None:
    rendered = render_console_line(_chat_message(col="2"))
    assert rendered.plain == "[6657] 💬 Alice: hello"
    assert any(span.style == "blue" for span in rendered.spans)


def test_render_console_line_chatmsg_uses_hex_color() -> None:
    rendered = render_console_line(_chat_message(col="#ff0000"))
    assert rendered.plain == "[6657] 💬 Alice: hello"
    assert any(span.style == "#ff0000" for span in rendered.spans)


def test_render_console_line_chatmsg_uses_decimal_color() -> None:
    rendered = render_console_line(_chat_message(col="255"))
    assert rendered.plain == "[6657] 💬 Alice: hello"
    assert any(span.style == "#0000ff" for span in rendered.spans)


def test_render_console_line_uenter_is_dim() -> None:
    rendered = render_console_line(
        DanmuMessage(
            timestamp=datetime(2026, 3, 10, 12, 0, 0),
            room_id="6657",
            msg_type=MessageType.UENTER,
            username="Visitor",
        )
    )
    assert rendered.plain == "[6657] 🚪 Visitor 进入了直播间"
    assert any(span.style == "dim" for span in rendered.spans)


def test_render_console_line_gift_uses_distinct_style() -> None:
    rendered = render_console_line(
        DanmuMessage(
            timestamp=datetime(2026, 3, 10, 12, 0, 0),
            room_id="6657",
            msg_type=MessageType.DGB,
            username="Donor",
            gift_name="火箭",
            gift_count=20,
        )
    )
    assert rendered.plain == "[6657] 🎁 Donor 送出了 20x 火箭"
    assert any(span.style == "bold underline" for span in rendered.spans)
