"""CSV storage handler for persisting danmu messages to files.

This module provides the CSVStorage implementation for saving danmu messages
to CSV files with automatic header creation and immediate write flushing.
"""

from __future__ import annotations

import csv
import os
from datetime import datetime
from typing import Any

# Import types needed for CSV storage
from ..types import DanmuMessage

# Import StorageHandler from base module
from .base import StorageHandler


class CSVStorage(StorageHandler):
    """Storage handler for persisting danmu messages to CSV files.

    This class implements the StorageHandler interface to save danmu messages
    to a CSV file with automatic header row creation and immediate write flushing.
    If the file already exists and has content, new messages are appended without
    re-writing the header.

    The CSV format includes the following columns:
        - timestamp: ISO 8601 formatted timestamp when the message was received
        - username: Nickname of the message sender (may be None)
        - content: The actual danmu/chat message text (may be None)
        - user_level: User's level/rank in the streaming channel (0 for unknown)
        - user_id: Unique identifier of the message sender (may be None)
        - room_id: ID of the streaming room where the message was sent (may be None)
        - msg_type: Type of protocol message (chatmsg, dgb, uenter, anbc, rnewbc, blab, upgrade)
        - extra: JSON string containing additional metadata (gift info, badge levels, noble levels) or empty string
    Attributes:
        filepath: Path to the CSV file where messages will be stored (may be auto-generated).
        room_id: ID of the streaming room (used for auto-generated filename).
        csv_file: File handle for the CSV file (None if not yet opened or closed).
        csv_writer: CSV writer object for writing rows to the file.

    Example:
        ```python
    from dytools import DanmuMessage
    from dytools.storage import CSVStorage

        # Write messages with explicit filename
        with CSVStorage('output.csv', room_id=6657) as storage:
            storage.save(message1)
            storage.save(message2)
        # File automatically closed and flushed

        # Or with auto-generated filename (from first message)
        with CSVStorage(room_id=6657) as storage:
            storage.save(message)  # Creates YYYYMMDD_HHMMSS_6657.csv
        ```
    """

    def __init__(self, filepath: str | None = None, room_id: int | None = None) -> None:
        """Initialize CSV storage with optional file path and auto-generation.

        Opens or creates the CSV file. If filepath is None, a filename will be
        auto-generated on the first save() call using the first message's timestamp
        and room_id in format: YYYYMMDD_HHMMSS_{room_id}.csv
        If filepath is provided, it's used as-is (backward compatible).
        If the file exists with content, new messages are appended without
        re-writing the header.

        Args:
            filepath: Path to the CSV file where messages will be stored.
                If None, a filename will be auto-generated on first save().
                If provided, it will be used as-is.
            room_id: ID of the streaming room (used for auto-generated filename).
                Required if filepath is None for auto-generation.

        Raises:
            OSError: If the file cannot be opened or created.
        """
        self.filepath = filepath
        self.room_id = room_id
        self.csv_file: Any = None
        self.csv_writer: Any = None
        self._auto_filename = filepath is None  # Track if we need to generate filename
        self._file_initialized = False  # Track if file has been opened and header written

    def _open_file(self, filepath: str) -> None:
        """Open or create CSV file and write header if needed.

        Args:
            filepath: Path to the CSV file to open.
        """
        if self._file_initialized:
            return  # Already opened

        self.filepath = filepath
        # Check if file exists and is not empty
        file_exists = os.path.exists(self.filepath) and os.path.getsize(self.filepath) > 0

        # Open file in append mode with newline=''
        self.csv_file = open(self.filepath, "a", newline="", encoding="utf-8")
        self.csv_writer = csv.writer(self.csv_file)

        # Write header if file is new
        if not file_exists:
            self.csv_writer.writerow(
                [
                    "timestamp",
                    "username",
                    "content",
                    "user_level",
                    "user_id",
                    "room_id",
                    "msg_type",
                    "gift_id",
                    "gift_count",
                    "gift_name",
                    "badge_level",
                    "badge_name",
                    "noble_level",
                    "avatar_url",
                ]
            )
            self.csv_file.flush()

        self._file_initialized = True

    def save(self, message: DanmuMessage) -> None:
        """Persist a single danmu message to the CSV file.

        If filepath is None (auto-generation mode), generates filename from the
        first message's timestamp (in YYYYMMDD_HHMMSS format) and room_id.
        Writes one row to the CSV file using the message's fields. The timestamp
        is converted from datetime to ISO 8601 format. All field values are
        extracted from the message and written in the column order: timestamp,
        username, content, user_level, user_id, room_id, msg_type.

        After each write, the file is flushed to disk to ensure immediate
        persistence, preventing data loss in case of unexpected termination.

        Args:
            message: A DanmuMessage object containing the message data to persist.
                The message must have a valid timestamp and msg_type. Other fields
                may be None.

        Returns:
            None

        Raises:
            IOError: If the file cannot be written to.
            ValueError: If the CSV writer is in an invalid state.
        """
        # Auto-generate filename on first save if needed
        if self._auto_filename and not self._file_initialized:
            if not isinstance(message.timestamp, datetime):
                raise ValueError("Message timestamp must be a datetime object")
            timestamp_str = message.timestamp.strftime("%Y%m%d_%H%M%S")
            filename = f"{timestamp_str}_{self.room_id}.csv"
            self._open_file(filename)

        # Ensure file is initialized before saving
        if not self._file_initialized:
            if self.filepath is None:
                raise ValueError("No filepath provided and auto-generation failed (no room_id?)")
            self._open_file(self.filepath)

        if self.csv_writer is not None and self.csv_file is not None:
            # Convert message to dict with serializable values
            msg_dict = message.to_dict()

            # Write row with specified column order
            self.csv_writer.writerow(
                [
                    msg_dict["timestamp"],
                    msg_dict["username"],
                    msg_dict["content"],
                    msg_dict["user_level"],
                    msg_dict["user_id"],
                    msg_dict["room_id"],
                    msg_dict["msg_type"],
                    msg_dict["gift_id"],
                    msg_dict["gift_count"],
                    msg_dict["gift_name"],
                    msg_dict["badge_level"],
                    msg_dict["badge_name"],
                    msg_dict["noble_level"],
                    msg_dict["avatar_url"],
                ]
            )
            # Flush immediately to disk for persistence
            self.csv_file.flush()

    def close(self) -> None:
        """Finalize storage and close the CSV file.

        Closes the file handle and releases associated resources. This method
        is idempotent and safe to call multiple times. If the file is already
        closed, subsequent calls have no effect.

        Returns:
            None
        """
        if self.csv_file is not None:
            self.csv_file.close()
            self.csv_file = None
            self.csv_writer = None
