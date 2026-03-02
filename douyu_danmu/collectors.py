"""Synchronous and asynchronous collectors for Douyu danmu messages.

This module provides collector classes that establish WebSocket connections to
Douyu's danmu servers, handle protocol communication, and persist messages via
pluggable storage handlers.

Classes:
    SyncCollector: Synchronous WebSocket-based collector using threading for
        heartbeat management. Integrates MessageBuffer for UTF-8-safe parsing
        and StorageHandler for modular message persistence.

Example Usage:
    ```python
    from douyu_danmu.collectors import SyncCollector
    from douyu_danmu.storage import CSVStorage

    # Create storage handler
    with CSVStorage('output.csv') as storage:
        # Initialize collector
        collector = SyncCollector(room_id=6657, storage=storage)

        # Connect and start receiving messages
        # (blocks until connection closed or Ctrl+C)
        try:
            collector.connect()
        except KeyboardInterrupt:
            collector.stop()
    ```

Design Notes:
    - SyncCollector uses websocket-client library with blocking I/O
    - MessageBuffer prevents UTF-8 truncation across packet boundaries
    - StorageHandler provides pluggable backends (CSV, console, database, etc.)
    - Heartbeat sent every 45 seconds to maintain connection
    - Graceful shutdown on KeyboardInterrupt
"""

from __future__ import annotations

import asyncio
import ssl
import threading
import time
from datetime import datetime
from typing import Any

import websockets
from websocket import WebSocketApp

from .buffer import MessageBuffer
from .log import logger
from .protocol import (
    DOUYU_WS_URL,
    encode_message,
    serialize_message,
)
from .storage import StorageHandler
from .types import DanmuMessage, MessageType


class SyncCollector:
    """Synchronous WebSocket collector for Douyu danmu messages.

    Establishes a WebSocket connection to Douyu's danmu server, handles login
    and room joining, maintains connection via periodic heartbeats, and processes
    incoming chat messages using MessageBuffer for UTF-8 safety.

    This collector runs in the calling thread and blocks during connect(). The
    heartbeat mechanism runs in a separate daemon thread to avoid blocking
    message reception.

    Attributes:
        room_id: Douyu room ID to connect to.
        storage: StorageHandler instance for persisting messages.
        ws: WebSocketApp instance (None until connect() is called).
        heartbeat_thread: Thread running the heartbeat loop.
        running: Flag indicating if collector is active.
        _buffer: MessageBuffer for accumulating incomplete packets.
    """

    def __init__(self, room_id: int, storage: StorageHandler) -> None:
        """Initialize the synchronous Douyu danmu collector.

        Args:
            room_id: Douyu room ID to connect to.
            storage: StorageHandler instance for persisting danmu messages.
                The storage handler should be opened/initialized before passing
                to this constructor. The collector does NOT close the storage
                handler; caller is responsible for cleanup (e.g., via context
                manager).
        """
        self.room_id = room_id
        self.storage = storage
        self.ws: WebSocketApp | None = None
        self.heartbeat_thread: threading.Thread | None = None
        self.running = False
        self._buffer = MessageBuffer()

    def _on_message(self, ws: WebSocketApp, message: bytes) -> None:
        """Handle incoming WebSocket messages.

        Uses MessageBuffer to accumulate bytes and extract complete packets,
        preventing UTF-8 truncation errors. Constructs DanmuMessage instances
        for chatmsg types and persists them via the storage handler.

        Args:
            ws: WebSocket application instance.
            message: Binary message data from server.
        """
        # Add data to buffer and extract complete messages
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
            else:
                # Log other message types in debug mode
                logger.debug(f"Received message type: {msg_type}")

    def _on_error(self, ws: WebSocketApp, error: object) -> None:
        """Handle WebSocket errors.

        Args:
            ws: WebSocket application instance.
            error: Error object from WebSocket.
        """
        logger.error(f"WebSocket error: {error}")

    def _on_close(
        self, ws: WebSocketApp, close_status_code: int, close_msg: str | None
    ) -> None:
        """Handle WebSocket close.

        Sets running flag to False, which stops the heartbeat thread.

        Args:
            ws: WebSocket application instance.
            close_status_code: Status code for close.
            close_msg: Close message from server.
        """
        logger.info("WebSocket connection closed")
        self.running = False

    def _on_open(self, ws: WebSocketApp) -> None:
        """Handle WebSocket connection open.

        Sends login request, joins the specified room, and starts the heartbeat
        thread to maintain connection.

        Args:
            ws: WebSocket application instance.
        """
        logger.info(f"Connected to {DOUYU_WS_URL}")

        # Send login request
        login_msg = serialize_message({"type": "loginreq", "roomid": self.room_id})
        ws.send(encode_message(login_msg), opcode=0x2)  # 0x2 = binary
        logger.debug(f"Sent loginreq: {login_msg}")

        # Send joingroup request
        joingroup_msg = serialize_message(
            {"type": "joingroup", "rid": self.room_id, "gid": -9999}
        )
        ws.send(encode_message(joingroup_msg), opcode=0x2)
        logger.debug(f"Sent joingroup: {joingroup_msg}")

        # Start heartbeat thread
        self.running = True
        self.heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop, daemon=True
        )
        self.heartbeat_thread.start()
        logger.debug("Heartbeat thread started")

    def _heartbeat_loop(self) -> None:
        """Send heartbeat messages every 45 seconds.

        Runs in a separate daemon thread. Automatically stops when running flag
        is set to False (e.g., on connection close or stop()).
        """
        while self.running:
            time.sleep(45)
            if self.running and self.ws:
                heartbeat_msg = serialize_message({"type": "mrkl"})
                try:
                    self.ws.send(encode_message(heartbeat_msg), opcode=0x2)
                    logger.debug("Sent heartbeat (mrkl)")
                except Exception as e:
                    logger.error(f"Failed to send heartbeat: {e}")
                    break

    def connect(self) -> None:
        """Connect to Douyu WebSocket server and start receiving messages.

        This method blocks until the WebSocket connection is closed (either by
        server, network error, or stop() call). Use KeyboardInterrupt (Ctrl+C)
        for graceful shutdown.

        The connection uses relaxed SSL settings (SECLEVEL=1) for compatibility
        with older Douyu servers.

        Raises:
            Exception: Any exception from WebSocket connection or SSL handshake.
        """
        self.ws = WebSocketApp(
            DOUYU_WS_URL,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
            on_open=self._on_open,
        )

        logger.info("Starting WebSocket connection...")

        # Use relaxed SSL settings with OpenSSL SECLEVEL=1 for older Douyu servers
        sslopt = {
            "cert_reqs": ssl.CERT_NONE,
            "check_hostname": False,
            "ssl_version": ssl.PROTOCOL_TLS_CLIENT,
            "ciphers": "DEFAULT@SECLEVEL=1",
        }
        self.ws.run_forever(sslopt=sslopt)

    def stop(self) -> None:
        """Stop the collector gracefully.

        Sets the running flag to False and closes the WebSocket connection.
        The heartbeat thread will automatically exit when running becomes False.

        This method is safe to call multiple times and can be called from signal
        handlers or KeyboardInterrupt.
        """
        logger.info("Stopping collector...")
        self.running = False
        if self.ws:
            self.ws.close()


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
        from douyu_danmu.collectors import AsyncCollector
        from douyu_danmu.storage import CSVStorage

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

    def __init__(self, room_id: int, storage: StorageHandler) -> None:
        """Initialize the asynchronous Douyu danmu collector.

        Args:
            room_id: Douyu room ID to connect to.
            storage: StorageHandler instance for persisting danmu messages.
                The storage handler should be opened/initialized before passing
                to this constructor. The collector does NOT close the storage
                handler; caller is responsible for cleanup (e.g., via context
                manager).
        """
        self.room_id = room_id
        self.storage = storage
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

        logger.info(f"Connecting to {DOUYU_WS_URL}...")

        try:
            async with websockets.connect(DOUYU_WS_URL, ssl=ssl_context) as websocket:
                self._websocket = websocket
                self._running = True

                logger.info(f"Connected to {DOUYU_WS_URL}")

                # Send login request
                await self._send_login()

                # Send joingroup request
                await self._send_joingroup()

                # Start heartbeat task
                self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
                logger.debug("Heartbeat task started")

                # Process incoming messages
                await self._process_messages()

        except asyncio.CancelledError:
            logger.info("Async collector cancelled")
            raise
        except Exception as e:
            logger.error(f"WebSocket connection error: {e}")
            raise
        finally:
            # Clean up heartbeat task
            if self._heartbeat_task:
                self._heartbeat_task.cancel()
                try:
                    await self._heartbeat_task
                except asyncio.CancelledError:
                    pass
            self._running = False
            self._websocket = None
            logger.info("AsyncCollector connection closed")

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

        login_msg = serialize_message({"type": "loginreq", "roomid": self.room_id})
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
            {"type": "joingroup", "rid": self.room_id, "gid": -9999}
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
                            # StorageHandler.save() is synchronous - call directly
                            self.storage.save(danmu_message)
                        except Exception as e:
                            logger.error(f"Failed to save danmu message: {e}")
                    else:
                        # Log other message types in debug mode
                        logger.debug(f"Received message type: {msg_type}")

        except asyncio.CancelledError:
            logger.debug("Message processing cancelled")
            raise
