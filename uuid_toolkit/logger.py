"""
Centralized, memory-safe logging configuration.

- RotatingFileHandler caps disk usage (5MB x 3 backups by default) so a
  long-running/looped process never grows an unbounded log file.
- A separate console handler gives human-friendly INFO+ output.
- `get_logger()` is idempotent: calling it repeatedly (e.g. from multiple
  modules or asyncio tasks) will not duplicate handlers.
"""

from __future__ import annotations
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

_CONFIGURED_LOGGERS: set[str] = set()


def get_logger(
    name: str = "uuid_toolkit",
    log_file: str = "uuid_toolkit.log",
    max_bytes: int = 5 * 1024 * 1024,
    backup_count: int = 3,
    level: int = logging.DEBUG,
) -> logging.Logger:
    logger = logging.getLogger(name)

    if name in _CONFIGURED_LOGGERS:
        return logger

    logger.setLevel(level)
    logger.propagate = False

    Path(log_file).parent.mkdir(parents=True, exist_ok=True)

    file_handler = RotatingFileHandler(
        log_file, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s | %(name)s | %(levelname)-8s | %(processName)s | %(message)s"
        )
    )

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter("%(levelname)s | %(message)s"))

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    _CONFIGURED_LOGGERS.add(name)
    return logger
