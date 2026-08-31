## dykit (meta package)

`dykit` is a pure aggregator package.

It does not provide runtime code or a CLI entrypoint. Installing `dykit` installs:

- `dyproto` (protocol layer)
- `dysource` (room resolution / danmu server discovery)
- `dycap` (collection layer)
- `dystat` (analysis layer)

### Install

```bash
uv add dykit
```

### Use installed tools

```bash
# Collect one run into a per-run SQLite file (default: ./dycap-data/<room>_<timestamp>.db)
dycap -r 6657

# Custom output location/filename (refuses to overwrite an existing file)
dycap -r 6657 -o backup/20260816_6657.db

# Analyze: single run file or a directory of run files (directory = union across runs)
dystat rank -r 6657 --top 10
dystat search -r 6657 --content "hello" --data backup/
```

### Data model

One SQLite file per collection run (see `docs/schema.md`):

- `danmaku` table: one row per message.
- `meta` table: room / started_at / ended_at / messages. A file without
  `ended_at` is an interrupted run (process killed) - downtime is visible
  at a glance. Run files are immutable: `dycap` refuses to overwrite them.

### PostgreSQL batch write tuning

PostgreSQL support was removed in 0.2.0 in favor of per-run SQLite files.
SQLite needs no server, no DSN, and no migrations; commits are buffered
(batch size 100 / 2s interval, see `dycap.storage.sqlite`).
