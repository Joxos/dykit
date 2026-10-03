"""Tests for source.room - room ID resolution.

Every HTTP call is stubbed; the point of these tests is the fallback chain
and the "one dead source must not abort the lookup" contract.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from dykit.source import room as room_module
from dykit.source.room import RoomResolutionError, resolve_room_id

from ._fakes import FakeResponse, HttpStub, json_response


def _install(monkeypatch: pytest.MonkeyPatch, stub: HttpStub) -> HttpStub:
    stub.install(monkeypatch, room_module)
    return stub


class TestNumericInputs:
    def test_large_numeric_id_short_circuits(self, monkeypatch: pytest.MonkeyPatch) -> None:
        stub = _install(monkeypatch, HttpStub({}))

        assert resolve_room_id(6979222) == 6979222
        assert stub.calls == []

    def test_small_numeric_id_is_resolved(self, monkeypatch: pytest.MonkeyPatch) -> None:
        stub = _install(
            monkeypatch,
            HttpStub({"betard": json_response({"room": {"room_id": 6657}})}),
        )

        assert resolve_room_id(6657) == 6657
        assert len(stub.calls) == 1


class TestFallbackChain:
    def test_betard_api_is_primary(self, monkeypatch: pytest.MonkeyPatch) -> None:
        stub = _install(
            monkeypatch,
            HttpStub({"betard": json_response({"room": {"room_id": 6657}})}),
        )

        assert resolve_room_id("longzhu") == 6657
        assert stub.calls == ["https://www.douyu.com/betard/longzhu"]

    def test_mobile_page_used_when_api_errors(self, monkeypatch: pytest.MonkeyPatch) -> None:
        stub = _install(
            monkeypatch,
            HttpStub(
                {
                    "betard": httpx.ConnectError("boom"),
                    "m.douyu.com": FakeResponse(text='{"rid":6979222}'),
                }
            ),
        )

        assert resolve_room_id("longzhu") == 6979222
        assert len(stub.calls) == 2

    def test_desktop_page_used_when_mobile_has_no_rid(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stub = _install(
            monkeypatch,
            HttpStub(
                {
                    "betard": json_response({"room": {}}),
                    "m.douyu.com": FakeResponse(text="no rid here"),
                    "www.douyu.com": FakeResponse(text='var x = {"room_id": "9988776"};'),
                }
            ),
        )

        assert resolve_room_id("longzhu") == 9988776
        assert len(stub.calls) == 3

    def test_error_in_one_source_does_not_abort_the_lookup(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stub = _install(
            monkeypatch,
            HttpStub(
                {
                    "betard": json_response({"room": {"room_id": "not-a-number"}}),
                    "m.douyu.com": FakeResponse(text='{"rid":123}'),
                }
            ),
        )

        assert resolve_room_id("longzhu") == 123
        assert len(stub.calls) == 2

    def test_all_sources_fail_falls_back_to_numeric_input(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stub = _install(
            monkeypatch,
            HttpStub({}, default=FakeResponse(text="nothing useful")),
        )

        assert resolve_room_id("6657") == 6657
        assert len(stub.calls) == 3

    def test_unresolvable_vanity_name_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The message must name the room, not leak Python's int() error."""
        _install(monkeypatch, HttpStub({}, default=FakeResponse(text="nothing useful")))

        with pytest.raises(RoomResolutionError, match="no-such-room") as excinfo:
            resolve_room_id("no-such-room")

        assert "invalid literal for int" not in str(excinfo.value)


class TestRequestShape:
    def test_vanity_name_is_stripped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        stub = _install(
            monkeypatch,
            HttpStub({"betard": json_response({"room": {"room_id": 6657}})}),
        )

        assert resolve_room_id("  longzhu  ") == 6657
        assert stub.calls == ["https://www.douyu.com/betard/longzhu"]

    def test_timeout_is_passed_through(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: list[tuple[str, float]] = []

        def handler(url: str, timeout: float) -> Any:
            seen.append((url, timeout))
            return json_response({"room": {"room_id": 6657}})

        _install(monkeypatch, HttpStub({"betard": handler}))

        assert resolve_room_id("longzhu", timeout=2.5) == 6657
        assert seen == [("https://www.douyu.com/betard/longzhu", 2.5)]
