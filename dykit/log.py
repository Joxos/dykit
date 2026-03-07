"""Loguru logging configuration for Douyu Danmu Collector.

This module provides a pre-configured logger instance using loguru.
Loguru is thread-safe and async-safe, making it suitable for
AsyncCollector implementations.

Usage:
    from dykit.log import logger

    logger.info("Message")
    logger.error("Error occurred")
"""

from __future__ import annotations

import sys

from loguru import logger as _logger

# Remove default handler
_logger.remove()

# Add colored stderr handler
_logger.add(
    sys.stderr,
    format=(
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan> - "
        "<level>{message}</level>"
    ),
    level="INFO",
    colorize=True,
)

# Export pre-configured logger
logger = _logger
