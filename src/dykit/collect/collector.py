"""Asynchronous collector for Douyu danmu messages.

Lifecycle is an explicit state machine (see :class:`CaptureState`) rather than
a `_running` flag scattered through the reconnect loop. Two properties matter:

* **Stop is a real interrupt.** ``stop()`` clears the running flag *and*
  cancels ``connect()``'s task, so an in-flight ``asyncio.to_thread`` room
  lookup (up to ~30s of HTTP retries) cannot hold up shutdown. Before this,
  Ctrl+C could take half a minute to exit.
* **Rotation never touches the socket.** Rolling over to a new run file swaps
  the write sink under a lock; connection, heartbeat and receive loop are
  untouched, so a rollover loses nothing and duplicates nothing.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import ssl
from collections.abc import Callable
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

import websockets
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential
from websockets import Origin

from dykit.protocol import MessageBuffer, encode_message, serialize_message
from dykit.source import get_danmu_server
from dykit.source.cache import load, store

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
    WS_SERVER_REFRESH_INTERVAL_SECONDS,
)
from .payload import (
    CHATMSG,
    LOGIN_RESPONSE,
    build_chat_message,
    build_structured_message,
    resolve_message_type,
    should_skip,
)
from .storage import StorageHandler
from .types import DanmuMessage

logger: logging.Logger = logging.getLogger(__name__)


class CaptureState(StrEnum):
    """Where the collector is in its lifecycle. Observability only."""

    IDLE = "idle"
    DISCOVERING = "discovering"
    CONNECTING = "connecting"
    HANDSHAKING = "handshaking"
    STREAMING = "streaming"
    BACKOFF = "backoff"
    STOPPING = "stopping"
    STOPPED = "stopped"


#: WebSocket connect kwargs (ping disabled per keepalive contract)
DOUYU_WS_CONNECT_KWARGS: dict[str, Any] = {
    "ping_interval": None,
    "ping_timeout": None,
}


def _douyu_ssl_context() -> ssl.SSLContext:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    context.set_ciphers("DEFAULT@SECLEVEL=1")
    return context


class AsyncCollector:
    """Asynchronous WebSocket collector for Douyu danmu messages.

    This collector connects to Douyu's danmu WebSocket server,
    receives and parses messages, and persists them via a StorageHandler.
    ``storage`` is swappable at runtime by :meth:`rotate`, which rolls over
    to a new run file without touching the socket.

    Example:
        from dykit import AsyncCollector
        from dykit import SQLiteStorage

        async with SQLiteStorage("run.db", room_id="6657") as storage:
            collector = AsyncCollector("6657", storage)
            try:
                await collector.connect()
            except KeyboardInterrupt:
                await collector.stop()
    """

    #: The sink currently being written. Replaced wholesale by ``rotate()``.
    storage: StorageHandler

    def __init__(
        self,
        room_id: str,
        storage: StorageHandler,
        ws_url: str | None = None,
        type_filter: list[str] | None = None,
        type_exclude: list[str] | None = None,
        message_callback: Callable[[DanmuMessage], None] | None = None,
        sink_factory: Callable[[], StorageHandler] | None = None,
        data_dir: Path | None = None,
    ) -> None:
        """Initialize the collector.

        Args:
            room_id: Douyu room ID to collect from.
            storage: Storage handler for persisting messages.
            ws_url: Optional WebSocket URL override.
            type_filter: Optional list of message types to collect.
            type_exclude: Optional list of message types to exclude.
            sink_factory: Creates the *next* sink when rotating. Required for
                ``rotate()``; without it the collector cannot shard.
            data_dir: Where to cache discovered endpoints for a fast warm start.
        """
        self.room_id = room_id
        self.storage = storage
        self.ws_url_override = ws_url
        self.type_filter = type_filter
        self.type_exclude = type_exclude
        self.message_callback = message_callback
        self._sink_factory = sink_factory
        self._data_dir = data_dir

        self._buffer = MessageBuffer()
        self._state = CaptureState.IDLE
        self._websocket: Any = None
        self._real_room_id: int = 0
        self._last_discovery_time: float = 0.0
        self._candidate_urls: list[str] = []
        self._candidate_index: int = 0
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._discovery_task: asyncio.Task[None] | None = None
        self._connect_task: asyncio.Task[None] | None = None
        self._sink_lock = asyncio.Lock()
        self._rotations: int = 0
        self._totals: dict[str, int] = {
            "messages": 0,
            "committed": 0,
            "flushes": 0,
            "flush_errors": 0,
        }

    # ------------------------------------------------------------------ #
    # observability
    # ------------------------------------------------------------------ #

    @property
    def state(self) -> CaptureState:
        return self._state

    @property
    def rotations(self) -> int:
        """How many run files this collector has rolled over to."""
        return self._rotations

    @property
    def current_run(self) -> str:
        """Identifier of the sink currently being written."""
        return self.storage.run_ref

    @property
    def totals(self) -> dict[str, int]:
        """Session counters summed across every shard this collector opened.

        ``SQLiteStorage.stats`` is per shard; these are the whole session, so
        the CLI summary cannot be read as "messages lost".
        """
        return dict(self._totals)

    @property
    def real_room_id(self) -> int:
        """Numeric room ID Douyu resolved this vanity name to (0 if unknown)."""
        return self._real_room_id

    @property
    def candidate_urls(self) -> list[str]:
        """Danmu endpoints currently in rotation, in preference order."""
        return list(self._candidate_urls)

    # ------------------------------------------------------------------ #
    # rotation
    # ------------------------------------------------------------------ #

    async def _retire(self, sink: StorageHandler) -> None:
        """Close a finished sink and fold its counters into the session totals.

        Without this the CLI would print the *last shard's* committed count next
        to the *session's* received count, which reads like lost messages.
        """
        await sink.close()
        reported: dict[str, int] = dict(getattr(sink, "stats", {}) or {})
        for key in self._totals:
            self._totals[key] += int(reported.get(key, 0))

    async def rotate(self, *, reason: str = "manual") -> str | None:
        """Roll over to a new run file without interrupting collection.

        The socket, the heartbeat, the candidate list and the receive loop all
        stay up; only the write target changes. Structured as prepare -> swap ->
        drain so the only section a message can be delayed by is a single
        pointer assignment (measured 0.00 ms, versus ~17 ms to open a file and
        ~6 ms to finalise one).

        Nothing is lost and nothing is duplicated: ``close()`` drains the old
        buffer into the old file, and every message after the swap goes to the
        new one.

        Returns the new run's identifier, or None when no rollover happened
        (no factory, or the new sink could not be opened). A failed rollover is
        deliberately non-fatal: the current sink stays live and collection
        continues, because losing the receive loop over a shard-naming or
        filesystem hiccup would cost real data.
        """
        if self._sink_factory is None:
            logger.debug("rotate(%s) ignored: no sink factory configured", reason)
            return None

        try:
            new_sink = self._sink_factory()  # slow: opens the file
            await new_sink.open()
        except Exception:
            logger.warning(
                "rotate(%s) failed to prepare a new run file; continuing in %s",
                reason,
                self.storage.run_ref,
                exc_info=True,
            )
            return None

        async with self._sink_lock:  # critical section: one assignment
            old_sink = self.storage
            self.storage = new_sink

        await self._retire(old_sink)  # slow: drains + writes ended_at
        self._rotations += 1
        logger.debug("rotated run file (reason=%s) -> %s", reason, new_sink.run_ref)
        return new_sink.run_ref

    # ------------------------------------------------------------------ #
    # lifecycle
    # ------------------------------------------------------------------ #

    async def connect(self) -> None:
        """Connect to Douyu WebSocket server and start receiving messages.

        Runs until the connection cannot be recovered or the task is cancelled.
        Re-raises :class:`asyncio.CancelledError` (proper cancellation
        semantics) after cleaning up, so the caller stays in control.
        """
        if self._connect_task is not None:
            raise RuntimeError("connect() is already running on this collector")
        self._connect_task = asyncio.current_task()
        self._state = CaptureState.DISCOVERING
        ssl_context = _douyu_ssl_context()

        try:
            while True:
                await self.refresh_candidates(force=not self._candidate_urls)

                if self._candidate_urls:
                    await self._try_candidates(ssl_context)

                # Either no endpoint was reachable or the session dropped:
                # back off before retrying so a dead edge cannot spin us.
                self._state = CaptureState.BACKOFF
                await asyncio.sleep(WS_RECOVERY_BACKOFF_SECONDS)
                self._state = CaptureState.DISCOVERING
                await self.refresh_candidates(force=True)
        except asyncio.CancelledError:
            self._state = CaptureState.STOPPING
            raise
        finally:
            await self._stop_heartbeat()
            if self._discovery_task is not None:
                self._discovery_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._discovery_task
                self._discovery_task = None
            self._websocket = None
            self._connect_task = None
            self._state = CaptureState.STOPPED

    async def _try_candidates(self, ssl_context: ssl.SSLContext) -> None:
        """Try each candidate once, stopping at the first that connects.

        Returns as soon as a session has run, whether it ended in a drop or
        all candidates were unreachable; the caller backs off either way.
        """
        for _ in range(len(self._candidate_urls)):
            url = self._candidate_urls[self._candidate_index % len(self._candidate_urls)]
            self._candidate_index += 1

            try:
                websocket = await self._connect_with_retry(url, ssl_context)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.debug("connect to %s failed: %s", url, exc)
                continue

            try:
                async with websocket:
                    self._websocket = websocket
                    self._state = CaptureState.HANDSHAKING
                    await self._send_login()
                    await self._send_joingroup()
                    self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
                    self._state = CaptureState.STREAMING
                    await self._process_messages()
                    return
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.debug("session on %s ended: %s", url, exc)
            finally:
                await self._stop_heartbeat()
                self._websocket = None
                self._state = CaptureState.CONNECTING
            return  # connected, then dropped: let the caller back off

    async def stop(self) -> None:
        """Stop the collector gracefully.

        Douyu's danmu server never completes the WebSocket close handshake,
        so ``close()`` is bounded by a timeout and the transport is aborted
        when the server stays silent - otherwise shutdown would hang forever.

        Also cancels an in-flight ``connect()`` so an await that is stuck in
        HTTP discovery cannot delay shutdown past this call.
        """
        task = self._connect_task
        websocket = self._websocket
        if task is not None:
            task.cancel()
        if websocket is None:
            return
        try:
            await asyncio.wait_for(websocket.close(), timeout=2)
        except TimeoutError:
            transport = getattr(websocket, "transport", None)
            if transport is not None:
                transport.abort()
        except Exception:
            logger.debug("socket already closed; nothing to close", exc_info=True)

    async def aclose(self) -> None:
        """Close the sink currently being written.

        The caller has to do this, not whoever opened the *first* sink: after a
        rollover those are different objects, and closing the first would leave
        the live shard unflushed with no ``ended_at`` - which reads as an
        interrupted run forever.
        """
        await self._retire(self.storage)

    async def _connect_with_retry(self, url: str, ssl_context: ssl.SSLContext) -> Any:
        """Connect to one endpoint, retrying transport failures."""
        self._state = CaptureState.CONNECTING
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

    async def refresh_candidates(self, force: bool = False) -> None:
        """Refresh danmu server candidates, preferring the warm cache.

        On a cold start the last known endpoints are adopted immediately so the
        socket handshake does not wait behind live discovery; the live lookup
        still runs (in the background) and refreshes the cache. Discovery is
        the slow part of a restart - seconds, versus a ~100-300ms handshake.
        """
        now = asyncio.get_running_loop().time()
        if not force and (now - self._last_discovery_time) < WS_SERVER_REFRESH_INTERVAL_SECONDS:
            return

        if not self._candidate_urls and self._data_dir is not None:
            cached = load(self._data_dir, self.room_id)
            if cached is not None:
                self._candidate_urls = list(cached.urls)
                self._real_room_id = cached.real_room_id
                self._last_discovery_time = now
                logger.debug(
                    "warm start from endpoint cache: %d urls for room %d",
                    len(cached.urls),
                    cached.real_room_id,
                )
                # Refresh in the background: a stale cache must not block the
                # connection we can already make.
                self._discovery_task = asyncio.create_task(self._refresh_in_background())
                return

        await self._discover()

    async def _refresh_in_background(self) -> None:
        """Live discovery that must not delay the current connection."""
        with contextlib.suppress(Exception):
            await self._discover()

    async def _discover(self) -> None:
        self._state = CaptureState.DISCOVERING
        urls, real_room_id = await asyncio.to_thread(
            get_danmu_server, self.room_id, 10.0, self.ws_url_override
        )
        self._candidate_urls, self._real_room_id = urls, real_room_id
        self._last_discovery_time = asyncio.get_running_loop().time()
        if self._candidate_index >= len(self._candidate_urls):
            self._candidate_index = 0
        if self._data_dir is not None:
            store(self._data_dir, self.room_id, urls, real_room_id)

    async def _heartbeat_loop(self) -> None:
        """Send heartbeat messages periodically until cancelled."""
        while self._websocket is not None:
            await asyncio.sleep(WS_DOUYU_HEARTBEAT_SECONDS)
            if self._websocket is None:
                return
            heartbeat_msg = serialize_message({"type": "mrkl"})
            await self._send_with_retry(encode_message(heartbeat_msg))

    async def _stop_heartbeat(self) -> None:
        """Stop heartbeat task."""
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._heartbeat_task
            self._heartbeat_task = None

    async def _process_messages(self) -> None:
        """Receive loop.

        Runs until the socket drops or the read goes idle for
        ``WS_READ_IDLE_TIMEOUT_SECONDS``; both are treated as a lost
        connection by the caller. A trailing partial packet left in
        ``MessageBuffer`` is dropped here - at most one message, per drop.
        """
        if not self._websocket:
            raise RuntimeError("WebSocket not connected")

        while self._websocket is not None:
            message = await asyncio.wait_for(
                self._websocket.recv(), timeout=WS_READ_IDLE_TIMEOUT_SECONDS
            )

            if isinstance(message, str):
                message_data = message.encode("utf-8", errors="ignore")
            else:
                message_data = message

            self._buffer.add_data(message_data)
            for msg_dict in self._buffer.get_messages():
                msg_type = msg_dict.get("type", "unknown")
                await self._handle_message(msg_type, msg_dict)

    async def _handle_message(self, msg_type: str, msg_dict: dict[str, str]) -> None:
        """Route one decoded message to storage, applying the type filters."""
        if msg_type == LOGIN_RESPONSE:
            return

        if should_skip(msg_type, self.type_filter, self.type_exclude):
            return

        timestamp = datetime.now()
        if msg_type == CHATMSG:
            message = build_chat_message(msg_dict, self._real_room_id, timestamp)
        else:
            enum_value = resolve_message_type(msg_type)
            if enum_value is None:
                return
            message = build_structured_message(msg_dict, enum_value, self._real_room_id, timestamp)

        await self.storage.save(message)
        if self.storage.needs_rotation:
            await self.rotate(reason="rotate_after")
        if self.message_callback is not None:
            self.message_callback(message)
