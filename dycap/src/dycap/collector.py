"""Asynchronous collector for Douyu danmu messages."""

from __future__ import annotations

import asyncio
import re
import ssl
from collections.abc import Callable
from datetime import datetime
from typing import Any

import websockets
from dyproto import (
    MSG_TYPE_TO_ENUM,
    MessageBuffer,
    MessageType,
    encode_message,
    serialize_message,
)
from dysource import get_danmu_server
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential
from websockets import Origin
from websockets.exceptions import ConnectionClosed

from .constants import (
    RETRY_ATTEMPTS_WS_CONNECT,
    RETRY_ATTEMPTS_WS_SEND,
    RETRY_BACKOFF_WS_CONNECT_MAX_SECONDS,
    RETRY_BACKOFF_WS_CONNECT_MIN_SECONDS,
    RETRY_BACKOFF_WS_CONNECT_MULTIPLIER,
    RETRY_BACKOFF_WS_SEND_MAX_SECONDS,
    RETRY_BACKOFF_WS_SEND_MIN_SECONDS,
    RETRY_BACKOFF_WS_SEND_MULTIPLIER,
    WS_DOUYU_HEARTBEAT_SECONDS,
    WS_READ_IDLE_TIMEOUT_SECONDS,
    WS_RECOVERY_BACKOFF_SECONDS,
)
from .render import render_message_text
from .storage import StorageHandler
from .types import DanmuMessage

# WebSocket connect kwargs (ping disabled per keepalive contract)
DOUYU_WS_CONNECT_KWARGS: dict[str, Any] = {
    "ping_interval": None,
    "ping_timeout": None,
}


class AsyncCollector:
    """Asynchronous WebSocket collector for Douyu danmu messages.

    This collector connects to Douyu's danmu WebSocket server,
    receives and parses messages, and persists them via a StorageHandler.

    Example:
        from dycap import AsyncCollector, PostgreSQLStorage

        storage = await PostgreSQLStorage.create(room_id="6657", ...)
        collector = AsyncCollector("6657", storage)

        try:
            await collector.connect()
        except KeyboardInterrupt:
            await collector.stop()
    """

    def __init__(
        self,
        room_id: str,
        storage: StorageHandler,
        ws_url: str | None = None,
        type_filter: list[str] | None = None,
        type_exclude: list[str] | None = None,
        message_callback: Callable[[DanmuMessage], None] | None = None,
    ) -> None:
        """Initialize the collector.

        Args:
            room_id: Douyu room ID to collect from.
            storage: Storage handler for persisting messages.
            ws_url: Optional WebSocket URL override.
            type_filter: Optional list of message types to collect.
            type_exclude: Optional list of message types to exclude.
        """
        self.room_id = room_id
        self.storage = storage
        self.ws_url_override = ws_url
        self.type_filter = type_filter
        self.type_exclude = type_exclude
        self.message_callback = message_callback

        self._buffer = MessageBuffer()
        self._running = False
        self._websocket: Any = None
        self._real_room_id: int = 0
        self._last_discovery_time = 0.0
        self._candidate_urls: list[str] = []
        self._candidate_index = 0
        self._heartbeat_task: asyncio.Task[None] | None = None

    async def connect(self) -> None:
        """Connect to Douyu WebSocket server and start receiving messages.

        This method runs until the connection closes or stop() is called.
        """
        self._running = True

        # SSL context for Douyu servers
        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        ssl_context.set_ciphers("DEFAULT@SECLEVEL=1")

        try:
            while self._running:
                await self._refresh_candidates_if_needed(force=not self._candidate_urls)

                if not self._candidate_urls:
                    await asyncio.sleep(WS_RECOVERY_BACKOFF_SECONDS)
                    continue

                cycle_errors: list[str] = []
                for _ in range(len(self._candidate_urls)):
                    url = self._candidate_urls[self._candidate_index % len(self._candidate_urls)]
                    self._candidate_index += 1

                    try:
                        websocket = await self._connect_with_retry(url, ssl_context)
                        async with websocket:
                            self._websocket = websocket
                            await self._send_login()
                            await self._send_joingroup()
                            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
                            await self._process_messages()
                    except asyncio.CancelledError:
                        raise
                    except Exception as e:
                        cycle_errors.append(str(e))
                        await self._stop_heartbeat()
                        self._websocket = None
                        await self._refresh_candidates_if_needed(force=True)
                        continue

                if cycle_errors:
                    await asyncio.sleep(WS_RECOVERY_BACKOFF_SECONDS)
                    await self._refresh_candidates_if_needed(force=True)
        finally:
            await self._stop_heartbeat()
            self._websocket = None
            self._running = False

    async def stop(self) -> None:
        """Stop the collector gracefully."""
        self._running = False
        if self._websocket:
            await self._websocket.close()

    async def _connect_with_retry(self, url: str, ssl_context: ssl.SSLContext) -> Any:
        """Connect with retries."""
        retryer = AsyncRetrying(
            stop=stop_after_attempt(RETRY_ATTEMPTS_WS_CONNECT),
            wait=wait_exponential(
                multiplier=RETRY_BACKOFF_WS_CONNECT_MULTIPLIER,
                min=RETRY_BACKOFF_WS_CONNECT_MIN_SECONDS,
                max=RETRY_BACKOFF_WS_CONNECT_MAX_SECONDS,
            ),
            retry=retry_if_exception_type(Exception),
            reraise=True,
        )

        async for attempt in retryer:
            with attempt:
                return await websockets.connect(
                    url,
                    ssl=ssl_context,
                    origin=Origin("https://www.douyu.com"),
                    **DOUYU_WS_CONNECT_KWARGS,
                )

        raise RuntimeError("WebSocket connection retry exhausted")

    async def _send_with_retry(self, payload: bytes) -> None:
        """Send payload with retries."""
        if not self._websocket:
            raise RuntimeError("WebSocket not connected")

        retryer = AsyncRetrying(
            stop=stop_after_attempt(RETRY_ATTEMPTS_WS_SEND),
            wait=wait_exponential(
                multiplier=RETRY_BACKOFF_WS_SEND_MULTIPLIER,
                min=RETRY_BACKOFF_WS_SEND_MIN_SECONDS,
                max=RETRY_BACKOFF_WS_SEND_MAX_SECONDS,
            ),
            retry=retry_if_exception_type(Exception),
            reraise=True,
        )

        async for attempt in retryer:
            with attempt:
                await self._websocket.send(payload)
                return

    async def _send_login(self) -> None:
        """Send login request."""
        if not self._websocket:
            raise RuntimeError("WebSocket not connected")

        login_msg = serialize_message({"type": "loginreq", "roomid": self._real_room_id})
        await self._send_with_retry(encode_message(login_msg))

    async def _send_joingroup(self) -> None:
        """Send join group request."""
        if not self._websocket:
            raise RuntimeError("WebSocket not connected")

        joingroup_msg = serialize_message(
            {
                "type": "joingroup",
                "rid": self._real_room_id,
                "gid": -9999,
            }
        )
        await self._send_with_retry(encode_message(joingroup_msg))

    async def _refresh_candidates_if_needed(self, force: bool = False) -> None:
        """Refresh danmu server candidates if needed."""
        now = asyncio.get_running_loop().time()
        if not force and (now - self._last_discovery_time) < 25:
            return

        self._candidate_urls, self._real_room_id = await asyncio.to_thread(
            get_danmu_server, self.room_id, 10.0, self.ws_url_override
        )
        self._last_discovery_time = now
        if self._candidate_index >= len(self._candidate_urls):
            self._candidate_index = 0

    async def _heartbeat_loop(self) -> None:
        """Send heartbeat messages periodically."""
        while self._running and self._websocket:
            await asyncio.sleep(WS_DOUYU_HEARTBEAT_SECONDS)
            if not self._running or not self._websocket:
                return
            heartbeat_msg = serialize_message({"type": "mrkl"})
            await self._send_with_retry(encode_message(heartbeat_msg))

    async def _stop_heartbeat(self) -> None:
        """Stop heartbeat task."""
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
            self._heartbeat_task = None

    async def _process_messages(self) -> None:
        """Main message receive loop."""
        if not self._websocket:
            raise RuntimeError("WebSocket not connected")

        try:
            while self._running and self._websocket:
                message = await asyncio.wait_for(
                    self._websocket.recv(), timeout=WS_READ_IDLE_TIMEOUT_SECONDS
                )
                if not self._running:
                    break

                if isinstance(message, str):
                    message_data = message.encode("utf-8", errors="ignore")
                else:
                    message_data = message

                self._buffer.add_data(message_data)
                for msg_dict in self._buffer.get_messages():
                    msg_type = msg_dict.get("type", "unknown")
                    await self._handle_message(msg_type, msg_dict)

        except asyncio.CancelledError:
            raise
        except ConnectionClosed:
            raise
        except TimeoutError:
            raise

    async def _handle_message(self, msg_type: str, msg_dict: dict[str, str]) -> None:
        """Handle received message by type."""
        match msg_type:
            case "loginres":
                return
            case "chatmsg":
                if self._should_skip_message(msg_type):
                    return
                await self._handle_chat_message(msg_dict)
                return
            case _:
                pass

        if self._should_skip_message(msg_type):
            return

        enum_value = MSG_TYPE_TO_ENUM.get(msg_type)
        if enum_value is None or enum_value == MessageType.CHATMSG:
            return

        await self._handle_structured_message(msg_dict, enum_value)

    def _should_skip_message(self, msg_type: str) -> bool:
        """Check if message should be skipped based on filters."""
        if self.type_filter and msg_type not in self.type_filter:
            return True
        if self.type_exclude and msg_type in self.type_exclude:
            return True
        return False

    async def _handle_chat_message(self, msg_dict: dict[str, str]) -> None:
        """Handle chat message."""
        nickname = re.sub(r"^\s+|\s+$", "", msg_dict.get("nn", "Unknown"))
        content = re.sub(r"^\s+|\s+$", "", msg_dict.get("txt", ""))
        level = msg_dict.get("level", "0")
        uid = msg_dict.get("uid", "0")

        danmu_message = DanmuMessage(
            timestamp=datetime.now(),
            username=nickname,
            content=content,
            user_level=int(level) if level.isdigit() else 0,
            user_id=uid,
            room_id=str(self._real_room_id),
            msg_type=MessageType.CHATMSG,
            color=msg_dict.get("col") or msg_dict.get("color"),
            raw_data=msg_dict,
        )

        await self.storage.save(danmu_message)
        if self.message_callback is not None:
            self.message_callback(danmu_message)

    async def _handle_structured_message(
        self, msg_dict: dict[str, str], msg_type: MessageType
    ) -> None:
        """Handle structured message (gift, enter, etc.)."""
        danmu_message = self._build_danmu_message(msg_dict, msg_type)
        await self.storage.save(danmu_message)
        if self.message_callback is not None:
            self.message_callback(danmu_message)

    @staticmethod
    def render_message_text(message: DanmuMessage) -> str:
        return render_message_text(message)

    def _build_danmu_message(self, msg_dict: dict[str, str], msg_type: MessageType) -> DanmuMessage:
        """Build DanmuMessage from raw dict."""
        # Extract common fields
        nickname = re.sub(r"^\s+|\s+$", "", msg_dict.get("nn", ""))
        level = msg_dict.get("level", "0")
        uid = msg_dict.get("uid", "0")

        payload: dict[str, Any] = {
            "timestamp": datetime.now(),
            "room_id": str(self._real_room_id),
            "msg_type": msg_type,
            "user_id": uid or None,
            "username": nickname or None,
            "user_level": int(level) if level.isdigit() else None,
            "color": msg_dict.get("col") or msg_dict.get("color"),
            "raw_data": msg_dict,
        }

        match msg_type:
            case MessageType.DGB | MessageType.ANBC | MessageType.RNEWBC:
                payload.update(
                    {
                        "gift_id": msg_dict.get("gfid"),
                        "gift_count": int(gfcnt)
                        if (gfcnt := msg_dict.get("gfcnt", "")).isdigit()
                        else None,
                        "gift_name": msg_dict.get("gfn") or msg_dict.get("gftype"),
                        "noble_level": int(msg_dict.get("nl", "0")) or None,
                    }
                )
            case MessageType.UENTER:
                payload.update(
                    {
                        "badge_level": int(msg_dict.get("bl", "0")) or None,
                        "badge_name": msg_dict.get("bnn"),
                        "avatar_url": msg_dict.get("ic") or msg_dict.get("av"),
                    }
                )
            case MessageType.BLAB:
                payload.update(
                    {
                        "badge_level": int(msg_dict.get("bl", "0")) or None,
                        "badge_name": msg_dict.get("bnn"),
                    }
                )
            case _:
                pass

        return DanmuMessage(**payload)
