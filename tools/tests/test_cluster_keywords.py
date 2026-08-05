# Tools for A Feminist Audit of Pop Music.
# Copyright 2026 imacat.  All rights reserved.
# Authors:
#   imacat@mail.imacat.idv.tw (imacat), 2026/8/5
"""Unit tests for the keyword clusterer module."""
import csv
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from typing import Any
from unittest import mock

import numpy as np

from pop_fem_audit_tools.commands import cluster_keywords


type Vectors = dict[str, tuple[float, float]]
"""A fixed 2D embedding, keyed by keyword."""


class TestClusterKeywords(unittest.TestCase):
    """Test cases for the keyword clusterer."""

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
        self.__output_dir: Path = self.__dir / "output"
        self.__source_keywords_txt: Path \
            = self.__output_dir \
            / cluster_keywords.SOURCE_KEYWORDS_TXT
        self.__source_provenance_csv: Path \
            = self.__output_dir \
            / cluster_keywords.SOURCE_PROVENANCE_CSV
        self.__result_keywords_txt: Path \
            = self.__output_dir \
            / cluster_keywords.RESULT_KEYWORDS_TXT
        self.__result_groups_csv: Path \
            = self.__output_dir \
            / cluster_keywords.RESULT_GROUPS_CSV
        self.__keywords_to_merge_json: Path \
            = self.__output_dir \
            / cluster_keywords.KEYWORDS_TO_MERGE_JSON

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

    @staticmethod
    def __two_cluster_vectors() -> Vectors:
        """Build two well-separated, exactly medoid-determined
        clusters of three unit vectors each.

        Each cluster is three points symmetric around a central
        angle on the unit circle, so the point at the exact
        central angle is uniquely closest to the cluster's
        renormalized mean direction.

        :return: The fixed embedding of every keyword.
        """
        return {
            "a-left": (0.9396926, -0.3420201),
            "a-center": (1.0, 0.0),
            "a-right": (0.9396926, 0.3420201),
            "b-north": (-0.9396926, 0.3420201),
            "b-middle": (-1.0, 0.0),
            "b-south": (-0.9396926, -0.3420201),
        }

    @staticmethod
    def __fake_encode(vectors: Vectors) -> Any:
        """Build a test double for :func:`encode_keywords`.

        :param vectors: The fixed 2D embedding of every keyword
            the double may be asked to encode.
        :return: A callable with the same signature as
            :func:`encode_keywords`, returning the fixed
            embeddings in the requested keyword order.
        """
        def fake(keywords: list[str], model_name: str,
                 revision: str | None) -> Any:
            """Return the fixed embeddings of the given keywords.

            :param keywords: The keywords to "encode".
            :param model_name: Unused; part of the seam contract.
            :param revision: Unused; part of the seam contract.
            :return: The fixed float32 embeddings, in order.
            """
            return np.asarray(
                [vectors[x] for x in keywords], dtype=np.float32)
        return fake

    def __run_cluster(self, extra_args: list[str] | None = None,
                      vectors: Vectors | None = None,
                      ) -> tuple[int, str]:
        """Run the clusterer with a fake encoder and captured
        standard error.

        :param extra_args: Extra command-line arguments appended
            after the three positional arguments.
        :param vectors: The fixed embedding to encode with; the
            two-cluster fixture is used when None.
        :return: A tuple of the exit status and the standard
            error.
        """
        argv: list[str] = [
            str(self.__run1), str(self.__run2),
            str(self.__output_dir)]
        argv.extend(extra_args or [])
        fake: Any = self.__fake_encode(
            vectors if vectors is not None
            else self.__two_cluster_vectors())
        stderr: io.StringIO = io.StringIO()
        with mock.patch.object(
                cluster_keywords, "encode_keywords", fake), \
                redirect_stderr(stderr):
            status: int = cluster_keywords.main(
                argv + ["--clusters", "2"])
        return status, stderr.getvalue()

    def __read_source_keywords(self) -> list[str]:
        """Read the pooled source keyword text file.

        :return: The keyword list, one keyword per line, with the
            trailing empty line from the final newline removed.
        """
        lines: list[str] = self.__source_keywords_txt.read_text(
            encoding="utf-8").split("\n")
        self.assertEqual(lines[-1], "")
        return lines[:-1]

    def __read_source_provenance(self) -> list[list[str]]:
        """Read the source provenance CSV file.

        :return: All rows, including the header row, in file
            order.
        """
        with open(self.__source_provenance_csv, encoding="utf-8",
                  newline="") as file:
            return list(csv.reader(file))

    def __read_groups(self) -> list[list[str]]:
        """Read the group membership CSV file.

        :return: All rows, including the header row, in file
            order.
        """
        with open(self.__result_groups_csv, encoding="utf-8",
                  newline="") as file:
            return list(csv.reader(file))

    def __read_result_keywords(self) -> list[str]:
        """Read the group name keyword text file.

        :return: The group names, in file order.
        """
        text: str = self.__result_keywords_txt.read_text(
            encoding="utf-8")
        lines: list[str] = text.split("\n")
        if len(lines) > 0 and lines[-1] == "":
            lines = lines[:-1]
        return lines

    def __read_keywords_to_merge(self) -> list[str]:
        """Read the coding keyword set JSON file.

        :return: The group names plus :data:`EXTRA_KEYWORD`
            under the "keywords" key.
        """
        data: dict[str, list[str]] = json.loads(
            self.__keywords_to_merge_json.read_text(
                encoding="utf-8"))
        return data["keywords"]

    def test_pools_union_dedup_sorted(self) -> None:
        """Test the union, dedup, and lexicographic ordering, and
        the plain one-keyword-per-line source keyword file
        shape."""
        self.__write_output(self.__run1, [
            {"id": "song-1",
             "text": json.dumps({"a-left": 1, "shared": 1})},
        ])
        self.__write_output(self.__run2, [
            {"id": "song-3",
             "text": json.dumps({"b-middle": 1, "shared": 1})},
        ])
        vectors: Vectors = {
            **self.__two_cluster_vectors(),
            "shared": (1.0, 0.0)}
        status: int
        stderr: str
        status, stderr = self.__run_cluster(vectors=vectors)
        self.assertEqual(status, 0)
        self.assertEqual(
            self.__read_source_keywords(),
            ["a-left", "b-middle", "shared"])
        self.assertIn(
            "done: 3 keywords pooled from 1+1 records", stderr)

    def test_skips_error_records(self) -> None:
        """Test that records carrying an "error" field are
        excluded from the pool and the record count."""
        self.__write_output(self.__run1, [
            {"id": "song-1",
             "text": json.dumps({"a-left": 1})},
            {"id": "song-2", "error": "invalid_request_error"},
        ])
        self.__write_output(self.__run2, [
            {"id": "song-3", "text": json.dumps({"b-middle": 1})},
        ])
        status: int
        stderr: str
        status, stderr = self.__run_cluster()
        self.assertEqual(status, 0)
        self.assertEqual(
            self.__read_source_keywords(), ["a-left", "b-middle"])
        self.assertIn(
            "done: 2 keywords pooled from 1+1 records", stderr)

    def test_skips_non_json_text_records(self) -> None:
        """Test that a refusal, whose "text" does not parse as
        JSON, is skipped rather than failing the run."""
        self.__write_output(self.__run1, [
            {"id": "song-1",
             "text": json.dumps({"a-left": 1})},
            {"id": "song-2", "text": "I cannot help with that."},
        ])
        self.__write_output(self.__run2, [
            {"id": "song-3", "text": json.dumps({"b-middle": 1})},
        ])
        status: int
        stderr: str
        status, stderr = self.__run_cluster()
        self.assertEqual(status, 0)
        self.assertEqual(
            self.__read_source_keywords(), ["a-left", "b-middle"])
        self.assertIn(
            "done: 2 keywords pooled from 1+1 records", stderr)

    def test_duplicate_key_in_text_rejected(self) -> None:
        """Test that a "text" JSON object with a duplicate key
        fails the run without writing any output file."""
        self.__write_output(self.__run1, [
            {"id": "song-1",
             "text": '{"a-left": 1, "a-left": 2}'},
        ])
        self.__write_output(self.__run2, [
            {"id": "song-3", "text": json.dumps({"b-middle": 1})},
        ])
        status: int
        stderr: str
        status, stderr = self.__run_cluster()
        self.assertEqual(status, 1)
        self.assertIn("duplicate key", stderr)
        self.assertFalse(self.__source_keywords_txt.exists())
        self.assertFalse(self.__source_provenance_csv.exists())
        self.assertFalse(self.__result_groups_csv.exists())
        self.assertFalse(self.__result_keywords_txt.exists())
        self.assertFalse(self.__keywords_to_merge_json.exists())

    def test_non_object_text_rejected(self) -> None:
        """Test that a "text" JSON value that is not an object
        fails the run without writing any output file."""
        self.__write_output(self.__run1, [
            {"id": "song-1", "text": json.dumps(["a-left"])},
        ])
        self.__write_output(self.__run2, [
            {"id": "song-3", "text": json.dumps({"b-middle": 1})},
        ])
        status: int
        stderr: str
        status, stderr = self.__run_cluster()
        self.assertEqual(status, 1)
        self.assertIn("song-1", stderr)
        self.assertFalse(self.__source_keywords_txt.exists())
        self.assertFalse(self.__source_provenance_csv.exists())
        self.assertFalse(self.__result_groups_csv.exists())
        self.assertFalse(self.__result_keywords_txt.exists())
        self.assertFalse(self.__keywords_to_merge_json.exists())

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
             "text": json.dumps({"shared": 1, "b-middle": 1})},
        ])
        vectors: Vectors = {
            **self.__two_cluster_vectors(),
            "shared": (1.0, 0.0)}
        status: int
        status, _ = self.__run_cluster(vectors=vectors)
        self.assertEqual(status, 0)
        rows: list[list[str]] = self.__read_source_provenance()
        self.assertEqual(rows[1:], [
            ["b-middle", "run2", "5"],
            ["shared", "run1", "1"],
            ["shared", "run1", "2"],
            ["shared", "run2", "5"],
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
             "text": json.dumps({"shared": 1, "b-middle": 1})},
        ])
        vectors: Vectors = {
            **self.__two_cluster_vectors(),
            "shared": (1.0, 0.0)}
        status: int
        status, _ = self.__run_cluster(vectors=vectors)
        self.assertEqual(status, 0)
        rows: list[list[str]] = self.__read_source_provenance()
        self.assertEqual(rows[0], ["Keyword", "Run", "Song"])
        self.assertEqual(len(rows), 1 + 4)

    def test_groups_csv_header_and_ordering(self) -> None:
        """Test the header row and the group/keyword ordering of
        the group membership CSV file."""
        self.__write_output(self.__run1, [
            {"id": "song-1", "text": json.dumps(
                {"a-left": 1, "a-center": 1, "a-right": 1})},
        ])
        self.__write_output(self.__run2, [
            {"id": "song-2", "text": json.dumps(
                {"b-north": 1, "b-middle": 1, "b-south": 1})},
        ])
        status: int
        status, _ = self.__run_cluster()
        self.assertEqual(status, 0)
        rows: list[list[str]] = self.__read_groups()
        self.assertEqual(rows[0], ["Group", "Keyword"])
        self.assertEqual(rows[1:], [
            ["a-center", "a-center"],
            ["a-center", "a-left"],
            ["a-center", "a-right"],
            ["b-middle", "b-middle"],
            ["b-middle", "b-north"],
            ["b-middle", "b-south"],
        ])

    def test_every_keyword_appears_exactly_once(self) -> None:
        """Test that every input keyword appears in exactly one
        row of the group membership CSV file."""
        keywords: list[str] = [
            "a-left", "a-center", "a-right",
            "b-north", "b-middle", "b-south"]
        self.__write_output(self.__run1, [
            {"id": "song-1", "text": json.dumps(
                {x: 1 for x in keywords})},
        ])
        self.__write_output(self.__run2, [])
        status: int
        status, _ = self.__run_cluster()
        self.assertEqual(status, 0)
        rows: list[list[str]] = self.__read_groups()[1:]
        self.assertEqual(
            sorted(x[1] for x in rows), sorted(keywords))

    def test_keywords_txt_sorted_medoids(self) -> None:
        """Test that the result keyword text file holds the
        sorted medoid group names without the extra a-priori
        keyword."""
        self.__write_output(self.__run1, [
            {"id": "song-1", "text": json.dumps(
                {"a-left": 1, "a-center": 1, "a-right": 1})},
        ])
        self.__write_output(self.__run2, [
            {"id": "song-2", "text": json.dumps(
                {"b-north": 1, "b-middle": 1, "b-south": 1})},
        ])
        status: int
        status, _ = self.__run_cluster()
        self.assertEqual(status, 0)
        names: list[str] = self.__read_result_keywords()
        self.assertEqual(names, ["a-center", "b-middle"])
        self.assertEqual(names, sorted(names))
        self.assertNotIn(cluster_keywords.EXTRA_KEYWORD, names)

    def test_keywords_to_merge_json_sorted_medoids(self) -> None:
        """Test that the coding keyword set JSON file holds the
        sorted medoid group names plus the extra a-priori
        keyword."""
        self.__write_output(self.__run1, [
            {"id": "song-1", "text": json.dumps(
                {"a-left": 1, "a-center": 1, "a-right": 1})},
        ])
        self.__write_output(self.__run2, [
            {"id": "song-2", "text": json.dumps(
                {"b-north": 1, "b-middle": 1, "b-south": 1})},
        ])
        status: int
        status, _ = self.__run_cluster()
        self.assertEqual(status, 0)
        keywords: list[str] = self.__read_keywords_to_merge()
        self.assertEqual(
            keywords,
            ["a-center", "b-middle", cluster_keywords.EXTRA_KEYWORD])
        self.assertEqual(keywords, sorted(keywords))
        self.assertEqual(len(keywords), 2 + 1)

    def test_extra_keyword_absent_from_groups_csv(self) -> None:
        """Test that the extra a-priori keyword appears in no row
        of the group membership CSV file."""
        self.__write_output(self.__run1, [
            {"id": "song-1", "text": json.dumps(
                {"a-left": 1, "a-center": 1, "a-right": 1})},
        ])
        self.__write_output(self.__run2, [
            {"id": "song-2", "text": json.dumps(
                {"b-north": 1, "b-middle": 1, "b-south": 1})},
        ])
        status: int
        status, _ = self.__run_cluster()
        self.assertEqual(status, 0)
        rows: list[list[str]] = self.__read_groups()
        for row in rows:
            self.assertNotIn(cluster_keywords.EXTRA_KEYWORD, row)
