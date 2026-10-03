"""Tests for source.server - danmu WebSocket endpoint discovery."""

from __future__ import annotations

import httpx
import pytest

from dykit.source import server as server_module
from dykit.source.server import DEFAULT_PORTS, get_danmu_server

from ._fakes import FakeResponse, HttpStub, room_page


def _stub_room(monkeypatch: pytest.MonkeyPatch, room_id: int) -> None:
    """Room resolution is exercised in test_room.py; stub it out here."""

    def fake_resolve(value: int | str, timeout: float = 10.0) -> int:
        _ = (value, timeout)
        return room_id

    monkeypatch.setattr(server_module, "resolve_room_id", fake_resolve)


@pytest.fixture(autouse=True)
def fixed_room(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_room(monkeypatch, 6657)


class TestManualUrl:
    def test_manual_url_short_circuits_discovery(self, monkeypatch: pytest.MonkeyPatch) -> None:
        stub = HttpStub({})
        stub.install(monkeypatch, server_module)

        urls, room_id = get_danmu_server(6657, manual_url="wss://manual.example/ws")

        assert urls == ["wss://manual.example/ws"]
        assert room_id == 6657
        assert stub.calls == []


class TestPortDiscovery:
    def test_defaults_when_no_port_in_page(self, monkeypatch: pytest.MonkeyPatch) -> None:
        HttpStub({}, default=FakeResponse(text="<html><body>no scripts</body></html>")).install(
            monkeypatch, server_module
        )

        urls, _room_id = get_danmu_server(6657)

        assert urls == [f"wss://danmuproxy.douyu.com:{port}/" for port in DEFAULT_PORTS]

    def test_defaults_when_the_page_request_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        HttpStub({}, default=httpx.ConnectError("offline")).install(monkeypatch, server_module)

        urls, _room_id = get_danmu_server(6657)

        assert len(urls) == len(DEFAULT_PORTS)

    def test_discovered_default_port_comes_first(self, monkeypatch: pytest.MonkeyPatch) -> None:
        first = DEFAULT_PORTS[1]
        HttpStub({}, default=FakeResponse(text=room_page(first))).install(
            monkeypatch, server_module
        )

        urls, _room_id = get_danmu_server(6657)

        assert urls[0] == f"wss://danmuproxy.douyu.com:{first}/"
        assert len(urls) == len(DEFAULT_PORTS)
        assert first not in [url.rsplit(":", 1)[1].strip("/'") for url in urls[1:]]

    def test_non_default_port_is_used_alone(self, monkeypatch: pytest.MonkeyPatch) -> None:
        HttpStub({}, default=FakeResponse(text=room_page(9501))).install(monkeypatch, server_module)

        urls, _room_id = get_danmu_server(6657)

        assert urls == ["wss://danmuproxy.douyu.com:9501/"]

    def test_resolved_room_id_is_returned(self, monkeypatch: pytest.MonkeyPatch) -> None:
        HttpStub({}, default=FakeResponse(text="<html></html>")).install(monkeypatch, server_module)
        _stub_room(monkeypatch, 42)

        _urls, room_id = get_danmu_server("some-room")

        assert room_id == 42

    def test_port_is_read_from_any_script_tag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        page = (
            "<html><body>"
            "<script>var a = 1;</script>"
            "<script>var u = 'https://danmuproxy.douyu.com:8502/';</script>"
            "</body></html>"
        )
        HttpStub({}, default=FakeResponse(text=page)).install(monkeypatch, server_module)

        urls, _room_id = get_danmu_server(6657)

        assert urls[0] == "wss://danmuproxy.douyu.com:8502/"
