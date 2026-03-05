"""Synchronous collector for Douyu danmu messages.

This module provides the SyncCollector class which establishes a WebSocket
connection to Douyu's danmu servers using the websocket-client library,
handles protocol communication with threading-based heartbeat, and persists
messages via pluggable storage handlers.

The collector runs blocking in the calling thread, with the heartbeat
mechanism running in a separate daemon thread to avoid blocking message
reception.

Example Usage:
    ```python
    from dytools.collectors import SyncCollector
    from dytools.storage import CSVStorage

    with CSVStorage('output.csv') as storage:
        collector = SyncCollector(room_id=6657, storage=storage)
        try:
            collector.connect()
        except KeyboardInterrupt:
            collector.stop()
    ```

Technical Notes:
    - Uses websocket-client library with blocking I/O and SSL customization
    - MessageBuffer prevents UTF-8 truncation across packet boundaries
    - StorageHandler provides pluggable backends (CSV, console, database, etc.)
    - Heartbeat sent every 45 seconds via separate daemon thread
    - Graceful shutdown on KeyboardInterrupt or connection close
"""

from __future__ import annotations

import re
import ssl
import threading
import time
from datetime import datetime

from websocket import WebSocketApp

from ..buffer import MessageBuffer
from ..log import logger
from ..protocol import (
    encode_message,
    get_danmu_server,
    serialize_message,
)
from ..storage import StorageHandler
from ..types import DanmuMessage, MessageType


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

    def __init__(
        self,
        room_id: str,
        storage: StorageHandler,
        ws_url: str | None = None,
        type_filter: list[str] | None = None,
        type_exclude: list[str] | None = None,
    ) -> None:
        """Initialize the synchronous Douyu danmu collector.

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
                are never filtered.
            type_exclude: Optional list of message types to exclude from collection.
                If None, no messages are excluded. Protocol messages (loginres, mrkl) are
                never excluded.
        """

        self.room_id = room_id
        self._real_room_id: int = 0
        self.storage = storage
        self.ws_url_override = ws_url
        self.ws: WebSocketApp | None = None
        self.heartbeat_thread: threading.Thread | None = None
        self.running = False
        self._buffer = MessageBuffer()
        self._type_filter = type_filter
        self._type_exclude = type_exclude

    def _build_danmu_message(self, msg_dict: dict[str, str], msg_type: MessageType) -> DanmuMessage:
        """Build DanmuMessage from raw message dict with typed flattened fields."""
        uid = msg_dict.get("uid") or msg_dict.get("unk")
        nn = msg_dict.get("nn") or msg_dict.get("donk")
        if nn:
            nn = re.sub(r'^\s+|\s+$', '', nn)
        # rid = msg_dict.get("rid") or msg_dict.get("drid")  # No longer used, composite room_id used instead
        room_id = f"{self.room_id}:{self._real_room_id}"
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

            # Filter message types if --with specified (never filter protocol messages)
            if (
                self._type_filter is not None
                and msg_type not in self._type_filter
                and msg_type not in ("loginres", "mrkl")
            ):
                continue
            if (
                self._type_exclude is not None
                and msg_type in self._type_exclude
                and msg_type not in ("loginres", "mrkl")
            ):
                continue
            elif msg_type == "chatmsg":
                # Extract chat message fields
                nickname = re.sub(r'^\s+|\s+$', '', msg_dict.get("nn", "Unknown"))
                content = re.sub(r'^\s+|\s+$', '', msg_dict.get("txt", ""))
                level = msg_dict.get("level", "0")
                uid = msg_dict.get("uid", "0")

                # Print to console
                print(f"[{nickname}] Lv{level}: {content}")
                logger.debug(f"chatmsg - uid={uid}, nn={nickname}, txt={content}, level={level}")

                # Construct DanmuMessage and persist via storage handler
                try:
                    danmu_message = DanmuMessage(
                        timestamp=datetime.now(),
                        username=nickname,
                        content=content,
                        user_level=int(level) if level.isdigit() else 0,
                        user_id=uid,
                        room_id=f"{self.room_id}:{self._real_room_id}",
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

    def _on_error(self, ws: WebSocketApp, error: object) -> None:
        """Handle WebSocket errors.

        Args:
            ws: WebSocket application instance.
            error: Error object from WebSocket.
        """
        logger.error(f"WebSocket error: {error}")

    def _on_close(self, ws: WebSocketApp, close_status_code: int, close_msg: str | None) -> None:
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
        logger.info(f"Connected to {self.ws_url}")

        # Send login request
        login_msg = serialize_message({"type": "loginreq", "roomid": self._real_room_id})
        ws.send(encode_message(login_msg), opcode=0x2)  # 0x2 = binary
        logger.debug(f"Sent loginreq: {login_msg}")

        # Send joingroup request
        joingroup_msg = serialize_message(
            {"type": "joingroup", "rid": self._real_room_id, "gid": -9999}
        )
        ws.send(encode_message(joingroup_msg), opcode=0x2)
        logger.debug(f"Sent joingroup: {joingroup_msg}")

        # Start heartbeat thread
        self.running = True
        self.heartbeat_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
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
        # Discover candidate WebSocket URLs (returns list)
        candidate_urls, self._real_room_id = get_danmu_server(
            self.room_id, manual_url=self.ws_url_override
        )

        # Try each candidate URL until one works
        last_error = None
        for url in candidate_urls:
            try:
                logger.info(f"Trying server: {url}")
                self.ws_url = url

                self.ws = WebSocketApp(
                    self.ws_url,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close,
                    on_open=self._on_open,
                    header={"Origin": "https://www.douyu.com"},  # Required for CDN nodes
                )

                logger.info("Starting WebSocket connection...")

                # Use relaxed SSL settings with OpenSSL SECLEVEL=1 for older Douyu servers
                sslopt = {
                    "cert_reqs": ssl.CERT_NONE,
                    "check_hostname": False,
                    "ssl_version": ssl.PROTOCOL_TLS_CLIENT,
                    "ciphers": "DEFAULT@SECLEVEL=1",
                }

                # This blocks until connection closes
                self.ws.run_forever(sslopt=sslopt)

                # If we reach here, connection was successful and then closed normally
                logger.info(f"Connection to {url} closed normally")
                return

            except Exception as e:
                last_error = e
                logger.warning(f"Failed to connect to {url}: {e}")
                continue

        # If we tried all URLs and all failed
        raise RuntimeError(
            f"Failed to connect to any danmu server after trying {len(candidate_urls)} URLs. "
            f"Last error: {last_error}"
        )

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
