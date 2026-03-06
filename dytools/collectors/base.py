"""Base collector class with shared message-parsing logic."""

from __future__ import annotations

import re
from datetime import datetime

from ..constants import PROTOCOL_MESSAGE_TYPES
from ..storage.base import StorageHandler
from ..types import DanmuMessage, MessageType


class BaseCollector:
    """Base class for collectors with shared initialization and message parsing."""

    def __init__(
        self,
        room_id: str,
        storage: StorageHandler,
        ws_url: str | None = None,
        type_filter: list[str] | None = None,
        type_exclude: list[str] | None = None,
    ) -> None:
        """Initialize the base collector with shared fields.

        Args:
            room_id: Douyu room ID to connect to.
            storage: StorageHandler instance for persisting danmu messages.
                The storage handler should be opened/initialized before passing
                to this constructor. The collector does NOT close the storage
                handler; caller is responsible for cleanup (e.g., via context
                manager).
            ws_url: Optional manual WebSocket URL override. If provided, bypasses
                discovery and uses this URL directly.
            type_filter: Optional list of message types to collect (e.g., ['chatmsg', 'dgb']).
            If None, all message types are collected. Protocol messages (see PROTOCOL_MESSAGE_TYPES)
                are never filtered.
            type_exclude: Optional list of message types to exclude from collection.
                If None, no messages are excluded. Protocol messages (see PROTOCOL_MESSAGE_TYPES) are
                never excluded.
        """
        self.room_id = room_id
        self._real_room_id: int = 0
        self.storage = storage
        self.ws_url_override = ws_url
        self._type_filter = type_filter
        self._type_exclude = type_exclude

    def _should_skip_message(self, msg_type_str: str) -> bool:
        """Check if a message type should be skipped based on filter/exclude rules.

        Args:
            msg_type_str: The message type string (e.g., 'chatmsg', 'dgb').

        Returns:
            True if the message should be skipped, False otherwise.
        """
        # Never filter protocol messages
        if msg_type_str in PROTOCOL_MESSAGE_TYPES:
            return False

        # Check type filter (whitelist)
        if self._type_filter is not None and msg_type_str not in self._type_filter:
            return True

        # Check type exclude (blacklist)
        if self._type_exclude is not None and msg_type_str in self._type_exclude:
            return True

        return False

    def _build_danmu_message(self, msg_dict: dict[str, str], msg_type: MessageType) -> DanmuMessage:
        """Build DanmuMessage from raw message dict with typed flattened fields.

        Args:
            msg_dict: Raw message dictionary from protocol decoder.
            msg_type: MessageType enum value.

        Returns:
            DanmuMessage with all fields populated according to message type.
        """
        uid = msg_dict.get("uid") or msg_dict.get("unk")
        nn = msg_dict.get("nn") or msg_dict.get("donk")
        if nn:
            nn = re.sub(r"^\s+|\s+$", "", nn)

        room_id = f"{self.room_id}:{self._real_room_id}"
        level = msg_dict.get("level", "0")

        # Extract content only for CHATMSG
        content: str | None = None
        if msg_type == MessageType.CHATMSG:
            content = re.sub(r"^\s+|\s+$", "", msg_dict.get("txt", ""))

        # Initialize optional fields
        gift_id: str | None = None
        gift_count: int | None = None
        gift_name: str | None = None
        badge_level: int | None = None
        badge_name: str | None = None
        noble_level: int | None = None
        avatar_url: str | None = None

        # Populate flattened fields by message type
        if msg_type == MessageType.DGB:
            gift_id = msg_dict.get("gfid")
            gfcnt = msg_dict.get("gfcnt")
            gift_count = int(gfcnt) if gfcnt and gfcnt.isdigit() else None
            gift_name = msg_dict.get("gfn")
        elif msg_type in (MessageType.UENTER, MessageType.BLAB):
            bl = msg_dict.get("bl")
            badge_level = int(bl) if bl and bl.isdigit() else None
            badge_name = msg_dict.get("bnn")
            if msg_type == MessageType.UENTER:
                avatar_url = msg_dict.get("ic")
        elif msg_type in (MessageType.ANBC, MessageType.RNEWBC):
            nl = msg_dict.get("nl")
            noble_level = int(nl) if nl and nl.isdigit() else None

        return DanmuMessage(
            timestamp=datetime.now(),
            username=nn,
            content=content,
            user_level=int(level) if str(level).isdigit() else 0,
            user_id=uid,
            room_id=room_id,
            msg_type=msg_type,
            raw_data=msg_dict,
            gift_id=gift_id,
            gift_count=gift_count,
            gift_name=gift_name,
            badge_level=badge_level,
            badge_name=badge_name,
            noble_level=noble_level,
            avatar_url=avatar_url,
        )
