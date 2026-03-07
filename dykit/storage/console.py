"""Console storage handler for printing danmu messages to stdout."""

from __future__ import annotations

from ..types import DanmuMessage, MessageType
from .base import StorageHandler


class ConsoleStorage(StorageHandler):
    """Console/stdout storage handler for printing danmu messages.

    Prints danmu messages directly to stdout with configurable verbosity.
    Useful for real-time monitoring, debugging, and log aggregation.

    In default mode, only prints CHATMSG type messages with the format:
        [username] Lv{level}: {content}

    In verbose mode, prints all message types with full details:
        [MESSAGE_TYPE] message details

    This handler does not perform any I/O besides stdout printing,
    so close() is a no-op.

    Attributes:
        verbose: Whether to print all message types or only chatmsg.

    Example:
        ```python
    from dykit import DanmuMessage
    from dykit.storage import ConsoleStorage

        # Default: print only chatmsg
        with ConsoleStorage() as storage:
            storage.save(message)

        # Verbose: print all message types
        with ConsoleStorage(verbose=True) as storage:
            storage.save(message)
        ```
    """

    def __init__(self, verbose: bool = False) -> None:
        """Initialize ConsoleStorage with optional verbosity.

        Args:
            verbose: If True, print all message types with full details.
                If False, only print CHATMSG type messages. Defaults to False.
        """
        self.verbose = verbose

    async def save(self, message: DanmuMessage) -> None:
        """Print a danmu message to stdout (async interface).

        In default mode (verbose=False), only prints CHATMSG messages with
        the format: [username] Lv{level}: {content}

        In verbose mode (verbose=True), prints all message types with
        the format: [MESSAGE_TYPE] additional details

        Args:
            message: The DanmuMessage to print.
        """
        if self.verbose:
            # Verbose mode: print all message types with full details
            msg_type_name = message.msg_type.value.upper()
            if message.msg_type == MessageType.CHATMSG:
                print(
                    f"[{msg_type_name}] [{message.username}] "
                    f"Lv{message.user_level}: {message.content}"
                )
            else:
                # For non-chatmsg types, print type and relevant fields
                print(f"[{msg_type_name}] {message.msg_type.value}")
        else:
            # Default mode: only print chatmsg
            if message.msg_type == MessageType.CHATMSG:
                print(f"[{message.username}] Lv{message.user_level}: {message.content}")

    async def close(self) -> None:
        """Finalize console output (async interface).

        This is a no-op for console storage since stdout does not require
        explicit closing. Provided to satisfy the StorageHandler interface.
        """
        pass
