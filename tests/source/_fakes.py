"""Fake HTTP layer for the source layer - no network, no extra dependency."""

from __future__ import annotations

import json
from types import ModuleType
from typing import Any

import httpx
import pytest


class FakeResponse:
    """Minimal stand-in for httpx.Response as the source layer uses it."""

    def __init__(self, text: str = "", payload: Any = None, status: int = 200) -> None:
        self.text = text
        self._payload = payload
        self._status = status

    def raise_for_status(self) -> None:
        if self._status >= 400:
            request = httpx.Request("GET", "https://example.invalid")
            raise httpx.HTTPStatusError(
                f"status {self._status}", request=request, response=httpx.Response(self._status)
            )

    def json(self) -> Any:
        if self._payload is None:
            raise ValueError("no json payload")
        return self._payload


class HttpStub:
    """Route handler installed over a source module's ``http_get``.

    ``routes`` maps a URL substring to either a FakeResponse, an exception
    instance (raised), or a callable taking the url.
    """

    def __init__(self, routes: dict[str, Any], default: Any = None) -> None:
        self.routes = routes
        self.default = default
        self.calls: list[str] = []

    def __call__(self, url: str, timeout: float) -> FakeResponse:
        self.calls.append(url)
        for fragment, result in self.routes.items():
            if fragment not in url:
                continue
            if isinstance(result, BaseException):
                raise result
            if isinstance(result, FakeResponse):
                return result
            return result(url, timeout)
        if self.default is None:
            raise AssertionError(f"unexpected URL: {url}")
        if isinstance(self.default, BaseException):
            raise self.default
        return self.default

    def install(self, monkeypatch: pytest.MonkeyPatch, module: ModuleType) -> None:
        monkeypatch.setattr(module, "http_get", self)


def room_page(port: int) -> str:
    """HTML shaped like a Douyu room page that names the danmu proxy port."""
    return (
        "<html><body><script>var roomInfo = "
        f'"{{\\"danmuproxy\\":\\"https://danmuproxy.douyu.com:{port}/\\"}}";'
        "</script></body></html>"
    )


def json_response(payload: Any) -> FakeResponse:
    return FakeResponse(text=json.dumps(payload), payload=payload)
