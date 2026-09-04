"""
Custom exception hierarchy for the UUID Toolkit.

All exceptions carry an optional machine-readable `error_code` so that
callers (CLI, logs, other services) can branch on failure type without
parsing strings.
"""

from __future__ import annotations
from typing import Optional


class UUIDToolkitError(Exception):
    """Base exception for every error raised by this package."""

    def __init__(self, message: str, error_code: Optional[str] = None):
        self.message = message
        self.error_code = error_code or self.__class__.__name__.upper()
        super().__init__(self.message)

    def __str__(self) -> str:
        return f"[{self.error_code}] {self.message}"

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(message={self.message!r}, error_code={self.error_code!r})"


class DatabaseError(UUIDToolkitError):
    """Raised for any SQLite/aiosqlite failure (connect, write, read)."""


class InputValidationError(UUIDToolkitError):
    """Raised when a caller supplies an invalid argument (bad prefix, category, etc.)."""


class DuplicateUUIDError(UUIDToolkitError):
    """Raised when a generated/inserted UUID already exists in storage."""


class UUIDGenerationError(UUIDToolkitError):
    """Raised when UUID generation itself fails (wraps lower-level causes)."""


class UUIDDetectionError(UUIDToolkitError):
    """Raised when a string cannot be parsed / classified as a UUID."""


class ConcurrencyError(UUIDToolkitError):
    """Raised when a parallel/async worker pool fails irrecoverably."""
