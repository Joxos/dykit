#!/usr/bin/env python3
from __future__ import annotations

"""DEPRECATED: Use the new modular 'douyu_danmu' package instead.

This module is maintained for backward compatibility only.
Please migrate to the new package structure:

    from douyu_danmu import SyncCollector, AsyncCollector
    from douyu_danmu.storage import CSVStorage, ConsoleStorage

Usage:
    # Old way (deprecated):
    python douyu_danmu.py --room-id 6657

    # New way (recommended):
    python -m douyu_danmu --room-id 6657
    python -m douyu_danmu --room-id 6657 --async

The modular package provides:
- Async/await support for high-concurrency scenarios
- Pluggable storage backends
- Type-safe dataclasses
- UTF-8 safety guarantees

Version 2.0.0 introduces breaking changes. See README.md for migration guide.
"""

import warnings
warnings.warn(
    "The standalone douyu_danmu.py module is deprecated. "
    "Please use 'python -m douyu_danmu' or import from 'douyu_danmu' package. "
    "Version 2.0.0 uses modular architecture - see README.md for migration.",
    DeprecationWarning,
    stacklevel=2
)

import argparse
import csv
import logging
import os
import struct
import threading
import time
from datetime import datetime
from io import TextIOWrapper

from websocket import WebSocketApp

# Douyu WebSocket server URL (use wss:// port 8506)
DOUYU_WS_URL = "wss://danmuproxy.douyu.com:8506/"

# Message types for Douyu protocol
CLIENT_MSG_TYPE = 689  # Client -> Server
SERVER_MSG_TYPE = 690  # Server -> Client


def serialize_message(msg_dict: dict[str, str | int]) -> str:
    """Serialize a message dictionary to Douyu key-value format.

    Format: key1@=value1/key2@=value2/
    Escaping: @ -> @A, / -> @S

    Args:
        msg_dict: Dictionary containing message key-value pairs.

    Returns:
        Serialized message string in Douyu format.
    """
    result = []
    for key, value in msg_dict.items():
        # Escape @ and / in key and value
        key_escaped = str(key).replace("@", "@A").replace("/", "@S")
        value_escaped = str(value).replace("@", "@A").replace("/", "@S")
        result.append(f"{key_escaped}@={value_escaped}/")
    return "".join(result)


def deserialize_message(msg_str: str) -> dict[str, str]:
    """Deserialize Douyu key-value format to a dictionary.

    Format: key1@=value1/key2@=value2/
    Unescaping: @A -> @, @S -> /

    Args:
        msg_str: Serialized message string in Douyu format.

    Returns:
        Dictionary with deserialized key-value pairs.
    """
    result: dict[str, str] = {}
    # Remove trailing / and split by /
    parts = msg_str.rstrip("/").split("/")
    for part in parts:
        if "@=" in part:
            key, value = part.split("@=", 1)
            # Unescape @A and @S
            key_unescaped = key.replace("@S", "/").replace("@A", "@")
            value_unescaped = value.replace("@S", "/").replace("@A", "@")
            result[key_unescaped] = value_unescaped
    return result


def encode_message(msg_str: str) -> bytes:
    """Encode a message string into Douyu binary protocol format.

    Format:
        - 4 bytes: packet length (little-endian)
        - 4 bytes: packet length (duplicate)
        - 2 bytes: message type (689 for client)
        - 1 byte: encrypt (0 = no encryption)
        - 1 byte: reserved (0)
        - N bytes: message body
        - 1 byte: null terminator (\\0)

    Args:
        msg_str: Message string to encode.

    Returns:
        Binary packet ready to send over WebSocket.
    """
    # Message body with null terminator
    body = msg_str.encode("utf-8") + b"\x00"

    # Calculate packet length (header + body)
    # Header is 12 bytes: 4+4+2+1+1
    packet_length = len(body) + 8  # 8 = 2+1+1+body length (excluding first 4 bytes)

    # Build packet
    packet = struct.pack("<I", packet_length)  # 4 bytes: length
    packet += struct.pack("<I", packet_length)  # 4 bytes: length (duplicate)
    packet += struct.pack("<H", CLIENT_MSG_TYPE)  # 2 bytes: msg type
    packet += struct.pack("<B", 0)  # 1 byte: encrypt
    packet += struct.pack("<B", 0)  # 1 byte: reserved
    packet += body

    return packet


def decode_message(data: bytes) -> str | None:
    """Decode Douyu binary protocol message.

    Args:
        data: Binary data received from WebSocket.

    Returns:
        Message string (without null terminator), or None if decode fails.
    """
    if len(data) < 12:
        return None

    # Parse packet header (kept for protocol documentation)
    _ = struct.unpack("<I", data[0:4])  # packet_length
    _ = struct.unpack("<H", data[8:10])  # msg_type

    # Skip header (12 bytes: 4+4+2+1+1)
    # Extract message body (until null terminator)
    body = data[12:]

    # Remove null terminator
    if body.endswith(b"\x00"):
        body = body[:-1]

    try:
        return body.decode("utf-8")
    except UnicodeDecodeError:
        # Retry with error handling for incomplete multi-byte sequences
        try:
            return body.decode("utf-8", errors="ignore")
        except Exception:
            logging.warning(f"Failed to decode message (len={len(body)}): {body[:50]}")
            return None


class DouyuDanmuClient:
    """WebSocket client for Douyu danmu (chat messages)."""

    def __init__(self, room_id: int, output_file: str) -> None:
        """Initialize the Douyu danmu client.

        Args:
            room_id: Douyu room ID to connect to.
            output_file: Path to CSV file for storing danmu messages.
        """
        self.room_id = room_id
        self.output_file = output_file
        self.csv_file: TextIOWrapper | None = None
        self.csv_writer: csv.writer | None = None  # type: ignore[assignment]
        self.ws: WebSocketApp | None = None
        self.heartbeat_thread: threading.Thread | None = None
        self.running = False
        self._init_csv()

    def _init_csv(self) -> None:
        """Initialize CSV file with header row if needed."""
        try:
            # Check if file exists and is not empty
            file_exists = (
                os.path.exists(self.output_file)
                and os.path.getsize(self.output_file) > 0
            )

            # Open file in append mode with newline=''
            self.csv_file = open(self.output_file, "a", newline="", encoding="utf-8")
            self.csv_writer = csv.writer(self.csv_file)  # type: ignore[arg-type]

            # Write header if file is new
            if not file_exists and self.csv_writer is not None:
                self.csv_writer.writerow(
                    [
                        "timestamp",
                        "username",
                        "content",
                        "user_level",
                        "user_id",
                        "room_id",
                    ]
                )
                self.csv_file.flush()
                logging.info(f"Created new CSV file: {self.output_file}")
            else:
                logging.info(f"Appending to existing CSV file: {self.output_file}")
        except Exception as e:
            logging.error(f"Failed to initialize CSV file: {e}")
            self.csv_file = None
            self.csv_writer = None

    def on_message(self, ws: WebSocketApp, message: bytes) -> None:
        """Handle incoming WebSocket messages.

        Args:
            ws: WebSocket application instance.
            message: Binary message data from server.
        """
        # Decode binary message
        msg_str = decode_message(message)
        if not msg_str:
            return

        # Deserialize key-value pairs
        msg_dict = deserialize_message(msg_str)
        msg_type = msg_dict.get("type")

        if msg_type == "loginres":
            logging.info("Received loginres - login successful")
        elif msg_type == "chatmsg":
            # Extract chat message fields
            nickname = msg_dict.get("nn", "Unknown")
            content = msg_dict.get("txt", "")
            level = msg_dict.get("level", "0")
            uid = msg_dict.get("uid", "0")

            # Print to console
            print(f"[{nickname}] Lv{level}: {content}")
            logging.debug(
                f"chatmsg - uid={uid}, nn={nickname}, txt={content}, level={level}"
            )

            # Write to CSV
            if self.csv_writer is not None and self.csv_file is not None:
                try:
                    self.csv_writer.writerow(
                        [
                            datetime.now().isoformat(),
                            nickname,
                            content,
                            level,
                            uid,
                            self.room_id,
                        ]
                    )
                    self.csv_file.flush()  # Ensure immediate write
                except Exception as e:
                    logging.error(f"Failed to write to CSV: {e}")
        else:
            # Log other message types in debug mode
            logging.debug(f"Received message type: {msg_type}")

    def on_error(self, ws: WebSocketApp, error: object) -> None:
        """Handle WebSocket errors.

        Args:
            ws: WebSocket application instance.
            error: Error object from WebSocket.
        """
        logging.error(f"WebSocket error: {error}")

    def on_close(
        self, ws: WebSocketApp, close_status_code: int, close_msg: str | None
    ) -> None:
        """Handle WebSocket close.

        Args:
            ws: WebSocket application instance.
            close_status_code: Status code for close.
            close_msg: Close message from server.
        """
        logging.info("WebSocket connection closed")
        self.running = False
        # Close CSV file gracefully
        if self.csv_file:
            try:
                self.csv_file.close()
                logging.info(f"CSV file closed: {self.output_file}")
            except Exception as e:
                logging.error(f"Failed to close CSV file: {e}")

    def on_open(self, ws: WebSocketApp) -> None:
        """Handle WebSocket connection open.

        Args:
            ws: WebSocket application instance.
        """
        logging.info(f"Connected to {DOUYU_WS_URL}")

        # Send login request
        login_msg = serialize_message({"type": "loginreq", "roomid": self.room_id})
        ws.send(encode_message(login_msg), opcode=0x2)  # 0x2 = binary
        logging.debug(f"Sent loginreq: {login_msg}")

        # Send joingroup request
        joingroup_msg = serialize_message(
            {"type": "joingroup", "rid": self.room_id, "gid": -9999}
        )
        ws.send(encode_message(joingroup_msg), opcode=0x2)
        logging.debug(f"Sent joingroup: {joingroup_msg}")

        # Start heartbeat thread
        self.running = True
        self.heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop, daemon=True
        )
        self.heartbeat_thread.start()
        logging.debug("Heartbeat thread started")

    def _heartbeat_loop(self) -> None:
        """Send heartbeat messages every 45 seconds."""
        while self.running:
            time.sleep(45)
            if self.running and self.ws:
                heartbeat_msg = serialize_message({"type": "mrkl"})
                try:
                    self.ws.send(encode_message(heartbeat_msg), opcode=0x2)
                    logging.debug("Sent heartbeat (mrkl)")
                except Exception as e:
                    logging.error(f"Failed to send heartbeat: {e}")
                    break

    def connect(self) -> None:
        """Connect to Douyu WebSocket server and start receiving messages."""
        import ssl

        self.ws = WebSocketApp(
            DOUYU_WS_URL,
            on_message=self.on_message,
            on_error=self.on_error,
            on_close=self.on_close,
            on_open=self.on_open,
        )

        logging.info("Starting WebSocket connection...")

        # Use relaxed SSL settings with OpenSSL SECLEVEL=1 for older Douyu servers
        sslopt = {
            "cert_reqs": ssl.CERT_NONE,
            "check_hostname": False,
            "ssl_version": ssl.PROTOCOL_TLS_CLIENT,
            "ciphers": "DEFAULT@SECLEVEL=1",
        }
        self.ws.run_forever(sslopt=sslopt)


def main() -> None:
    """Main entry point for the danmu crawler."""
    parser = argparse.ArgumentParser(
        description="Douyu live stream danmu (chat message) crawler"
    )
    parser.add_argument(
        "--room-id", type=int, default=6657, help="Douyu room ID (default: 6657)"
    )
    parser.add_argument(
        "--output",
        type=str,
        default="danmu.csv",
        help="Output CSV file path (default: danmu.csv)",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable verbose logging"
    )

    args = parser.parse_args()

    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level, format="%(asctime)s - %(levelname)s - %(message)s"
    )

    logging.info(f"Starting danmu crawler for room {args.room_id}")
    logging.info(f"Output file: {args.output}")

    # Create and connect danmu client
    client = DouyuDanmuClient(args.room_id, args.output)
    try:
        client.connect()
    except KeyboardInterrupt:
        logging.info("Interrupted by user")
        client.running = False
    except Exception as e:
        logging.error(f"Connection error: {e}")
        raise


if __name__ == "__main__":
    main()
