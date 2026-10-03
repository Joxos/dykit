"""Presentation metadata: label and icon per message type.

Lives in the collect layer, not the protocol layer - the wire format has no
opinion about how a gift is labelled or which emoji it gets.
"""

from __future__ import annotations

from dykit.collect.render import MESSAGE_KINDS, UNKNOWN_KIND, MessageKindInfo
from dykit.protocol import MessageType


class TestMessageKinds:
    def test_covers_every_enum_member(self) -> None:
        assert set(MESSAGE_KINDS) == set(MessageType)

    def test_entries_have_labels_and_icons(self) -> None:
        for info in MESSAGE_KINDS.values():
            assert isinstance(info, MessageKindInfo)
            assert info.label_cn
            assert info.icon

    def test_known_chinese_labels(self) -> None:
        assert MESSAGE_KINDS[MessageType.CHATMSG].label_cn == "弹幕"
        assert MESSAGE_KINDS[MessageType.DGB].label_cn == "礼物"
        assert MESSAGE_KINDS[MessageType.UENTER].label_cn == "进场"

    def test_unknown_kind_fallback(self) -> None:
        assert UNKNOWN_KIND.label_cn == "未知"
        assert UNKNOWN_KIND.icon
