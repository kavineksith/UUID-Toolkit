"""
Command-line interface for the UUID Toolkit.

Subcommands
-----------
generate   Generate one UUID (v1, v3, v4, v5, timestamp)
bulk       Generate many UUIDs in parallel (memory-safe streaming)
detect     Inspect / classify an existing UUID string
stats      Show stored UUID statistics
"""

from __future__ import annotations
import argparse
import asyncio
import json
import sys
import uuid as _uuid

from .generator import AsyncUUIDGenerator
from .detector import UUIDDetector
from .storage import AsyncUUIDStore
from .exceptions import UUIDToolkitError
from .logger import get_logger

logger = get_logger()

_NAMESPACES = {
    "dns": _uuid.NAMESPACE_DNS,
    "url": _uuid.NAMESPACE_URL,
    "oid": _uuid.NAMESPACE_OID,
    "x500": _uuid.NAMESPACE_X500,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="uuid-toolkit",
        description="Async, parallel-capable UUID generator, detector, and audit-logged store.",
    )
    parser.add_argument("--db", default="uuids.db", help="Path to SQLite database (default: uuids.db)")
    sub = parser.add_subparsers(dest="command", required=True)

    gen = sub.add_parser("generate", help="Generate a single UUID")
    gen.add_argument("--type", choices=["v1", "v3", "v4", "v5", "timestamp"], required=True)
    gen.add_argument("--category", help="Optional category label")
    gen.add_argument("--prefix", help="Prefix for timestamp UUIDs (max 5 alnum chars)")
    gen.add_argument("--namespace", choices=list(_NAMESPACES), help="Namespace for v3/v5")
    gen.add_argument("--name", help="Name string for v3/v5")

    bulk = sub.add_parser("bulk", help="Generate many UUIDs in parallel")
    bulk.add_argument("--type", choices=["v1", "v3", "v4", "v5", "timestamp"], required=True)
    bulk.add_argument("--count", type=int, required=True, help="Number of UUIDs to generate")
    bulk.add_argument("--category", help="Optional category label")
    bulk.add_argument("--prefix", help="Prefix for timestamp UUIDs (max 5 alnum chars)")
    bulk.add_argument("--concurrency", type=int, default=20, help="Max parallel workers (default: 20)")
    bulk.add_argument("--stream", action="store_true", help="Stream sequentially with low memory use instead of parallel")

    det = sub.add_parser("detect", help="Inspect/classify an existing UUID string")
    det.add_argument("value", help="UUID string to inspect")
    det.add_argument("--json", action="store_true", help="Output as JSON")

    stats = sub.add_parser("stats", help="Show statistics for stored UUIDs")
    stats.add_argument("--recent", type=int, default=0, help="Also list N most recent UUIDs")

    return parser


async def _run_generate(args: argparse.Namespace) -> int:
    async with AsyncUUIDGenerator(db_path=args.db) as gen:
        namespace = _NAMESPACES.get(args.namespace) if args.namespace else None
        value = await gen.generate(
            args.type, category=args.category, prefix=args.prefix, namespace=namespace, name=args.name
        )
        print(f"Generated UUID: {value}")
    return 0


async def _run_bulk(args: argparse.Namespace) -> int:
    async with AsyncUUIDGenerator(db_path=args.db, max_concurrency=args.concurrency) as gen:
        if args.stream:
            n = 0
            async for value in gen.stream(args.type, args.count, category=args.category, prefix=args.prefix):
                print(value)
                n += 1
            print(f"\nStreamed {n} UUIDs (memory-safe, one at a time).", file=sys.stderr)
        else:
            results = await gen.generate_bulk_parallel(
                args.type, args.count, category=args.category, prefix=args.prefix
            )
            for value in results:
                print(value)
            print(f"\nGenerated {len(results)}/{args.count} UUIDs in parallel.", file=sys.stderr)
    return 0


def _run_detect(args: argparse.Namespace) -> int:
    detector = UUIDDetector()
    report = detector(args.value)
    if args.json:
        print(json.dumps(report.__dict__, default=str, indent=2))
    else:
        print(report)
    return 0 if report.is_valid else 1


async def _run_stats(args: argparse.Namespace) -> int:
    async with AsyncUUIDStore(args.db) as store:
        stats = await store.stats()
        print("UUID Statistics:")
        print(json.dumps(stats, indent=2))
        if args.recent > 0:
            recent = await store.recent(args.recent)
            print(f"\nMost recent {len(recent)} UUIDs:")
            print(json.dumps(recent, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "generate":
            return asyncio.run(_run_generate(args))
        if args.command == "bulk":
            return asyncio.run(_run_bulk(args))
        if args.command == "detect":
            return _run_detect(args)
        if args.command == "stats":
            return asyncio.run(_run_stats(args))
    except UUIDToolkitError as exc:
        logger.error(str(exc))
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130

    return 0


if __name__ == "__main__":
    sys.exit(main())
