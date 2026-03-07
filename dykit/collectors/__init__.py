"""Collectors package for Douyu danmu message collection.

This package provides an async collector implementation:
- AsyncCollector: Non-blocking, asyncio-based WebSocket collector
Both collectors handle login, room joining, heartbeat maintenance, and
message parsing with UTF-8 safety via MessageBuffer.


Example Usage:
    ```python
    import asyncio
    from dykit.collectors import AsyncCollector
    from dykit.storage import CSVStorage

    async def main():
        async with CSVStorage('output.csv') as storage:
            collector = AsyncCollector(room_id=6657, storage=storage)
            await collector.connect()  # Await until connection closes

    asyncio.run(main())
    ```
"""

from .async_ import AsyncCollector

__all__ = ["AsyncCollector"]
