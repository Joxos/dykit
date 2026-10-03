"""Live capture: the collector, its payload mapping, and storage backends.

from dykit.collect import AsyncCollector, SQLiteStorage

async with SQLiteStorage("run.db", room_id="6657") as storage:
    await AsyncCollector("6657", storage).connect()
"""

from __future__ import annotations

from .collector import AsyncCollector
from .storage import ConsoleStorage, CSVStorage, SQLiteStorage, StorageHandler
from .types import DanmuMessage

__all__ = [
    "AsyncCollector",
    "CSVStorage",
    "ConsoleStorage",
    "DanmuMessage",
    "SQLiteStorage",
    "StorageHandler",
]
