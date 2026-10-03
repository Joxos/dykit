"""dykit - Douyu danmu capture and analysis.

One package, two commands, three leaf layers:

- ``dykit.protocol``  wire format encode/decode. Pure; no IO, no network.
- ``dykit.source``    the only module that talks HTTP to douyu.com.
- ``dykit.schema``    the run-file contract (columns, DDL, timestamps).
- ``dykit.collect``   live capture: ``dykit-capture`` CLI + storage backends.
- ``dykit.stats``     offline analysis over run files: ``dykit-stats`` CLI.

The leaves do not import each other or anything above them; ``tests/arch/
test_layering.py`` enforces it.

Quick start:
    import asyncio

    from dykit import AsyncCollector, SQLiteStorage

    async def main() -> None:
        async with SQLiteStorage("run.db", room_id="6657") as storage:
            await AsyncCollector("6657", storage).connect()

    asyncio.run(main())
"""

from __future__ import annotations

from .collect import (
    AsyncCollector,
    ConsoleStorage,
    CSVStorage,
    DanmuMessage,
    SQLiteStorage,
    StorageHandler,
)
from .protocol import (
    MessageBuffer,
    MessageType,
    PacketHeader,
    decode_message,
    deserialize_message,
    encode_message,
    serialize_message,
)
from .source import get_danmu_server, resolve_room_id

__version__ = "6.0.0"

__all__ = [
    "__version__",
    # capture
    "AsyncCollector",
    "DanmuMessage",
    # storage
    "StorageHandler",
    "SQLiteStorage",
    "CSVStorage",
    "ConsoleStorage",
    # protocol
    "MessageBuffer",
    "MessageType",
    "PacketHeader",
    "encode_message",
    "decode_message",
    "serialize_message",
    "deserialize_message",
    # source
    "resolve_room_id",
    "get_danmu_server",
]
