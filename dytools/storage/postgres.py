"""PostgreSQL storage handler for persisting danmu messages to database.

This module provides the PostgreSQLStorage implementation for saving danmu messages
to a PostgreSQL database with automatic table creation and connection management.
All messages are stored in a single unified table named `danmaku` with flattened
fields for all message types.
"""

from __future__ import annotations

from typing import Any

import psycopg
from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from ..types import DanmuMessage
from .base import StorageHandler


class PostgreSQLStorage(StorageHandler):
    """Async storage handler for persisting danmu messages to PostgreSQL database.

    This class implements the StorageHandler interface to save danmu messages
    to a PostgreSQL database using async operations. All messages are stored in
    a single unified table named `danmaku` with flattened columns for optional
    fields (gifts, badges, noble status, avatar). The table is automatically
    created if it does not exist.

    Use the factory classmethod `create()` to instantiate and initialize the
    storage handler, as `__init__` cannot perform async operations.

    The PostgreSQL table schema is:
        ```sql
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
        ```

    Attributes:
        room_id: ID of the streaming room (for filtering records in queries).
        connection: Async PostgreSQL database connection object.

    Example:
        ```python
        from dytools import DanmuMessage
        from dytools.storage import PostgreSQLStorage

        storage = await PostgreSQLStorage.create(
            room_id="6657",
            host="localhost",
            port=5432,
            database="douyu_danmu",
            user="douyu",
            password="douyu6657"
        )
        async with storage:
            await storage.save(message1)
            await storage.save(message2)
        # Connection automatically closed
        ```
    """

    def __init__(
        self,
        room_id: str,
        host: str,
        port: int,
        database: str,
        user: str,
        password: str,
    ) -> None:
        """Initialize PostgreSQL storage with connection parameters.

        IMPORTANT: Do not call this constructor directly. Use the `create()`
        classmethod instead, which performs async connection setup and table
        initialization.

        Args:
            room_id: ID of the streaming room (stored for filtering/reference).
            host: PostgreSQL server hostname or IP address.
            port: PostgreSQL server port number.
            database: Name of the database to use.
            user: Username for authentication.
            password: Password for authentication.
        """
        self.room_id = room_id
        self.connection: AsyncConnection[Any] | None = None
        self._host = host
        self._port = port
        self._database = database
        self._user = user
        self._password = password

    @classmethod
    async def create(
        cls,
        room_id: str,
        host: str,
        port: int,
        database: str,
        user: str,
        password: str,
    ) -> PostgreSQLStorage:
        """Factory method to create and initialize PostgreSQL storage.

        Establishes an async connection to the PostgreSQL database and creates
        the unified danmaku table if it does not exist.

        Args:
            room_id: ID of the streaming room (stored for filtering/reference).
            host: PostgreSQL server hostname or IP address.
            port: PostgreSQL server port number.
            database: Name of the database to use.
            user: Username for authentication.
            password: Password for authentication.

        Returns:
            A fully initialized PostgreSQLStorage instance with active connection.

        Raises:
            psycopg.Error: If connection fails or table creation fails.

        Example:
            ```python
            storage = await PostgreSQLStorage.create(
                room_id="6657",
                host="localhost",
                port=5432,
                database="douyu",
                user="douyu",
                password="password"
            )
            ```
        """
        instance = cls(
            room_id=room_id,
            host=host,
            port=port,
            database=database,
            user=user,
            password=password,
        )

        try:
            # Establish async database connection
            instance.connection = await AsyncConnection.connect(
                host=host,
                port=port,
                dbname=database,  # psycopg uses 'dbname', not 'database'
                user=user,
                password=password,
            )
            # Create table if not exists
            await instance._create_table()
        except psycopg.Error:
            if instance.connection is not None:
                await instance.connection.close()
            raise

        return instance

    async def _create_table(self) -> None:
        """Create the unified danmaku table with flattened schema.

        Uses CREATE TABLE IF NOT EXISTS to safely handle cases where the table
        already exists. Creates a single denormalized table with all optional
        fields as columns, plus indexes for efficient querying.

        Raises:
            psycopg.Error: If table creation fails.
        """
        if self.connection is None:
            return

        try:
            async with self.connection.cursor() as cursor:
                # Create unified danmaku table with flattened schema
                create_table_query = """
                CREATE TABLE IF NOT EXISTS danmaku (
                    id          SERIAL PRIMARY KEY,
                    timestamp   TIMESTAMP NOT NULL,
                    room_id     TEXT NOT NULL,
                    msg_type    TEXT NOT NULL,
                    user_id     TEXT,
                    username    TEXT,
                    content     TEXT,
                    user_level  INTEGER,
                    -- Gift fields (dgb)
                    gift_id     TEXT,
                    gift_count  INTEGER,
                    gift_name   TEXT,
                    -- Badge fields (uenter, blab)
                    badge_level INTEGER,
                    badge_name  TEXT,
                    -- Noble fields (anbc, rnewbc)
                    noble_level INTEGER,
                    -- Avatar (uenter)
                    avatar_url  TEXT,
                    raw_data    JSONB
                );
                CREATE INDEX IF NOT EXISTS idx_danmaku_room_time
                    ON danmaku(room_id, timestamp DESC);
                CREATE INDEX IF NOT EXISTS idx_danmaku_user_id
                    ON danmaku(user_id);
                CREATE INDEX IF NOT EXISTS idx_danmaku_msg_type
                    ON danmaku(msg_type);
                """

                await cursor.execute(create_table_query)
            await self.connection.commit()
        except psycopg.Error:
            await self.connection.rollback()
            raise

    async def save(self, message: DanmuMessage) -> None:
        """Persist a single danmu message to the PostgreSQL database.

        Inserts one row into the unified danmaku table using the message's fields.
        All optional fields (gift_*, badge_*, noble_level, avatar_url) are
        inserted, with None for any missing data.

        After each insert, the transaction is committed to ensure persistence.

        Args:
            message: A DanmuMessage object containing the message data to persist.
                The message must have a valid timestamp and msg_type. Other fields
                may be None.

        Returns:
            None

        Raises:
            psycopg.Error: If the insert operation fails.
        """
        if self.connection is None:
            return

        try:
            async with self.connection.cursor() as cursor:
                # Insert message into unified danmaku table with all flattened fields
                insert_query = """
                INSERT INTO danmaku (
                    timestamp, room_id, msg_type, user_id, username, content,
                    user_level, gift_id, gift_count, gift_name,
                    badge_level, badge_name, noble_level, avatar_url, raw_data
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                """

                # Execute insert with message values
                await cursor.execute(
                    insert_query,
                    (
                        message.timestamp,
                        message.room_id,
                        message.msg_type.value,
                        message.user_id,
                        message.username,
                        message.content,
                        message.user_level,
                        message.gift_id,
                        message.gift_count,
                        message.gift_name,
                        message.badge_level,
                        message.badge_name,
                        message.noble_level,
                        message.avatar_url,
                        Jsonb(message.raw_data) if message.raw_data else None,
                    ),
                )
            await self.connection.commit()
        except psycopg.Error:
            await self.connection.rollback()
            raise

    async def close(self) -> None:
        """Finalize storage and close the database connection.

        Closes the async PostgreSQL connection and releases associated resources.
        This method is idempotent and safe to call multiple times. If the
        connection is already closed, subsequent calls have no effect.

        Returns:
            None
        """
        if self.connection is not None:
            await self.connection.close()
            self.connection = None
