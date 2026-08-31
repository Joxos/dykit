"""SQLite run-file schema - single source of truth.

One database file per collection run (see ``SQLiteStorage``). Tables:

- ``danmaku``: one row per message. Known analysis-worthy fields are real
  columns; ``raw_data`` keeps only the payload fields NOT extracted into
  columns (deduplicated), so nothing is ever lost and nothing is stored
  twice. ``timestamp`` is stored as fixed-width ISO text (see
  ``dycommon.timestamps``) so TEXT comparisons are chronologically correct.
- ``meta``: key/value run metadata (``room``, ``started_at``, ``ended_at``,
  ``messages``). A file whose ``meta`` lacks ``ended_at`` is an interrupted
  run (process killed) - this is how downtime becomes visible.
"""

from __future__ import annotations

SCHEMA_SQL: str = """
CREATE TABLE IF NOT EXISTS danmaku (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp            TEXT NOT NULL,
    room_id              TEXT NOT NULL,
    msg_type             TEXT NOT NULL,
    user_id              TEXT,
    username             TEXT,
    user_level           INTEGER,
    avatar_url           TEXT,
    color                TEXT,
    content              TEXT,
    badge_level          INTEGER,
    badge_name           TEXT,
    badge_room_id        TEXT,
    gift_id              TEXT,
    gift_count           INTEGER,
    gift_name            TEXT,
    gift_hits            INTEGER,
    gift_receiver_uid    TEXT,
    gift_receiver_name   TEXT,
    noble_level          INTEGER,
    client_type          TEXT,
    raw_data             TEXT
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
