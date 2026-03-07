"""Abstract base class for pluggable danmu message storage implementations.

This module defines the StorageHandler interface that all concrete storage
implementations must follow. It provides a standardized way to save danmu messages
to different backends (CSV, database, cloud storage, etc.) with automatic resource
cleanup via the async context manager protocol.

Classes:
    StorageHandler: Abstract base class defining the storage interface.

Usage Example:
    ```python
    from dykit import DanmuMessage
    from dykit.storage import StorageHandler

    class FileStorage(StorageHandler):
        '''Custom storage that appends messages to a file.'''

        def __init__(self, filepath):
            self.filepath = filepath
            self.file = open(filepath, 'w')

        async def save(self, message: DanmuMessage) -> None:
            self.file.write(f"{message.username}: {message.content}\\n")

        async def close(self) -> None:
            self.file.close()

    # Usage with context manager (automatic cleanup)
    async with FileStorage('messages.txt') as storage:
        await storage.save(some_message)
        await storage.save(another_message)
        # File automatically closed when exiting 'with' block
    ```

Design Notes:
    - All subclasses MUST implement save() and close() methods as async functions
    - Use the async context manager protocol (__aenter__/__aexit__) for resource management
    - Storage handlers should be tolerant of concurrent calls and edge cases
    - The save() method receives complete DanmuMessage objects with all fields set
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ..types import DanmuMessage


class StorageHandler(ABC):
    """Abstract base class for danmu message storage backends.

    This class defines the interface that all concrete storage implementations
    must follow. It supports the async context manager protocol for safe resource
    management and provides abstract methods for persisting and finalizing
    danmu message storage.

    Methods:
        save(message): Persist a single danmu message to storage (async).
        close(): Finalize storage and release any held resources (async).

    Async Context Manager Protocol:
        StorageHandler supports Python's async context manager protocol, enabling
        use with 'async with' statements for automatic resource cleanup.

    Example:
        ```python
        async with MyCustomStorage(config) as storage:
            for message in collector.messages:
                await storage.save(message)
        # Resources automatically cleaned up
        ```
    """

    @abstractmethod
    async def save(self, message: DanmuMessage) -> None:
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
    async def close(self) -> None:
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

    async def __aenter__(self) -> StorageHandler:
        """Enter the async runtime context related to this object.

        Called when entering an 'async with' block. By default, returns self to allow
        the context variable to be assigned.

        Subclasses may override to perform async initialization operations.

        Returns:
            The StorageHandler instance (typically self).
        """
        return self

    async def __aexit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc_val: BaseException | None,
        _exc_tb: Any,
    ) -> None:
        """Exit the async runtime context and ensure cleanup.

        Called when exiting an 'async with' block. Automatically calls close() to
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
        await self.close()
