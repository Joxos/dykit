"""Unit tests for the protocol message-type registry."""

from __future__ import annotations

from dykit.protocol import MSG_TYPE_TO_ENUM, MessageType


class TestStringToEnumMap:
    def test_covers_recognized_types(self) -> None:
        assert MSG_TYPE_TO_ENUM["chatmsg"] is MessageType.CHATMSG
        assert MSG_TYPE_TO_ENUM["dgb"] is MessageType.DGB
        assert MSG_TYPE_TO_ENUM["uenter"] is MessageType.UENTER
        assert MSG_TYPE_TO_ENUM["anbc"] is MessageType.ANBC
        assert MSG_TYPE_TO_ENUM["rnewbc"] is MessageType.RNEWBC
        assert MSG_TYPE_TO_ENUM["blab"] is MessageType.BLAB
        assert MSG_TYPE_TO_ENUM["upgrade"] is MessageType.UPGRADE

    def test_map_and_enum_stay_in_step(self) -> None:
        """Every modelled type must have a wire string, and vice versa."""
        assert set(MSG_TYPE_TO_ENUM.values()) == set(MessageType)
        assert set(MSG_TYPE_TO_ENUM) == {member.value for member in MessageType}

    def test_all_values_are_valid_enum_members(self) -> None:
        for value in MSG_TYPE_TO_ENUM.values():
            assert isinstance(value, MessageType)

    def test_enum_value_is_wire_string(self) -> None:
        assert MessageType.CHATMSG.value == "chatmsg"
