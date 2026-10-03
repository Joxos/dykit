"""Protocol constants for Douyu danmu protocol."""

from __future__ import annotations

# Douyu WebSocket server URL
DOUYU_WS_URL = "wss://danmuproxy.douyu.com:8506/"

# Message types
CLIENT_MSG_TYPE = 689  # Client -> Server
SERVER_MSG_TYPE = 690  # Server -> Client

# Packet header size (bytes)
PACKET_HEADER_SIZE = 12

# Packet size limits
MIN_PACKET_SIZE = 13
MAX_PACKET_SIZE = 65536
