# dyproto

Douyu Live Stream Protocol - minimal library for encoding/decoding danmu messages.

## Installation

```bash
pip install dyproto
```

## Quick Start

```python
from dyproto import pack, unpack, MessageBuffer

# Encode a message to bytes
data = pack({"type": "chatmsg", "content": "Hello"})

# Decode bytes to message
msg = unpack(data)  # {"type": "chatmsg", "content": "Hello"}

# For streaming, use MessageBuffer
buffer = MessageBuffer()
buffer.add_data(raw_bytes)
for msg_dict in buffer.get_messages():
    process(msg_dict)
```

## API

### Core Functions

| Function | Description |
|----------|-------------|
| `pack(msg_dict)` | Encode dict to bytes (serialize + encode) |
| `unpack(data)` | Decode bytes to dict (decode + deserialize) |
| `encode_message(msg_str)` | Encode string to bytes |
| `decode_message(data)` | Decode bytes to string |
| `serialize_message(msg_dict)` | Serialize dict to Douyu KV format |
| `deserialize_message(msg_str)` | Deserialize Douyu KV format to dict |

### Buffer

| Class | Description |
|-------|-------------|
| `MessageBuffer` | UTF-8 safe buffer for streaming packet reassembly |

### Types

| Type | Description |
|------|-------------|
| `MessageType` | Enum of recognized Douyu message types |
| `PacketHeader` | Dataclass for packet header fields |

### Constants

| Constant | Description |
|----------|-------------|
| `DOUYU_WS_URL` | Default WebSocket URL |
| `CLIENT_MSG_TYPE` | Client message type (689) |
| `SERVER_MSG_TYPE` | Server message type (690) |

## Room Discovery

Room ID resolution and danmu server discovery moved to the
[`dysource`](https://pypi.org/project/dysource/) package (dyproto is now a
pure codec with no network dependencies):

```python
from dysource import resolve_room_id, get_danmu_server

# Resolve vanity URL to numeric ID
room_id = resolve_room_id("longzhu")  # -> 6657

# Get danmu WebSocket servers
urls, room_id = get_danmu_server(6657)
# -> (['wss://danmuproxy.douyu.com:8506/', ...], 6657)
```

## License

MIT
