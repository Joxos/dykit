"""Storage handlers for persisting danmu messages.

This package provides abstract base class and concrete implementations for
storing danmu messages from Douyu live streams. It includes support for
CSV files, console output, and PostgreSQL database, with extensible design
for custom backends.

Classes:
    StorageHandler: Abstract base class for all storage implementations.
    CSVStorage: Persist messages to CSV files.
    ConsoleStorage: Print messages to stdout (see console.py).
    PostgreSQLStorage: Persist messages to PostgreSQL database.
"""

from __future__ import annotations

# Import types needed for concrete implementations
# Import StorageHandler from base module
from .base import StorageHandler

# Import ConsoleStorage from console module
from .console import ConsoleStorage

# Import CSVStorage from csv module
from .csv import CSVStorage

# Import PostgreSQLStorage from postgres module
from .postgres import PostgreSQLStorage

__all__ = [
    "StorageHandler",
    "CSVStorage",
    "ConsoleStorage",
    "PostgreSQLStorage",
]
