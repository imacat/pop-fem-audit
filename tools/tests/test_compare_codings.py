# Tools for A Feminist Audit of Pop Music.
# Copyright 2026 imacat.  All rights reserved.
# Authors:
#   imacat@mail.imacat.idv.tw (imacat), 2026/8/6
"""Unit tests for the coding run comparison module."""
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from typing import Any

from pop_fem_audit_tools.commands import compare_codings


class TestCompareCodings(unittest.TestCase):
    """Test cases for the coding run comparison."""

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
        self.__disagreements_json: Path \
            = self.__output_dir \
            / compare_codings.DISAGREEMENTS_JSON

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

    def __write_codings(
            self, run_dir: Path,
            codings: dict[str, dict[str, list[str]]]) -> None:
        """Write the coding of every song of one run.

        :param run_dir: The run's archive directory.
        :param codings: The keyword assignments of every song,
            keyed by the song ID, in file order.
        :return: None.
        """
        self.__write_output(run_dir, [
            {"id": song_id, "text": json.dumps(
                coding, ensure_ascii=False),
             "stop_reason": "end_turn", "usage": {}}
            for song_id, coding in codings.items()])

    def __run_compare(self) -> tuple[int, str]:
        """Run the comparison with captured standard error.

        :return: A tuple of the exit status and the standard
            error.
        """
        argv: list[str] = [
            str(self.__run1), str(self.__run2),
            str(self.__output_dir)]
        stderr: io.StringIO = io.StringIO()
        with redirect_stderr(stderr):
            status: int = compare_codings.main(argv)
        return status, stderr.getvalue()

    def __read_disagreements(self) -> dict[str, Any]:
        """Read the disagreement JSON file.

        :return: The parsed disagreements, as written, with every
            song's keywords in its "disagreements" wrapper.
        """
        return json.loads(
            self.__disagreements_json.read_text(encoding="utf-8"))

    def __read_keywords(self, song_id: str) -> dict[str, Any]:
        """Read one song's disagreed keywords from the file.

        :param song_id: The song ID.
        :return: The keywords of that song, unwrapped.
        """
        return self.__read_disagreements()[song_id]["disagreements"]

    def __read_disagreement_text(self) -> str:
        """Read the disagreement JSON file verbatim.

        :return: The file content, as written.
        """
        return self.__disagreements_json.read_text(
            encoding="utf-8")

    def test_keyword_in_one_run_only_disagrees(self) -> None:
        """Test that a keyword assigned by exactly one run is a
        disagreement carrying that run's quotes."""
        self.__write_codings(self.__run1, {
            "song-1": {"shared": ["q1"], "only-1": ["q2"]}})
        self.__write_codings(self.__run2, {
            "song-1": {"shared": ["q3"], "only-2": ["q4"]}})
        status: int
        status, _ = self.__run_compare()
        self.assertEqual(status, 0)
        self.assertEqual(self.__read_disagreements(), {
            "song-1": {"disagreements": {
                "only-1": ["q2"], "only-2": ["q4"]}}})

    def test_keywords_wrapped_for_merging(self) -> None:
        """Test that each song's value is the object merged into
        the arbitration input, holding "disagreements" alone."""
        self.__write_codings(self.__run1, {
            "song-1": {"only-1": ["q"]}})
        self.__write_codings(self.__run2, {"song-1": {}})
        status: int
        status, _ = self.__run_compare()
        self.assertEqual(status, 0)
        self.assertEqual(
            list(self.__read_disagreements()["song-1"].keys()),
            ["disagreements"])
        self.assertEqual(
            self.__read_keywords("song-1"), {"only-1": ["q"]})

    def test_quotes_do_not_take_part_in_comparison(self) -> None:
        """Test that identical key sets with different quotes
        yield no disagreement at all."""
        self.__write_codings(self.__run1, {
            "song-1": {"shared": ["one quote"]}})
        self.__write_codings(self.__run2, {
            "song-1": {"shared": ["another", "quote"]}})
        status: int
        stderr: str
        status, stderr = self.__run_compare()
        self.assertEqual(status, 0)
        self.assertEqual(self.__read_disagreements(), {})
        self.assertIn("0 of 1 songs disagree on 0 keywords.",
                      stderr)

    def test_agreeing_songs_omitted(self) -> None:
        """Test that only the songs with at least one
        disagreement are written."""
        self.__write_codings(self.__run1, {
            "song-1": {"shared": ["q"]},
            "song-2": {"shared": ["q"], "only-1": ["q"]}})
        self.__write_codings(self.__run2, {
            "song-1": {"shared": ["q"]},
            "song-2": {"shared": ["q"]}})
        status: int
        status, _ = self.__run_compare()
        self.assertEqual(status, 0)
        self.assertEqual(
            list(self.__read_disagreements().keys()), ["song-2"])

    def test_songs_in_ascending_song_number_order(self) -> None:
        """Test that the songs are ordered by ascending song
        number, not by the song ID as text."""
        self.__write_codings(self.__run1, {
            "song-10": {"only-1": ["q"]},
            "song-2": {"only-1": ["q"]},
            "song-1": {"only-1": ["q"]}})
        self.__write_codings(self.__run2, {
            "song-1": {}, "song-2": {}, "song-10": {}})
        status: int
        status, _ = self.__run_compare()
        self.assertEqual(status, 0)
        self.assertEqual(
            list(self.__read_disagreements().keys()),
            ["song-1", "song-2", "song-10"])

    def test_keywords_in_lexicographic_order(self) -> None:
        """Test that a song's disagreed keywords are ordered
        lexicographically, whichever run assigned them."""
        self.__write_codings(self.__run1, {
            "song-1": {"zeta": ["q"], "alpha": ["q"]}})
        self.__write_codings(self.__run2, {
            "song-1": {"mu": ["q"], "beta": ["q"]}})
        status: int
        status, _ = self.__run_compare()
        self.assertEqual(status, 0)
        self.assertEqual(
            list(self.__read_keywords("song-1").keys()),
            ["alpha", "beta", "mu", "zeta"])

    def test_summary_line_counts(self) -> None:
        """Test the closing summary line's song and keyword
        counts."""
        self.__write_codings(self.__run1, {
            "song-1": {"only-1": ["q"], "also-1": ["q"]},
            "song-2": {"shared": ["q"]},
            "song-3": {}})
        self.__write_codings(self.__run2, {
            "song-1": {},
            "song-2": {"shared": ["q"]},
            "song-3": {"only-2": ["q"]}})
        status: int
        stderr: str
        status, stderr = self.__run_compare()
        self.assertEqual(status, 0)
        self.assertIn("Done.  2 of 3 songs disagree on 3"
                      " keywords.", stderr)
        self.assertIn("elapsed.", stderr)

    def test_control_character_in_quote_kept(self) -> None:
        """Test that a quote holding a line-separating control
        character neither truncates the record nor is lost."""
        quote: str = "first line\u0085second line"
        self.__write_codings(self.__run1, {
            "song-1": {"only-1": [quote]}})
        self.__write_codings(self.__run2, {"song-1": {}})
        status: int
        status, _ = self.__run_compare()
        self.assertEqual(status, 0)
        self.assertEqual(
            self.__read_keywords("song-1"), {"only-1": [quote]})

    def test_non_ascii_written_verbatim(self) -> None:
        """Test that the output is UTF-8 with the non-ASCII text
        unescaped, indented by two spaces, and newline
        terminated."""
        self.__write_codings(self.__run1, {
            "song-1": {"only-1": ["女性力量"]}})
        self.__write_codings(self.__run2, {"song-1": {}})
        status: int
        status, _ = self.__run_compare()
        self.assertEqual(status, 0)
        text: str = self.__read_disagreement_text()
        self.assertIn("女性力量", text)
        self.assertIn("\n  \"song-1\": {", text)
        self.assertTrue(text.endswith("}\n"))

    def test_existing_output_dir_reused(self) -> None:
        """Test that an already-existing output directory is
        written into rather than rejected."""
        self.__output_dir.mkdir(parents=True)
        (self.__output_dir / "keep.txt").write_text(
            "kept", encoding="utf-8")
        self.__write_codings(self.__run1, {
            "song-1": {"only-1": ["q"]}})
        self.__write_codings(self.__run2, {"song-1": {}})
        status: int
        status, _ = self.__run_compare()
        self.assertEqual(status, 0)
        self.assertTrue(self.__disagreements_json.exists())
        self.assertEqual(
            (self.__output_dir / "keep.txt").read_text(
                encoding="utf-8"),
            "kept")

    def test_mismatched_song_sets_rejected(self) -> None:
        """Test that runs covering different songs fail without
        writing the disagreement file."""
        self.__write_codings(self.__run1, {
            "song-1": {"only-1": ["q"]}})
        self.__write_codings(self.__run2, {
            "song-2": {"only-2": ["q"]}})
        status: int
        stderr: str
        status, stderr = self.__run_compare()
        self.assertEqual(status, 1)
        self.assertIn("song-1", stderr)
        self.assertIn("song-2", stderr)
        self.assertFalse(self.__disagreements_json.exists())

    def test_extra_song_in_one_run_rejected(self) -> None:
        """Test that one run covering an extra song fails."""
        self.__write_codings(self.__run1, {
            "song-1": {}, "song-2": {}})
        self.__write_codings(self.__run2, {"song-1": {}})
        status: int
        stderr: str
        status, stderr = self.__run_compare()
        self.assertEqual(status, 1)
        self.assertIn("song-2", stderr)
        self.assertFalse(self.__disagreements_json.exists())

    def test_non_object_text_rejected(self) -> None:
        """Test that a "text" field parsing to something other
        than a JSON object fails the run."""
        self.__write_output(self.__run1, [
            {"id": "song-1", "text": json.dumps(["only-1"])}])
        self.__write_codings(self.__run2, {"song-1": {}})
        status: int
        stderr: str
        status, stderr = self.__run_compare()
        self.assertEqual(status, 1)
        self.assertIn("song-1", stderr)
        self.assertFalse(self.__disagreements_json.exists())

    def test_unparsable_text_rejected(self) -> None:
        """Test that a "text" field that is not JSON at all, such
        as a refusal, fails the run."""
        self.__write_output(self.__run1, [
            {"id": "song-1", "text": "I cannot help with that."}])
        self.__write_codings(self.__run2, {"song-1": {}})
        status: int
        stderr: str
        status, stderr = self.__run_compare()
        self.assertEqual(status, 1)
        self.assertIn("song-1", stderr)
        self.assertFalse(self.__disagreements_json.exists())

    def test_duplicate_keyword_in_text_rejected(self) -> None:
        """Test that a "text" JSON object with a duplicate keyword
        fails the run."""
        self.__write_output(self.__run1, [
            {"id": "song-1",
             "text": '{"only-1": ["q"], "only-1": ["r"]}'}])
        self.__write_codings(self.__run2, {"song-1": {}})
        status: int
        stderr: str
        status, stderr = self.__run_compare()
        self.assertEqual(status, 1)
        self.assertIn("duplicate key", stderr)
        self.assertFalse(self.__disagreements_json.exists())

    def test_duplicate_key_in_envelope_rejected(self) -> None:
        """Test that an envelope record with a duplicate key fails
        the run."""
        (self.__run1 / "output.jsonl").write_text(
            '{"id": "song-1", "id": "song-2", "text": "{}"}\n',
            encoding="utf-8")
        self.__write_codings(self.__run2, {"song-1": {}})
        status: int
        stderr: str
        status, stderr = self.__run_compare()
        self.assertEqual(status, 1)
        self.assertIn("duplicate key", stderr)
        self.assertFalse(self.__disagreements_json.exists())

    def test_duplicate_song_id_rejected(self) -> None:
        """Test that the same song ID appearing twice in one run
        fails the run."""
        self.__write_output(self.__run1, [
            {"id": "song-1", "text": "{}"},
            {"id": "song-1", "text": "{}"}])
        self.__write_codings(self.__run2, {"song-1": {}})
        status: int
        stderr: str
        status, stderr = self.__run_compare()
        self.assertEqual(status, 1)
        self.assertIn("duplicate song ID", stderr)
        self.assertFalse(self.__disagreements_json.exists())

    def test_malformed_song_id_rejected(self) -> None:
        """Test that a song ID not in the ``song-<N>`` form fails
        the run."""
        self.__write_output(self.__run1, [
            {"id": "track-1", "text": "{}"}])
        self.__write_codings(self.__run2, {"song-1": {}})
        status: int
        stderr: str
        status, stderr = self.__run_compare()
        self.assertEqual(status, 1)
        self.assertIn("track-1", stderr)
        self.assertFalse(self.__disagreements_json.exists())

    def test_missing_output_file_reported(self) -> None:
        """Test that a run directory without ``output.jsonl``
        fails with the path in the message."""
        self.__write_codings(self.__run2, {"song-1": {}})
        status: int
        stderr: str
        status, stderr = self.__run_compare()
        self.assertEqual(status, 1)
        self.assertIn("output.jsonl", stderr)
        self.assertFalse(self.__disagreements_json.exists())

    def test_blank_lines_skipped(self) -> None:
        """Test that blank lines in ``output.jsonl`` are
        ignored."""
        (self.__run1 / "output.jsonl").write_text(
            '\n{"id": "song-1", "text": "{\\"only-1\\": [\\"q\\"]}"}'
            "\n\n",
            encoding="utf-8")
        self.__write_codings(self.__run2, {"song-1": {}})
        status: int
        status, _ = self.__run_compare()
        self.assertEqual(status, 0)
        self.assertEqual(
            self.__read_keywords("song-1"), {"only-1": ["q"]})

    def test_compare_returns_agreed_keyword_names(self) -> None:
        """Test that the comparison function returns the agreed
        keyword names alone, sorted, without their quotes."""
        codings1: dict[str, dict[str, list[str]]] = {
            "song-1": {"zeta": ["a", "b"], "alpha": ["c"],
                       "only-1": ["d"]}}
        codings2: dict[str, dict[str, list[str]]] = {
            "song-1": {"zeta": ["b", "e"], "alpha": ["f"]}}
        agreed: dict[str, list[str]]
        disagreed: dict[str, dict[str, list[str]]]
        agreed, disagreed = compare_codings.compare_codings(
            codings1, codings2)
        self.assertEqual(agreed, {"song-1": ["alpha", "zeta"]})
        self.assertEqual(
            disagreed, {"song-1": {"only-1": ["d"]}})

    def test_compare_omits_songs_without_agreement(self) -> None:
        """Test that a song with no agreed keyword has no entry in
        the agreed half."""
        agreed: dict[str, list[str]]
        agreed = compare_codings.compare_codings(
            {"song-1": {"only-1": ["q"]}, "song-2": {"both": ["q"]}},
            {"song-1": {}, "song-2": {"both": ["q"]}})[0]
        self.assertEqual(list(agreed.keys()), ["song-2"])

    def test_compare_rejects_different_song_sets(self) -> None:
        """Test that the comparison function rejects runs that do
        not cover the same songs."""
        with self.assertRaises(ValueError):
            compare_codings.compare_codings(
                {"song-1": {}}, {"song-2": {}})
