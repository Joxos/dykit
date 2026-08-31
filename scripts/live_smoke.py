"""Live smoke test - collect danmu from a real Douyu room for N seconds.

Usage:
    uv run python scripts/live_smoke.py [--room 6657] [--seconds 45] [--ws-url URL]

Exits 0 if at least one message was received, 1 otherwise.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections import Counter

from dycap.collector import AsyncCollector
from dycap.storage import ConsoleStorage
from dycap.types import DanmuMessage


async def _run(room: str, seconds: float, ws_url: str | None) -> int:
    received = 0
    by_type: Counter[str] = Counter()

    def on_message(message: DanmuMessage) -> None:
        nonlocal received
        received += 1
        by_type[message.msg_type.value] += 1

    async with ConsoleStorage() as storage:
        collector = AsyncCollector(room, storage, ws_url=ws_url, message_callback=on_message)
        task = asyncio.create_task(collector.connect())
        try:
            await asyncio.sleep(seconds)
        except KeyboardInterrupt:
            pass
        await collector.stop()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            print(f"collector ended with error: {exc}", file=sys.stderr)

    breakdown = ", ".join(f"{msg_type}={count}" for msg_type, count in by_type.most_common())
    print(f"live smoke: room={room} seconds={seconds} messages={received} by_type={breakdown}")
    return 0 if received > 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--room", default="6657", help="Douyu room ID (default: 6657)")
    parser.add_argument(
        "--seconds", type=float, default=45.0, help="Collection duration in seconds (default: 45)"
    )
    parser.add_argument("--ws-url", default=None, help="Optional manual WebSocket URL override")
    args = parser.parse_args()
    return asyncio.run(_run(args.room, args.seconds, args.ws_url))


if __name__ == "__main__":
    sys.exit(main())
