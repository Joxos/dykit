"""PostgreSQL storage handler for persisting danmu messages to database.

This module provides the PostgreSQLStorage implementation for saving danmu messages
to a PostgreSQL database with automatic table creation and connection management.
Each room gets its own table named `danmu_{room_id}` with automatic schema creation.
"""

from __future__ import annotations

from typing import Any

import psycopg2
from psycopg2 import sql
from psycopg2.extras import Json

from ..types import DanmuMessage
from .base import StorageHandler


class PostgreSQLStorage(StorageHandler):
    """Storage handler for persisting danmu messages to PostgreSQL database.

    This class implements the StorageHandler interface to save danmu messages
    to a PostgreSQL database. Each streaming room gets its own table named
    `danmu_{room_id}` for message storage. The table is automatically created
    if it does not exist, with columns for timestamp, username, content, user level,
    user ID, and room ID.

    The PostgreSQL table schema is:
        ```sql
        CREATE TABLE IF NOT EXISTS danmu_{room_id} (
            id SERIAL PRIMARY KEY,
            timestamp TIMESTAMP NOT NULL,
            username TEXT,
            content TEXT,
            user_level INTEGER NOT NULL DEFAULT 0,
            user_id TEXT,
            room_id INTEGER
        );
        ```

    Attributes:
        room_id: ID of the streaming room.
        connection: PostgreSQL database connection object.
        table_name: Name of the table for this room (`danmu_{room_id}`).

    Example:
        ```python
        from douyu_danmu import DanmuMessage
        from douyu_danmu.storage import PostgreSQLStorage

        with PostgreSQLStorage(
            room_id=6657,
            host='localhost',
            port=5432,
            database='douyu_danmu',
            user='douyu',
            password='douyu6657'
        ) as storage:
            storage.save(message1)
            storage.save(message2)
        # Connection automatically closed
        ```
    """

    def __init__(
        self,
        room_id: int,
        host: str,
        port: int,
        database: str,
        user: str,
        password: str,
    ) -> None:
        """Initialize PostgreSQL storage with connection parameters.

        Establishes a connection to the PostgreSQL database and creates the
        table for this room if it does not exist.

        Args:
            room_id: ID of the streaming room (used for table name).
            host: PostgreSQL server hostname or IP address.
            port: PostgreSQL server port number.
            database: Name of the database to use.
            user: Username for authentication.
            password: Password for authentication.

        Raises:
            psycopg2.Error: If connection fails or table creation fails.
        """
        self.room_id = room_id
        self.table_name = f"danmu_{room_id}"
        self.connection: Any = None

        try:
            # Establish database connection
            self.connection = psycopg2.connect(
                host=host,
                port=port,
                database=database,
                user=user,
                password=password,
            )

            # Create table if not exists
            self._create_table()
        except psycopg2.Error:
            if self.connection is not None:
                self.connection.close()
            raise

    def _create_table(self) -> None:
        """Create the table for this room if it does not exist.

        Uses CREATE TABLE IF NOT EXISTS to safely handle cases where the table
        already exists. The table schema includes all columns needed for danmu
        message storage.

        Raises:
            psycopg2.Error: If table creation fails.
        """
        if self.connection is None:
            return

        try:
            cursor = self.connection.cursor()

            # Build CREATE TABLE query with parameterized table name
            create_table_query = sql.SQL(
                """
                CREATE TABLE IF NOT EXISTS {} (
                    id SERIAL PRIMARY KEY,
                    timestamp TIMESTAMP NOT NULL,
                    username TEXT,
                    content TEXT,
                    user_level INTEGER NOT NULL DEFAULT 0,
                    user_id TEXT,
                    room_id INTEGER
                )
                """
            ).format(sql.Identifier(self.table_name))

            cursor.execute(create_table_query)
            self.connection.commit()

            # Add msg_type column
            cursor.execute(
                sql.SQL("ALTER TABLE {} ADD COLUMN IF NOT EXISTS msg_type TEXT").format(
                    sql.Identifier(self.table_name)
                )
            )
            # Add extra column
            cursor.execute(
                sql.SQL("ALTER TABLE {} ADD COLUMN IF NOT EXISTS extra JSONB").format(
                    sql.Identifier(self.table_name)
                )
            )
            self.connection.commit()
            cursor.close()
        except psycopg2.Error:
            if self.connection is not None:
                self.connection.rollback()
            raise

    def save(self, message: DanmuMessage) -> None:
        """Persist a single danmu message to the PostgreSQL database.

        Inserts one row into the table for this room using the message's fields.
        The timestamp is converted from datetime to PostgreSQL TIMESTAMP format.
        All field values are extracted from the message and inserted in the
        column order: timestamp, username, content, user_level, user_id, room_id.

        After each insert, the transaction is committed to ensure persistence.

        Args:
            message: A DanmuMessage object containing the message data to persist.
                The message must have a valid timestamp and msg_type. Other fields
                may be None.

        Returns:
            None

        Raises:
            psycopg2.Error: If the insert operation fails.
        """
        if self.connection is None:
            return

        try:
            cursor = self.connection.cursor()

            # Convert message to dict with serializable values
            msg_dict = message.to_dict()

            # Build INSERT query with parameterized table name
            insert_query = sql.SQL(
                """
                INSERT INTO {} (timestamp, username, content, user_level, user_id, room_id, msg_type, extra)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """
            ).format(sql.Identifier(self.table_name))

            # Execute insert with message values
            cursor.execute(
                insert_query,
                (
                    msg_dict["timestamp"],
                    msg_dict["username"],
                    msg_dict["content"],
                    msg_dict["user_level"],
                    msg_dict["user_id"],
                    msg_dict["room_id"],
                    msg_dict["msg_type"],
                    Json(msg_dict["extra"]) if msg_dict["extra"] is not None else None,
                ),
            )
            self.connection.commit()
            cursor.close()
        except psycopg2.Error:
            if self.connection is not None:
                self.connection.rollback()
            raise

    def close(self) -> None:
        """Finalize storage and close the database connection.

        Closes the PostgreSQL connection and releases associated resources.
        This method is idempotent and safe to call multiple times. If the
        connection is already closed, subsequent calls have no effect.

        Returns:
            None
        """
        if self.connection is not None:
            self.connection.close()
            self.connection = None
