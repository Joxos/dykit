"""Unit tests for dyproto message-type registry (single source of truth)."""

from __future__ import annotations

from dyproto import MESSAGE_KINDS, MSG_TYPE_TO_ENUM, UNKNOWN_KIND, MessageKindInfo, MessageType


class TestMessageTypeRegistry:
    def test_registry_covers_every_enum_member(self) -> None:
        assert set(MESSAGE_KINDS.keys()) == set(MessageType)

    def test_registry_entries_have_labels_and_icons(self) -> None:
        for kind in MessageType:
            info = MESSAGE_KINDS[kind]
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


class TestStringToEnumMap:
    def test_covers_recognized_types(self) -> None:
        assert MSG_TYPE_TO_ENUM["chatmsg"] is MessageType.CHATMSG
        assert MSG_TYPE_TO_ENUM["dgb"] is MessageType.DGB
        assert MSG_TYPE_TO_ENUM["uenter"] is MessageType.UENTER
        assert MSG_TYPE_TO_ENUM["anbc"] is MessageType.ANBC
        assert MSG_TYPE_TO_ENUM["rnewbc"] is MessageType.RNEWBC
        assert MSG_TYPE_TO_ENUM["blab"] is MessageType.BLAB
        assert MSG_TYPE_TO_ENUM["upgrade"] is MessageType.UPGRADE

    def test_all_values_are_valid_enum_members(self) -> None:
        for value in MSG_TYPE_TO_ENUM.values():
            assert isinstance(value, MessageType)

    def test_enum_value_is_wire_string(self) -> None:
        assert MessageType.CHATMSG.value == "chatmsg"
