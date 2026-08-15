"""PostgreSQL storage handler with batch write support."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

import psycopg
from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from ..constants import DB_BATCH_FLUSH_INTERVAL_SECONDS, DB_BATCH_SIZE
from ..types import DanmuMessage
from .base import StorageHandler

INSERT_DANMAKU_QUERY = """
INSERT INTO danmaku (
    timestamp, room_id, msg_type, user_id, username, content,
    user_level, gift_id, gift_count, gift_name,
    badge_level, badge_name, noble_level, avatar_url, raw_data
) VALUES (
    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
)
"""


def _normalize_string(value: str) -> tuple[str, bool]:
    normalized = value
    modified = False

    if "\x00" in normalized:
        normalized = normalized.replace("\x00", "")
        modified = True

    try:
        normalized.encode("utf-8", "strict")
    except UnicodeEncodeError:
        normalized = normalized.encode("utf-8", "replace").decode("utf-8")
        modified = True

    return normalized, modified


def _sanitize_json_value(value: Any) -> tuple[Any, bool]:
    if isinstance(value, str):
        return _normalize_string(value)

    if isinstance(value, dict):
        sanitized_dict: dict[str, Any] = {}
        modified = False
        for key, nested_value in value.items():
            sanitized_key, key_modified = _normalize_string(key)
            sanitized_nested_value, value_modified = _sanitize_json_value(nested_value)
            sanitized_dict[sanitized_key] = sanitized_nested_value
            modified = modified or key_modified or value_modified
        return sanitized_dict, modified

    if isinstance(value, list):
        sanitized_list: list[Any] = []
        modified = False
        for nested_value in value:
            sanitized_nested_value, value_modified = _sanitize_json_value(nested_value)
            sanitized_list.append(sanitized_nested_value)
            modified = modified or value_modified
        return sanitized_list, modified

    if isinstance(value, tuple):
        sanitized_items: list[Any] = []
        modified = False
        for nested_value in value:
            sanitized_nested_value, value_modified = _sanitize_json_value(nested_value)
            sanitized_items.append(sanitized_nested_value)
            modified = modified or value_modified
        return tuple(sanitized_items), modified

    return value, False


def _serialize_log_record(record: dict[str, Any]) -> str:
    return json.dumps(record, ensure_ascii=True, default=str, sort_keys=True)


def _append_text_line(path: Path, line: str) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line)


def _is_data_error(exc: Exception) -> bool:
    if isinstance(exc, psycopg.DataError):
        return True

    error_text = str(exc).lower()
    return (
        "unsupported unicode escape sequence" in error_text
        or "cannot be converted to text" in error_text
        or "invalid byte sequence" in error_text
    )


def _is_operational_error(exc: Exception) -> bool:
    return isinstance(exc, (psycopg.InterfaceError, psycopg.OperationalError))


class _PreparedMessage:
    def __init__(
        self,
        *,
        original: DanmuMessage,
        values: tuple[object, ...],
        sanitation_reasons: list[str],
        sanitized_raw_data: dict[str, Any] | None,
    ) -> None:
        self.original = original
        self.values = values
        self.sanitation_reasons = sanitation_reasons
        self.sanitized_raw_data = sanitized_raw_data


class PostgreSQLStorage(StorageHandler):
    """Async PostgreSQL storage with batch write optimization.

    This storage handler buffers messages and writes them in batches
    to improve performance for high-frequency collection.

    The buffer is flushed when:
    - Buffer reaches DB_BATCH_SIZE (default 100)
    - DB_BATCH_FLUSH_INTERVAL_SECONDS (default 5) elapsed since last flush
    - Storage is closed

    Example:
        # Create with factory method
        storage = await PostgreSQLStorage.create(
            room_id="6657",
            host="localhost",
            port=5432,
            database="douyu",
            user="douyu",
            password="pass"
        )

        # Use as context manager
        async with storage:
            await storage.save(message1)
            await storage.save(message2)
        # Auto-flushes and closes
    """

    def __init__(
        self,
        room_id: str,
        host: str,
        port: int,
        database: str,
        user: str,
        password: str,
        batch_size: int = DB_BATCH_SIZE,
        flush_interval: float = DB_BATCH_FLUSH_INTERVAL_SECONDS,
    ) -> None:
        """Initialize PostgreSQL storage.

        Note: Use create() factory method instead of calling directly.

        Args:
            room_id: Room ID for this storage instance.
            host: PostgreSQL server hostname.
            port: PostgreSQL server port.
            database: Database name.
            user: Username.
            password: Password.
            batch_size: Number of messages to buffer before flushing.
            flush_interval: Maximum seconds between flushes.
        """
        self.room_id = room_id
        self._host = host
        self._port = port
        self._database = database
        self._user = user
        self._password = password
        self._batch_size = batch_size
        self._flush_interval = flush_interval

        self._connection: AsyncConnection[Any] | None = None
        self._buffer: list[DanmuMessage] = []
        self._flush_task: asyncio.Task[None] | None = None
        self._last_flush_time: float = 0
        self._closed = False
        quarantine_path = os.environ.get("DYCAP_BAD_RECORDS_PATH")
        if quarantine_path:
            self._bad_records_path = Path(quarantine_path)
        else:
            self._bad_records_path = Path.cwd() / ".dycap-bad-records.ndjson"

    @classmethod
    async def create(
        cls,
        room_id: str,
        host: str = "localhost",
        port: int = 5432,
        database: str = "douyu",
        user: str = "douyu",
        password: str = "",
        batch_size: int = DB_BATCH_SIZE,
        flush_interval: float = DB_BATCH_FLUSH_INTERVAL_SECONDS,
    ) -> PostgreSQLStorage:
        """Factory method to create and initialize PostgreSQL storage.

        Args:
            room_id: Room ID for this storage.
            host: PostgreSQL server hostname.
            port: PostgreSQL server port.
            database: Database name.
            user: Username.
            password: Password.
            batch_size: Number of messages to buffer before flushing.
            flush_interval: Maximum seconds between flushes.

        Returns:
            Initialized PostgreSQLStorage instance.
        """
        instance = cls(
            room_id=room_id,
            host=host,
            port=port,
            database=database,
            user=user,
            password=password,
            batch_size=batch_size,
            flush_interval=flush_interval,
        )
        await instance._connect()
        return instance

    @classmethod
    async def create_from_dsn(
        cls,
        room_id: str,
        dsn: str,
        batch_size: int = DB_BATCH_SIZE,
        flush_interval: float = DB_BATCH_FLUSH_INTERVAL_SECONDS,
    ) -> PostgreSQLStorage:
        """Factory method to create and initialize PostgreSQL storage from DSN."""
        instance = cls(
            room_id=room_id,
            host="localhost",
            port=5432,
            database="douyu",
            user="douyu",
            password="",
            batch_size=batch_size,
            flush_interval=flush_interval,
        )

        # Keep full DSN query params (e.g., search_path).
        instance._connection = await AsyncConnection.connect(dsn)
        await instance._create_schema()
        instance._last_flush_time = asyncio.get_running_loop().time()
        instance._flush_task = asyncio.create_task(instance._flush_loop())
        return instance

    async def _connect(self) -> None:
        """Establish database connection and create schema."""
        self._connection = await AsyncConnection.connect(
            host=self._host,
            port=self._port,
            dbname=self._database,
            user=self._user,
            password=self._password,
        )
        await self._create_schema()
        self._last_flush_time = asyncio.get_running_loop().time()
        self._flush_task = asyncio.create_task(self._flush_loop())

    async def _create_schema(self) -> None:
        """Create danmaku table and indexes if not exists."""
        if self._connection is None:
            return

        async with self._connection.cursor() as cursor:
            schema_query = """
            CREATE TABLE IF NOT EXISTS danmaku (
                id          SERIAL PRIMARY KEY,
                timestamp   TIMESTAMP NOT NULL,
                room_id     TEXT NOT NULL,
                msg_type    TEXT NOT NULL,
                user_id     TEXT,
                username    TEXT,
                content     TEXT,
                user_level  INTEGER,
                gift_id     TEXT,
                gift_count  INTEGER,
                gift_name   TEXT,
                badge_level INTEGER,
                badge_name  TEXT,
                noble_level INTEGER,
                avatar_url  TEXT,
                raw_data    JSONB
            );
            CREATE INDEX IF NOT EXISTS idx_danmaku_room_time
                ON danmaku(room_id, timestamp DESC);
            CREATE INDEX IF NOT EXISTS idx_danmaku_user_id
                ON danmaku(user_id);
            CREATE INDEX IF NOT EXISTS idx_danmaku_msg_type
                ON danmaku(msg_type);

            CREATE TABLE IF NOT EXISTS danmaku_dead_letter (
                id            SERIAL PRIMARY KEY,
                failed_at     TIMESTAMP NOT NULL DEFAULT NOW(),
                room_id       TEXT NOT NULL,
                msg_type      TEXT NOT NULL,
                username      TEXT,
                content       TEXT,
                reason        TEXT NOT NULL,
                error_type    TEXT,
                error_message TEXT,
                payload_text  TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_danmaku_dead_letter_failed_at
                ON danmaku_dead_letter(failed_at DESC);
            """
            await cursor.execute(schema_query)
        await self._connection.commit()

    def _prepare_message(self, msg: DanmuMessage) -> _PreparedMessage:
        sanitation_reasons: list[str] = []

        user_id = msg.user_id
        if user_id is not None:
            user_id, modified = _normalize_string(user_id)
            if modified:
                sanitation_reasons.append("user_id")

        username = msg.username
        if username is not None:
            username, modified = _normalize_string(username)
            if modified:
                sanitation_reasons.append("username")

        content = msg.content
        if content is not None:
            content, modified = _normalize_string(content)
            if modified:
                sanitation_reasons.append("content")

        gift_id = msg.gift_id
        if gift_id is not None:
            gift_id, modified = _normalize_string(gift_id)
            if modified:
                sanitation_reasons.append("gift_id")

        gift_name = msg.gift_name
        if gift_name is not None:
            gift_name, modified = _normalize_string(gift_name)
            if modified:
                sanitation_reasons.append("gift_name")

        badge_name = msg.badge_name
        if badge_name is not None:
            badge_name, modified = _normalize_string(badge_name)
            if modified:
                sanitation_reasons.append("badge_name")

        avatar_url = msg.avatar_url
        if avatar_url is not None:
            avatar_url, modified = _normalize_string(avatar_url)
            if modified:
                sanitation_reasons.append("avatar_url")

        sanitized_raw_data: dict[str, Any] | None = None
        raw_data_json: Jsonb | None = None
        if msg.raw_data is not None:
            sanitized_raw_data_candidate, modified = _sanitize_json_value(msg.raw_data)
            if not isinstance(sanitized_raw_data_candidate, dict):
                sanitized_raw_data = {"value": sanitized_raw_data_candidate}
                modified = True
            else:
                sanitized_raw_data = sanitized_raw_data_candidate
            if modified:
                sanitation_reasons.append("raw_data")
            raw_data_json = Jsonb(sanitized_raw_data)

        return _PreparedMessage(
            original=msg,
            values=(
                msg.timestamp,
                msg.room_id,
                msg.msg_type.value,
                user_id,
                username,
                content,
                msg.user_level,
                gift_id,
                msg.gift_count,
                gift_name,
                msg.badge_level,
                badge_name,
                msg.noble_level,
                avatar_url,
                raw_data_json,
            ),
            sanitation_reasons=sanitation_reasons,
            sanitized_raw_data=sanitized_raw_data,
        )

    def _build_bad_record_payload(
        self,
        prepared: _PreparedMessage,
        *,
        reason: str,
        error: Exception | None = None,
    ) -> dict[str, Any]:
        msg = prepared.original
        payload = {
            "timestamp": msg.timestamp.isoformat(),
            "room_id": msg.room_id,
            "msg_type": msg.msg_type.value,
            "user_id": msg.user_id,
            "username": msg.username,
            "content": msg.content,
            "user_level": msg.user_level,
            "gift_id": msg.gift_id,
            "gift_count": msg.gift_count,
            "gift_name": msg.gift_name,
            "badge_level": msg.badge_level,
            "badge_name": msg.badge_name,
            "noble_level": msg.noble_level,
            "avatar_url": msg.avatar_url,
            "raw_data": msg.raw_data,
            "sanitized_raw_data": prepared.sanitized_raw_data,
            "sanitation_reasons": prepared.sanitation_reasons,
            "reason": reason,
        }
        if error is not None:
            payload["error_type"] = type(error).__name__
            payload["error_message"] = str(error)
        return payload

    async def _append_bad_record_log(self, payload: dict[str, Any]) -> None:
        self._bad_records_path.parent.mkdir(parents=True, exist_ok=True)
        line = _serialize_log_record(payload) + "\n"
        await asyncio.to_thread(_append_text_line, self._bad_records_path, line)

    async def _store_dead_letter(
        self,
        prepared: _PreparedMessage,
        *,
        reason: str,
        error: Exception | None = None,
    ) -> None:
        if self._connection is None:
            return

        payload = self._build_bad_record_payload(prepared, reason=reason, error=error)
        payload_text = _serialize_log_record(payload)
        await self._append_bad_record_log(payload)

        try:
            async with self._connection.cursor() as cursor:
                await cursor.execute(
                    """
                    INSERT INTO danmaku_dead_letter (
                        room_id, msg_type, username, content,
                        reason, error_type, error_message, payload_text
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        prepared.original.room_id,
                        prepared.original.msg_type.value,
                        prepared.original.username,
                        prepared.original.content,
                        reason,
                        type(error).__name__ if error is not None else None,
                        str(error) if error is not None else None,
                        payload_text,
                    ),
                )
            await self._connection.commit()
        except Exception:
            await self._connection.rollback()

    async def _insert_prepared_messages(self, prepared_messages: list[_PreparedMessage]) -> None:
        if not prepared_messages or self._connection is None:
            return

        async with self._connection.cursor() as cursor:
            await cursor.executemany(
                INSERT_DANMAKU_QUERY,
                [prepared.values for prepared in prepared_messages],
            )

    async def _insert_single_prepared_message(self, prepared: _PreparedMessage) -> None:
        if self._connection is None:
            return

        async with self._connection.cursor() as cursor:
            await cursor.execute(INSERT_DANMAKU_QUERY, prepared.values)

    async def _flush_loop(self) -> None:
        """Background task to flush buffer periodically."""
        while not self._closed:
            await asyncio.sleep(self._flush_interval)
            if self._buffer and not self._closed:
                await self._flush()

    async def _flush(self) -> None:
        """Flush buffered messages to database."""
        if not self._buffer or self._connection is None:
            return

        messages = self._buffer.copy()
        self._buffer.clear()
        self._last_flush_time = asyncio.get_running_loop().time()
        prepared_messages = [self._prepare_message(msg) for msg in messages]

        try:
            await self._insert_prepared_messages(prepared_messages)
            await self._connection.commit()
        except Exception as exc:
            await self._connection.rollback()

            batch_payload = {
                "reason": "batch_insert_failed",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "batch_size": len(prepared_messages),
                "room_id": self.room_id,
                "messages": [
                    self._build_bad_record_payload(prepared, reason="batch_insert_failed")
                    for prepared in prepared_messages
                ],
            }
            await self._append_bad_record_log(batch_payload)

            if _is_operational_error(exc):
                self._buffer = messages + self._buffer
                raise

            if not _is_data_error(exc):
                self._buffer = messages + self._buffer
                raise

            for index, prepared in enumerate(prepared_messages):
                try:
                    await self._insert_single_prepared_message(prepared)
                    await self._connection.commit()
                except Exception as row_exc:
                    await self._connection.rollback()
                    if _is_operational_error(row_exc):
                        remaining_messages = [
                            pending.original for pending in prepared_messages[index:]
                        ]
                        self._buffer = remaining_messages + self._buffer
                        raise

                    await self._store_dead_letter(
                        prepared,
                        reason="row_insert_failed_after_batch_failure",
                        error=row_exc,
                    )

    async def save(self, message: DanmuMessage) -> None:
        """Add message to buffer (not immediately written).

        Message is buffered and written in batch when buffer is full
        or flush interval elapses.

        Args:
            message: Danmu message to save.
        """
        if self._closed:
            return

        self._buffer.append(message)

        if len(self._buffer) >= self._batch_size:
            await self._flush()

    async def close(self) -> None:
        """Close storage and flush remaining buffer."""
        if self._closed:
            return

        self._closed = True

        # Cancel flush task
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass

        # Final flush
        if self._buffer and self._connection:
            await self._flush()

        # Close connection
        if self._connection:
            await self._connection.close()
            self._connection = None


# Also support DSN-based creation
class PostgreSQLStorageFromDSN:
    """Factory namespace for creating PostgreSQLStorage from DSN."""

    @staticmethod
    async def create(
        room_id: str,
        dsn: str,
        batch_size: int = DB_BATCH_SIZE,
        flush_interval: float = DB_BATCH_FLUSH_INTERVAL_SECONDS,
    ) -> PostgreSQLStorage:
        """Create storage from DSN.

        Args:
            room_id: Room ID.
            dsn: PostgreSQL connection string.
            batch_size: Buffer size.
            flush_interval: Flush interval.
        """
        return await PostgreSQLStorage.create_from_dsn(
            room_id=room_id,
            dsn=dsn,
            batch_size=batch_size,
            flush_interval=flush_interval,
        )
