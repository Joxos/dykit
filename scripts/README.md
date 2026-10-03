# scripts/

Two kinds of script live here, and they have different lifetimes.

## Ops tools (shipped)

Maintained, unit-tested (`tests/scripts/`), part of the deployment story.

| Script | Purpose |
|---|---|
| `scan_runs.py` | Find interrupted run files (no `meta.ended_at`), report collection `GAP`s between consecutive runs of a room, and print disk usage. Wired to a systemd timer - see `docs/deployment.md`. Exit 1 when interrupted runs exist. |

```bash
uv run python scripts/scan_runs.py [--data DIR] [--min-age-minutes N] [--max-gap-seconds S]
```

A `GAP` line means two runs of the same room are further apart than
`--max-gap-seconds` (default 60s). Normal rotation hands over in milliseconds,
so anything reported is a real interruption in coverage - a deploy, a crash -
worth an audit trail rather than an assumption.

## Probes (exploration only, `probes/`)

Interactive tools for a human at a terminal. They need a live Douyu room, so
they are **not** part of the test suite or CI. They may break when Douyu
changes; that is acceptable — re-derive them if you need to.

| Script | Purpose |
|---|---|
| `probes/live_smoke.py` | Collect from a real room for N seconds; print or write a run file. Exit 0 if any message arrived. |
| `probes/capture_raw_fields.py` | Record which raw payload keys each message type carries (used to design the run-file columns). |

```bash
uv run python scripts/probes/live_smoke.py [--room 6657] [--seconds 45] [--db out.db]
uv run python scripts/probes/capture_raw_fields.py [--room 6657] [--seconds 60]
```

Rule: if a script will still be useful in a year, it belongs at `scripts/` top
level with a test; otherwise it is a probe.
