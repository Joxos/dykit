"""SQLite run-file schema - single source of truth.

One database file per collection run (see ``SQLiteStorage``). Tables:

- ``danmaku``: one row per message. Only the columns that analysis commands
  actually query are real columns (timestamp, room_id, msg_type, user_id,
  username, content). Every other field of the payload lives in ``raw_data``
  (full original payload as JSON text) - nothing is ever lost, and any field
  is reachable with ``json_extract``. ``timestamp`` is stored as fixed-width
  ISO text (see ``dycommon.timestamps``) so TEXT comparisons are
  chronologically correct.
- ``meta``: key/value run metadata (``room``, ``started_at``, ``ended_at``,
  ``messages``). A file whose ``meta`` lacks ``ended_at`` is an interrupted
  run (process killed) - this is how downtime becomes visible.
"""

from __future__ import annotations

SCHEMA_SQL: str = """
CREATE TABLE IF NOT EXISTS danmaku (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   TEXT NOT NULL,
    room_id     TEXT NOT NULL,
    msg_type    TEXT NOT NULL,
    user_id     TEXT,
    username    TEXT,
    content     TEXT,
    raw_data    TEXT
);

CREATE INDEX IF NOT EXISTS idx_danmaku_room_ts
    ON danmaku(room_id, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_danmaku_msg_type
    ON danmaku(msg_type);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""
