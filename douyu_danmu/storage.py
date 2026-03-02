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
