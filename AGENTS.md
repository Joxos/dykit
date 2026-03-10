# AGENTS.md — dykit Meta Package Guide

`dykit` is a pure meta package that aggregates several specialized layers. It contains no runtime source code or CLI entrypoint itself, serving instead as a distribution and development anchor for the workspace.

## Repo structure & scope
This repository is a monorepo managed by `uv`. All runtime logic lives in the component packages:

- `dyproto/` — Protocol definitions and core models
- `dycap/` — Data collection engine (CLI: `dycap`)
- `dystat/` — Analysis and reporting layer (CLI: `dystat`)
- `dycommon/` — Shared internal utilities

Implement changes directly in the relevant package directory. Do not add logic to the root `dykit` package.

### Components in detail
The architecture is designed to decouple data collection from analysis.

1. **Protocol (dyproto)**: Defines the data structures and communication standards used throughout the system.
2. **Collection (dycap)**: A CLI tool for gathering data from external sources and persisting it to a database.
3. **Analysis (dystat)**: A CLI tool for querying collected data and generating insights or reports.
4. **Shared (dycommon)**: Internal modules providing shared helpers like logging and configuration parsing.

### Development scope guidelines
When adding new features, consider the following scope:
- If it's a new data model, add it to `dyproto`.
- If it's a new collection strategy, add it to `dycap`.
- If it's a new statistical method, add it to `dystat`.
- If it's a common helper, add it to `dycommon`.

## Environment
Development requires Python 3.12+ and `uv`. The project uses a `uv` workspace to manage internal dependencies efficiently.

### Workspace management
Use `uv` for all dependency management tasks within the repository.

- `uv sync`: Synchronizes the virtual environment with the workspace configuration.
- `uv add`: Adds a new dependency to a specific package.
- `uv lock`: Updates the lockfile without synchronizing the environment.

## Commands
Common development tasks are run from the repository root:

- **Setup**: `uv sync --dev`
- **Lint**: `uv run ruff check .`
- **Typecheck**: `uv run basedpyright dycap/src dyproto/src dystat/src`
- **Tests**: `uv run pytest`

## Single-test recipes
Use these patterns to run specific tests efficiently during development:

- **Specific test**: `uv run pytest tests/test_cli.py::TestCollectCommand::test_collect_version_option -q`
- **Specific file**: `uv run pytest tests/test_cli.py -q`
- **By name filter**: `uv run pytest -k "collect_version_option" -q`
- **Smoke tests**: `DYKIT_DSN="postgresql://..." uv run pytest -m smoke tests/test_smoke_6657.py::test_smoke_6657_commands -q`
- **Exclude smoke tests**: `uv run pytest -m "not smoke" -q`

### Advanced pytest usage
You can also use additional pytest flags to refine your testing:
- `--lf`: Run only the tests that failed in the last run.
- `--ff`: Run all tests but fail fast on the first failure.
- `-v`: Verbose output for detailed test execution information.

## Smoke-test caveats
Tests marked with `@pytest.mark.smoke` require a live database. You must provide a valid connection string via `DYKIT_DSN`. If this environment variable is not set, smoke tests will be skipped automatically to avoid environment-specific failures.

### Database setup for smoke tests
To run smoke tests, ensure you have a local PostgreSQL instance running.

```bash
docker run --name dykit-db -e POSTGRES_PASSWORD=password -p 5432:5432 -d postgres
export DYKIT_DSN="postgresql://postgres:password@localhost:5432/postgres"
uv run pytest -m smoke
```

## Build & release checks
Before publishing, verify the package integrity using the following:

- **Build**: `python -m build`
- **Metadata check**: `python -m twine check dist/*`
- **Extra typecheck**: `uv run basedpyright dycommon/src`

## Code style & conventions
Maintain consistency across the workspace by following these standards:

- **Python**: Use 3.12+ features like `X | None` for optional types and `match/case` for complex branching.
- **Ruff**: Target `line-length=100`. The configuration selects `E`, `F`, `W`, and `I` rules while ignoring `E501`.
- **BasedPyright**: Strict mode is enabled. Address all type errors before submitting changes.
- **Imports**: Always include `from __future__ import annotations` at the top of files. Group imports into standard library, third-party, and local workspace modules.
- **Typing**: Provide type hints for all public functions and dataclasses. Avoid using `Any` where possible.
- **Error handling**: Validate CLI inputs early. Exit with code 1 on expected errors and ensure the original exception cause is preserved where appropriate.

### Detailed coding guidelines
When contributing code, prioritize readability and explicit types.

- Use descriptive variable names. Avoid abbreviations like `ctx` or `mgr` in public APIs.
- Prefer dataclasses for data-only structures.
- Document complex logic with inline comments, but keep function-level docstrings concise.
- Use async/await for I/O operations where supported by the underlying libraries.
- Avoid global state; inject dependencies where possible.

## Cursor/Copilot rules
No .cursor/rules/, .cursorrules, or .github/copilot-instructions.md found in this repository. Use standard Python development extensions and ensure your editor respects the `pyproject.toml` settings for linting and type checking.

## DSN + database notes
Database access is configured via environment variables:

- `DYKIT_DSN`: The primary connection string used across the workspace.
- `DYCAP_DSN` / `DYSTAT_DSN`: Legacy aliases that may be supported by individual components, but `DYKIT_DSN` is preferred for consistency across the monorepo.

### Connection handling
The `dycap` package uses psycopg's async connection directly for database operations (see dycap/src/dycap/storage/postgres.py). There is no shared connection pool in `dycommon`. For batch writes prefer buffering and controlled flushes rather than assuming a shared pool implementation.

## Change discipline
Follow these rules to ensure repository health and maintainability:

- Always keep code, tests, and documentation in sync in the same change.
- Do not ship behavior changes without corresponding test updates.
- Do not ship CLI/API changes without updating relevant README or usage documentation.
- Verify that your changes do not introduce new linting or type-checking warnings.
- Keep commits atomic and focused on a single logical change.

## CI guardrail
The CI pipeline prevents local cache artifacts from being committed. Ensure your `.gitignore` is working correctly and do not manually add `__pycache__/` or `*.pyc` files to the repository. If you encounter errors related to tracked cache files, use `git rm --cached` to remove them.

### Pre-commit checklist
Before pushing your branch, run the following:
1. `uv sync`
2. `uv run ruff check .`
3. `uv run basedpyright dycap/src dyproto/src dystat/src`
4. `uv run pytest -m "not smoke"`

### CI configuration
The CI workflow is defined in `.github/workflows/ci.yml`. It runs on every push and pull request to the `main` branch. The quality job ensures that the codebase passes linting, type checking, and tests.

### Troubleshooting CI failures
If the CI pipeline fails, check the logs for:
- Ruff errors: Usually related to formatting or imports.
- Type errors: BasedPyright strictness often catches subtle bugs.
- Test failures: Ensure you haven't introduced regressions.
- Tracked artifacts: Verify no `__pycache__` directories were accidentally committed.
