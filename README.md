# UUID Toolkit (Async, Parallel, Auditable)

A rewritten, production-oriented UUID toolkit in Python. It **generates**
UUIDs (v1, v3, v4, v5, timestamp) and **inspects/classifies** existing
UUID strings — async from the ground up, parallel-capable, memory-safe
for large batches, and fully audit-logged.

This is a from-scratch redesign of a simpler synchronous script, built
around: `asyncio`, async generators (`yield`), dunder methods
(`__aenter__`/`__aexit__`/`__repr__`/`__len__`/`__bool__`/`__call__`),
a custom OOP exception hierarchy, bounded parallelism, and rotating logs.

---

## 1. Problem this solves

Teams generating IDs at scale run into the same recurring issues:

| Problem | How this toolkit addresses it |
|---|---|
| Simple scripts generate one UUID per process call — slow for bulk needs | `bulk` subcommand generates thousands concurrently via bounded `asyncio` parallelism |
| Generating huge batches (millions) blows up memory if you build a list first | `stream` mode uses an **async generator** (`yield`) — one UUID exists in memory at a time |
| No visibility into *what type* an unknown UUID is, or when a v1 UUID was actually created | `detect` subcommand decodes version, variant, and (for v1) the embedded timestamp/node/clock sequence — this is just RFC 4122 bit-parsing, not decryption |
| Silent failures / no accountability trail | Every generation, duplicate, and error is written to a rotating log file with timestamps, for after-the-fact auditing |
| Generic `Exception` catches hide real causes | A typed exception hierarchy (`InputValidationError`, `DuplicateUUIDError`, `DatabaseError`, `UUIDGenerationError`, `UUIDDetectionError`, `ConcurrencyError`) makes failure modes explicit and scriptable |
| Unbounded log files fill disks on long-running services | `RotatingFileHandler` caps the log at 5MB × 3 backups by default |

### A note on "detect existing UUIDs"

UUID version/variant bits are **stored in plaintext inside the UUID
itself** (RFC 4122 §4.1) — the same information `uuid.UUID(x).version`
already exposes in Python's standard library. `detect` just surfaces
that clearly, plus decodes the human-readable timestamp/node fields that
v1 UUIDs carry in the open. It **cannot** reverse a v4 UUID's random
bits, predict future UUIDs, or de-anonymize anything — v4 is 122 bits of
randomness with no recoverable structure beyond "this is version 4."

---

## 2. Architecture

```
uuid-toolkit/
├── uuid_toolkit/
│   ├── __init__.py       # public API exports
│   ├── generator.py      # AsyncUUIDGenerator: generate/stream/parallel bulk
│   ├── detector.py       # UUIDDetector: version/variant/timestamp parsing
│   ├── storage.py        # AsyncUUIDStore: sqlite3 wrapped for asyncio
│   ├── logger.py         # rotating file + console logger factory
│   ├── exceptions.py     # custom exception hierarchy
│   └── cli.py            # argparse CLI entry point
├── tests/
│   └── test_toolkit.py   # unittest suite
├── run.sh                # bash wrapper (venv + deps + CLI)
├── requirements.txt      # stdlib-only; kept for future optional deps
├── README.md
└── LICENSE
```

Key design choices:

- **Async everywhere**: `AsyncUUIDGenerator` and `AsyncUUIDStore` are
  async context managers. Storage uses stdlib `sqlite3` pushed through
  `asyncio.to_thread` (zero external dependencies), so the event loop is
  never blocked by disk I/O.
- **Generators (`yield`)**: `AsyncUUIDGenerator.stream()` is an async
  generator — it yields one UUID at a time instead of building a list,
  so `bulk --stream --count 5000000` doesn't need 5 million strings
  resident in memory simultaneously.
- **Parallelism**: `generate_bulk_parallel()` fans generation out across
  `asyncio.gather()` tasks bounded by a `Semaphore` (`--concurrency`,
  default 20), so DB writes overlap instead of serializing.
- **Dunder methods**: `__aenter__`/`__aexit__` (context management),
  `__repr__` (debugging), `__len__`/`__bool__` (session UUID count),
  `__call__` (`UUIDDetector()(value)` reads like a function).
- **Accountability logging**: every generate/detect/error event is
  timestamped into `uuid_toolkit.log` (rotated at 5MB, 3 backups kept).

---

## 3. Installation

Requires Python 3.9+. No external dependencies are required — the
toolkit only uses the standard library.

```bash
git clone <this-repo>
cd uuid-toolkit
chmod +x run.sh
```

`run.sh` will create a local virtualenv on first run automatically.

---

## 4. Usage

All commands can be run either via the bash wrapper or directly with Python:

```bash
./run.sh <subcommand> [options]
# or
python3 -m uuid_toolkit.cli <subcommand> [options]
```

### Generate a single UUID

```bash
./run.sh generate --type v4
./run.sh generate --type v1 --category session
./run.sh generate --type timestamp --prefix ABC --category order
./run.sh generate --type v5 --namespace dns --name example.com
```

### Generate many UUIDs (parallel or memory-safe streaming)

```bash
# Parallel (default): fans out across asyncio tasks, bounded by --concurrency
./run.sh bulk --type v4 --count 5000 --concurrency 50

# Streaming: one UUID in memory at a time (best for very large counts)
./run.sh bulk --type v4 --count 5000000 --stream > uuids.txt
```

### Detect / classify an existing UUID

```bash
./run.sh detect 550e8400-e29b-41d4-a716-446655440000
./run.sh detect 7570fa4c-7770-11f1-a1bc-15f962fc079c --json
```

Example output for a v1 UUID:

```
UUID:      7570fa4c-7770-11f1-a1bc-15f962fc079c
Version:   1
Variant:   RFC 4122
Timestamp: 2026-07-04T06:20:37.891805+00:00
Node:      15f962fc079c
ClockSeq:  3911
```

### View statistics

```bash
./run.sh stats
./run.sh stats --recent 10
```

### Custom database location

Every subcommand accepts `--db <path>` (default: `uuids.db`) as a
top-level flag before the subcommand:

```bash
./run.sh --db /var/data/orders.db generate --type v4
```

---

## 5. Running tests

```bash
python3 -m unittest discover tests -v
```

---

## 6. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `DuplicateUUIDError` during `bulk --stream --type timestamp` | Timestamp UUIDs are keyed to microsecond time; generating faster than the clock resolution with the same prefix can collide | Reduce concurrency, or use `v4`/`v1` for very high-throughput bulk runs |
| `InputValidationError: Prefix must be alphanumeric...` | `--prefix` was longer than 5 chars or had symbols | Use a short alphanumeric prefix, e.g. `ABC12` |
| `DatabaseError: Failed to initialize database` | No write permission to the `--db` path/directory | Point `--db` at a writable path, or `chmod`/`chown` the target directory |
| CLI hangs on very large `--count` with default parallel mode | Too many concurrent SQLite writes contending on the internal lock | Prefer `--stream` for counts above ~100k, or lower `--concurrency` |
| `ModuleNotFoundError: No module named 'uuid_toolkit'` | Running `python3 -m uuid_toolkit.cli` from outside the project root | `cd` into the `uuid-toolkit/` directory first, or use `./run.sh` |
| Log file growing unexpectedly large | Very high generation volume | Rotation is automatic (5MB × 3 backups); lower `max_bytes`/`backup_count` in `logger.get_logger()` if you need tighter caps |
| `detect` reports `INVALID` for a value you expected to be valid | Extra whitespace, wrong dashes, or it's simply not RFC-4122-shaped | Copy the value exactly; `detect` trims surrounding whitespace but won't fix malformed hex groups |

---

## 7. Disclaimer

This project is intended for demonstration, prototyping, and internal
tooling purposes. It includes reasonable engineering practices (input
validation, typed exceptions, async I/O, bounded parallelism, rotating
audit logs, and a test suite), but it is **not guaranteed to be secure
or complete for every production context** without your own review.

- The `detect` command only parses publicly-documented, unencrypted
  RFC 4122 structure. It performs no cryptographic attacks and cannot
  recover randomness from v4 UUIDs.
- SQLite is used as a lightweight embedded store; for high-throughput,
  multi-process production workloads, evaluate a server-based database.
- This software is provided **"as is"**, without warranty of any kind,
  express or implied. The authors are not responsible for any outcomes
  resulting from its use. **Use at your own risk.**

## License

MIT License — see [LICENSE](LICENSE).
