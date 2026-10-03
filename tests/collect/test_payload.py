"""Tests for collect.payload - Douyu payload -> DanmuMessage mapping."""

from __future__ import annotations

from datetime import datetime

from dykit.collect.payload import (
    build_chat_message,
    build_structured_message,
    resolve_message_type,
    should_skip,
)
from dykit.protocol import MessageType

STAMP = datetime(2026, 3, 7, 10, 0, 0, 123456)
ROOM = 6657


class TestResolveMessageType:
    def test_known_structured_type_is_mapped(self) -> None:
        assert resolve_message_type("dgb") is MessageType.DGB

    def test_unknown_type_is_not_collected(self) -> None:
        assert resolve_message_type("some_new_douyu_type") is None

    def test_chatmsg_is_not_a_structured_type(self) -> None:
        assert resolve_message_type("chatmsg") is None


class TestShouldSkip:
    def test_no_filters_keeps_everything(self) -> None:
        assert should_skip("dgb", None, None) is False

    def test_include_filter_drops_unlisted(self) -> None:
        assert should_skip("uenter", ["chatmsg", "dgb"], None) is True
        assert should_skip("dgb", ["chatmsg", "dgb"], None) is False

    def test_exclude_filter_drops_listed(self) -> None:
        assert should_skip("uenter", None, ["uenter"]) is True
        assert should_skip("dgb", None, ["uenter"]) is False


class TestBuildChatMessage:
    def test_common_fields_are_extracted(self) -> None:
        message = build_chat_message(
            {
                "nn": "  alice  ",
                "txt": " hello  ",
                "level": "18",
                "uid": "u1",
                "col": "2",
                "ct": "web",
                "ic": "https://a/b.png",
                "bl": "12",
                "bnn": "粉丝牌",
                "brid": "6657",
                "type": "chatmsg",
            },
            ROOM,
            STAMP,
        )

        assert message.msg_type is MessageType.CHATMSG
        assert message.timestamp == STAMP
        assert message.room_id == "6657"
        assert message.username == "alice"
        assert message.content == "hello"
        assert message.user_level == 18
        assert message.user_id == "u1"
        assert message.color == "2"
        assert message.client_type == "web"
        assert message.avatar_url == "https://a/b.png"
        assert message.badge_level == 12
        assert message.badge_name == "粉丝牌"
        assert message.badge_room_id == "6657"

    def test_missing_nickname_falls_back_to_unknown(self) -> None:
        message = build_chat_message({}, ROOM, STAMP)

        assert message.username == "Unknown"
        assert message.content == ""

    def test_non_numeric_level_and_badge_degrade_to_defaults(self) -> None:
        message = build_chat_message({"level": "N/A", "bl": "?"}, ROOM, STAMP)

        assert message.user_level == 0
        assert message.badge_level is None

    def test_raw_payload_is_preserved(self) -> None:
        payload = {"type": "chatmsg", "txt": "hi", "unknown_field": "kept"}
        message = build_chat_message(payload, ROOM, STAMP)

        assert message.raw_data == payload


class TestBuildStructuredMessage:
    def test_gift_fields_from_gfn(self) -> None:
        message = build_structured_message(
            {
                "nn": "GiftUser",
                "uid": "u2001",
                "level": "18",
                "gfid": "g1",
                "gfcnt": "3",
                "gfn": "火箭",
                "type": "dgb",
            },
            MessageType.DGB,
            ROOM,
            STAMP,
        )

        assert message.gift_id == "g1"
        assert message.gift_count == 3
        assert message.gift_name == "火箭"

    def test_gift_name_falls_back_to_gftype(self) -> None:
        message = build_structured_message(
            {"gftype": "小星星", "gfcnt": "1"}, MessageType.DGB, ROOM, STAMP
        )

        assert message.gift_name == "小星星"

    def test_gift_count_and_hits_accept_only_digits(self) -> None:
        message = build_structured_message(
            {"gfcnt": "many", "hits": "12"}, MessageType.DGB, ROOM, STAMP
        )

        assert message.gift_count is None
        assert message.gift_hits == 12

    def test_noble_level_zero_is_normalized_to_none(self) -> None:
        message = build_structured_message({"nl": "0"}, MessageType.ANBC, ROOM, STAMP)

        assert message.noble_level is None

    def test_noble_fields_for_anbc(self) -> None:
        message = build_structured_message(
            {"nn": "noble", "nl": "12", "gfid": "g9"}, MessageType.ANBC, ROOM, STAMP
        )

        assert message.noble_level == 12
        assert message.gift_id == "g9"

    def test_avatar_falls_back_to_av(self) -> None:
        message = build_structured_message(
            {"av": "https://x/y.png"}, MessageType.UENTER, ROOM, STAMP
        )

        assert message.avatar_url == "https://x/y.png"

    def test_enter_message_has_no_gift_fields(self) -> None:
        message = build_structured_message({"nn": "bob"}, MessageType.UENTER, ROOM, STAMP)

        assert message.username == "bob"
        assert message.gift_id is None
        assert message.gift_count is None
        assert message.noble_level is None

    def test_empty_username_becomes_none(self) -> None:
        message = build_structured_message({"nn": "  "}, MessageType.BLAB, ROOM, STAMP)

        assert message.username is None

    def test_non_numeric_level_becomes_none(self) -> None:
        message = build_structured_message({"level": "-"}, MessageType.BLAB, ROOM, STAMP)

        assert message.user_level is None
