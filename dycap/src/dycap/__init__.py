"""dycap - Douyu Live Stream Collector.

A modular, async library for collecting chat messages from Douyu live streams.
Each run is stored in its own SQLite file (see ``SQLiteStorage``).

Quick Start:
    # CLI
    dycap -r 6657                       # -> ./dycap-data/6657_<timestamp>.db
    dycap -r 6657 -o out/run.db         # custom location/filename

    # Python API
    from dycap import AsyncCollector
    from dycap.storage import SQLiteStorage

    async with SQLiteStorage("run.db", room_id="6657") as storage:
        collector = AsyncCollector("6657", storage)
        await collector.connect()
"""

from __future__ import annotations

from .collector import AsyncCollector
from .storage import ConsoleStorage, CSVStorage, SQLiteStorage, StorageHandler
from .types import DanmuMessage, MessageType

__version__ = "0.2.0"

__all__ = [
    "__version__",
    # Collector
    "AsyncCollector",
    # Storage
    "StorageHandler",
    "SQLiteStorage",
    "CSVStorage",
    "ConsoleStorage",
    # Types
    "DanmuMessage",
    "MessageType",
]
