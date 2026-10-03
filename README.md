# dykit

Douyu danmu capture and analysis. One package, two commands.

```bash
uv add dykit
```

## Commands

| Command | What it does |
|---|---|
| `dykit-capture` | Collect a live room into a per-run SQLite file |
| `dykit-stats` | Query collected run files (rank / cluster / search) |

```bash
# Collect one run (default: ./dycap-data/<room>_<timestamp>.db)
dykit-capture -r 6657

# Custom output location/filename (refuses to overwrite an existing file)
dykit-capture -r 6657 -o backup/20260816_6657.db

# Only the message types you care about
dykit-capture -r 6657 --with chatmsg,dgb --without uenter

# Analyze: one run file, or a directory of them (directory = union across runs)
dykit-stats rank -r 6657 --top 10
dykit-stats search -r 6657 --content "hello" --data backup/
```

## Architecture

Three leaf layers that depend on nothing else in the package, and two
applications on top:

```
collect ──┐                    live capture -> run files
          ├── protocol         wire format codec (pure, no IO)
          ├── source           the only HTTP to douyu.com
stats ────┤
          └── schema           the run-file contract (columns, DDL, timestamps)
```

- `dykit.protocol` - encode/decode Douyu packets. Pure functions; testable
  without a room.
- `dykit.source` - room ID resolution and danmu endpoint discovery. The only
  modules that touch the network.
- `dykit.schema` - one definition of the run file. Capture's DDL and stats'
  column projection are both generated from it, so they cannot drift.
- `dykit.collect` - the WebSocket collector, the payload mapping, and the
  storage backends (SQLite / CSV / console).
- `dykit.stats` - read-only analysis over run files.

The layering is enforced, not just documented: `tests/arch/test_layering.py`
parses the source and fails if a leaf imports from an application or the
graph grows a cycle.

## Python API

```python
import asyncio

from dykit import AsyncCollector, SQLiteStorage


async def main() -> None:
    async with SQLiteStorage("run.db", room_id="6657") as storage:
        await AsyncCollector("6657", storage).connect()


asyncio.run(main())
```

## Data model

One SQLite file per collection run (see `docs/schema.md`):

- `danmaku` table: one row per message. Known analysis-worthy fields are real
  columns; `raw_data` keeps only the payload fields *not* extracted into
  columns, so nothing is lost and nothing is stored twice.
- `meta` table: room / started_at / ended_at / messages. A file without
  `ended_at` is an interrupted run (process killed) - downtime is visible at a
  glance. Run files are immutable: `dykit-capture` refuses to overwrite them.

## Ops

`scripts/scan_runs.py` finds interrupted runs and reports disk usage; see
`scripts/README.md` and `docs/deployment.md`.
