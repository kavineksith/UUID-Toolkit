"""
UUID inspection / classification utilities.

A UUID's version and variant are stored as plain, unencrypted bits inside
the value itself (RFC 4122, section 4.1). Reading them back out is
standard parsing - identical to what `uuid.UUID(...).version` already
does in the standard library - not a cryptographic attack. This module
just wraps that parsing with friendlier diagnostics: version, variant,
and (for time-based v1 UUIDs) the embedded timestamp/clock/node fields
that RFC 4122 stores in the clear.

Nothing here can recover a v4 UUID's random bits, predict future UUIDs,
or de-anonymize anything - v4 UUIDs are 122 bits of randomness with no
recoverable structure beyond "this is version 4".
"""

from __future__ import annotations
import uuid as _uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from .exceptions import UUIDDetectionError

# UUID v1 timestamp epoch starts 1582-10-15 (Gregorian reform date),
# not the Unix epoch. Offset in 100-ns intervals between the two epochs.
_GREGORIAN_TO_UNIX_OFFSET = 0x01B21DD213814000


@dataclass
class UUIDReport:
    raw: str
    is_valid: bool
    version: Optional[int] = None
    variant: Optional[str] = None
    canonical: Optional[str] = None
    timestamp: Optional[str] = None  # only populated for v1
    node: Optional[str] = None  # only populated for v1 (MAC or random node id)
    clock_sequence: Optional[int] = None  # only populated for v1
    extra: Dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        if not self.is_valid:
            return f"{self.raw!r} -> INVALID (not a UUID)"
        lines = [f"UUID:      {self.canonical}", f"Version:   {self.version}", f"Variant:   {self.variant}"]
        if self.version == 1:
            lines += [
                f"Timestamp: {self.timestamp}",
                f"Node:      {self.node}",
                f"ClockSeq:  {self.clock_sequence}",
            ]
        return "\n".join(lines)


class UUIDDetector:
    """Callable classifier: `UUIDDetector()(some_string)` -> UUIDReport."""

    _VARIANT_NAMES = {
        _uuid.RESERVED_NCS: "reserved (NCS backward compatibility)",
        _uuid.RFC_4122: "RFC 4122",
        _uuid.RESERVED_MICROSOFT: "reserved (Microsoft backward compatibility)",
        _uuid.RESERVED_FUTURE: "reserved (future use)",
    }

    def __call__(self, candidate: str) -> UUIDReport:
        return self.inspect(candidate)

    def inspect(self, candidate: str) -> UUIDReport:
        if not isinstance(candidate, str) or not candidate.strip():
            raise UUIDDetectionError("Input must be a non-empty string")

        try:
            parsed = _uuid.UUID(candidate.strip())
        except (ValueError, AttributeError, TypeError):
            return UUIDReport(raw=candidate, is_valid=False)

        report = UUIDReport(
            raw=candidate,
            is_valid=True,
            version=parsed.version,
            variant=self._VARIANT_NAMES.get(parsed.variant, str(parsed.variant)),
            canonical=str(parsed),
        )

        if parsed.version == 1:
            report.timestamp = self._decode_v1_timestamp(parsed.time)
            report.node = f"{parsed.node:012x}"
            report.clock_sequence = parsed.clock_seq
            report.extra["node_is_multicast_or_random"] = bool(parsed.node & 0x010000000000)

        elif parsed.version in (3, 5):
            report.extra["note"] = (
                "Deterministic hash of a namespace + name "
                f"({'MD5' if parsed.version == 3 else 'SHA-1'}). "
                "Same inputs always reproduce this UUID."
            )

        elif parsed.version == 4:
            report.extra["note"] = "122 bits of randomness; no embedded metadata to recover."

        else:
            report.extra["note"] = f"Version {parsed.version} is non-standard or unrecognized."

        return report

    @staticmethod
    def _decode_v1_timestamp(time_field: int) -> str:
        unix_100ns = time_field - _GREGORIAN_TO_UNIX_OFFSET
        unix_seconds = unix_100ns / 1e7
        try:
            dt = datetime.fromtimestamp(unix_seconds, tz=timezone.utc)
            return dt.isoformat()
        except (OverflowError, OSError, ValueError):
            return "unrepresentable (out of platform datetime range)"
