# dystat

Douyu Statistics Tools - analyze danmu run files with rank, cluster, and search.

## Installation

```bash
pip install dystat
```

## Quick Start

```bash
# Rank users by message count (default data: ./dycap-data)
dystat rank -r 6657 --top 10

# Rank content (repeated messages)
dystat rank -r 6657 --by content --top 10

# Cluster similar messages
dystat cluster -r 6657 --threshold 0.5

# Search messages
dystat search -r 6657 --content "hello"
dystat search -r 6657 --user "username"

# Analyze a specific run file, or a directory of run files
dystat rank -r 6657 --data backup/20260816_6657.db
dystat rank -r 6657 --data backup/        # union across all run files
```

## Data source

`--data` accepts a single SQLite run file (produced by `dycap`) or a
directory of run files. Directory mode unions all `*.db` files in the
directory, so accumulated runs are analyzed together. Default: `./dycap-data`.

## Commands

### rank

Rank users or content by frequency.

```bash
dystat rank -r 6657 --top 10                    # Top users (default)
dystat rank -r 6657 --by content --top 10      # Repeated content
dystat rank -r 6657 --type dgb --top 5         # Gift messages
dystat rank -r 6657 --days 7                   # Last 7 days
```

Options:
- `-r, --room ROOM` - Room ID (required)
- `--data PATH` - Run file or directory of run files (default: `./dycap-data`)
- `--top N` - Number of results (default: 10)
- `--by user|content` - Rank mode (default: user)
- `--type TYPE` - Message type (default: chatmsg)
- `--days N` - Limit to recent N days
- `--from TIME` - Start time (`YYYY-MM-DD` or `YYYY-MM-DD HH:MM:SS`)
- `--to TIME` - End time (`YYYY-MM-DD` or `YYYY-MM-DD HH:MM:SS`, inclusive)
- `--last N` - Use latest N messages as source window
- `--first N` - Use earliest N messages as source window

### cluster

Cluster similar messages using fuzzy text matching.

```bash
dystat cluster -r 6657 --threshold 0.5         # Default threshold
dystat cluster -r 6657 --limit 100             # More source messages
```

Options:
- `-r, --room ROOM` - Room ID (required)
- `--data PATH` - Run file or directory of run files (default: `./dycap-data`)
- `--threshold FLOAT` - Similarity threshold 0-1 (default: 0.5)
- `--limit N` - Source message limit (default: 50)
- `--type TYPE` - Message type (default: chatmsg)
- `--from TIME` / `--to TIME` / `--last N` / `--first N` / `--days N`

### search

Search messages with filters.

```bash
dystat search -r 6657 --content "hello"        # LIKE search
dystat search -r 6657 --user "username"        # By username
dystat search -r 6657 --type dgb               # By message type
```

Options:
- `-r, --room ROOM` - Room ID (required)
- `--data PATH` - Run file or directory of run files (default: `./dycap-data`)
- `--content TEXT` - Content filter (LIKE)
- `--user USERNAME` - Username exact match
- `--user-id UID` - User ID exact match
- `--type TYPE` - Message type
- `--from TIME` / `--to TIME` / `--last N` / `--first N`

## License

MIT
