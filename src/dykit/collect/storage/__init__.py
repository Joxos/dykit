"""Storage backends for capture."""

from __future__ import annotations

from .base import StorageHandler
from .console import ConsoleStorage
from .csv import CSVStorage
from .sqlite import SQLiteStorage

__all__ = [
    "CSVStorage",
    "ConsoleStorage",
    "SQLiteStorage",
    "StorageHandler",
]
