"""CSV storage handler."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import IO, Any

from ..types import DanmuMessage
from .base import StorageHandler

#: Column order of the CSV, matching the header written on open.
COLUMNS: tuple[str, ...] = (
    "room_id",
    "msg_type",
    "user_id",
    "username",
    "content",
    "user_level",
    "gift_id",
    "gift_count",
    "gift_name",
    "badge_level",
    "badge_name",
    "noble_level",
    "avatar_url",
)


def _cell(value: object) -> str:
    """Render one cell, keeping 0 distinguishable from absent.

    `value or ""` would turn a real 0 (a user level, a gift count) into an
    empty cell, which is indistinguishable from "not present".
    """
    return "" if value is None else str(value)


class CSVStorage(StorageHandler):
    """CSV file storage handler.

    Writes danmu messages to a CSV file, one row per message.

    Example:
        async with CSVStorage("output.csv") as storage:
            await storage.save(message)
    """

    def __init__(self, filename: str | Path) -> None:
        """Initialize CSV storage.

        Args:
            filename: Output CSV file path.
        """
        self._filename = Path(filename)
        self._closed = False
        self._file: IO[str] | None = None
        self._csv_writer: Any = None

    async def __aenter__(self) -> CSVStorage:
        """Open CSV file and write header."""
        self._file = self._filename.open("w", newline="", encoding="utf-8")
        self._csv_writer = csv.writer(self._file)
        self._csv_writer.writerow(["timestamp", *COLUMNS])
        self._file.flush()
        return self

    async def save(self, message: DanmuMessage) -> None:
        """Write one message to CSV file."""
        if self._closed or self._file is None or self._csv_writer is None:
            return

        self._csv_writer.writerow(
            [message.timestamp.isoformat(), message.msg_type.value]
            + [_cell(getattr(message, name)) for name in COLUMNS if name != "msg_type"]
        )
        self._file.flush()

    async def close(self) -> None:
        """Close storage and output file."""
        if self._closed:
            return
        self._closed = True
        if self._file is not None:
            self._file.close()
            self._file = None
