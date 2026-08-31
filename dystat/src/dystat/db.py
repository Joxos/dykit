"""SQLite data access for dystat: one file, or a directory of run files.

Directory mode attaches every ``*.db`` file and exposes a UNION ALL view
``danmaku_all`` so all commands query across runs uniformly. File mode
exposes the same view over the single file, so command SQL never changes.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from types import TracebackType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

DANMAKU_VIEW_COLUMNS = (
    "timestamp, room_id, msg_type, user_id, username, user_level, "
    "avatar_url, color, content, badge_level, badge_name, badge_room_id, "
    "gift_id, gift_count, gift_name, gift_hits, gift_receiver_uid, "
    "gift_receiver_name, noble_level, client_type, raw_data"
)

# Zero-row row source with properly named columns, used for the empty view
# so queries against a directory without run files still work.
_NULL_ROW_SELECT = ", ".join(f"NULL AS {name}" for name in DANMAKU_VIEW_COLUMNS.split(", "))


class DataDb:
    """Read-only wrapper over one SQLite run file or a directory of run files."""

    def __init__(self, path: Path) -> None:
        self.files: list[Path]
        if path.is_file():
            self.files = [path]
            self._conn = sqlite3.connect(str(path))
            self._conn.execute(
                "CREATE TEMP VIEW danmaku_all AS "
                f"SELECT {DANMAKU_VIEW_COLUMNS} FROM main.danmaku"
            )
        elif path.is_dir():
            self.files = sorted(p for p in path.glob("*.db") if p.is_file())
            self._conn = sqlite3.connect(":memory:")
            parts: list[str] = []
            for index, file in enumerate(self.files):
                alias = f"run_{index}"
                self._conn.execute(f"ATTACH DATABASE ? AS {alias}", (str(file),))
                parts.append(f"SELECT {DANMAKU_VIEW_COLUMNS} FROM {alias}.danmaku")
            if parts:
                self._conn.execute(
                    "CREATE TEMP VIEW danmaku_all AS " + " UNION ALL ".join(parts)
                )
            else:
                self._conn.execute(
                    "CREATE TEMP VIEW danmaku_all AS "
                    f"SELECT {DANMAKU_VIEW_COLUMNS} FROM (SELECT {_NULL_ROW_SELECT} WHERE 0)"
                )
        else:
            raise ValueError(f"Data path is neither file nor directory: {path}")

    def query(self, sql: str, params: Sequence[object] = ()) -> list[sqlite3.Row]:
        """Execute a SELECT against the union view and return all rows."""
        with self._conn:
            cursor = self._conn.execute(sql, params)
            return cursor.fetchall()

    def close(self) -> None:
        """Close the underlying connection(s)."""
        self._conn.close()

    def __enter__(self) -> DataDb:
        return self

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc_val: BaseException | None,
        _exc_tb: TracebackType | None,
    ) -> None:
        self.close()
