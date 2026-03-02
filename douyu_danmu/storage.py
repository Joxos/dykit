"""Abstract base class for pluggable danmu message storage implementations.

This module defines the StorageHandler interface that all concrete storage
implementations must follow. It provides a standardized way to save danmu messages
to different backends (CSV, database, cloud storage, etc.) with automatic resource
cleanup via the context manager protocol.

Classes:
    StorageHandler: Abstract base class defining the storage interface.

Usage Example:
    ```python
    from douyu_danmu import DanmuMessage
    from douyu_danmu.storage import StorageHandler

    class FileStorage(StorageHandler):
        '''Custom storage that appends messages to a file.'''

        def __init__(self, filepath):
            self.filepath = filepath
            self.file = open(filepath, 'w')

        def save(self, message: DanmuMessage) -> None:
            self.file.write(f"{message.username}: {message.content}\\n")

        def close(self) -> None:
            self.file.close()

    # Usage with context manager (automatic cleanup)
    with FileStorage('messages.txt') as storage:
        storage.save(some_message)
        storage.save(another_message)
        # File automatically closed when exiting 'with' block
    ```

Design Notes:
    - All subclasses MUST implement save() and close() methods
    - Use the context manager protocol (__enter__/__exit__) for resource management
    - Storage handlers should be tolerant of concurrent calls and edge cases
    - The save() method receives complete DanmuMessage objects with all fields set
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from .types import DanmuMessage


class StorageHandler(ABC):
    """Abstract base class for danmu message storage backends.

    This class defines the interface that all concrete storage implementations
    must follow. It supports the context manager protocol for safe resource
    management and provides abstract methods for persisting and finalizing
    danmu message storage.

    Methods:
        save(message): Persist a single danmu message to storage.
        close(): Finalize storage and release any held resources.

    Context Manager Protocol:
        StorageHandler supports Python's context manager protocol, enabling
        use with 'with' statements for automatic resource cleanup.

    Example:
        ```python
        with MyCustomStorage(config) as storage:
            for message in collector.messages:
                storage.save(message)
        # Resources automatically cleaned up
        ```
    """

    @abstractmethod
    def save(self, message: DanmuMessage) -> None:
        """Store a single danmu message.

        Implementations should persist the message to their configured storage
        backend (file, database, cloud, etc.). The message object is immutable
        and fully populated with all available fields.

        Args:
            message: A complete DanmuMessage object containing timestamp, user
                info, content, and raw protocol data.

        Returns:
            None

        Raises:
            Subclasses may raise appropriate exceptions for I/O errors, storage
            unavailability, etc. The caller is responsible for error handling.

        Note:
            - This method may be called frequently (many messages per second)
            - Implementations should optimize for throughput
            - The message object is immutable (frozen dataclass)
            - All fields may be None except timestamp and msg_type
        """
        pass

    @abstractmethod
    def close(self) -> None:
        """Finalize storage and release resources.

        Implementations should perform final cleanup operations such as:
        - Flushing pending writes to disk
        - Closing file handles or database connections
        - Finalizing transaction batches
        - Writing footers or metadata

        Returns:
            None

        Note:
            - Called automatically when exiting a 'with' context
            - May be called multiple times; should be idempotent
            - Should not raise exceptions if called on already-closed storage
        """
        pass

    def __enter__(self) -> StorageHandler:
        """Enter the runtime context related to this object.

        Called when entering a 'with' block. By default, returns self to allow
        the context variable to be assigned.

        Subclasses may override to perform initialization operations.

        Returns:
            The StorageHandler instance (typically self).
        """
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        """Exit the runtime context and ensure cleanup.

        Called when exiting a 'with' block. Automatically calls close() to
        ensure resources are cleaned up regardless of whether an exception
        occurred.

        Args:
            exc_type: The exception type if an exception was raised, else None.
            exc_val: The exception instance if an exception was raised, else None.
            exc_tb: The exception traceback if an exception was raised, else None.

        Returns:
            None (exceptions are not suppressed)

        Note:
            - Returning None means exceptions are NOT suppressed
            - Implementations can override to handle cleanup-related errors
        """
        self.close()


import csv
import os

from .types import MessageType


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

    Attributes:
        filepath: Path to the CSV file where messages will be stored.
        csv_file: File handle for the CSV file (None if not yet opened or closed).
        csv_writer: CSV writer object for writing rows to the file.

    Example:
        ```python
        from douyu_danmu import DanmuMessage
        from douyu_danmu.storage import CSVStorage

        # Write messages with automatic file creation and cleanup
        with CSVStorage('output.csv') as storage:
            storage.save(message1)
            storage.save(message2)
        # File automatically closed and flushed
        ```
    """

    def __init__(self, filepath: str) -> None:
        """Initialize CSV storage with a file path.

        Opens or creates the CSV file. If the file is new, a header row is
        automatically written. If the file already exists with content, new
        messages are appended without re-writing the header.

        Args:
            filepath: Path to the CSV file where messages will be stored.
                If the file does not exist, it will be created with a header row.
                If the file exists and has content, messages are appended.

        Raises:
            OSError: If the file cannot be opened or created.
        """
        self.filepath = filepath
        self.csv_file: Any = None
        self.csv_writer: Any = None

        # Check if file exists and is not empty
        file_exists = (
            os.path.exists(self.filepath) and os.path.getsize(self.filepath) > 0
        )

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
                ]
            )
            self.csv_file.flush()

    def save(self, message: DanmuMessage) -> None:
        """Persist a single danmu message to the CSV file.

        Writes one row to the CSV file using the message's fields. The timestamp
        is converted from datetime to ISO 8601 format. All field values are
        extracted from the message and written in the column order: timestamp,
        username, content, user_level, user_id, room_id.

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


class ConsoleStorage(StorageHandler):
    """Console/stdout storage handler for printing danmu messages.

    Prints danmu messages directly to stdout with configurable verbosity.
    Useful for real-time monitoring, debugging, and log aggregation.

    In default mode, only prints CHATMSG type messages with the format:
        [username] Lv{level}: {content}

    In verbose mode, prints all message types with full details:
        [MESSAGE_TYPE] message details

    This handler does not perform any I/O besides stdout printing,
    so close() is a no-op.

    Attributes:
        verbose: Whether to print all message types or only chatmsg.

    Example:
        ```python
        from douyu_danmu import DanmuMessage
        from douyu_danmu.storage import ConsoleStorage

        # Default: print only chatmsg
        with ConsoleStorage() as storage:
            storage.save(message)

        # Verbose: print all message types
        with ConsoleStorage(verbose=True) as storage:
            storage.save(message)
        ```
    """

    def __init__(self, verbose: bool = False) -> None:
        """Initialize ConsoleStorage with optional verbosity.

        Args:
            verbose: If True, print all message types with full details.
                If False, only print CHATMSG type messages. Defaults to False.
        """
        self.verbose = verbose

    def save(self, message: DanmuMessage) -> None:
        """Print a danmu message to stdout.

        In default mode (verbose=False), only prints CHATMSG messages with
        the format: [username] Lv{level}: {content}

        In verbose mode (verbose=True), prints all message types with
        the format: [MESSAGE_TYPE] additional details

        Args:
            message: The DanmuMessage to print.
        """
        if self.verbose:
            # Verbose mode: print all message types with full details
            msg_type_name = message.msg_type.value.upper()
            if message.msg_type == MessageType.CHATMSG:
                print(
                    f"[{msg_type_name}] [{message.username}] "
                    f"Lv{message.user_level}: {message.content}"
                )
            else:
                # For non-chatmsg types, print type and relevant fields
                print(f"[{msg_type_name}] {message.msg_type.value}")
        else:
            # Default mode: only print chatmsg
            if message.msg_type == MessageType.CHATMSG:
                print(f"[{message.username}] Lv{message.user_level}: {message.content}")

    def close(self) -> None:
        """Finalize console output.

        This is a no-op for console storage since stdout does not require
        explicit closing. Provided to satisfy the StorageHandler interface.
        """
        pass
