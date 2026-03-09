"""Console storage handler (stdout logging)."""

from __future__ import annotations

from ..render import render_message_text
from ..types import DanmuMessage
from .base import StorageHandler


class ConsoleStorage(StorageHandler):
    """Console/stdout storage handler.

    Prints danmu messages to stdout. Useful for debugging.

    Example:
        async with ConsoleStorage() as storage:
            await storage.save(message)
    """

    def __init__(self) -> None:
        """Initialize console storage."""
        pass

    async def save(self, message: DanmuMessage) -> None:
        """Print message to stdout."""
        print(f"[{message.room_id}] {render_message_text(message)}")

    async def close(self) -> None:
        """No-op for console storage."""
        pass
