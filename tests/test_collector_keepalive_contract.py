from __future__ import annotations

import ssl
from typing import Any

import pytest

from dykit.collectors.async_ import DOUYU_WS_CONNECT_KWARGS, AsyncCollector
from dykit.storage.base import StorageHandler


class _DummyStorage(StorageHandler):
    async def save(self, message: Any) -> None:
        _ = message

    async def close(self) -> None:
        return None


class _ProbeCollector(AsyncCollector):
    async def probe_connect_kwargs(self, ssl_context: ssl.SSLContext) -> Any:
        return await self._connect_with_retry("wss://example", ssl_context)

    async def run_heartbeat_once(self) -> None:
        await self._heartbeat_loop()

    def seed_heartbeat_state(self) -> None:
        self._running = True
        self._websocket = object()

    def stop_running(self) -> None:
        self._running = False


@pytest.mark.asyncio
async def test_connect_uses_protocol_keepalive_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    collector = _ProbeCollector(room_id="6657", storage=_DummyStorage())
    captured: dict[str, Any] = {}

    async def fake_connect(*args: Any, **kwargs: Any) -> str:
        _ = args
        captured.update(kwargs)
        return "ok"

    monkeypatch.setattr("dykit.collectors.async_.websockets.connect", fake_connect)
    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    result = await collector.probe_connect_kwargs(ssl_context)

    assert result == "ok"
    assert captured["ping_interval"] is None
    assert captured["ping_timeout"] is None
    assert DOUYU_WS_CONNECT_KWARGS["ping_interval"] is None
    assert DOUYU_WS_CONNECT_KWARGS["ping_timeout"] is None


@pytest.mark.asyncio
async def test_heartbeat_loop_sends_mrkl(monkeypatch: pytest.MonkeyPatch) -> None:
    collector = _ProbeCollector(room_id="6657", storage=_DummyStorage())
    collector.seed_heartbeat_state()

    sent_payloads: list[bytes] = []

    async def fake_send(payload: bytes) -> None:
        sent_payloads.append(payload)
        collector.stop_running()

    async def fake_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(collector, "_send_with_retry", fake_send)
    monkeypatch.setattr("dykit.collectors.async_.asyncio.sleep", fake_sleep)

    await collector.run_heartbeat_once()

    assert sent_payloads
    assert b"type@=mrkl" in sent_payloads[0]
