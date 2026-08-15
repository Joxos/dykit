# AGENTS.md — dykit Agent Guide

Python 3.12 `uv` workspace. Root `dykit` is a meta package; runtime code belongs in workspace members.

## Scope
- `dyproto/`: protocol + encode/decode primitives
- `dycap/`: collection CLI + storage
- `dystat/`: analytics CLI + queries
- `dycommon/`: shared helpers
- `tests/`: repo-level tests
Rule: do not add runtime logic in root `dykit`.

---

## Canonical commands (run at repo root)

### Setup
```bash
uv sync --dev
```

### Lint
```bash
uv run ruff check .
```

### Type check
```bash
uv run basedpyright dycap/src dyproto/src dystat/src
```
Optional:
```bash
uv run basedpyright dycommon/src
```

### Tests
```bash
uv run pytest
```

### CI-equivalent local gate
```bash
uv run ruff check .
uv run basedpyright dycap/src dyproto/src dystat/src
uv run pytest
```
CI reference: `.github/workflows/ci.yml`

---

## Single-test and focused-test recipes
```bash
# Single test node
uv run pytest tests/test_cli.py::TestCollectCommand::test_collect_version_option -q

# Single file
uv run pytest tests/test_cli.py -q

# Name filter
uv run pytest -k "collect_version_option" -q

# Last failed / fail fast
uv run pytest --lf -q
uv run pytest --ff -q
```

### Smoke tests
`smoke` tests require a live PostgreSQL DSN via `DYKIT_DSN`.
```bash
export DYKIT_DSN="postgresql://postgres:password@localhost:5432/postgres"
uv run pytest -m smoke -q
```
Run non-smoke only:
```bash
uv run pytest -m "not smoke" -q
```

---

## Build/publish validation
Workflow reference: `.github/workflows/publish.yml`
```bash
python -m build --outdir dist/dyproto ./dyproto
python -m build --outdir dist/dycommon ./dycommon
python -m build --outdir dist/dycap ./dycap
python -m build --outdir dist/dystat ./dystat
python -m build --outdir dist/dykit .

python -m twine check dist/dyproto/*
python -m twine check dist/dycommon/*
python -m twine check dist/dycap/*
python -m twine check dist/dystat/*
python -m twine check dist/dykit/*
```

---

## Code style rules
From `pyproject.toml` and current source patterns.

### Formatting/linting
- Ruff line length: 100
- Enabled rules: `E`, `F`, `W`, `I`
- `E501` ignored, but keep lines readable

### Typing
- `basedpyright` strict mode
- Explicit types for public functions and key locals
- Prefer `X | None` over `Optional[X]`
- Avoid `Any` unless unavoidable

### Imports
- Use `from __future__ import annotations`
- Import order: stdlib, third-party, local
- Keep imports Ruff-clean and deterministic

### Naming/structure
- snake_case for functions/vars (`room_id`, `msg_type`)
- PascalCase for classes/dataclasses
- Keep CLI thin: validate -> call domain logic -> render output

### Error handling
- Validate prerequisites early (e.g., DSN)
- CLI failures: clear message + `raise SystemExit(1)`
- Preserve cause: `raise SystemExit(1) from e`
- Never silently swallow exceptions

### Async/DB patterns
- Use async/await + async context managers for IO
- Cancel background tasks cleanly on shutdown
- On DB batch failures: rollback, keep buffered data for retry, re-raise

---

## Environment variables
- Primary: `DYKIT_DSN`
- Aliases: `DYCAP_DSN`, `DYSTAT_DSN`
- Prefer `DYKIT_DSN` in new docs/scripts

---

## Agent working agreement
When changing code:
1. Edit only relevant package(s)
2. Run lint + typecheck + targeted tests
3. Add/update tests with behavior changes
4. Re-run full `uv run pytest` for cross-package changes
5. Keep README/CLI help aligned with behavior
Do not:
- commit `__pycache__/` or `*.pyc`
- bypass strict typing to force passing checks
- ship behavior changes without tests

---

## Cursor/Copilot rules
Checked and not present:
- `.cursor/rules/`
- `.cursorrules`
- `.github/copilot-instructions.md`
If added later, treat them as authoritative and merge into this guide.
