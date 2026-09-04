"""
Async persistence layer.

Zero external dependencies: wraps the stdlib `sqlite3` module and pushes
every blocking call through `asyncio.to_thread`, so storage never blocks
the event loop even though `sqlite3` itself is synchronous. This matters
once generation is happening concurrently across many asyncio tasks.

A single `threading.Lock` serializes writes to the one underlying
connection (sqlite3 connections are not safe to share across threads
without care), which is exactly what's needed for correctness under
`asyncio.gather`-driven parallel generation.

Implements `__aenter__` / `__aexit__` so it can be used as:

    async with AsyncUUIDStore("uuids.db") as store:
        await store.save(uuid_str, "v4", category="session")
"""

from __future__ import annotations
import asyncio
import json
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .exceptions import DatabaseError, DuplicateUUIDError


class AsyncUUIDStore:
    _SCHEMA = """
        CREATE TABLE IF NOT EXISTS uuids (
            uuid TEXT PRIMARY KEY,
            uuid_type TEXT NOT NULL,
            created_at TEXT NOT NULL,
            category TEXT,
            additional_info TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_uuid_type ON uuids(uuid_type);
        CREATE INDEX IF NOT EXISTS idx_category ON uuids(category);
    """

    def __init__(self, db_path: str = "uuids.db"):
        self.db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None
        self._lock = threading.Lock()

    async def __aenter__(self) -> "AsyncUUIDStore":
        try:
            self._conn = await asyncio.to_thread(
                sqlite3.connect, self.db_path, check_same_thread=False
            )
            await asyncio.to_thread(self._conn.executescript, self._SCHEMA)
            await asyncio.to_thread(self._conn.commit)
        except Exception as exc:  # noqa: BLE001 - normalize all DB errors
            raise DatabaseError(f"Failed to initialize database: {exc}") from exc
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._conn is not None:
            await asyncio.to_thread(self._conn.close)
            self._conn = None

    def __repr__(self) -> str:
        return f"AsyncUUIDStore(db_path={self.db_path!r}, open={self._conn is not None})"

    def _save_sync(
        self,
        uuid_str: str,
        uuid_type: str,
        category: Optional[str],
        additional_info: Optional[Dict[str, Any]],
    ) -> None:
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO uuids (uuid, uuid_type, created_at, category, additional_info) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        uuid_str,
                        uuid_type,
                        datetime.now(timezone.utc).isoformat(),
                        category,
                        json.dumps(additional_info) if additional_info else None,
                    ),
                )
                self._conn.commit()
            except sqlite3.IntegrityError as exc:
                raise DuplicateUUIDError(f"UUID {uuid_str} already exists") from exc

    async def save(
        self,
        uuid_str: str,
        uuid_type: str,
        category: Optional[str] = None,
        additional_info: Optional[Dict[str, Any]] = None,
    ) -> None:
        assert self._conn is not None, "Use 'async with AsyncUUIDStore(...)' first"
        try:
            await asyncio.to_thread(self._save_sync, uuid_str, uuid_type, category, additional_info)
        except DuplicateUUIDError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise DatabaseError(f"Failed to store UUID {uuid_str}: {exc}") from exc

    def _exists_sync(self, uuid_str: str) -> bool:
        with self._lock:
            cursor = self._conn.execute("SELECT 1 FROM uuids WHERE uuid = ? LIMIT 1", (uuid_str,))
            return cursor.fetchone() is not None

    async def exists(self, uuid_str: str) -> bool:
        assert self._conn is not None
        try:
            return await asyncio.to_thread(self._exists_sync, uuid_str)
        except Exception as exc:  # noqa: BLE001
            raise DatabaseError(f"Failed to check UUID existence: {exc}") from exc

    def _stats_sync(self) -> Dict[str, Any]:
        with self._lock:
            result: Dict[str, Any] = {}
            cursor = self._conn.execute("SELECT uuid_type, COUNT(*) FROM uuids GROUP BY uuid_type")
            result["by_type"] = dict(cursor.fetchall())

            cursor = self._conn.execute(
                "SELECT category, COUNT(*) FROM uuids WHERE category IS NOT NULL GROUP BY category"
            )
            result["by_category"] = dict(cursor.fetchall())

            cursor = self._conn.execute("SELECT COUNT(*) FROM uuids")
            row = cursor.fetchone()
            result["total"] = row[0] if row else 0
            return result

    async def stats(self) -> Dict[str, Any]:
        assert self._conn is not None
        try:
            return await asyncio.to_thread(self._stats_sync)
        except Exception as exc:  # noqa: BLE001
            raise DatabaseError(f"Failed to compute stats: {exc}") from exc

    def _recent_sync(self, limit: int) -> List[Dict[str, Any]]:
        with self._lock:
            cursor = self._conn.execute(
                "SELECT uuid, uuid_type, created_at, category FROM uuids "
                "ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
            rows = cursor.fetchall()
            return [
                {"uuid": r[0], "uuid_type": r[1], "created_at": r[2], "category": r[3]}
                for r in rows
            ]

    async def recent(self, limit: int = 20) -> List[Dict[str, Any]]:
        assert self._conn is not None
        try:
            return await asyncio.to_thread(self._recent_sync, limit)
        except Exception as exc:  # noqa: BLE001
            raise DatabaseError(f"Failed to fetch recent UUIDs: {exc}") from exc
