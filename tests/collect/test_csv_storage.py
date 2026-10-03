"""CSV storage: the writer must not flatten 0 into "absent".

``value or ""`` renders a real 0 - a user level, a gift count - as an empty
cell, which is indistinguishable from "not present".
"""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

import pytest

from dykit.collect.storage.csv import COLUMNS, CSVStorage
from dykit.collect.types import DanmuMessage
from dykit.protocol import MessageType


def _row(path: Path) -> dict[str, str]:
    with path.open(encoding="utf-8") as handle:
        return dict(next(csv.DictReader(handle)))


class TestZeroIsNotAbsent:
    @pytest.mark.asyncio
    async def test_zero_valued_fields_are_written_as_zero(self, tmp_path: Path) -> None:
        path = tmp_path / "out.csv"
        async with CSVStorage(path) as storage:
            await storage.save(
                DanmuMessage(
                    timestamp=datetime(2026, 3, 7),
                    room_id="6657",
                    msg_type=MessageType.CHATMSG,
                    user_level=0,
                    gift_count=0,
                    badge_level=0,
                    noble_level=0,
                )
            )

        row = _row(path)

        assert row["user_level"] == "0"
        assert row["gift_count"] == "0"
        assert row["badge_level"] == "0"
        assert row["noble_level"] == "0"

    @pytest.mark.asyncio
    async def test_none_is_still_written_as_empty(self, tmp_path: Path) -> None:
        """The fix must not turn absent values into a literal "None"."""
        path = tmp_path / "out.csv"
        async with CSVStorage(path) as storage:
            await storage.save(
                DanmuMessage(
                    timestamp=datetime(2026, 3, 7),
                    room_id="6657",
                    msg_type=MessageType.CHATMSG,
                )
            )

        row = _row(path)

        assert row["user_level"] == ""
        assert row["username"] == ""

    @pytest.mark.asyncio
    async def test_empty_string_stays_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "out.csv"
        async with CSVStorage(path) as storage:
            await storage.save(
                DanmuMessage(
                    timestamp=datetime(2026, 3, 7),
                    room_id="6657",
                    msg_type=MessageType.CHATMSG,
                    username="alice",
                    content="",
                )
            )

        row = _row(path)

        assert row["username"] == "alice"
        assert row["content"] == ""


class TestShape:
    @pytest.mark.asyncio
    async def test_header_matches_the_declared_columns(self, tmp_path: Path) -> None:
        path = tmp_path / "out.csv"
        async with CSVStorage(path):
            pass

        with path.open(encoding="utf-8") as handle:
            header = next(csv.reader(handle))

        assert header == ["timestamp", *COLUMNS]

    @pytest.mark.asyncio
    async def test_every_row_has_a_cell_for_every_column(self, tmp_path: Path) -> None:
        """A column silently dropped from the row would misalign the file."""
        path = tmp_path / "out.csv"
        async with CSVStorage(path) as storage:
            await storage.save(
                DanmuMessage(
                    timestamp=datetime(2026, 3, 7),
                    room_id="6657",
                    msg_type=MessageType.DGB,
                    gift_id="g1",
                    gift_count=2,
                    gift_name="rocket",
                )
            )

        with path.open(encoding="utf-8") as handle:
            rows = list(csv.reader(handle))

        assert all(len(row) == len(rows[0]) for row in rows)

    @pytest.mark.asyncio
    async def test_saving_after_close_is_a_noop(self, tmp_path: Path) -> None:
        path = tmp_path / "out.csv"
        storage = CSVStorage(path)
        async with storage:
            await storage.save(
                DanmuMessage(
                    timestamp=datetime(2026, 3, 7), room_id="1", msg_type=MessageType.CHATMSG
                )
            )

        await storage.save(
            DanmuMessage(timestamp=datetime(2026, 3, 7), room_id="1", msg_type=MessageType.CHATMSG)
        )

        with path.open(encoding="utf-8") as handle:
            assert len(list(csv.reader(handle))) == 2
