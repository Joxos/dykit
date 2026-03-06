"""Asynchronous collector for Douyu danmu messages.

This module provides the AsyncCollector class which establishes an async
WebSocket connection to Douyu's danmu servers using the websockets library,
uses built-in WebSocket keepalive, and persists messages via pluggable storage
handlers.

The collector uses asyncio for non-blocking I/O. All methods are async and
should be awaited.

Example Usage:
    ```python
    import asyncio
    from dytools.collectors import AsyncCollector
    from dytools.storage import CSVStorage

    async def main():
        async with CSVStorage('output.csv') as storage:
            collector = AsyncCollector(room_id=6657, storage=storage)
            try:
                await collector.connect()
            except KeyboardInterrupt:
                await collector.stop()

    asyncio.run(main())
    ```

Technical Notes:
    - Uses websockets library for async WebSocket communication
    - Uses MessageBuffer for safe packet reassembly and decode
    - StorageHandler provides pluggable backends (CSV, console, database, etc.)
    - Uses WebSocket keepalive via ping_interval / ping_timeout
    - Graceful shutdown via stop() or task cancellation
"""

from __future__ import annotations

import asyncio
import re
import ssl
from datetime import datetime
from typing import Any

import websockets
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential
from websockets import Origin

from ..buffer import MessageBuffer
from ..constants import (
    RETRY_ATTEMPTS_WS_CONNECT,
    RETRY_ATTEMPTS_WS_SEND,
    RETRY_BACKOFF_WS_CONNECT_MAX_SECONDS,
    RETRY_BACKOFF_WS_CONNECT_MIN_SECONDS,
    RETRY_BACKOFF_WS_CONNECT_MULTIPLIER,
    RETRY_BACKOFF_WS_SEND_MAX_SECONDS,
    RETRY_BACKOFF_WS_SEND_MIN_SECONDS,
    RETRY_BACKOFF_WS_SEND_MULTIPLIER,
)
from ..log import logger
from ..protocol import (
    encode_message,
    get_danmu_server,
    serialize_message,
)
from ..storage import StorageHandler
from ..types import DanmuMessage, MessageType
from .base import BaseCollector

CHAT_FIELD_MAP: dict[MessageType, tuple[str, str]] = {
    MessageType.DGB: ("送出了 {gfcnt}x 礼物{gfid}", "dgb"),
    MessageType.UENTER: ("进入了直播间", "uenter"),
    MessageType.ANBC: ("开通了{nl}级贵族", "anbc"),
    MessageType.RNEWBC: ("续费了{nl}级贵族", "rnewbc"),
    MessageType.BLAB: ("粉丝牌《{bnn}》升级至{bl}级", "blab"),
    MessageType.UPGRADE: ("升级到{user_level}级", "upgrade"),
}

MSG_TYPE_TO_ENUM: dict[str, MessageType] = {
    "chatmsg": MessageType.CHATMSG,
    "dgb": MessageType.DGB,
    "uenter": MessageType.UENTER,
    "anbc": MessageType.ANBC,
    "rnewbc": MessageType.RNEWBC,
    "blab": MessageType.BLAB,
    "upgrade": MessageType.UPGRADE,
}


class AsyncCollector(BaseCollector):
    """Asynchronous WebSocket collector for Douyu danmu messages.

    Establishes an async WebSocket connection to Douyu's danmu server using the
    `websockets` library. Handles login, room joining, and maintains connection
    via built-in WebSocket keepalive. Processes incoming messages using
    MessageBuffer packet reassembly.

    This collector uses asyncio for non-blocking I/O. All methods are async and
    should be awaited.

    Example Usage:
        ```python
        import asyncio
    from dytools.collectors import AsyncCollector
    from dytools.storage import CSVStorage

        async def main():
            async with CSVStorage('output.csv') as storage:
                collector = AsyncCollector(room_id=6657, storage=storage)
                try:
                    await collector.connect()
                except KeyboardInterrupt:
                    await collector.stop()

        asyncio.run(main())
        ```

    Attributes:
        room_id: Douyu room ID to connect to.
        storage: StorageHandler instance for persisting messages.
        _buffer: MessageBuffer for accumulating incomplete packets.
        _running: Flag indicating if collector is active.
        _websocket: Active WebSocket connection (None until connected).
    """

    def __init__(
        self,
        room_id: str,
        storage: StorageHandler,
        ws_url: str | None = None,
        type_filter: list[str] | None = None,
        type_exclude: list[str] | None = None,
    ) -> None:
        """Initialize the asynchronous Douyu danmu collector.

        Args:
            room_id: Douyu room ID to connect to.
            storage: StorageHandler instance for persisting danmu messages.
                The storage handler should be opened/initialized before passing
                to this constructor. The collector does NOT close the storage
                handler; caller is responsible for cleanup (e.g., via context
                manager).
            ws_url: Optional manual WebSocket URL override. If provided, bypasses
                discovery and uses this URL directly.
            type_filter: Optional list of message types to collect (e.g., ['chatmsg', 'dgb']).
                If None, all message types are collected. Protocol messages (loginres, mrkl)
                are never filtered.
            type_exclude: Optional list of message types to exclude from collection.
                If None, no messages are excluded. Protocol messages (loginres, mrkl) are
                never excluded.
        """
        super().__init__(room_id, storage, ws_url, type_filter, type_exclude)
        self._buffer = MessageBuffer()
        self._running = False
        self._websocket: Any = None

    async def connect(self) -> None:
        """Connect to Douyu WebSocket server and start receiving messages.

        This method establishes an async WebSocket connection, sends login and
        joingroup messages, and enters the main message processing loop. It will
        run until the connection closes or stop() is called.

        The connection uses relaxed SSL settings for compatibility with Douyu
        servers.

        Raises:
            asyncio.CancelledError: If the task is cancelled during operation.
            Exception: Any exception from WebSocket connection or SSL handshake.
        """
        # Configure SSL context for Douyu servers
        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        ssl_context.set_ciphers("DEFAULT@SECLEVEL=1")

        # Discover candidate WebSocket URLs (returns list)
        candidate_urls, self._real_room_id = get_danmu_server(
            self.room_id, manual_url=self.ws_url_override
        )

        # Try each candidate URL until one works
        last_error = None
        for url in candidate_urls:
            try:
                logger.info(f"Trying server: {url}")

                websocket = await self._connect_with_retry(url, ssl_context)
                async with websocket:
                    self._websocket = websocket
                    self._running = True
                    logger.info(f"Connected to {url}")

                    # Send login request
                    await self._send_login()

                    # Send joingroup request
                    await self._send_joingroup()

                    # Process incoming messages
                    await self._process_messages()

                    # If we reach here, connection was successful and then closed normally
                    logger.info(f"Connection to {url} closed normally")
                    return

            except asyncio.CancelledError:
                logger.info("Async collector cancelled")
                raise
            except Exception as e:
                last_error = e
                logger.warning(f"Failed to connect to {url}: {e}")
                self._running = False
                self._websocket = None
                continue

        # If we tried all URLs and all failed
        raise RuntimeError(
            f"Failed to connect to any danmu server after trying {len(candidate_urls)} URLs. "
            f"Last error: {last_error}"
        )

    async def stop(self) -> None:
        """Stop the collector gracefully.

        Sets the running flag to False and closes the WebSocket connection.
        The message processing loop exits when the socket closes.

        This method is safe to call multiple times and can be called from signal
        handlers or exception handlers.
        """
        logger.info("Stopping async collector...")
        self._running = False

        if self._websocket:
            await self._websocket.close()

    async def _send_login(self) -> None:
        """Send login request to Douyu server.

        Constructs and sends a loginreq message with the room ID.

        Raises:
            Exception: If WebSocket is not connected or send fails.
        """
        if not self._websocket:
            raise RuntimeError("WebSocket not connected")

        login_msg = serialize_message({"type": "loginreq", "roomid": self._real_room_id})
        await self._send_with_retry(encode_message(login_msg))
        logger.debug(f"Sent loginreq: {login_msg}")

    async def _send_joingroup(self) -> None:
        """Send joingroup request to join the specified room.

        Constructs and sends a joingroup message with room ID and group ID (-9999
        is the default group for public messages).

        Raises:
            Exception: If WebSocket is not connected or send fails.
        """
        if not self._websocket:
            raise RuntimeError("WebSocket not connected")

        joingroup_msg = serialize_message(
            {"type": "joingroup", "rid": self._real_room_id, "gid": -9999}
        )
        await self._send_with_retry(encode_message(joingroup_msg))
        logger.debug(f"Sent joingroup: {joingroup_msg}")

    async def _connect_with_retry(self, url: str, ssl_context: ssl.SSLContext) -> Any:
        """Connect to a WebSocket endpoint with bounded retries."""
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
                    ping_interval=45,
                    ping_timeout=20,
                )

        raise RuntimeError("WebSocket connection retry exhausted")

    async def _send_with_retry(self, payload: bytes) -> None:
        """Send a payload with retries for transient transport failures."""
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

    async def _process_messages(self) -> None:
        """Main message receive loop.

        Receives binary messages from WebSocket and processes each decoded protocol
        message according to its type.

        This method runs until the WebSocket connection closes or _running becomes
        False.

        Message Types Handled:
            - loginres: Logs successful login
            - chatmsg: Constructs DanmuMessage and persists via StorageHandler
            - others: Logged in debug mode only
        """
        if not self._websocket:
            raise RuntimeError("WebSocket not connected")

        try:
            async for message in self._websocket:
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
            logger.debug("Message processing cancelled")
            raise

    async def _handle_message(self, msg_type: str, msg_dict: dict[str, str]) -> None:
        if msg_type == "loginres":
            logger.info("Received loginres - login successful")

        if self._should_skip_message(msg_type):
            return

        if msg_type == "chatmsg":
            await self._handle_chat_message(msg_dict)
            return

        enum_value = MSG_TYPE_TO_ENUM.get(msg_type)
        if enum_value is None or enum_value == MessageType.CHATMSG:
            logger.debug(f"Received message type: {msg_type}")
            return

        await self._handle_structured_message(msg_dict, enum_value)

    async def _handle_chat_message(self, msg_dict: dict[str, str]) -> None:
        nickname = re.sub(r"^\s+|\s+$", "", msg_dict.get("nn", "Unknown"))
        content = re.sub(r"^\s+|\s+$", "", msg_dict.get("txt", ""))
        level = msg_dict.get("level", "0")
        uid = msg_dict.get("uid", "0")

        logger.info(f"[{nickname}] Lv{level}: {content}")

        try:
            danmu_message = DanmuMessage(
                timestamp=datetime.now(),
                username=nickname,
                content=content,
                user_level=int(level) if level.isdigit() else 0,
                user_id=uid,
                room_id=str(self._real_room_id),
                msg_type=MessageType.CHATMSG,
                raw_data=msg_dict,
            )
            await self.storage.save(danmu_message)
        except Exception as e:
            logger.error(f"Failed to save danmu message: {e}")

    async def _handle_structured_message(
        self, msg_dict: dict[str, str], msg_type: MessageType
    ) -> None:
        danmu_message = self._build_danmu_message(msg_dict, msg_type)
        template_and_label = CHAT_FIELD_MAP.get(msg_type)
        if template_and_label is None:
            logger.debug(f"Received message type: {msg_type.value}")
            return

        template, label = template_and_label
        context = {
            "gfcnt": msg_dict.get("gfcnt", "1"),
            "gfid": msg_dict.get("gfid", "unknown"),
            "nl": msg_dict.get("nl", "?"),
            "bnn": msg_dict.get("bnn", "粉丝牌"),
            "bl": msg_dict.get("bl", "?"),
            "user_level": str(danmu_message.user_level),
        }
        logger.info(f"[{danmu_message.username}] {template.format(**context)}")

        try:
            await self.storage.save(danmu_message)
        except Exception as e:
            logger.error(f"Failed to save {label} message: {e}")
