# dycap

Douyu Live Stream Danmu Collector - async library and CLI for collecting chat messages.

## Installation

```bash
pip install dycap
```

## Quick Start

### CLI

```bash
# Collect to PostgreSQL (default)
export DYKIT_DSN="postgresql://user:pass@localhost:5432/douyu"
dycap collect -r 6657

# Collect to CSV
dycap collect -r 6657 --storage csv -o backup.csv

# Collect to console
dycap collect -r 6657 --storage console

# Show version
dycap --version
```

### Python API

```python
import asyncio
from dycap import AsyncCollector, PostgreSQLStorage

async def main():
    storage = await PostgreSQLStorage.create(
        room_id="6657",
        host="localhost",
        port=5432,
        database="douyu",
        user="douyu",
        password="pass"
    )
    
    async with storage:
        collector = AsyncCollector("6657", storage)
        try:
            await collector.connect()
        except KeyboardInterrupt:
            await collector.stop()

asyncio.run(main())
```

## Features

- **Async WebSocket collection** - High-performance async collection
- **Multiple storage backends** - PostgreSQL, CSV, Console
- **Batch writes** - Optimized PostgreSQL with buffered batch inserts
- **Type filtering** - Filter message types to collect
- **Automatic reconnection** - Robust connection handling

## CLI Options

| Option | Description |
|--------|-------------|
| `-r, --room` | Room ID (required) |
| `--dsn` | PostgreSQL DSN |
| `--storage` | Storage backend (postgres/csv/console) |
| `-o, --output` | Output file for CSV |
| `-v, --verbose` | Enable verbose logging |
| `--with TYPES` | Include only specified message types (comma-separated). Available: `chatmsg（弹幕）`, `dgb（礼物）`, `uenter（进场）`, `anbc（开通贵族）`, `rnewbc（续费贵族）`, `blab（粉丝牌升级）`, `upgrade（等级升级）` |
| `--without TYPES` | Exclude specified message types (comma-separated), same candidate set as `--with` |

## Environment Variables

| Variable | Description |
|----------|-------------|
| `DYKIT_DSN` | PostgreSQL connection string |
| `DYCAP_DSN` | Alias for DYKIT_DSN |

## License

MIT
