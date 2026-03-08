## dykit (meta package)

`dykit` is a pure aggregator package.

It does not provide runtime code or a CLI entrypoint. Installing `dykit` installs:

- `dyproto` (protocol layer)
- `dycap` (collection layer)
- `dystat` (analysis layer)

### Install

```bash
uv add dykit
```

### Use installed tools

```bash
dycap --help
dystat --help
```

### Environment variable

Use `DYKIT_DSN` for database DSN.

```bash
export DYKIT_DSN="postgresql://user:pass@localhost:5432/douyu"
```
