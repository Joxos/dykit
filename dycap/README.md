# dycap

Douyu Live Stream Danmu Collector - async library and CLI for collecting chat
messages into per-run SQLite files.

## Installation

```bash
pip install dycap
```

## Quick Start

### CLI

```bash
# Collect one run (default: ./dycap-data/6657_<timestamp>.db)
dycap -r 6657

# Custom output location/filename
dycap -r 6657 -o backup/run.db

# Collect to CSV or console
dycap -r 6657 --storage csv -o backup.csv
dycap -r 6657 --storage console

# Show version
dycap --version
```

### Python API

```python
import asyncio
from dycap import AsyncCollector
from dycap.storage import SQLiteStorage

async def main():
    async with SQLiteStorage("run.db", room_id="6657") as storage:
        collector = AsyncCollector("6657", storage)
        try:
            await collector.connect()
        except KeyboardInterrupt:
            await collector.stop()

asyncio.run(main())
```

## Run files

Each run produces one SQLite file (`.db`) containing:

- `danmaku` - one row per message. Known analysis-worthy fields are real
  columns (user, badge, gift, noble, client type, color, ...); `raw_data`
  keeps only the payload fields NOT extracted into columns (deduplicated),
  so nothing is lost and nothing is stored twice.
- `meta` - run metadata: `room`, `started_at`, `ended_at`, `messages`.

A run file without `ended_at` is an interrupted run (process killed) - check
`meta` to spot downtime. `dycap` refuses to overwrite an existing file: every
run gets its own file, and files are immutable history.

## Features

- **Async WebSocket collection** - High-performance async collection
- **Per-run SQLite storage** - One file per run, no server, no DSN
- **Buffered commits** - Batch size 100 / 2s interval by default
- **Type filtering** - Filter message types to collect
- **Automatic reconnection** - Robust connection handling

## CLI Options

| Option | Description |
|--------|-------------|
| `-r, --room` | Room ID (required) |
| `--storage` | Storage backend: `sqlite` (default) / `csv` / `console` |
| `-o, --output` | Output path: SQLite `.db` file or CSV file. Default: `dycap-data/<room>_<timestamp>.db` |
| `-v, --verbose` | Enable verbose logging |
| `--with TYPES` | Include only specified message types (comma-separated). Available: `chatmsg（弹幕）`, `dgb（礼物）`, `uenter（进场）`, `anbc（开通贵族）`, `rnewbc（续费贵族）`, `blab（粉丝牌升级）`, `upgrade（等级升级）` |
| `--without TYPES` | Exclude specified message types (comma-separated), same candidate set as `--with` |

## License

MIT
