"""
Basic sanity tests. Run with: python -m pytest tests/ -v
(or: python -m unittest discover tests)
"""
import asyncio
import os
import tempfile
import unittest
import uuid as _uuid

from uuid_toolkit.generator import AsyncUUIDGenerator
from uuid_toolkit.detector import UUIDDetector
from uuid_toolkit.exceptions import InputValidationError


class TestDetector(unittest.TestCase):
    def setUp(self):
        self.detector = UUIDDetector()

    def test_detects_v4(self):
        value = str(_uuid.uuid4())
        report = self.detector(value)
        self.assertTrue(report.is_valid)
        self.assertEqual(report.version, 4)

    def test_detects_v1_with_timestamp(self):
        value = str(_uuid.uuid1())
        report = self.detector(value)
        self.assertTrue(report.is_valid)
        self.assertEqual(report.version, 1)
        self.assertIsNotNone(report.timestamp)
        self.assertIsNotNone(report.node)

    def test_invalid_string(self):
        report = self.detector("not-a-uuid")
        self.assertFalse(report.is_valid)

    def test_empty_string_raises(self):
        with self.assertRaises(Exception):
            self.detector("")


class TestGenerator(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp_dir, "test.db")

    def test_generate_v4(self):
        async def _run():
            async with AsyncUUIDGenerator(db_path=self.db_path) as gen:
                value = await gen.generate("v4")
                self.assertIsInstance(value, str)
                self.assertEqual(len(gen), 1)

        asyncio.run(_run())

    def test_stream_memory_safe(self):
        async def _run():
            async with AsyncUUIDGenerator(db_path=self.db_path) as gen:
                results = [v async for v in gen.stream("v4", 5)]
                self.assertEqual(len(results), 5)
                self.assertEqual(len(set(results)), 5)

        asyncio.run(_run())

    def test_parallel_bulk(self):
        async def _run():
            async with AsyncUUIDGenerator(db_path=self.db_path, max_concurrency=10) as gen:
                results = await gen.generate_bulk_parallel("v4", 25)
                self.assertEqual(len(results), 25)
                self.assertEqual(len(set(results)), 25)

        asyncio.run(_run())

    def test_invalid_category_raises(self):
        async def _run():
            async with AsyncUUIDGenerator(db_path=self.db_path) as gen:
                with self.assertRaises(InputValidationError):
                    await gen.generate("v4", category="x" * 51)

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
