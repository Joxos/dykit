"""Capture raw payload field keys per message type from a live Douyu room.

Usage:
    uv run python scripts/capture_raw_fields.py [--room 6657] [--seconds 60]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections import defaultdict

from dycap.collector import AsyncCollector
from dycap.storage.base import StorageHandler


class _NullStorage(StorageHandler):
    async def save(self, message: object) -> None:
        return None

    async def close(self) -> None:
        return None


class _KeyProbe(AsyncCollector):
    """Collector that records the raw field keys per message type."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self.keys_by_type: dict[str, set[str]] = defaultdict(set)

    async def _handle_message(self, msg_type: str, msg_dict: dict[str, str]) -> None:
        self.keys_by_type[msg_type].update(msg_dict.keys())
        await super()._handle_message(msg_type, msg_dict)


async def _run(room: str, seconds: float) -> int:
    probe = _KeyProbe(room, _NullStorage())
    task = asyncio.create_task(probe.connect())
    await asyncio.sleep(seconds)
    await probe.stop()
    try:
        await task
    except asyncio.CancelledError:
        pass
    except Exception as exc:
        print(f"collector ended with error: {exc}", file=sys.stderr)

    for msg_type in sorted(probe.keys_by_type):
        print(f"== {msg_type} ==")
        print(", ".join(sorted(probe.keys_by_type[msg_type])))
    print(f"\ncaptured types: {len(probe.keys_by_type)}")
    return 0 if probe.keys_by_type else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--room", default="6657", help="Douyu room ID (default: 6657)")
    parser.add_argument(
        "--seconds", type=float, default=60.0, help="Capture duration in seconds (default: 60)"
    )
    args = parser.parse_args()
    return asyncio.run(_run(args.room, args.seconds))


if __name__ == "__main__":
    sys.exit(main())
