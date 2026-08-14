# Tools for A Feminist Audit of Pop Music.
# Copyright 2026 imacat.  All rights reserved.
# Authors:
#   imacat@mail.imacat.idv.tw (imacat), 2026/8/15
# AI assistance: Claude Code (Anthropic)
"""Unit tests for the group tally module."""
import csv
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

from pop_fem_audit_tools.commands import tally_groups


class TestTallyGroups(unittest.TestCase):
    """Test cases for the group tally."""

    def setUp(self) -> None:
        """Create the run directories and the input files."""
        tmp: tempfile.TemporaryDirectory[str] \
            = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.__dir: Path = Path(tmp.name)
        self.__runs: list[Path] = []
        number: int
        for number in (1, 2, 3):
            run_dir: Path = self.__dir / f"run{number}"
            run_dir.mkdir()
            self.__runs.append(run_dir)
        self.__valid: Path = self.__dir / "valid-keywords.txt"
        self.__valid.write_text(
            "alpha\nbeta\ngamma\ndelta\n", encoding="utf-8")
        self.__output_csv: Path \
            = self.__dir / "results" / "groups.csv"

    def __write_runs(
            self, runs: list[dict[str, list[str]]]) -> None:
        """Write the three runs' output.jsonl files.

        :param runs: The selections of each run, keyed by the
            group record ID.
        :return: None.
        """
        run_dir: Path
        selections: dict[str, list[str]]
        for run_dir, selections in zip(self.__runs, runs):
            lines: list[str] = [
                json.dumps({"id": x, "text": json.dumps(y),
                            "stop_reason": "end_turn"})
                for x, y in selections.items()]
            (run_dir / "output.jsonl").write_text(
                "\n".join(lines) + "\n", encoding="utf-8")

    def __run_tally(self) -> tuple[int, str]:
        """Run the tally command against the run directories.

        :return: The exit status and the standard error text.
        """
        stderr: io.StringIO = io.StringIO()
        status: int
        with redirect_stderr(stderr):
            status = tally_groups.main(
                [str(x) for x in self.__runs]
                + [str(self.__valid), str(self.__output_csv)])
        return status, stderr.getvalue()

    def __read_rows(self) -> list[list[str]]:
        """Read the written CSV file back as rows.

        :return: The rows, the header row included.
        """
        with open(self.__output_csv, encoding="utf-8",
                  newline="") as file:
            return list(csv.reader(file))

    def test_majority_vote_settles_two_of_three(self) -> None:
        """Test that a pair needs at least two votes to settle."""
        self.__write_runs([
            {"group-one": ["alpha", "beta", "gamma"]},
            {"group-one": ["alpha", "beta"]},
            {"group-one": ["alpha"]}])
        status: int
        status, _ = self.__run_tally()
        self.assertEqual(status, 0)
        self.assertEqual(self.__read_rows(), [
            ["Group", "Keyword", "Votes"],
            ["one", "alpha", "3"],
            ["one", "beta", "2"]])

    def test_rows_sorted_by_group_then_keyword(self) -> None:
        """Test the row order: group name, then keyword, by
        Unicode code point."""
        selections: dict[str, list[str]] = {
            "group-women-power": ["beta", "alpha"],
            "group-masculine": ["delta", "gamma"]}
        self.__write_runs([selections, selections, selections])
        status: int
        status, _ = self.__run_tally()
        self.assertEqual(status, 0)
        self.assertEqual(self.__read_rows(), [
            ["Group", "Keyword", "Votes"],
            ["masculine", "delta", "3"],
            ["masculine", "gamma", "3"],
            ["women-power", "alpha", "3"],
            ["women-power", "beta", "3"]])

    def test_output_is_crlf_with_header(self) -> None:
        """Test the written bytes: RFC 4180, CRLF, header row."""
        selections: dict[str, list[str]] = {"group-one": ["alpha"]}
        self.__write_runs([selections, selections, selections])
        status: int
        status, _ = self.__run_tally()
        self.assertEqual(status, 0)
        self.assertEqual(
            self.__output_csv.read_bytes(),
            b"Group,Keyword,Votes\r\n"
            b"one,alpha,3\r\n")

    def test_out_of_vocabulary_item_casts_no_vote(self) -> None:
        """Test that a selected item outside the valid keyword
        list is dropped, each occurrence reported on standard
        error."""
        selections: dict[str, list[str]] = {
            "group-one": ["alpha", "hallucinated"]}
        self.__write_runs([selections, selections, selections])
        status: int
        stderr: str
        status, stderr = self.__run_tally()
        self.assertEqual(status, 0)
        self.assertEqual(self.__read_rows(), [
            ["Group", "Keyword", "Votes"],
            ["one", "alpha", "3"]])
        self.assertEqual(stderr.count(
            "dropped out-of-vocabulary item \"hallucinated\""), 3)

    def test_duplicate_selection_counts_once(self) -> None:
        """Test that a keyword listed twice in one run's selection
        casts one vote only."""
        self.__write_runs([
            {"group-one": ["alpha", "alpha"]},
            {"group-one": []},
            {"group-one": []}])
        status: int
        status, _ = self.__run_tally()
        self.assertEqual(status, 0)
        self.assertEqual(self.__read_rows(),
                         [["Group", "Keyword", "Votes"]])

    def test_empty_selections_yield_header_only(self) -> None:
        """Test that no settled pair still writes the header."""
        selections: dict[str, list[str]] = {"group-one": []}
        self.__write_runs([selections, selections, selections])
        status: int
        status, _ = self.__run_tally()
        self.assertEqual(status, 0)
        self.assertEqual(self.__read_rows(),
                         [["Group", "Keyword", "Votes"]])

    def test_mismatched_group_sets_fail(self) -> None:
        """Test that runs covering different groups fail, nothing
        written."""
        self.__write_runs([
            {"group-one": ["alpha"]},
            {"group-one": ["alpha"]},
            {"group-two": ["alpha"]}])
        status: int
        stderr: str
        status, stderr = self.__run_tally()
        self.assertNotEqual(status, 0)
        self.assertIn("do not cover the same groups", stderr)
        self.assertFalse(self.__output_csv.exists())

    def test_id_without_the_group_prefix_fails(self) -> None:
        """Test that a record ID without the "group-" prefix
        fails the run."""
        selections: dict[str, list[str]] = {"song-1": ["alpha"]}
        self.__write_runs([selections, selections, selections])
        status: int
        stderr: str
        status, stderr = self.__run_tally()
        self.assertNotEqual(status, 0)
        self.assertIn("group-", stderr)
        self.assertFalse(self.__output_csv.exists())

    def test_duplicate_record_fails(self) -> None:
        """Test that two records of one group in one run fail the
        run."""
        selections: dict[str, list[str]] = {"group-one": ["alpha"]}
        self.__write_runs([selections, selections, selections])
        path: Path = self.__runs[0] / "output.jsonl"
        path.write_text(
            path.read_text(encoding="utf-8")
            + json.dumps({"id": "group-one",
                          "text": json.dumps(["beta"])}) + "\n",
            encoding="utf-8")
        status: int
        stderr: str
        status, stderr = self.__run_tally()
        self.assertNotEqual(status, 0)
        self.assertIn("duplicate record", stderr)

    def test_text_not_an_array_of_strings_fails(self) -> None:
        """Test that a "text" that is not a JSON array of strings
        fails the run."""
        self.__write_runs([
            {"group-one": ["alpha"]},
            {"group-one": ["alpha"]},
            {"group-one": ["alpha"]}])
        (self.__runs[2] / "output.jsonl").write_text(
            json.dumps({"id": "group-one",
                        "text": json.dumps({"alpha": []})})
            + "\n", encoding="utf-8")
        status: int
        stderr: str
        status, stderr = self.__run_tally()
        self.assertNotEqual(status, 0)
        self.assertIn("JSON array of strings", stderr)

    def test_unsuccessful_record_fails(self) -> None:
        """Test that an errored record fails the run."""
        selections: dict[str, list[str]] = {"group-one": ["alpha"]}
        self.__write_runs([selections, selections, selections])
        (self.__runs[1] / "output.jsonl").write_text(
            json.dumps({"id": "group-one", "error": "overloaded"})
            + "\n", encoding="utf-8")
        status: int
        stderr: str
        status, stderr = self.__run_tally()
        self.assertNotEqual(status, 0)
        self.assertIn("not a successful result", stderr)

    def test_missing_valid_keywords_file_fails(self) -> None:
        """Test that a missing valid keyword list fails the run."""
        selections: dict[str, list[str]] = {"group-one": ["alpha"]}
        self.__write_runs([selections, selections, selections])
        self.__valid.unlink()
        status: int
        status, _ = self.__run_tally()
        self.assertNotEqual(status, 0)
        self.assertFalse(self.__output_csv.exists())
