"""The Douyu message-type registry.

The wire format only cares about the type string; the human label and icon
for each type are presentation and live in ``dykit.collect.render``.
"""

from __future__ import annotations

from enum import Enum


class MessageType(str, Enum):
    """Douyu message type enumeration.

    These are the recognized message types in the Douyu protocol.
    """

    # User messages
    CHATMSG = "chatmsg"  # Regular chat message
    DGB = "dgb"  # Gift
    UENTER = "uenter"  # User entered
    ANBC = "anbc"  # Noble opened
    RNEWBC = "rnewbc"  # Noble renewed
    BLAB = "blab"  # Badge level up
    UPGRADE = "upgrade"  # User level up


#: Raw Douyu type string -> the type dykit models. This is the protocol-side
#: registry: teaching dykit a new message type starts here.
MSG_TYPE_TO_ENUM: dict[str, MessageType] = {
    "chatmsg": MessageType.CHATMSG,
    "dgb": MessageType.DGB,
    "uenter": MessageType.UENTER,
    "anbc": MessageType.ANBC,
    "rnewbc": MessageType.RNEWBC,
    "blab": MessageType.BLAB,
    "upgrade": MessageType.UPGRADE,
}
