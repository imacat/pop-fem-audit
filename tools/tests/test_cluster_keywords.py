# Tools for A Feminist Audit of Pop Music.
# Copyright 2026 imacat.  All rights reserved.
# Authors:
#   imacat@mail.imacat.idv.tw (imacat), 2026/8/5
"""Unit tests for the keyword clusterer module."""
import argparse
import csv
import io
import json
import tempfile
import unittest
from contextlib import ExitStack, redirect_stderr
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
            / cluster_keywords.PooledKeywords.SOURCE_KEYWORDS_TXT
        self.__result_keywords_txt: Path \
            = self.__output_dir \
            / cluster_keywords.KeywordGroups.RESULT_KEYWORDS_TXT
        self.__result_groups_csv: Path \
            = self.__output_dir \
            / cluster_keywords.KeywordGroups.RESULT_GROUPS_CSV
        self.__keywords_to_merge_json: Path \
            = self.__output_dir \
            / cluster_keywords.KeywordsToMerge \
            .KEYWORDS_TO_MERGE_JSON
        self.__meta_json: Path \
            = self.__output_dir \
            / cluster_keywords.RunMeta.META_JSON

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
        """Build a test double for the clusterer's encoder.

        :param vectors: The fixed 2D embedding of every keyword
            the double may be asked to encode.
        :return: A callable with the same signature as the
            clusterer's encoder, returning the fixed embeddings in
            the requested keyword order.
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

    @staticmethod
    def __fake_versions() -> dict[str, str]:
        """Return a fixed version mapping test double.

        :return: A fixed mapping with the same keys the metadata
            builder's version collector returns.
        """
        return {
            "python": "9.9.9",
            "torch": "9.9.9",
            "transformers": "9.9.9",
            "sentence-transformers": "9.9.9",
            "scikit-learn": "9.9.9",
            "numpy": "9.9.9",
        }

    def __run_cluster(self, extra_args: list[str] | None = None,
                      vectors: Vectors | None = None,
                      clusters: str = "2",
                      ) -> tuple[int, str]:
        """Run the clusterer with a fake encoder, a fake version
        mapping, and captured standard error.

        :param extra_args: Extra command-line arguments appended
            after the three positional arguments.
        :param vectors: The fixed embedding to encode with; the
            two-cluster fixture is used when None.
        :param clusters: The ``--clusters`` option value.
        :return: A tuple of the exit status and the standard
            error.
        """
        argv: list[str] = [
            str(self.__run1), str(self.__run2),
            str(self.__output_dir), "--clusters", clusters]
        argv.extend(extra_args or [])
        stderr: io.StringIO = io.StringIO()
        with self.__fake_environment(vectors), \
                redirect_stderr(stderr):
            status: int = cluster_keywords.main(argv)
        return status, stderr.getvalue()

    def __read_meta(self) -> dict[str, Any]:
        """Read the run metadata JSON file.

        :return: The parsed metadata.
        """
        return json.loads(
            self.__meta_json.read_text(encoding="utf-8"))

    def __read_source_keywords(self) -> list[str]:
        """Read the pooled source keyword text file.

        :return: The keyword list, one keyword per line, with the
            trailing empty line from the final newline removed.
        """
        lines: list[str] = self.__source_keywords_txt.read_text(
            encoding="utf-8").split("\n")
        self.assertEqual(lines[-1], "")
        return lines[:-1]

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

        :return: The group names plus every given extra keyword,
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
            "Done.  Clustered 3 keywords into 2.", stderr)

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
            "Done.  Clustered 2 keywords into 2.", stderr)

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
            "Done.  Clustered 2 keywords into 2.", stderr)

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
        self.assertFalse(self.__result_groups_csv.exists())
        self.assertFalse(self.__result_keywords_txt.exists())
        self.assertFalse(self.__keywords_to_merge_json.exists())
        self.assertFalse(self.__meta_json.exists())

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
        self.assertFalse(self.__result_groups_csv.exists())
        self.assertFalse(self.__result_keywords_txt.exists())
        self.assertFalse(self.__keywords_to_merge_json.exists())
        self.assertFalse(self.__meta_json.exists())

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
        sorted medoid group names alone."""
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

    def test_no_extra_keyword_merge_json_equals_group_names(
            self) -> None:
        """Test that with no ``--extra-keyword`` given, the
        coding keyword set JSON file holds exactly the sorted
        medoid group names."""
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
        self.assertEqual(keywords, ["a-center", "b-middle"])
        self.assertEqual(keywords, sorted(keywords))

    def test_extra_keyword_included_in_merge_json(self) -> None:
        """Test that a single ``--extra-keyword`` is added to the
        coding keyword set JSON file, sorted with the group
        names, while the group name text file and the group
        membership CSV file hold no trace of it."""
        self.__write_output(self.__run1, [
            {"id": "song-1", "text": json.dumps(
                {"a-left": 1, "a-center": 1, "a-right": 1})},
        ])
        self.__write_output(self.__run2, [
            {"id": "song-2", "text": json.dumps(
                {"b-north": 1, "b-middle": 1, "b-south": 1})},
        ])
        status: int
        status, _ = self.__run_cluster(
            extra_args=["--extra-keyword", "zzz-extra"])
        self.assertEqual(status, 0)
        self.assertEqual(
            self.__read_keywords_to_merge(),
            ["a-center", "b-middle", "zzz-extra"])
        self.assertEqual(
            self.__read_result_keywords(),
            ["a-center", "b-middle"])
        rows: list[list[str]] = self.__read_groups()
        row: list[str]
        for row in rows:
            self.assertNotIn("zzz-extra", row)

    def test_multiple_extra_keywords_sorted_union(self) -> None:
        """Test that several ``--extra-keyword`` options are all
        added, and the whole coding keyword set is
        lexicographically sorted."""
        self.__write_output(self.__run1, [
            {"id": "song-1", "text": json.dumps(
                {"a-left": 1, "a-center": 1, "a-right": 1})},
        ])
        self.__write_output(self.__run2, [
            {"id": "song-2", "text": json.dumps(
                {"b-north": 1, "b-middle": 1, "b-south": 1})},
        ])
        status: int
        status, _ = self.__run_cluster(extra_args=[
            "--extra-keyword", "zzz-extra",
            "--extra-keyword", "aaa-extra"])
        self.assertEqual(status, 0)
        keywords: list[str] = self.__read_keywords_to_merge()
        self.assertEqual(
            keywords,
            ["a-center", "aaa-extra", "b-middle", "zzz-extra"])
        self.assertEqual(keywords, sorted(keywords))

    def test_duplicate_extra_keyword_rejected(self) -> None:
        """Test that repeating the same ``--extra-keyword`` value
        fails the run without writing the coding keyword set JSON
        file or the run metadata JSON file."""
        self.__write_output(self.__run1, [
            {"id": "song-1", "text": json.dumps(
                {"a-left": 1, "a-center": 1, "a-right": 1})},
        ])
        self.__write_output(self.__run2, [
            {"id": "song-2", "text": json.dumps(
                {"b-north": 1, "b-middle": 1, "b-south": 1})},
        ])
        status: int
        stderr: str
        status, stderr = self.__run_cluster(extra_args=[
            "--extra-keyword", "zzz-extra",
            "--extra-keyword", "zzz-extra"])
        self.assertEqual(status, 1)
        self.assertIn("zzz-extra", stderr)
        self.assertFalse(self.__keywords_to_merge_json.exists())
        self.assertFalse(self.__meta_json.exists())

    def test_extra_keyword_duplicating_group_name_rejected(
            self) -> None:
        """Test that an ``--extra-keyword`` matching a clustered
        group name fails the run without writing the coding
        keyword set JSON file or the run metadata JSON file."""
        self.__write_output(self.__run1, [
            {"id": "song-1", "text": json.dumps(
                {"a-left": 1, "a-center": 1, "a-right": 1})},
        ])
        self.__write_output(self.__run2, [
            {"id": "song-2", "text": json.dumps(
                {"b-north": 1, "b-middle": 1, "b-south": 1})},
        ])
        status: int
        stderr: str
        status, stderr = self.__run_cluster(
            extra_args=["--extra-keyword", "a-center"])
        self.assertEqual(status, 1)
        self.assertIn("a-center", stderr)
        self.assertFalse(self.__keywords_to_merge_json.exists())
        self.assertFalse(self.__meta_json.exists())

    def test_meta_json_records_documented_keys(self) -> None:
        """Test that the metadata JSON file records exactly the
        documented keys."""
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
        meta: dict[str, Any] = self.__read_meta()
        self.assertEqual(set(meta.keys()), {
            "script_version", "source_runs", "source_records",
            "embedding", "clustering", "extra_keywords",
            "keyword_count", "versions"})
        self.assertEqual(
            meta["script_version"], "cluster_keywords.py 1.0.0")
        self.assertEqual(
            meta["versions"], self.__fake_versions())

    def test_meta_json_source_runs_and_records(self) -> None:
        """Test that the metadata records the given run
        directories and their valid record counts."""
        self.__write_output(self.__run1, [
            {"id": "song-1", "text": json.dumps(
                {"a-left": 1, "a-center": 1, "a-right": 1})},
            {"id": "song-9", "error": "invalid_request_error"},
        ])
        self.__write_output(self.__run2, [
            {"id": "song-2", "text": json.dumps(
                {"b-north": 1, "b-middle": 1, "b-south": 1})},
        ])
        status: int
        status, _ = self.__run_cluster()
        self.assertEqual(status, 0)
        meta: dict[str, Any] = self.__read_meta()
        self.assertEqual(
            meta["source_runs"],
            [str(self.__run1), str(self.__run2)])
        self.assertEqual(meta["source_records"], [1, 1])

    def test_meta_json_clustering_and_embedding(self) -> None:
        """Test that the metadata records the given cluster count
        and the embedding model and revision."""
        self.__write_output(self.__run1, [
            {"id": "song-1", "text": json.dumps(
                {"a-left": 1, "a-center": 1, "a-right": 1})},
        ])
        self.__write_output(self.__run2, [
            {"id": "song-2", "text": json.dumps(
                {"b-north": 1, "b-middle": 1, "b-south": 1})},
        ])
        status: int
        status, _ = self.__run_cluster(extra_args=[
            "--model", "some-model", "--revision", "abc123"])
        self.assertEqual(status, 0)
        meta: dict[str, Any] = self.__read_meta()
        self.assertEqual(meta["clustering"]["clusters"], 2)
        self.assertEqual(
            meta["clustering"]["algorithm"],
            "AgglomerativeClustering")
        self.assertEqual(meta["embedding"], {
            "model": "some-model", "revision": "abc123"})

    def test_meta_json_extra_keywords_order_and_count(self) -> None:
        """Test that the metadata's ``extra_keywords`` reflects the
        given options in the given order, and ``keyword_count``
        matches the pooled keyword count."""
        self.__write_output(self.__run1, [
            {"id": "song-1", "text": json.dumps(
                {"a-left": 1, "a-center": 1, "a-right": 1})},
        ])
        self.__write_output(self.__run2, [
            {"id": "song-2", "text": json.dumps(
                {"b-north": 1, "b-middle": 1, "b-south": 1})},
        ])
        status: int
        status, _ = self.__run_cluster(extra_args=[
            "--extra-keyword", "zzz-extra",
            "--extra-keyword", "aaa-extra"])
        self.assertEqual(status, 0)
        meta: dict[str, Any] = self.__read_meta()
        self.assertEqual(
            meta["extra_keywords"], ["zzz-extra", "aaa-extra"])
        self.assertEqual(meta["keyword_count"], 6)

    def test_missing_clusters_option_rejected(self) -> None:
        """Test that omitting ``--clusters`` exits with an
        argparse error."""
        argv: list[str] = [
            str(self.__run1), str(self.__run2),
            str(self.__output_dir)]
        stderr: io.StringIO = io.StringIO()
        with redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as context:
                cluster_keywords.parse_args(argv)
        self.assertNotEqual(context.exception.code, 0)

    def test_builder_failure_raises_cluster_error(self) -> None:
        """Test that a builder reports its own failure as a
        ``ClusterError``, writing no file of its own."""
        self.__write_two_clusters()
        args: argparse.Namespace = self.__parse_args()
        self.__output_dir.mkdir()
        with self.__fake_environment():
            source: cluster_keywords.PooledKeywords \
                = cluster_keywords.KeywordPooler(
                    args.run_dir_1, args.run_dir_2,
                    self.__output_dir).run()
            groups: cluster_keywords.KeywordGroups \
                = cluster_keywords.KeywordClusterer(
                    source, args.model, args.revision,
                    args.clusters, self.__output_dir).run()
            with self.assertRaises(
                    cluster_keywords.ClusterError) as context:
                cluster_keywords.KeywordsToMergeBuilder(
                    groups, ["a-center"],
                    self.__output_dir).run()
        self.assertIn("a-center", str(context.exception))
        self.assertFalse(self.__keywords_to_merge_json.exists())

    def __write_two_clusters(self) -> None:
        """Write the two runs' outputs of the two-cluster fixture.

        :return: None.
        """
        self.__write_output(self.__run1, [
            {"id": "song-1", "text": json.dumps(
                {"a-left": 1, "a-center": 1, "a-right": 1})},
        ])
        self.__write_output(self.__run2, [
            {"id": "song-2", "text": json.dumps(
                {"b-north": 1, "b-middle": 1, "b-south": 1})},
        ])

    def __parse_args(self) -> argparse.Namespace:
        """Parse a two-cluster command line over the fixture.

        :return: The parsed arguments.
        """
        return cluster_keywords.parse_args([
            str(self.__run1), str(self.__run2),
            str(self.__output_dir), "--clusters", "2"])

    def __fake_environment(
            self, vectors: Vectors | None = None) -> ExitStack:
        """Build the fake encoder and version collector context.

        :param vectors: The fixed embedding to encode with; the
            two-cluster fixture is used when None.
        :return: A context manager patching the clusterer's
            encoder with the fixed embedding and the metadata
            builder's version collector with a fixed mapping.
        """
        fake: Any = self.__fake_encode(
            vectors if vectors is not None
            else self.__two_cluster_vectors())
        stack: ExitStack = ExitStack()
        stack.enter_context(mock.patch.object(
            cluster_keywords.KeywordClusterer,
            "_KeywordClusterer__encode", staticmethod(fake)))
        stack.enter_context(mock.patch.object(
            cluster_keywords.MetaBuilder,
            "_MetaBuilder__collect_versions",
            staticmethod(self.__fake_versions)))
        return stack
