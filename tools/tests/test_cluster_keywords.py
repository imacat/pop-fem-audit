# Tools for A Feminist Audit of Pop Music.
# Copyright 2026 imacat.  All rights reserved.
# Authors:
#   imacat@mail.imacat.idv.tw (imacat), 2026/8/5
"""Unit tests for the keyword clusterer module."""
import csv
import io
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
        """Create a temporary directory for the output files."""
        tmp: tempfile.TemporaryDirectory[str] \
            = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.__dir: Path = Path(tmp.name)
        self.__keywords_txt: Path = self.__dir / "keywords.txt"
        self.__groups_csv: Path = self.__dir / "groups.csv"
        self.__vocabulary_txt: Path = self.__dir / "vocabulary.txt"

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

    def __write_keywords(self, keywords: list[str]) -> None:
        """Write the pooled keyword input file.

        :param keywords: The keywords, one per line.
        :return: None.
        """
        self.__keywords_txt.write_text(
            "".join(f"{x}\n" for x in keywords), encoding="utf-8")

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
            str(self.__keywords_txt), str(self.__groups_csv),
            str(self.__vocabulary_txt)]
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

    def __read_groups(self) -> list[list[str]]:
        """Read the group membership CSV file.

        :return: All rows, including the header row, in file
            order.
        """
        with open(self.__groups_csv, encoding="utf-8",
                  newline="") as file:
            return list(csv.reader(file))

    def __read_vocabulary(self) -> list[str]:
        """Read the vocabulary text file.

        :return: The group names, one per line, with the trailing
            empty line from the final newline removed.
        """
        lines: list[str] = self.__vocabulary_txt.read_text(
            encoding="utf-8").split("\n")
        self.assertEqual(lines[-1], "")
        return lines[:-1]

    def test_groups_csv_header_and_ordering(self) -> None:
        """Test the header row and the group/keyword ordering of
        the group membership CSV file."""
        self.__write_keywords([
            "a-left", "a-center", "a-right",
            "b-north", "b-middle", "b-south"])
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
        self.__write_keywords(keywords)
        status: int
        status, _ = self.__run_cluster()
        self.assertEqual(status, 0)
        rows: list[list[str]] = self.__read_groups()[1:]
        self.assertEqual(
            sorted(x[1] for x in rows), sorted(keywords))

    def test_vocabulary_file_sorted_medoids(self) -> None:
        """Test that the vocabulary file holds the sorted medoid
        group names."""
        self.__write_keywords([
            "a-left", "a-center", "a-right",
            "b-north", "b-middle", "b-south"])
        status: int
        status, _ = self.__run_cluster()
        self.assertEqual(status, 0)
        self.assertEqual(
            self.__read_vocabulary(), ["a-center", "b-middle"])

    def test_duplicate_keyword_rejected(self) -> None:
        """Test that a duplicate keyword line fails the run
        without writing any output file."""
        self.__write_keywords(["shared", "shared"])
        status: int
        stderr: str
        status, stderr = self.__run_cluster()
        self.assertEqual(status, 1)
        self.assertIn("duplicate keyword", stderr)
        self.assertFalse(self.__groups_csv.exists())
        self.assertFalse(self.__vocabulary_txt.exists())

    def test_empty_input_rejected(self) -> None:
        """Test that an empty keyword file fails the run without
        writing any output file."""
        self.__keywords_txt.write_text("", encoding="utf-8")
        status: int
        stderr: str
        status, stderr = self.__run_cluster()
        self.assertEqual(status, 1)
        self.assertIn("no keywords", stderr)
        self.assertFalse(self.__groups_csv.exists())
        self.assertFalse(self.__vocabulary_txt.exists())
