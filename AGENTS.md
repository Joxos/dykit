# AGENTS.md — dykit Meta Package Guide

`dykit` is a **pure meta package**.

It contains no runtime source code and no CLI entrypoint.

## Installed packages

- `dyproto` — protocol layer
- `dycap` — collector layer (CLI: `dycap`)
- `dystat` — analysis layer (CLI: `dystat`)

## Development scope

- Implement protocol changes in `dyproto/`
- Implement collection changes in `dycap/`
- Implement analysis changes in `dystat/`

## DSN convention

Use `DYKIT_DSN` as the primary environment variable for DB access.
