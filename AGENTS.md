# AGENTS.md — dykit Repository Guide

> For AI coding agents operating in this repository.
> See also: `.ai/HOW_TO.md` for human-AI collaboration norms (private, not version-controlled).

---

## Project Overview

**dykit** is a Python library and CLI tool for collecting and analyzing Douyu live stream danmu (弹幕/chat) messages. PostgreSQL is the primary storage backend; async WebSocket-based collection.

- **Version**: 4.0.0 (post-MVP) | **Python**: ≥3.12 (runtime), 3.12 in `.venv`
- **Entry point**: `dykit` CLI → `dykit/__main__.py`
- **No tests exist yet** — but test infrastructure is ready (`pytest`, `pytest-asyncio`). Write tests if explicitly requested.

---

## Build / Dev Toolchain

All tools are managed via `uv`. **Never touch global pip.**

```bash
# Setup environment
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"

# OR use uv sync (used in CI, reads uv.lock)
uv sync --extra dev

# Code quality
uv run ruff format .          # Format code
uv run ruff check .           # Lint (includes import sorting via isort rules)
uv run ruff check --fix .     # Lint + auto-fix
uv run basedpyright           # Type checking (strict mode; installed as 'pyright' in dev deps but invoked as 'basedpyright')

# Testing
uv run pytest                                                # Run all tests
uv run pytest tests/test_cli.py                             # Run single test file
uv run pytest tests/test_cli.py::test_function_name         # Run single test by name
uv run pytest -v                                             # Verbose output
uv run pytest -k "pattern"                                   # Run tests matching pattern

# CLI verification
uv pip install -e . && dykit --help  # Install and verify CLI
```

---

## Project Structure

```
dykit/
├── __main__.py          # CLI compatibility entry point (exports cli + main)
├── cli/
│   ├── app.py           # Root Click group and command registration
│   ├── common.py        # Shared CLI middle layer (dsn/validation/room resolve/conversions)
│   ├── formatters.py    # Shared terminal output renderers
│   ├── services/
│   │   └── dbio.py      # SQL/CSV data access helpers for CLI commands
│   └── commands/
│       ├── collect_cmd.py   # collect command
│       ├── analysis_cmd.py  # rank/prune/cluster/search commands
│       ├── io_cmd.py        # import/export commands
│       ├── initdb_cmd.py    # init-db command
│       └── service_cmd.py   # service subgroup commands
├── __init__.py          # Public API surface / __all__
├── types.py             # DanmuMessage dataclass, MessageType enum
├── constants.py         # Shared constants: MIN/MAX_PACKET_SIZE, PROTOCOL_MESSAGE_TYPES, USER_FILTERABLE_TYPES
├── protocol.py          # Binary encode/decode, KV serialization, room ID resolution (uses httpx + bs4)
├── buffer.py            # UTF-8 safe buffering for WebSocket frames
├── log.py               # Loguru logger configuration
├── collectors/
│   ├── base.py          # BaseCollector ABC
│   └── async_.py        # AsyncCollector (primary); Douyu mrkl heartbeat + idle-timeout reconnect
├── storage/
│   ├── base.py          # StorageHandler ABC (async context manager)
│   ├── postgres.py      # PostgreSQLStorage — use factory: await PostgreSQLStorage.create(...)
│   ├── csv.py           # CSVStorage
│   └── console.py       # ConsoleStorage (stdout logging)
├── service/
│   ├── __init__.py      # Exports ServiceManager
│   ├── manager.py       # ServiceManager for systemd --user operations (create/start/stop/remove/logs/status/where/edit)
│   └── templates.py     # Systemd unit file templates
└── tools/
    ├── rank.py          # User/content frequency ranking
    ├── prune.py         # Duplicate removal
    ├── cluster.py       # Text similarity clustering
    └── search.py        # Flexible message search (ILIKE, date range, user filters)

scripts/                 # Maintenance scripts (zsh/python); not part of the library
tests/                   # Test suite (pytest + pytest-asyncio)
```

---

## Code Style Guidelines

### General

- **Line length**: 100 characters (`ruff` enforced, `E501` ignored in lint)
- **Target Python**: 3.12 (`pyproject.toml` `target-version`)
- **Code comments**: Always in **English**. Full sentences on their own line (capitalized, not end-of-line). Incomplete inline phrases go on end-of-line (lowercase).
- **Magic literals**: Avoid. Use `Enum` or named constants instead.
- **No backward compatibility**: Do not add compatibility shims or deprecated aliases.

### Imports

Always include `from __future__ import annotations` as the **first non-docstring line** in every module.

Import order (ruff `I` rules enforce this automatically):
1. `from __future__ import annotations`
2. Standard library imports
3. Third-party imports
4. Local/relative imports

```python
from __future__ import annotations

import asyncio
import sys
from typing import Any

import click
import psycopg

from dykit.log import logger
from dykit.storage import PostgreSQLStorage
```

### Type Annotations

- Use **built-in generics** (PEP 585): `list[str]`, `dict[str, int]`, `tuple[int, ...]`
- Use **union syntax** (PEP 604): `str | None`, NOT `Optional[X]` or `Union[X, Y]`
- Exception: `Optional` from `typing` is acceptable for dataclass field defaults with `None` (see `types.py`)
- `basedpyright` in `strict` mode is enforced — no untyped code
- Do not suppress type errors with `cast`, `# type: ignore`, or `Any` as a shortcut
- psycopg3 stubs are incomplete; `reportUnknownMemberType/VariableType/ArgumentType` are downgraded to warnings in `pyproject.toml`

```python
# Correct
def process(msg: DanmuMessage, room: str | None = None) -> dict[str, str | int | None]: ...

# Wrong
def process(msg: DanmuMessage, room: Optional[str] = None) -> Dict[str, Any]: ...
```

### Naming Conventions

| Construct | Convention | Example |
|---|---|---|
| Modules | `snake_case` | `async_.py`, `rank.py` |
| Classes | `PascalCase` | `PostgreSQLStorage`, `AsyncCollector` |
| Functions / methods | `snake_case` | `encode_message`, `to_dict` |
| Variables | `snake_case` | `room_id`, `msg_type` |
| Constants / Enum values | `UPPER_SNAKE_CASE` | `CLIENT_MSG_TYPE`, `CHATMSG` |
| Private members | `_single_leading_underscore` | `_conn`, `_buffer` |
| CLI commands | `kebab-case` (Click) | `init-db`, `rank-cmd` |

### Docstrings

Use **Google Style** docstrings for all public classes and functions. Skip module docstrings that add no information. Do **not** write trivially redundant docstrings like `"""Tests for foo."""`.

```python
def rank(dsn: str, room: str, top: int, mode: str = "user") -> list[dict[str, Any]]:
    """Rank users or content by frequency in a room.

    Args:
        dsn: PostgreSQL connection string.
        room: Room ID to query.
        top: Number of top results to return.
        mode: Either "user" or "content".

    Returns:
        List of dicts with ranking data.

    Raises:
        psycopg.Error: On database query failure.
    """
```

### Error Handling

- Catch specific exceptions — never bare `except:` or `except Exception` without re-raising or logging
- CLI commands catch `psycopg.Error` explicitly and call `sys.exit(1)`
- Use `logger.error(...)` from `dykit.log`; pass `exc_info=True` for debug context
- Never swallow exceptions silently with empty `except` blocks

```python
try:
    results = rank.rank(dsn, room, top, msg_type, days)
except psycopg.Error as e:
    click.echo(f"Error: Database query failed: {e}", err=True)
    sys.exit(1)
```

### Dataclasses, Enums, and Async Patterns

- Prefer **frozen dataclasses** (`@dataclass(frozen=True)`) for value objects
- Use `Enum` for protocol message types — never raw string literals in logic
- `DanmuMessage` is the canonical data transfer object; use it across all layers
- Use `asyncio.run(...)` at the top-level CLI entry point
- `PostgreSQLStorage` requires the async factory: `storage = await PostgreSQLStorage.create(...)`
- `StorageHandler` subclasses support `async with` for automatic resource cleanup
- Storage handlers use async psycopg3 (`AsyncConnection`) — do not use blocking psycopg calls
- `psycopg` uses `dbname` (not `database`) as the kwarg for `AsyncConnection.connect()`

### Collector Keepalive Contract (Critical)

- For Douyu collection, **do not enable** websockets built-in ping keepalive.
  - Keep `ping_interval=None` and `ping_timeout=None` in `dykit/collectors/async_.py`.
- Liveness strategy is:
  1. protocol heartbeat: send `mrkl` every `WS_DOUYU_HEARTBEAT_SECONDS`
  2. idle detection: reconnect when no message within `WS_READ_IDLE_TIMEOUT_SECONDS`
- Rationale: websockets ping/pong can trigger periodic false disconnects on this path (proxy/CDN behavior); Douyu protocol heartbeat is the stable approach.
- Regression guard tests:
  - `tests/test_collector_keepalive_contract.py`
  - These tests must keep passing in refactors.

### Subprocess Patterns

When executing external commands (like `systemctl` or `journalctl`):

- **Never use `shell=True`**: Always pass arguments as a list.
- **Capture output**: Use `capture_output=True` and `text=True`.
- **Manual error handling**: Set `check=False` and inspect `returncode` / `stderr` for context-rich errors.

```python
def _systemctl(self, args: list[str]) -> subprocess.CompletedProcess[str]:
    # Security: list form only, NEVER shell=True
    return subprocess.run(
        ["systemctl", "--user"] + args,
        capture_output=True,
        text=True,
        check=False,
    )
```

---

## Database Conventions

- Table: `danmaku` with 14 data columns + `id SERIAL PRIMARY KEY` + `raw_data JSONB`
- Indexes: `idx_danmaku_room_time`, `idx_danmaku_user_id`, `idx_danmaku_msg_type`
- Always use parameterized queries: `cur.execute(query, [param1, param2])`
- Use `psycopg` (psycopg3, `AsyncConnection`), not `psycopg2`
- DSN passed via `--dsn` CLI flag or `DYTOOLS_DSN` env var
- Use `Jsonb(...)` from `psycopg.types.json` when inserting JSONB values

---

## Git / Commit Conventions

Follow **Conventional Commits**:

```
feat: add search subcommand with flexible filtering
fix: handle None username in rank output
refactor: extract buffer logic into buffer.py
chore: update ruff to 0.3.0
```

- Always provide a commit message suggestion after completing a task
- Ask permission before running any mutating git commands (add, commit, push)
- Exception: trivial typo fixes may be committed without asking

---

## Key Rules from `.ai/HOW_TO.md`

- **Sync AGENTS.md** whenever code structure changes significantly
- **`.ai/` folder is private** — never include its contents in version control
- No magic literals — use enums; all code comments in English
- Avoid reinventing the wheel — check stdlib and existing dependencies first
- Maintain docstrings and README in sync with implementation changes
- Tasks should be small and targeted (one commit's worth of change)
- Always provide a summary report after completing a task and ask for next steps
- Before answering questions about project internals, **search the code first** — never guess
- If from requirements to implementation there are multiple valid approaches, present them and let the user choose
