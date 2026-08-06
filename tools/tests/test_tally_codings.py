# Tools for A Feminist Audit of Pop Music.
# Copyright 2026 imacat.  All rights reserved.
# Authors:
#   imacat@mail.imacat.idv.tw (imacat), 2026/8/6
"""Unit tests for the coding tally module."""
import csv
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from typing import Any
from unittest import mock

from sqlalchemy.orm import Session

from pop_fem_audit_tools import config
from pop_fem_audit_tools.commands import tally_codings
from pop_fem_audit_tools.database import Base, DataSource
from pop_fem_audit_tools.models import Song


class TestTallyCodings(unittest.TestCase):
    """Test cases for the coding tally."""

    def setUp(self) -> None:
        """Create the run directories and a temporary store."""
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
        self.__output_csv: Path \
            = self.__dir / "results" / "codings.csv"
        url: str = f"sqlite:///{self.__dir}/store.sqlite3"
        config.set_settings(config.Settings(
            SQLALCHEMY_DATABASE_URL=url,
            ANTHROPIC_API_KEY="test-key"))
        self.__ds: DataSource = DataSource()
        patcher: Any = mock.patch.object(
            tally_codings, "ds", self.__ds)
        patcher.start()
        self.addCleanup(patcher.stop)

    def __seed(self, songs: list[tuple[str, str]]) -> None:
        """Create the schema and the fixture songs.

        The song IDs are assigned in list order starting from 1.

        :param songs: The (title, artist credit) pairs.
        :return: None.
        """
        Base.metadata.create_all(self.__ds.engine)
        session: Session = self.__ds.get_db()
        try:
            title: str
            artist_credit: str
            for title, artist_credit in songs:
                session.add(Song(
                    title=title, artist_credit=artist_credit,
                    lyrics="la la la"))
            session.commit()
        finally:
            session.close()

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
    def __record(song_id: int,
                 keywords: dict[str, list[str]]) -> dict[str, Any]:
        """Build one successful coding output record.

        :param song_id: The numeric part of the song ID.
        :param keywords: The lyric quotes of every assigned
            keyword.
        :return: The envelope record.
        """
        return {
            "id": f"song-{song_id}",
            "text": json.dumps(keywords, ensure_ascii=False),
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 1, "output_tokens": 1}}

    def __write_codings(
            self,
            runs: list[dict[int, dict[str, list[str]]]]) -> None:
        """Write the three runs' output files.

        :param runs: The assigned keywords and their quotes of
            every song, per run, in run order.
        :return: None.
        """
        index: int
        songs: dict[int, dict[str, list[str]]]
        for index, songs in enumerate(runs):
            self.__write_output(self.__runs[index], [
                self.__record(x, songs[x]) for x in songs])

    def __run_tally(self) -> tuple[int, str]:
        """Run the tally over the three run directories.

        :return: A tuple of the exit status and the standard
            error.
        """
        argv: list[str] = [
            *(str(x) for x in self.__runs), str(self.__output_csv)]
        stderr: io.StringIO = io.StringIO()
        with redirect_stderr(stderr):
            status: int = tally_codings.main(argv)
        return status, stderr.getvalue()

    def __read_rows(self) -> list[list[str]]:
        """Read the coding table CSV file.

        :return: All rows, including the header row, in file
            order.
        """
        with open(self.__output_csv, encoding="utf-8",
                  newline="") as file:
            return list(csv.reader(file))

    def test_majority_of_three_settles_the_code(self) -> None:
        """Test that a keyword three or two runs assign is written
        out, and one a single run assigns is not."""
        self.__seed([("Alpha", "A Singer")])
        self.__write_codings([
            {1: {"all-three": ["q"], "two-of-three": ["q"],
                 "only-first": ["q"]}},
            {1: {"all-three": ["q"], "two-of-three": ["q"]}},
            {1: {"all-three": ["q"], "only-third": ["q"]}},
        ])
        status: int
        status, _ = self.__run_tally()
        self.assertEqual(status, 0)
        rows: list[list[str]] = self.__read_rows()
        self.assertEqual(rows, [
            ["Song", "Artist Credit", "Keyword", "Quote"],
            ["Alpha", "A Singer", "all-three", "q"],
            ["Alpha", "A Singer", "two-of-three", "q"],
        ])

    def test_quotes_do_not_take_part_in_the_tally(self) -> None:
        """Test that only the keyword keys are tallied, however
        the quotes differ between the runs."""
        self.__seed([("Alpha", "A Singer")])
        self.__write_codings([
            {1: {"shared": ["one quote"]}},
            {1: {"shared": ["a wholly different quote", "and"]}},
            {1: {"shared": []}},
        ])
        status: int
        status, _ = self.__run_tally()
        self.assertEqual(status, 0)
        self.assertEqual(self.__read_rows()[1:], [
            ["Alpha", "A Singer", "shared",
             "a wholly different quote|and|one quote"]])

    def test_identical_quotes_collapse_to_one(self) -> None:
        """Test that the one quote all three runs give is written
        once."""
        self.__seed([("Alpha", "A Singer")])
        codings: dict[int, dict[str, list[str]]] \
            = {1: {"kw": ["the same line"]}}
        self.__write_codings([codings, codings, codings])
        status: int
        status, _ = self.__run_tally()
        self.assertEqual(status, 0)
        self.assertEqual(self.__read_rows()[1:], [
            ["Alpha", "A Singer", "kw", "the same line"]])

    def test_distinct_quotes_joined_in_code_point_order(self) -> None:
        """Test that the distinct quotes of the runs that assigned
        the keyword are joined with a single "|" in Unicode code
        point order, whichever run gave which."""
        self.__seed([("Alpha", "A Singer")])
        self.__write_codings([
            {1: {"kw": ["zebra line", "middle line"]}},
            {1: {"kw": ["apple line", "middle line"]}},
            {1: {"kw": ["zebra line"]}},
        ])
        status: int
        status, _ = self.__run_tally()
        self.assertEqual(status, 0)
        self.assertEqual(self.__read_rows()[1:], [
            ["Alpha", "A Singer", "kw",
             "apple line|middle line|zebra line"]])

    def test_quote_with_comma_and_double_quote(self) -> None:
        """Test that a quote holding a comma and a double quote is
        escaped per RFC 4180 and reads back unchanged."""
        quote: str = "she said \"no\", twice"
        self.__seed([("Alpha", "A Singer")])
        codings: dict[int, dict[str, list[str]]] \
            = {1: {"kw": [quote]}}
        self.__write_codings([codings, codings, codings])
        status: int
        status, _ = self.__run_tally()
        self.assertEqual(status, 0)
        self.assertEqual(self.__read_rows()[1:], [
            ["Alpha", "A Singer", "kw", quote]])
        self.assertEqual(
            self.__output_csv.read_bytes(),
            b"Song,Artist Credit,Keyword,Quote\r\n"
            b"Alpha,A Singer,kw,"
            b"\"she said \"\"no\"\", twice\"\r\n")

    def test_empty_quote_lists_yield_an_empty_cell(self) -> None:
        """Test that a settled keyword whose runs all gave an empty
        quote list carries an empty quote cell."""
        self.__seed([("Alpha", "A Singer")])
        codings: dict[int, dict[str, list[str]]] = {1: {"kw": []}}
        self.__write_codings([codings, codings, codings])
        status: int
        status, _ = self.__run_tally()
        self.assertEqual(status, 0)
        self.assertEqual(self.__read_rows()[1:], [
            ["Alpha", "A Singer", "kw", ""]])

    def test_non_list_quotes_rejected(self) -> None:
        """Test that a keyword whose quotes are not a list of
        strings fails the run without writing the CSV file."""
        self.__seed([("Alpha", "A Singer")])
        self.__write_codings([
            {1: {"kw": ["q"]}}, {1: {"kw": ["q"]}},
            {1: {"kw": ["q"]}},
        ])
        self.__write_output(self.__runs[0], [
            {"id": "song-1", "text": json.dumps({"kw": "q"}),
             "stop_reason": "end_turn", "usage": {}}])
        status: int
        stderr: str
        status, stderr = self.__run_tally()
        self.assertEqual(status, 1)
        self.assertIn("not a list of strings", stderr)
        self.assertFalse(self.__output_csv.exists())

    def test_song_named_from_the_working_store(self) -> None:
        """Test that the song is written as its title and its
        stored artist credit, and the song ID never appears."""
        self.__seed([("Alpha", "A Singer feat. B Singer")])
        self.__write_codings([
            {1: {"kw": ["q"]}}, {1: {"kw": ["q"]}},
            {1: {"kw": ["q"]}},
        ])
        status: int
        status, _ = self.__run_tally()
        self.assertEqual(status, 0)
        self.assertEqual(self.__read_rows()[1:], [
            ["Alpha", "A Singer feat. B Singer", "kw", "q"]])
        text: str = self.__output_csv.read_text(encoding="utf-8")
        self.assertNotIn("song-1", text)

    def test_rows_ordered_by_the_printed_columns(self) -> None:
        """Test that the rows are ordered by song title, then
        artist credit, then keyword, by Unicode code point, not by
        the song ID."""
        self.__seed([
            ("Zulu", "Z Singer"),
            ("Alpha", "B Singer"),
            ("Alpha", "A Singer"),
        ])
        codings: dict[int, dict[str, list[str]]] = {
            1: {"beta": ["q"], "alpha": ["q"]},
            2: {"gamma": ["q"]},
            3: {"delta": ["q"]},
        }
        self.__write_codings([codings, codings, codings])
        status: int
        status, _ = self.__run_tally()
        self.assertEqual(status, 0)
        self.assertEqual(self.__read_rows()[1:], [
            ["Alpha", "A Singer", "delta", "q"],
            ["Alpha", "B Singer", "gamma", "q"],
            ["Zulu", "Z Singer", "alpha", "q"],
            ["Zulu", "Z Singer", "beta", "q"],
        ])

    def test_csv_uses_crlf_line_endings(self) -> None:
        """Test that the CSV file uses CRLF line endings and
        quotes a value holding a comma."""
        self.__seed([("Alpha, Reprise", "A Singer")])
        self.__write_codings([
            {1: {"kw": ["q"]}}, {1: {"kw": ["q"]}},
            {1: {"kw": ["q"]}},
        ])
        status: int
        status, _ = self.__run_tally()
        self.assertEqual(status, 0)
        data: bytes = self.__output_csv.read_bytes()
        self.assertEqual(
            data,
            b"Song,Artist Credit,Keyword,Quote\r\n"
            b"\"Alpha, Reprise\",A Singer,kw,q\r\n")

    def test_summary_line(self) -> None:
        """Test the closing summary line."""
        self.__seed([("Alpha", "A Singer"), ("Beta", "B Singer")])
        codings: dict[int, dict[str, list[str]]] = {
            1: {"kw": ["q"], "kw2": ["q"]}, 2: {"kw": ["q"]}}
        self.__write_codings([codings, codings, codings])
        status: int
        stderr: str
        status, stderr = self.__run_tally()
        self.assertEqual(status, 0)
        self.assertIn(
            "Done.  Tallied 3 codes across 2 songs.", stderr)

    def test_song_without_settled_code_still_counted(self) -> None:
        """Test that a song no two runs agree on writes no row but
        still counts as a covered song."""
        self.__seed([("Alpha", "A Singer")])
        self.__write_codings([
            {1: {"one": ["q"]}}, {1: {"two": ["q"]}},
            {1: {"three": ["q"]}},
        ])
        status: int
        stderr: str
        status, stderr = self.__run_tally()
        self.assertEqual(status, 0)
        self.assertEqual(self.__read_rows(), [
            ["Song", "Artist Credit", "Keyword", "Quote"]])
        self.assertIn(
            "Done.  Tallied 0 codes across 1 songs.", stderr)

    def test_control_character_in_quote_does_not_truncate(
            self) -> None:
        """Test that a quote holding U+0085, which the generic
        line splitting would break the record on, is read whole."""
        self.__seed([("Alpha", "A Singer")])
        quote: str = "a line\u0085another line"
        codings: dict[int, dict[str, list[str]]] \
            = {1: {"kw": [quote]}}
        self.__write_codings([codings, codings, codings])
        raw: str = (self.__runs[0] / "output.jsonl").read_text(
            encoding="utf-8")
        self.assertIn("\u0085", raw)
        lines: list[str] = raw.split("\n")[:-1]
        self.assertEqual(len(lines), 1)
        self.assertGreater(len(raw.splitlines()), len(lines))
        status: int
        status, _ = self.__run_tally()
        self.assertEqual(status, 0)
        self.assertEqual(self.__read_rows()[1:], [
            ["Alpha", "A Singer", "kw", quote]])

    def test_different_song_sets_rejected(self) -> None:
        """Test that archives covering different songs fail the
        run without writing the CSV file."""
        self.__seed([("Alpha", "A Singer"), ("Beta", "B Singer")])
        self.__write_codings([
            {1: {"kw": ["q"]}, 2: {"kw": ["q"]}},
            {1: {"kw": ["q"]}, 2: {"kw": ["q"]}},
            {1: {"kw": ["q"]}},
        ])
        status: int
        stderr: str
        status, stderr = self.__run_tally()
        self.assertEqual(status, 1)
        self.assertIn("song-2", stderr)
        self.assertFalse(self.__output_csv.exists())

    def test_failed_record_rejected(self) -> None:
        """Test that a record carrying an "error" field fails the
        run without writing the CSV file."""
        self.__seed([("Alpha", "A Singer")])
        self.__write_codings([
            {1: {"kw": ["q"]}}, {1: {"kw": ["q"]}},
            {1: {"kw": ["q"]}},
        ])
        self.__write_output(self.__runs[2], [
            {"id": "song-1", "error": "invalid_request_error"}])
        status: int
        stderr: str
        status, stderr = self.__run_tally()
        self.assertEqual(status, 1)
        self.assertIn("not a successful result", stderr)
        self.assertFalse(self.__output_csv.exists())

    def test_non_json_text_rejected(self) -> None:
        """Test that a refusal, whose "text" is not JSON, fails
        the run without writing the CSV file."""
        self.__seed([("Alpha", "A Singer")])
        self.__write_codings([
            {1: {"kw": ["q"]}}, {1: {"kw": ["q"]}},
            {1: {"kw": ["q"]}},
        ])
        self.__write_output(self.__runs[1], [
            {"id": "song-1", "text": "I cannot help with that.",
             "stop_reason": "end_turn", "usage": {}}])
        status: int
        stderr: str
        status, stderr = self.__run_tally()
        self.assertEqual(status, 1)
        self.assertIn("song-1", stderr)
        self.assertFalse(self.__output_csv.exists())

    def test_non_object_text_rejected(self) -> None:
        """Test that a "text" JSON value that is not an object
        fails the run without writing the CSV file."""
        self.__seed([("Alpha", "A Singer")])
        self.__write_codings([
            {1: {"kw": ["q"]}}, {1: {"kw": ["q"]}},
            {1: {"kw": ["q"]}},
        ])
        self.__write_output(self.__runs[0], [
            {"id": "song-1", "text": json.dumps(["kw"]),
             "stop_reason": "end_turn", "usage": {}}])
        status: int
        stderr: str
        status, stderr = self.__run_tally()
        self.assertEqual(status, 1)
        self.assertIn(
            "does not parse to a JSON object", stderr)
        self.assertFalse(self.__output_csv.exists())

    def test_duplicate_key_in_text_rejected(self) -> None:
        """Test that a "text" JSON object with a duplicate keyword
        key fails the run without writing the CSV file."""
        self.__seed([("Alpha", "A Singer")])
        self.__write_codings([
            {1: {"kw": ["q"]}}, {1: {"kw": ["q"]}},
            {1: {"kw": ["q"]}},
        ])
        self.__write_output(self.__runs[0], [
            {"id": "song-1", "text": '{"kw": ["a"], "kw": ["b"]}',
             "stop_reason": "end_turn", "usage": {}}])
        status: int
        stderr: str
        status, stderr = self.__run_tally()
        self.assertEqual(status, 1)
        self.assertIn("duplicate key", stderr)
        self.assertFalse(self.__output_csv.exists())

    def test_duplicate_song_record_rejected(self) -> None:
        """Test that two records of one song in a run fail the run
        without writing the CSV file."""
        self.__seed([("Alpha", "A Singer")])
        self.__write_codings([
            {1: {"kw": ["q"]}}, {1: {"kw": ["q"]}},
            {1: {"kw": ["q"]}},
        ])
        self.__write_output(self.__runs[1], [
            self.__record(1, {"kw": ["q"]}),
            self.__record(1, {"kw": ["q"]})])
        status: int
        stderr: str
        status, stderr = self.__run_tally()
        self.assertEqual(status, 1)
        self.assertIn("duplicate record", stderr)
        self.assertFalse(self.__output_csv.exists())

    def test_malformed_item_id_rejected(self) -> None:
        """Test that an item ID not in the ``song-<ID>`` form
        fails the run without writing the CSV file."""
        self.__seed([("Alpha", "A Singer")])
        self.__write_codings([
            {1: {"kw": ["q"]}}, {1: {"kw": ["q"]}},
            {1: {"kw": ["q"]}},
        ])
        self.__write_output(self.__runs[0], [
            {"id": "track-1", "text": json.dumps({"kw": ["q"]}),
             "stop_reason": "end_turn", "usage": {}}])
        status: int
        stderr: str
        status, stderr = self.__run_tally()
        self.assertEqual(status, 1)
        self.assertIn("song-<ID>", stderr)
        self.assertFalse(self.__output_csv.exists())

    def test_song_missing_from_the_store_rejected(self) -> None:
        """Test that a song the working store does not have fails
        the run without writing the CSV file."""
        self.__seed([("Alpha", "A Singer")])
        codings: dict[int, dict[str, list[str]]] = {
            1: {"kw": ["q"]}, 2: {"kw": ["q"]}}
        self.__write_codings([codings, codings, codings])
        status: int
        stderr: str
        status, stderr = self.__run_tally()
        self.assertEqual(status, 1)
        self.assertIn("song-2", stderr)
        self.assertIn("working store", stderr)
        self.assertFalse(self.__output_csv.exists())

    def test_missing_output_file_rejected(self) -> None:
        """Test that a run archive without ``output.jsonl`` fails
        the run without writing the CSV file."""
        self.__seed([("Alpha", "A Singer")])
        self.__write_codings([
            {1: {"kw": ["q"]}}, {1: {"kw": ["q"]}},
            {1: {"kw": ["q"]}},
        ])
        (self.__runs[2] / "output.jsonl").unlink()
        status: int
        stderr: str
        status, stderr = self.__run_tally()
        self.assertEqual(status, 1)
        self.assertIn("output.jsonl", stderr)
        self.assertFalse(self.__output_csv.exists())

    def test_tallier_writes_nothing(self) -> None:
        """Test that the tallier alone settles the codes and
        writes no file."""
        self.__write_codings([
            {1: {"kw": ["q"], "solo": ["q"]}},
            {1: {"kw": ["q"]}}, {1: {"kw": ["q"]}},
        ])
        codings: tally_codings.TalliedCodings \
            = tally_codings.CodingTallier(*self.__runs).run()
        self.assertEqual(codings.codings, {1: {"kw": "q"}})
        self.assertEqual(codings.song_count, 1)
        self.assertFalse(self.__output_csv.exists())

    def test_builder_failure_raises_tally_error(self) -> None:
        """Test that the table builder reports its own failure as
        a ``TallyError``, writing no file."""
        self.__seed([("Alpha", "A Singer")])
        codings: tally_codings.TalliedCodings \
            = tally_codings.TalliedCodings(
                codings={9: {"kw": "q"}})
        with self.assertRaises(tally_codings.TallyError) as context:
            tally_codings.CodingTableBuilder(
                codings, self.__output_csv).run()
        self.assertIn("song-9", str(context.exception))
        self.assertFalse(self.__output_csv.exists())
