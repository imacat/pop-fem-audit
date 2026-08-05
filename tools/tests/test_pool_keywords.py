# Tools for A Feminist Audit of Pop Music.
# Copyright 2026 imacat.  All rights reserved.
# Authors:
#   imacat@mail.imacat.idv.tw (imacat), 2026/8/5
"""Unit tests for the keyword pooler module."""
import csv
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from typing import Any

from pop_fem_audit_tools.commands import pool_keywords


class TestPoolKeywords(unittest.TestCase):
    """Test cases for the keyword pooler."""

    def setUp(self) -> None:
        """Create a temporary directory with two run directories."""
        tmp: tempfile.TemporaryDirectory[str] \
            = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.__dir: Path = Path(tmp.name)
        self.__run1: Path = self.__dir / "run1"
        self.__run2: Path = self.__dir / "run2"
        self.__run1.mkdir()
        self.__run2.mkdir()
        self.__pool: Path = self.__dir / "pool.txt"
        self.__provenance: Path = self.__dir / "provenance.csv"

    @staticmethod
    def __write_output(
            run_dir: Path, records: list[dict[str, Any]]) -> None:
        """Write the ``output.jsonl`` file of one run.

        :param run_dir: The run's archive directory.
        :param records: The envelope records, in file order.
        :return: None.
        """
        lines: list[str] = [
            json.dumps(x, ensure_ascii=False) for x in records]
        (run_dir / "output.jsonl").write_text(
            "\n".join(lines) + "\n", encoding="utf-8")

    def __run_pool(self) -> tuple[int, str]:
        """Run the pooler with the standard error captured.

        :return: A tuple of the exit status and the standard
            error.
        """
        stderr: io.StringIO = io.StringIO()
        with redirect_stderr(stderr):
            status: int = pool_keywords.main([
                str(self.__run1), str(self.__run2),
                str(self.__pool), str(self.__provenance)])
        return status, stderr.getvalue()

    def __read_pool(self) -> list[str]:
        """Read the pool text file.

        :return: The keyword list, one keyword per line, with the
            trailing empty line from the final newline removed.
        """
        lines: list[str] = self.__pool.read_text(
            encoding="utf-8").split("\n")
        self.assertEqual(lines[-1], "")
        return lines[:-1]

    def __read_provenance(self) -> list[list[str]]:
        """Read the provenance CSV file.

        :return: All rows, including the header row, in file
            order.
        """
        with open(self.__provenance, encoding="utf-8",
                  newline="") as file:
            return list(csv.reader(file))

    def test_pools_union_dedup_sorted(self) -> None:
        """Test the union, dedup, and lexicographic ordering, and
        the plain one-keyword-per-line pool file shape."""
        self.__write_output(self.__run1, [
            {"id": "song-1",
             "text": json.dumps({"strength": 1, "shared": 1})},
        ])
        self.__write_output(self.__run2, [
            {"id": "song-3",
             "text": json.dumps({"warrior": 1, "shared": 1})},
        ])
        status: int
        stderr: str
        status, stderr = self.__run_pool()
        self.assertEqual(status, 0)
        self.assertEqual(
            self.__read_pool(), ["shared", "strength", "warrior"])
        self.assertIn(
            "done: 3 keywords pooled from 1+1 records", stderr)

    def test_skips_error_records(self) -> None:
        """Test that records carrying an "error" field are
        excluded from the pool and the record count."""
        self.__write_output(self.__run1, [
            {"id": "song-1",
             "text": json.dumps({"strength": 1})},
            {"id": "song-2", "error": "invalid_request_error"},
        ])
        self.__write_output(self.__run2, [
            {"id": "song-3", "text": json.dumps({"warrior": 1})},
        ])
        status: int
        stderr: str
        status, stderr = self.__run_pool()
        self.assertEqual(status, 0)
        self.assertEqual(
            self.__read_pool(), ["strength", "warrior"])
        self.assertIn(
            "done: 2 keywords pooled from 1+1 records", stderr)

    def test_skips_non_json_text_records(self) -> None:
        """Test that a refusal, whose "text" does not parse as
        JSON, is skipped rather than failing the run."""
        self.__write_output(self.__run1, [
            {"id": "song-1",
             "text": json.dumps({"strength": 1})},
            {"id": "song-2", "text": "I cannot help with that."},
        ])
        self.__write_output(self.__run2, [
            {"id": "song-3", "text": json.dumps({"warrior": 1})},
        ])
        status: int
        stderr: str
        status, stderr = self.__run_pool()
        self.assertEqual(status, 0)
        self.assertEqual(
            self.__read_pool(), ["strength", "warrior"])
        self.assertIn(
            "done: 2 keywords pooled from 1+1 records", stderr)

    def test_duplicate_key_in_text_rejected(self) -> None:
        """Test that a "text" JSON object with a duplicate key
        fails the run without writing any output file."""
        self.__write_output(self.__run1, [
            {"id": "song-1",
             "text": '{"strength": 1, "strength": 2}'},
        ])
        self.__write_output(self.__run2, [
            {"id": "song-3", "text": json.dumps({"warrior": 1})},
        ])
        status: int
        stderr: str
        status, stderr = self.__run_pool()
        self.assertEqual(status, 1)
        self.assertIn("duplicate key", stderr)
        self.assertFalse(self.__pool.exists())
        self.assertFalse(self.__provenance.exists())

    def test_non_object_text_rejected(self) -> None:
        """Test that a "text" JSON value that is not an object
        fails the run without writing any output file."""
        self.__write_output(self.__run1, [
            {"id": "song-1", "text": json.dumps(["strength"])},
        ])
        self.__write_output(self.__run2, [
            {"id": "song-3", "text": json.dumps({"warrior": 1})},
        ])
        status: int
        stderr: str
        status, stderr = self.__run_pool()
        self.assertEqual(status, 1)
        self.assertIn("song-1", stderr)
        self.assertFalse(self.__pool.exists())
        self.assertFalse(self.__provenance.exists())

    def test_provenance_content_and_ordering(self) -> None:
        """Test the provenance content and its ordering: rows
        sorted by keyword lexicographically, then by run label,
        then by song ID."""
        self.__write_output(self.__run1, [
            {"id": "song-2", "text": json.dumps({"shared": 1})},
            {"id": "song-1", "text": json.dumps({"shared": 1})},
        ])
        self.__write_output(self.__run2, [
            {"id": "song-5",
             "text": json.dumps({"shared": 1, "warrior": 1})},
        ])
        status: int
        status, _ = self.__run_pool()
        self.assertEqual(status, 0)
        rows: list[list[str]] = self.__read_provenance()
        self.assertEqual(rows[1:], [
            ["shared", "run1", "1"],
            ["shared", "run1", "2"],
            ["shared", "run2", "5"],
            ["warrior", "run2", "5"],
        ])

    def test_provenance_file_header_and_row_count(self) -> None:
        """Test that the provenance CSV file starts with the
        ``Keyword,Run,Song`` header row and has exactly one row
        per keyword occurrence."""
        self.__write_output(self.__run1, [
            {"id": "song-2", "text": json.dumps({"shared": 1})},
            {"id": "song-1", "text": json.dumps({"shared": 1})},
        ])
        self.__write_output(self.__run2, [
            {"id": "song-5",
             "text": json.dumps({"shared": 1, "warrior": 1})},
        ])
        status: int
        status, _ = self.__run_pool()
        self.assertEqual(status, 0)
        rows: list[list[str]] = self.__read_provenance()
        self.assertEqual(rows[0], ["Keyword", "Run", "Song"])
        self.assertEqual(len(rows), 1 + 4)
