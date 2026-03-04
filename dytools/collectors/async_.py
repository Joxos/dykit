"""Asynchronous collector for Douyu danmu messages.

This module provides the AsyncCollector class which establishes an async
WebSocket connection to Douyu's danmu servers using the websockets library,
handles protocol communication with asyncio-based heartbeat, and persists
messages via pluggable storage handlers.

The collector uses asyncio for non-blocking I/O. All methods are async and
should be awaited.

Example Usage:
    ```python
    import asyncio
    from dytools.collectors import AsyncCollector
    from dytools.storage import CSVStorage

    async def main():
        with CSVStorage('output.csv') as storage:
            collector = AsyncCollector(room_id=6657, storage=storage)
            try:
                await collector.connect()
            except KeyboardInterrupt:
                await collector.stop()

    asyncio.run(main())
    ```

Technical Notes:
    - Uses websockets library for async WebSocket communication
    - MessageBuffer prevents UTF-8 truncation across packet boundaries
    - StorageHandler provides pluggable backends (CSV, console, database, etc.)
    - Heartbeat sent every 45 seconds via separate asyncio.Task
    - Graceful shutdown via stop() or task cancellation
"""

from __future__ import annotations

import asyncio
import ssl
from datetime import datetime
from typing import Any

import websockets

from ..buffer import MessageBuffer
from ..log import logger
from ..protocol import (
    encode_message,
    get_danmu_server,
    serialize_message,
)
from ..storage import StorageHandler
from ..types import DanmuMessage, MessageType


class AsyncCollector:
    """Asynchronous WebSocket collector for Douyu danmu messages.

    Establishes an async WebSocket connection to Douyu's danmu server using the
    `websockets` library. Handles login, room joining, and maintains connection
    via periodic async heartbeats. Processes incoming messages using MessageBuffer
    for UTF-8-safe parsing.

    This collector uses asyncio for non-blocking I/O. All methods are async and
    should be awaited. The heartbeat runs as a background asyncio task.

    Example Usage:
        ```python
        import asyncio
    from dytools.collectors import AsyncCollector
    from dytools.storage import CSVStorage

        async def main():
            with CSVStorage('output.csv') as storage:
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
        _heartbeat_task: Asyncio task running the heartbeat loop.
        _running: Flag indicating if collector is active.
        _websocket: Active WebSocket connection (None until connected).
    """

    def __init__(self, room_id: int, storage: StorageHandler, ws_url: str | None = None) -> None:
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
        """

        self.room_id = room_id
        self._real_room_id: int = room_id
        self.storage = storage
        self.ws_url_override = ws_url
        self._buffer = MessageBuffer()
        self._heartbeat_task: asyncio.Task | None = None
        self._running = False
        self._websocket: Any = None

    async def connect(self) -> None:
        """Connect to Douyu WebSocket server and start receiving messages.

        This method establishes an async WebSocket connection, sends login and
        joingroup messages, starts the heartbeat task, and enters the main
        message processing loop. It will run until the connection closes or
        stop() is called.

        The connection uses relaxed SSL settings for compatibility with Douyu
        servers (same as SyncCollector).

        Raises:
            asyncio.CancelledError: If the task is cancelled during operation.
            Exception: Any exception from WebSocket connection or SSL handshake.
        """
        # Configure SSL context (same relaxed settings as SyncCollector)
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

                # Connect with Origin header (required for CDN nodes)
                # Connect with Origin header (websockets 16.0 API)
                # Disable built-in ping to avoid conflicts with Douyu heartbeat protocol
                async with websockets.connect(
                    url,
                    ssl=ssl_context,
                    origin="https://www.douyu.com",
                    ping_interval=None,  # Disable websockets built-in ping
                    ping_timeout=None,   # Disable websockets built-in ping timeout
                ) as websocket:
                    self._websocket = websocket
                    self._running = True
                    logger.info(f"Connected to {url}")

                    # Send login request
                    await self._send_login()

                    # Send joingroup request
                    await self._send_joingroup()

                    # Start heartbeat task
                    self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
                    logger.debug("Heartbeat task started")

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
                # Clean up heartbeat task if it was created
                if self._heartbeat_task:
                    self._heartbeat_task.cancel()
                    try:
                        await self._heartbeat_task
                    except asyncio.CancelledError:
                        pass
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

        Sets the running flag to False and cancels the heartbeat task. The
        WebSocket connection will close when the message processing loop exits.

        This method is safe to call multiple times and can be called from signal
        handlers or exception handlers.
        """
        logger.info("Stopping async collector...")
        self._running = False

        if self._heartbeat_task:
            self._heartbeat_task.cancel()

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
        await self._websocket.send(encode_message(login_msg))
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
        await self._websocket.send(encode_message(joingroup_msg))
        logger.debug(f"Sent joingroup: {joingroup_msg}")

    async def _heartbeat_loop(self) -> None:
        """Send heartbeat messages every 45 seconds.

        Runs as a background asyncio task. Automatically stops when the task is
        cancelled (e.g., on connection close or stop()).

        The heartbeat message (type=mrkl) keeps the connection alive and prevents
        server-side timeout.
        """
        try:
            while self._running:
                await asyncio.sleep(45)
                if self._running and self._websocket:
                    heartbeat_msg = serialize_message({"type": "mrkl"})
                    try:
                        await self._websocket.send(encode_message(heartbeat_msg))
                        logger.debug("Sent heartbeat (mrkl)")
                    except Exception as e:
                        logger.error(f"Failed to send heartbeat: {e}")
                        break
        except asyncio.CancelledError:
            logger.debug("Heartbeat loop cancelled")
            # Normal shutdown, don't re-raise

    def _build_danmu_message(self, msg_dict: dict[str, str], msg_type: MessageType) -> DanmuMessage:
        """Build DanmuMessage from raw message dict with typed flattened fields."""
        uid = msg_dict.get("uid") or msg_dict.get("unk")
        nn = msg_dict.get("nn") or msg_dict.get("donk")
        rid = msg_dict.get("rid") or msg_dict.get("drid")
        room_id = int(rid) if rid and str(rid).isdigit() else self.room_id
        level = msg_dict.get("level", "0")
        
        # Base kwargs
        kwargs = {
            "timestamp": datetime.now(),
            "username": nn,
            "content": None,
            "user_level": int(level) if str(level).isdigit() else 0,
            "user_id": uid,
            "room_id": room_id,
            "msg_type": msg_type,
            "raw_data": msg_dict,
        }
        
        # Populate flattened fields by message type
        if msg_type == MessageType.DGB:
            kwargs["gift_id"] = msg_dict.get("gfid")
            gfcnt = msg_dict.get("gfcnt")
            kwargs["gift_count"] = int(gfcnt) if gfcnt and gfcnt.isdigit() else None
            kwargs["gift_name"] = msg_dict.get("gfn")
        elif msg_type in (MessageType.UENTER, MessageType.BLAB):
            bl = msg_dict.get("bl")
            kwargs["badge_level"] = int(bl) if bl and bl.isdigit() else None
            kwargs["badge_name"] = msg_dict.get("bnn")
            if msg_type == MessageType.UENTER:
                kwargs["avatar_url"] = msg_dict.get("ic")
        elif msg_type in (MessageType.ANBC, MessageType.RNEWBC):
            nl = msg_dict.get("nl")
            kwargs["noble_level"] = int(nl) if nl and nl.isdigit() else None
        
        return DanmuMessage(**kwargs)

    async def _process_messages(self) -> None:
        """Main message receive loop.

        Receives binary messages from WebSocket, accumulates them in MessageBuffer,
        extracts complete packets, and processes each message according to its type.

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

                # Add binary data to buffer and extract complete messages
                self._buffer.add_data(message)
                for msg_dict in self._buffer.get_messages():
                    msg_type = msg_dict.get("type", "unknown")

                    if msg_type == "loginres":
                        logger.info("Received loginres - login successful")
                    elif msg_type == "chatmsg":
                        # Extract chat message fields
                        nickname = msg_dict.get("nn", "Unknown")
                        content = msg_dict.get("txt", "")
                        level = msg_dict.get("level", "0")
                        uid = msg_dict.get("uid", "0")

                        # Print to console
                        print(f"[{nickname}] Lv{level}: {content}")
                        logger.debug(
                            f"chatmsg - uid={uid}, nn={nickname}, txt={content}, level={level}"
                        )

                        # Construct DanmuMessage and persist via storage handler
                        try:
                            danmu_message = DanmuMessage(
                                timestamp=datetime.now(),
                                username=nickname,
                                content=content,
                                user_level=int(level) if level.isdigit() else 0,
                                user_id=uid,
                                room_id=self.room_id,
                                msg_type=MessageType.CHATMSG,
                                raw_data=msg_dict,
                            )
                            self.storage.save(danmu_message)
                        except Exception as e:
                            logger.error(f"Failed to save danmu message: {e}")
                    elif msg_type == "dgb":  # Gift
                        danmu_message = self._build_danmu_message(msg_dict, MessageType.DGB)
                        gfcnt = msg_dict.get("gfcnt", "1")
                        gfid = msg_dict.get("gfid", "unknown")
                        print(f"[{danmu_message.username}] 送出了 {gfcnt}x 礼物{gfid}")
                        try:
                            self.storage.save(danmu_message)
                        except Exception as e:
                            logger.error(f"Failed to save dgb message: {e}")

                    elif msg_type == "uenter":  # User enter
                        danmu_message = self._build_danmu_message(msg_dict, MessageType.UENTER)
                        print(f"[{danmu_message.username}] 进入了直播间")
                        try:
                            self.storage.save(danmu_message)
                        except Exception as e:
                            logger.error(f"Failed to save uenter message: {e}")

                    elif msg_type == "anbc":  # Open noble
                        danmu_message = self._build_danmu_message(msg_dict, MessageType.ANBC)
                        nl = msg_dict.get("nl", "?")
                        print(f"[{danmu_message.username}] 开通了{nl}级贵族")
                        try:
                            self.storage.save(danmu_message)
                        except Exception as e:
                            logger.error(f"Failed to save anbc message: {e}")

                    elif msg_type == "rnewbc":  # Renew noble
                        danmu_message = self._build_danmu_message(msg_dict, MessageType.RNEWBC)
                        nl = msg_dict.get("nl", "?")
                        print(f"[{danmu_message.username}] 续费了{nl}级贵族")
                        try:
                            self.storage.save(danmu_message)
                        except Exception as e:
                            logger.error(f"Failed to save rnewbc message: {e}")

                    elif msg_type == "blab":  # Fan badge level up
                        danmu_message = self._build_danmu_message(msg_dict, MessageType.BLAB)
                        bl = msg_dict.get("bl", "?")
                        bnn = msg_dict.get("bnn", "粉丝牌")
                        print(f"[{danmu_message.username}] 粉丝牌《{bnn}》升级至{bl}级")
                        try:
                            self.storage.save(danmu_message)
                        except Exception as e:
                            logger.error(f"Failed to save blab message: {e}")

                    elif msg_type == "upgrade":  # User level up
                        danmu_message = self._build_danmu_message(msg_dict, MessageType.UPGRADE)
                        print(f"[{danmu_message.username}] 升级到{danmu_message.user_level}级")
                        try:
                            self.storage.save(danmu_message)
                        except Exception as e:
                            logger.error(f"Failed to save upgrade message: {e}")

                    else:
                        # Log other message types in debug mode
                        logger.debug(f"Received message type: {msg_type}")

        except asyncio.CancelledError:
            logger.debug("Message processing cancelled")
            raise
