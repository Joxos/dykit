# AGENTS.md — dykit Agent Guide

Python 3.12 `uv` project. **One package**: `src/dykit/`. Do not split it back
into multiple distributions — the boundaries that matter are enforced by
`tests/arch/test_layering.py`, not by package metadata.

## Layout

```
src/dykit/
  protocol/   pure wire codec - no IO, no network          (leaf)
  source/     the only HTTP to douyu.com                    (leaf)
  schema.py   the run-file contract: columns, DDL, timestamps, default dir (leaf)
  collect/    live capture: collector, payload, storage/, render, CLI
  stats/      read-only analysis: db, filters, rank/cluster/search, CLI
scripts/      ops tools + probes/ (see scripts/README.md)
tests/        one directory per layer, plus arch/ and integration/
```

Allowed dependencies (anything else is a layering violation):

| Layer | May import |
|---|---|
| `protocol`, `source`, `schema` | nothing else in `dykit` |
| `collect` | `protocol`, `source`, `schema` |
| `stats` | `source`, `schema` |

Commands: `dykit-capture` (collect) and `dykit-stats` (stats). There is no
dispatcher command and no forwarding shims - if you catch yourself adding
one, delete it instead.

---

## Canonical commands (run at repo root)

### Setup
```bash
uv sync --dev
```

### Format
```bash
uv run ruff format .
uv run ruff format --check .   # CI gate
```

### Lint
```bash
uv run ruff check .
```

### Type check
```bash
uv run basedpyright             # src + scripts + tests (driven by config `include`)
uv run basedpyright --verifytypes dykit --ignoreexternal   # PEP 561 completeness
```

### Dead code
```bash
uv run vulture src/dykit scripts --min-confidence 80
```

### Tests
```bash
uv run pytest
uv run pytest -m smoke -q          # end-to-end over real run files
uv run pytest -m "not smoke" -q
uv run pytest --lf -q              # last failed
```

### Coverage
```bash
uv run pytest --cov --cov-report=term-missing
```
Floor: `fail_under = 72` in `pyproject.toml` (measured 76%). Raise it, never lower it.

### CI-equivalent local gate
```bash
uv run ruff format --check .
uv run ruff check .
uv run basedpyright
uv run pytest --cov --cov-report=term-missing
```
CI reference: `.github/workflows/ci.yml` (adds the build job on top)

### Pre-commit
```bash
uv run pre-commit install     # first time
uv run pre-commit run -a      # run everything
```

### Build
```bash
uv build --out-dir dist
uv run twine check dist/*.whl dist/*.tar.gz
```
The wheel ships `py.typed`; keep it in `[tool.setuptools.package-data]` if you
add package data.

---

## Single-test and focused-test recipes
```bash
uv run pytest tests/collect/test_cli.py::TestCollectCommand::test_collect_version_option -q
uv run pytest tests/stats/test_cli.py -q
uv run pytest tests/protocol -q        # one layer
uv run pytest -k "collect_version_option" -q
```

### Test layout
| Path | Covers |
|---|---|
| `tests/protocol/` | codec + type registry |
| `tests/source/` | room resolution, endpoint discovery (stubbed HTTP) |
| `tests/collect/` | collector, payload mapping, storage, render, CLI |
| `tests/stats/` | data access, filters, CLI |
| `tests/scripts/` | the ops scripts |
| `tests/integration/` | cross-layer: capture writes, stats reads; schema contract |
| `tests/arch/` | layering invariants - keep these green, they protect the merge |

Shared fixtures live in `tests/conftest.py`; the CLI harness is
`tests/cli_test_runner.py`. Add new tests to the directory they belong to.

---

## Code style rules

### Formatting/linting
- Formatter: `ruff format` (run it; CI fails on `--check` drift)
- Ruff line length: 100
- Enabled rules: `E`, `F`, `W`, `I`, `UP`, `B`, `C4`, `SIM`, `RET`, `PERF`, `PIE`,
  `PT`, `PTH`, `RUF`, `FURB`, `ISC`
- Ignored on purpose: `E501` (formatter's job), `RUF001/002/003` (CJK text is
  intentional), `UP042` (`str`+`Enum` kept for API compatibility)

### Tooling config location
All `[tool.*]` settings live in the root `pyproject.toml` only.

### Adding a column to the run file
1. Append it to `DANMAKU_SCHEMA` in `src/dykit/schema.py`.
2. Add the value source to `_ROW_FIELDS` in `collect/storage/sqlite.py`.
3. Add the raw payload key to `EXTRACTED_RAW_KEYS` in `schema.py`.

`tests/integration/test_schema_contract.py` fails if any step is missed.

### Typing
- `basedpyright` strict mode
- Explicit types for public functions and key locals
- Prefer `X | None` over `Optional[X]`; avoid `Any` unless unavoidable

### Naming/structure
- snake_case for functions/vars (`room_id`, `msg_type`); PascalCase for classes
- Keep CLIs thin: validate -> call domain logic -> render output
- Presentation data (labels, icons) belongs to `collect`, not `protocol`

### Error handling
- Validate prerequisites early (output path for capture, --data for stats)
- Runtime failures: clear message + `raise SystemExit(1)`; usage errors exit 2
- Preserve cause: `raise SystemExit(1) from e`
- Never silently swallow exceptions - log at debug and fall through instead

### Async/DB patterns
- async/await + async context managers for IO; cancel background tasks cleanly
- SQLite writes are small and synchronous; buffer commits (batch size/interval)
  and flush on close before writing `meta.ended_at`
- Run files are immutable: refuse to overwrite an existing .db

---

## Agent working agreement
When changing code:
1. Edit only the layer(s) that need it
2. Run lint + typecheck + targeted tests
3. Add/update tests with behavior changes
4. Re-run full `uv run pytest` for cross-layer changes
5. Keep README/CLI help aligned with behavior
Do not:
- add runtime logic outside `src/dykit/`
- commit `__pycache__/` or `*.pyc`
- bypass strict typing to force passing checks
- ship behavior changes without tests
- create a new PyPI distribution without an explicit decision

---

## Cursor/Copilot rules
Checked and not present:
- `.cursor/rules/`
- `.cursorrules`
- `.github/copilot-instructions.md`
If added later, treat them as authoritative and merge into this guide.
