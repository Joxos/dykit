"""Database schema - single source of truth for danmaku storage.

All DDL statements live here so that storage code, smoke-test fixtures, and
docs reference the same schema. Statements are idempotent (``CREATE ... IF
NOT EXISTS``) and additive: running them against an existing database only
creates missing tables/indexes and never alters existing data.

Tables:

- ``danmaku``: collected messages (one row per message).
- ``danmaku_dead_letter``: rows that failed to insert after retries, with
  the failure reason (quarantine).
- ``collection_sessions``: one row per storage session, updated on close
  with counters - the observability anchor for batch-write tuning.
"""

from __future__ import annotations

from typing import LiteralString

DANMAKU_DDL: LiteralString = """
CREATE TABLE IF NOT EXISTS danmaku (
    id          SERIAL PRIMARY KEY,
    timestamp   TIMESTAMP NOT NULL,
    room_id     TEXT NOT NULL,
    msg_type    TEXT NOT NULL,
    user_id     TEXT,
    username    TEXT,
    content     TEXT,
    user_level  INTEGER,
    gift_id     TEXT,
    gift_count  INTEGER,
    gift_name   TEXT,
    badge_level INTEGER,
    badge_name  TEXT,
    noble_level INTEGER,
    avatar_url  TEXT,
    raw_data    JSONB
);
"""

DANMAKU_INDEX_DDL: LiteralString = """
CREATE INDEX IF NOT EXISTS idx_danmaku_room_time
    ON danmaku(room_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_danmaku_user_id
    ON danmaku(user_id);
CREATE INDEX IF NOT EXISTS idx_danmaku_msg_type
    ON danmaku(msg_type);
"""

DEAD_LETTER_DDL: LiteralString = """
CREATE TABLE IF NOT EXISTS danmaku_dead_letter (
    id            SERIAL PRIMARY KEY,
    failed_at     TIMESTAMP NOT NULL DEFAULT NOW(),
    room_id       TEXT NOT NULL,
    msg_type      TEXT NOT NULL,
    username      TEXT,
    content       TEXT,
    reason        TEXT NOT NULL,
    error_type    TEXT,
    error_message TEXT,
    payload_text  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_danmaku_dead_letter_failed_at
    ON danmaku_dead_letter(failed_at DESC);
"""

SESSIONS_DDL: LiteralString = """
CREATE TABLE IF NOT EXISTS collection_sessions (
    id                 SERIAL PRIMARY KEY,
    room_id            TEXT NOT NULL,
    started_at         TIMESTAMP NOT NULL DEFAULT NOW(),
    ended_at           TIMESTAMP,
    message_count      INTEGER NOT NULL DEFAULT 0,
    dead_letter_count  INTEGER NOT NULL DEFAULT 0,
    flush_count        INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_collection_sessions_room_started
    ON collection_sessions(room_id, started_at DESC);
"""

SCHEMA_STATEMENTS: list[LiteralString] = [DANMAKU_DDL, DANMAKU_INDEX_DDL, DEAD_LETTER_DDL, SESSIONS_DDL]
