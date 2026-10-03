"""Storage handler base class and implementations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from types import TracebackType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..types import DanmuMessage


class StorageHandler(ABC):
    """Abstract base class for danmu storage backends.

    All storage implementations must inherit from this class and implement
    the required async methods.

    Example:
        class MyStorage(StorageHandler):
            async def save(self, message: DanmuMessage) -> None:
                ...

            async def close(self) -> None:
                ...
    """

    @abstractmethod
    async def save(self, message: DanmuMessage) -> None:
        """Persist a single danmu message.

        Args:
            message: The danmu message to persist.
        """
        ...

    @abstractmethod
    async def close(self) -> None:
        """Close and cleanup storage resources."""
        ...

    @property
    def needs_rotation(self) -> bool:
        """True when the collector should roll over to a new run file.

        Only sinks that are backed by a rotatable file (SQLite) ever answer
        true; the collector uses this to decide whether to call ``rotate()``.
        """
        return False

    @property
    def run_ref(self) -> str:
        """Human-readable identifier of the file/sink currently being written."""
        return type(self).__name__

    async def open(self) -> StorageHandler:
        """Acquire resources. Idempotent-ish: called once per sink instance."""
        await self.__aenter__()
        return self

    async def __aenter__(self) -> StorageHandler:
        """Async context manager entry."""
        return self

    async def __aexit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc_val: BaseException | None,
        _exc_tb: TracebackType | None,
    ) -> None:
        """Async context manager exit."""
        await self.close()
