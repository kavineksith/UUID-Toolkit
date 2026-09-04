"""
Core async UUID generator.

Design notes
------------
- `AsyncUUIDGenerator` is an async context manager (`__aenter__`/`__aexit__`)
  that owns one `AsyncUUIDStore`.
- `__len__` / `__repr__` / `__bool__` are implemented for ergonomic use.
- `stream(...)` is an ASYNC GENERATOR (`async def` + `yield`): it produces
  UUIDs one at a time instead of building a list in memory, so a caller
  requesting 5,000,000 UUIDs never holds them all in RAM at once - each
  one can be written out / persisted / printed and then discarded.
- `generate_bulk_parallel(...)` fans work out across many asyncio tasks
  (bounded by a semaphore) to parallelize the I/O-bound part (DB writes)
  while generation itself streams lazily.
"""

from __future__ import annotations
import asyncio
import uuid as _uuid
from typing import AsyncIterator, Optional, Dict, Any

from .exceptions import InputValidationError, UUIDGenerationError, ConcurrencyError
from .storage import AsyncUUIDStore
from .logger import get_logger

logger = get_logger()

_VALID_TYPES = {"v1", "v3", "v4", "v5", "timestamp"}


class AsyncUUIDGenerator:
    """Async, concurrency-safe UUID generator backed by SQLite storage."""

    def __init__(self, db_path: str = "uuids.db", max_concurrency: int = 20):
        self.db_path = db_path
        self.max_concurrency = max_concurrency
        self._store: Optional[AsyncUUIDStore] = None
        self._count_this_session = 0

    # -- async context manager -------------------------------------------------
    async def __aenter__(self) -> "AsyncUUIDGenerator":
        self._store = AsyncUUIDStore(self.db_path)
        await self._store.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._store is not None:
            await self._store.__aexit__(exc_type, exc_val, exc_tb)
            self._store = None

    # -- dunder ergonomics -------------------------------------------------------
    def __repr__(self) -> str:
        return f"AsyncUUIDGenerator(db_path={self.db_path!r}, generated_this_session={self._count_this_session})"

    def __len__(self) -> int:
        return self._count_this_session

    def __bool__(self) -> bool:
        return self._count_this_session > 0

    # -- validation --------------------------------------------------------------
    @staticmethod
    def _validate_category(category: Optional[str]) -> None:
        if category is None:
            return
        if not isinstance(category, str) or len(category) > 50:
            raise InputValidationError("Category must be a string of 50 characters or fewer")

    @staticmethod
    def _validate_prefix(prefix: Optional[str]) -> Optional[str]:
        if prefix is None:
            return None
        if not isinstance(prefix, str) or not prefix.isalnum() or len(prefix) > 5:
            raise InputValidationError("Prefix must be alphanumeric and 5 characters or fewer")
        return prefix.upper()

    # -- single-item generation ---------------------------------------------------
    async def generate(
        self,
        uuid_type: str,
        category: Optional[str] = None,
        prefix: Optional[str] = None,
        namespace: Optional[_uuid.UUID] = None,
        name: Optional[str] = None,
    ) -> str:
        if uuid_type not in _VALID_TYPES:
            raise InputValidationError(f"Unknown uuid_type {uuid_type!r}; expected one of {_VALID_TYPES}")
        self._validate_category(category)

        try:
            additional_info: Optional[Dict[str, Any]] = None

            if uuid_type == "v1":
                value = str(_uuid.uuid1())
            elif uuid_type == "v4":
                value = str(_uuid.uuid4())
            elif uuid_type in ("v3", "v5"):
                if namespace is None or name is None:
                    raise InputValidationError(f"uuid_type {uuid_type} requires both namespace and name")
                value = str(_uuid.uuid3(namespace, name) if uuid_type == "v3" else _uuid.uuid5(namespace, name))
                additional_info = {"namespace": str(namespace), "name": name}
            else:  # timestamp
                prefix = self._validate_prefix(prefix)
                ts = int(asyncio.get_event_loop().time() * 1_000_000)
                value = f"{prefix}-{ts:X}" if prefix else f"{ts:X}"
                additional_info = {"prefix": prefix} if prefix else None

            await self._store.save(value, uuid_type, category, additional_info)
            self._count_this_session += 1
            logger.info(f"Generated {uuid_type} UUID: {value}")
            return value

        except InputValidationError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.error(f"Failed to generate {uuid_type} UUID: {exc}")
            raise UUIDGenerationError(f"Failed to generate {uuid_type} UUID: {exc}") from exc

    # -- memory-efficient streaming (async generator, uses `yield`) --------------
    async def stream(
        self, uuid_type: str, count: int, category: Optional[str] = None, prefix: Optional[str] = None
    ) -> AsyncIterator[str]:
        """Yield UUIDs one at a time. Never materializes the full batch in memory."""
        if count <= 0:
            raise InputValidationError("count must be a positive integer")

        for _ in range(count):
            yield await self.generate(uuid_type, category=category, prefix=prefix)
            # Cooperative yield to the event loop so a huge stream doesn't
            # starve other tasks (health checks, other requests, etc.).
            await asyncio.sleep(0)

    # -- parallel bulk generation --------------------------------------------------
    async def generate_bulk_parallel(
        self, uuid_type: str, count: int, category: Optional[str] = None, prefix: Optional[str] = None
    ) -> list[str]:
        """
        Generate `count` UUIDs concurrently, bounded by `max_concurrency`.

        Uses a semaphore so we get real parallelism on the I/O-bound DB
        writes without opening unbounded concurrent SQLite connections.
        """
        if count <= 0:
            raise InputValidationError("count must be a positive integer")

        semaphore = asyncio.Semaphore(self.max_concurrency)
        results: list[str] = []
        errors: list[BaseException] = []

        async def _worker() -> None:
            async with semaphore:
                try:
                    results.append(await self.generate(uuid_type, category=category, prefix=prefix))
                except Exception as exc:  # noqa: BLE001
                    errors.append(exc)

        await asyncio.gather(*(_worker() for _ in range(count)))

        if errors and not results:
            raise ConcurrencyError(f"All {len(errors)} parallel generation tasks failed; first error: {errors[0]}")
        if errors:
            logger.warning(f"{len(errors)}/{count} parallel generation tasks failed (partial results returned)")

        return results
