# dysource

Douyu Live Stream Source - room ID resolution and danmu server discovery.

## Installation

```bash
pip install dysource
```

## Quick Start

```python
from dysource import get_danmu_server, resolve_room_id

# Resolve a vanity/URL room name to the real numeric room ID
room_id = resolve_room_id("6657")  # 6657

# Discover danmu WebSocket server candidates for a room
urls, real_room_id = get_danmu_server(6657)
# ['wss://danmuproxy.douyu.com:8506/', ...], 6657
```

## API

| Function | Description |
|----------|-------------|
| `resolve_room_id(room_id, timeout=10.0)` | Resolve room ID (betard API → m.douyu.com → www.douyu.com fallback chain). |
| `get_danmu_server(room_id, timeout=10.0, manual_url=None)` | Return `(candidate_ws_urls, real_room_id)`. `manual_url` short-circuits discovery. |

## Notes

- Moved out of `dyproto.discovery` (the protocol package is now network-free).
- All functions are synchronous HTTP calls; call them via `asyncio.to_thread` from async code.
