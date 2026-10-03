"""The run file: format, schema and location - one contract, one module.

Everything about the per-run SQLite file is defined here and nowhere else:

- ``DANMAKU_SCHEMA``      the column registry; the DDL and the reader's
                          projection are both generated from it
- ``SCHEMA_SQL``          the full DDL a run file is created with
- ``EXTRACTED_RAW_KEYS``  raw payload keys that already live in a column, so
                          they are stripped from ``raw_data`` (stored once)
- ``format_timestamp``    the fixed-width text the ``timestamp`` column uses,
                          so TEXT comparisons are chronologically correct
- ``DEFAULT_RUN_DIR``     where run files go when ``-o`` is not given

Both sides derive from this module, so the writer (``dykit.collect``) and the
reader (``dykit.stats``) cannot drift apart.
``tests/integration/test_schema_contract.py`` pins the agreement.

Adding a column: append it to ``DANMAKU_SCHEMA``, add the value source in
``dykit/collect/storage/sqlite.py``, and add the raw payload key to
``EXTRACTED_RAW_KEYS``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

# Where run files are written when no -o is given, and where both CLIs look
# for them when no --data is given.
DEFAULT_RUN_DIR = "dycap-data"

#: Fixed-width storage text. Same length for every row, so lexicographic
#: TEXT comparison in SQLite equals chronological order.
TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S.%f"


@dataclass(frozen=True)
class Column:
    """One table column: name plus its full SQL type/constraint text."""

    name: str
    sql_type: str

    def definition(self) -> str:
        return f"{self.name} {self.sql_type}"


# Ordered as readers see them. `id` is the storage's surrogate key: it is
# created here but never selected by name (see `DANMAKU_VIEW_COLUMNS`).
DANMAKU_SCHEMA: tuple[Column, ...] = (
    Column("id", "INTEGER PRIMARY KEY AUTOINCREMENT"),
    Column("timestamp", "TEXT NOT NULL"),
    Column("room_id", "TEXT NOT NULL"),
    Column("msg_type", "TEXT NOT NULL"),
    Column("user_id", "TEXT"),
    Column("username", "TEXT"),
    Column("user_level", "INTEGER"),
    Column("avatar_url", "TEXT"),
    Column("color", "TEXT"),
    Column("content", "TEXT"),
    Column("badge_level", "INTEGER"),
    Column("badge_name", "TEXT"),
    Column("badge_room_id", "TEXT"),
    Column("gift_id", "TEXT"),
    Column("gift_count", "INTEGER"),
    Column("gift_name", "TEXT"),
    Column("gift_hits", "INTEGER"),
    Column("gift_receiver_uid", "TEXT"),
    Column("gift_receiver_name", "TEXT"),
    Column("noble_level", "INTEGER"),
    Column("client_type", "TEXT"),
    Column("raw_data", "TEXT"),
)

# Storage-owned columns that no reader selects by name.
INTERNAL_COLUMNS = frozenset({column.name for column in DANMAKU_SCHEMA[:1]})

#: The columns a reader projects out of a run file.
DANMAKU_VIEW_COLUMNS: tuple[str, ...] = tuple(
    column.name for column in DANMAKU_SCHEMA if column.name not in INTERNAL_COLUMNS
)

# Raw payload keys whose value is already stored in a dedicated column. They
# are stripped from raw_data at write time; column + raw_data together stay
# the complete original payload.
EXTRACTED_RAW_KEYS: frozenset[str] = frozenset(
    {
        "type",  # -> msg_type
        "rid",  # -> room_id
        "uid",  # -> user_id
        "nn",  # -> username
        "txt",  # -> content
        "level",  # -> user_level
        "col",  # -> color
        "color",  # -> color
        "ic",  # -> avatar_url
        "av",  # -> avatar_url
        "bl",  # -> badge_level
        "bnn",  # -> badge_name
        "brid",  # -> badge_room_id
        "nl",  # -> noble_level
        "gfid",  # -> gift_id
        "gfcnt",  # -> gift_count
        "gfn",  # -> gift_name
        "gftype",  # -> gift_name
        "hits",  # -> gift_hits
        "receive_uid",  # -> gift_receiver_uid
        "receive_nn",  # -> gift_receiver_name
        "ct",  # -> client_type
    }
)

_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_danmaku_room_ts
    ON danmaku(room_id, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_danmaku_msg_type
    ON danmaku(msg_type);
"""

_META_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def create_danmaku_table_sql() -> str:
    """DDL for the `danmaku` table, generated from :data:`DANMAKU_SCHEMA`."""
    body = ",\n".join(f"    {column.definition()}" for column in DANMAKU_SCHEMA)
    return f"CREATE TABLE IF NOT EXISTS danmaku (\n{body}\n);"


def columns_sql(columns: Sequence[str]) -> str:
    """Comma-separated column list for embedding in a SELECT."""
    return ", ".join(columns)


#: Full DDL executed when a run file is opened: danmaku + indexes + meta.
SCHEMA_SQL: str = f"{create_danmaku_table_sql()}\n{_INDEX_SQL}{_META_TABLE_SQL}"


def format_timestamp(dt: datetime) -> str:
    """Format a datetime as fixed-width storage text."""
    return dt.strftime(TIMESTAMP_FORMAT)


def parse_timestamp(value: str) -> datetime:
    """Parse storage text back to a datetime."""
    return datetime.strptime(value, TIMESTAMP_FORMAT)


def default_run_file(room: str, stamp: str) -> Path:
    """Default path for a new run file: ``<room>_<YYYYMMDD_HHMMSS>.db``."""
    return Path(DEFAULT_RUN_DIR) / f"{room}_{stamp}.db"
