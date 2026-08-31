"""Unit tests for dyproto protocol codec primitives (no network required)."""

from __future__ import annotations

from dyproto.constants import CLIENT_MSG_TYPE
from dyproto.protocol import build_packet_header, parse_packet_header, parse_packet_length

from dyproto import (
    MAX_PACKET_SIZE,
    MIN_PACKET_SIZE,
    PACKET_HEADER_SIZE,
    MessageBuffer,
    PacketHeader,
    decode_message,
    deserialize_message,
    encode_message,
    serialize_message,
)


class TestKeyValueSerialization:
    def test_serialize_escapes_at_and_slash(self) -> None:
        assert serialize_message({"a": "x@y", "b": "p/q"}) == "a@=x@Ay/b@=p@Sq/"

    def test_serialize_roundtrip_with_unicode_and_empty_values(self) -> None:
        original = {"type": "chatmsg", "txt": "你好，弹幕@测试/", "nn": "", "uid": "42"}
        assert deserialize_message(serialize_message(original)) == original

    def test_serialize_values_are_stringified(self) -> None:
        assert serialize_message({"n": 42, "f": 1.5}) == "n@=42/f@=1.5/"

    def test_deserialize_empty_string(self) -> None:
        assert deserialize_message("") == {}

    def test_deserialize_ignores_malformed_parts(self) -> None:
        assert deserialize_message("key@=value/broken/no_sep") == {"key": "value"}


class TestBinaryCodec:
    def _roundtrip(self, msg_dict: dict[str, str]) -> dict[str, str]:
        payload = serialize_message(msg_dict)
        data = encode_message(payload)
        decoded = decode_message(data)
        assert decoded is not None
        return deserialize_message(decoded)

    def test_encode_decode_roundtrip(self) -> None:
        original = {"type": "chatmsg", "txt": "hello world", "nn": "Alice", "uid": "123"}
        assert self._roundtrip(original) == original

    def test_roundtrip_unicode_and_escapes(self) -> None:
        original = {"type": "dgb", "gfn": "火箭@测试/", "nn": "礼物哥"}
        assert self._roundtrip(original) == original

    def test_decode_short_data_returns_none(self) -> None:
        assert decode_message(b"") is None
        assert decode_message(b"\x00\x01\x02") is None

    def test_decode_length_duplicate_mismatch_returns_none(self) -> None:
        header = build_packet_header(
            PacketHeader(packet_length=20, packet_length_dup=21, msg_type=689, encrypt_flag=0, reserved=0)
        )
        assert decode_message(header + b"x" * 20) is None

    def test_decode_out_of_range_length_returns_none(self) -> None:
        header = build_packet_header(
            PacketHeader(
                packet_length=MAX_PACKET_SIZE + 10,
                packet_length_dup=MAX_PACKET_SIZE + 10,
                msg_type=689,
                encrypt_flag=0,
                reserved=0,
            )
        )
        assert decode_message(header) is None

    def test_decode_incomplete_packet_returns_none(self) -> None:
        payload = serialize_message({"type": "chatmsg", "txt": "incomplete"})
        data = encode_message(payload)
        assert decode_message(data[:-2]) is None

    def test_packet_header_build_parse_roundtrip(self) -> None:
        header = PacketHeader(
            packet_length=100, packet_length_dup=100, msg_type=CLIENT_MSG_TYPE, encrypt_flag=0, reserved=0
        )
        parsed = parse_packet_header(build_packet_header(header))
        assert parsed is not None
        assert parsed == header

    def test_parse_packet_length_short_data(self) -> None:
        assert parse_packet_length(b"\x00\x01") is None

    def test_parse_packet_length_value(self) -> None:
        assert parse_packet_length(b"\x0e\x00\x00\x00") == 14

    def test_encode_message_header_fields(self) -> None:
        data = encode_message("hello")
        assert len(data) == PACKET_HEADER_SIZE + len("hello") + 1
        header = parse_packet_header(data[:PACKET_HEADER_SIZE])
        assert header is not None
        assert header.msg_type == CLIENT_MSG_TYPE
        assert header.encrypt_flag == 0
        assert header.packet_length == header.packet_length_dup


class TestMessageBuffer:
    def test_multiple_packets_in_one_frame(self) -> None:
        buffer = MessageBuffer()
        msg1 = {"type": "chatmsg", "txt": "first"}
        msg2 = {"type": "dgb", "gfn": "second"}
        buffer.add_data(encode_message(serialize_message(msg1)) + encode_message(serialize_message(msg2)))
        assert buffer.get_messages() == [msg1, msg2]

    def test_packet_split_across_frames(self) -> None:
        buffer = MessageBuffer()
        msg = {"type": "chatmsg", "txt": "split me"}
        data = encode_message(serialize_message(msg))
        buffer.add_data(data[:5])
        assert buffer.get_messages() == []
        buffer.add_data(data[5:])
        assert buffer.get_messages() == [msg]

    def test_utf8_sequence_split_across_frames(self) -> None:
        buffer = MessageBuffer()
        msg = {"type": "chatmsg", "txt": "你好斗鱼"}
        data = encode_message(serialize_message(msg))
        # Cut inside the middle of the UTF-8 encoded payload.
        cut = 15
        buffer.add_data(data[:cut])
        assert buffer.get_messages() == []
        buffer.add_data(data[cut:])
        assert buffer.get_messages() == [msg]

    def test_invalid_length_clears_buffer(self) -> None:
        buffer = MessageBuffer()
        buffer.add_data(b"\xff\xff\xff\xff" + b"junk")
        assert buffer.get_messages() == []
        assert len(buffer) == 0

    def test_empty_buffer(self) -> None:
        assert MessageBuffer().get_messages() == []

    def test_min_packet_size_respected(self) -> None:
        buffer = MessageBuffer()
        # Header claiming a too-small packet: below MIN_PACKET_SIZE total.
        header = build_packet_header(
            PacketHeader(
                packet_length=MIN_PACKET_SIZE - 5,
                packet_length_dup=MIN_PACKET_SIZE - 5,
                msg_type=689,
                encrypt_flag=0,
                reserved=0,
            )
        )
        buffer.add_data(header)
        assert buffer.get_messages() == []
        assert len(buffer) == 0
