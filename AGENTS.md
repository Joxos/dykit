# AGENTS.md — dytools Repository Guide

> For AI coding agents operating in this repository.
> See also: `HOW_TO.md` for human-AI collaboration norms.

---

## Project Overview

**dytools** is a Python library and CLI tool for collecting and analyzing Douyu live stream danmu (弹幕/chat) messages. It uses PostgreSQL as the primary storage backend with async WebSocket-based collection.

- **Version**: 4.0.0 (post-MVP)
- **Python**: ≥3.9 (runtime), 3.12 in `.venv`
- **Entry point**: `dytools` CLI → `dytools/__main__.py`

---

## Build / Dev Toolchain

All tools are managed via `uv`. **Never touch global pip.**

```bash
# Environment setup
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"

# Format code
uv run ruff format .

# Lint (includes import sorting via isort rules)
uv run ruff check .
uv run ruff check --fix .

# Type checking
uv run basedpyright

# Run all tests
uv run pytest

# Run a single test file
uv run pytest tests/test_protocol.py

# Run a single test by name
uv run pytest tests/test_protocol.py::test_encode_message

# Install the CLI locally
uv pip install -e .
dytools --help
```

> **Note**: There are currently no project-owned tests (pre-MVP convention from HOW_TO.md). Do not write tests unless explicitly requested.

---

## Project Structure

```
dytools/
├── __main__.py          # Click CLI entry point (7 subcommands)
├── __init__.py          # Public API surface / __all__
├── types.py             # DanmuMessage dataclass, MessageType enum
├── protocol.py          # Binary encode/decode, KV serialization
├── buffer.py            # UTF-8 safe buffering for WebSocket frames
├── log.py               # Loguru logger configuration
├── collectors/
│   ├── async_.py        # AsyncCollector (primary)
│   └── sync.py          # SyncCollector
├── storage/
│   ├── base.py          # StorageHandler ABC
│   ├── postgres.py      # PostgreSQLStorage (primary backend)
│   └── csv.py           # CSVStorage + ConsoleStorage
└── tools/
    ├── rank.py          # User/content frequency ranking
    ├── prune.py         # Duplicate removal
    ├── cluster.py       # Text similarity clustering
    └── search.py        # Flexible message search
```

---

## Code Style Guidelines

### General

- **Line length**: 100 characters (`ruff` enforced, E501 ignored)
- **Target Python**: 3.9 (`pyproject.toml` `target-version`)
- **Code comments**: Always in **English**. Full sentences on their own line (capitalized). Inline/incomplete phrases use end-of-line comments (lowercase).
- **Magic literals**: Avoid. Use `Enum` or named constants instead.
- **No backward compatibility**: Do not add compatibility shims or deprecated aliases.

### Imports

Always include `from __future__ import annotations` as the **first non-docstring line**. This enables PEP 563 postponed evaluation of annotations for Python 3.9 compat.

Import order (ruff `I` rules enforce this automatically):
1. `from __future__ import annotations`
2. Blank line
3. Standard library imports
4. Blank line
5. Third-party imports
6. Blank line
7. Local/relative imports

```python
from __future__ import annotations

import asyncio
import sys
from typing import Any

import click
import psycopg

from dytools.log import logger
from dytools.storage import PostgreSQLStorage
```

### Type Annotations

- Use **built-in generics** (PEP 585): `list[str]`, `dict[str, int]`, `tuple[int, ...]`
- Use **union syntax** (PEP 604): `str | None`, `int | str`, NOT `Optional[X]` or `Union[X, Y]`
- Exception: `Optional` from `typing` is used in `types.py` for optional dataclass fields — acceptable for dataclass defaults, but prefer `X | None` in function signatures
- `basedpyright` in `strict` mode is enforced — no untyped code
- Do not suppress type errors with `cast`, `# type: ignore`, or `Any` as a shortcut

```python
# Correct
def process(msg: DanmuMessage, room: str | None = None) -> dict[str, str | int | None]:
    ...

# Wrong
def process(msg: DanmuMessage, room: Optional[str] = None) -> Dict[str, Any]:
    ...
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

Use **Google Style** docstrings. Write docstrings for all classes and functions. Skip module docstrings that add no information. Do **not** write trivially redundant docstrings like `"""Tests for foo."""`.

```python
def rank(dsn: str, room: str, top: int, mode: str = "user") -> list[dict[str, Any]]:
    """Rank users or content by frequency in a room.

    Args:
        dsn: PostgreSQL connection string.
        room: Room ID to query.
        top: Number of top results to return.
        mode: Either "user" or "content".

    Returns:
        List of dicts with ranking data. User mode returns keys
        ``username`` and ``count``; content mode adds ``first_seen``
        and ``last_seen``.

    Raises:
        psycopg.Error: On database query failure.
    """
```

### Error Handling

- Catch specific exceptions — never bare `except:` or `except Exception` without re-raising or logging
- CLI commands catch `psycopg.Error` explicitly and call `sys.exit(1)`
- Use `logger.error(...)` from `dytools.log` for logging errors; pass `exc_info=True` (or `exc_info=verbose`) for debug context
- Never swallow exceptions silently with empty `except` blocks

```python
try:
    results = rank.rank(dsn, room, top, msg_type, days)
except psycopg.Error as e:
    click.echo(f"Error: Database query failed: {e}", err=True)
    sys.exit(1)
```

### Dataclasses and Enums

- Prefer **frozen dataclasses** (`@dataclass(frozen=True)`) for value objects
- Use `Enum` for protocol message types — never raw string literals in logic
- `DanmuMessage` is the canonical data transfer object; use it across all layers

### Async Patterns

- Use `asyncio.run(...)` at the top-level CLI entry point
- Collectors expose `async def connect()` / `async def stop()`
- Storage handlers are synchronous (psycopg3 blocking API); do not mix async storage calls

---

## Database Conventions

- Table: `danmaku` with 14 data columns (see README for schema)
- Always use parameterized queries: `cur.execute(query, [param1, param2])`
- Use `psycopg` (psycopg3), not `psycopg2`
- DSN passed via `--dsn` CLI flag or `DYTOOLS_DSN` env var

---

## Git / Commit Conventions

Follow **Conventional Commits** (see HOW_TO.md):

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

## Key Rules from HOW_TO.md

- Sync AGENTS.md whenever code structure changes significantly
- No magic literals — use enums
- All code comments in English
- Avoid reinventing the wheel — check stdlib and existing dependencies first
- Maintain docstrings and README in sync with implementation changes
- Tasks should be small and targeted (one commit's worth of change)
- Always provide a summary report after completing a task and ask for next steps
