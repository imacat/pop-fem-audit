# Tools for A Feminist Audit of Pop Music.
# Copyright 2026 imacat.  All rights reserved.
# Authors:
#   imacat@mail.imacat.idv.tw (imacat), 2026/8/15
# AI assistance: Claude Code (Anthropic)
"""Unit tests for the step-5 annotation tally module."""
import csv
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.orm import Session

from pop_fem_audit_tools.commands import tally_annotations
from pop_fem_audit_tools.database import Base
from pop_fem_audit_tools.models import Song


class TestTallyAnnotations(unittest.TestCase):
    """Test cases for the step-5 pattern annotation tally."""

    def setUp(self) -> None:
        """Create the archive directories, the database, and the
        output paths."""
        tmp: tempfile.TemporaryDirectory[str] \
            = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.__dir: Path = Path(tmp.name)
        self.__male_synthesis: Path = self.__dir / "male-synthesis"
        self.__female_synthesis: Path \
            = self.__dir / "female-synthesis"
        self.__mixed_synthesis: Path = self.__dir / "mixed-synthesis"
        self.__male_synthesis.mkdir()
        self.__female_synthesis.mkdir()
        self.__mixed_synthesis.mkdir()
        self.__db_path: Path = self.__dir / "working.sqlite3"
        self.__patterns_csv: Path \
            = self.__dir / "results" / "patterns.csv"
        self.__annotations_csv: Path \
            = self.__dir / "results" / "annotations.csv"
        self.__runs: list[Path] = []
        number: int
        for number in (1, 2, 3):
            run_dir: Path = self.__dir / f"run{number}"
            run_dir.mkdir()
            self.__runs.append(run_dir)

    def __write_default_synthesis_archives(self) -> None:
        """Write the male, female, and mixed synthesis archives.

        The male archive holds two patterns (``M1``, ``M2``), and
        the female and mixed archives hold one pattern each
        (``F1``, ``X1``).

        :return: None.
        """
        self.__write_synthesis(self.__male_synthesis, [
            ("模式一：厭女語彙的常態化", ["描述一。"], ["「引文一」"]),
            ("模式二：陰陽權力階序", ["描述二。"], ["「引文二」"])])
        self.__write_synthesis(self.__female_synthesis, [
            ("一、女女敵對", ["描述三。"], ["「引文三」"])])
        self.__write_synthesis(self.__mixed_synthesis, [
            ("模式一：佔有語法", ["描述四。"], ["「引文四」"])])

    @staticmethod
    def __write_synthesis(
            synthesis_dir: Path,
            sections: list[tuple[str, list[str], list[str]]]) \
            -> None:
        """Write one synthesis archive's ``output.jsonl``.

        :param synthesis_dir: The synthesis run's archive
            directory.
        :param sections: Each pattern's heading text, description
            lines, and example quote lines (written with the
            ``- `` prefix).
        :return: None.
        """
        parts: list[str] = []
        heading: str
        body: list[str]
        quotes: list[str]
        for heading, body, quotes in sections:
            parts.append(f"## {heading}")
            parts.append("")
            parts.extend(body)
            parts.append("")
            parts.extend(f"- {x}" for x in quotes)
            parts.append("")
        text: str = "\n".join(parts)
        record: dict[str, str] = {
            "id": "synthesis", "text": text,
            "stop_reason": "end_turn"}
        (synthesis_dir / "output.jsonl").write_text(
            json.dumps(record, ensure_ascii=False) + "\n",
            encoding="utf-8")

    def __seed_songs(
            self,
            songs: list[tuple[int, str, str, str | None]]) -> None:
        """Create the working store schema and the fixture songs.

        :param songs: The song ID, title, artist credit, and
            stored performer gender of every fixture song.
        :return: None.
        """
        engine: sa.Engine = sa.create_engine(
            f"sqlite:///{self.__db_path}")
        Base.metadata.create_all(engine)
        session: Session
        with Session(engine) as session:
            song_id: int
            title: str
            artist_credit: str
            gender: str | None
            for song_id, title, artist_credit, gender in songs:
                session.add(Song(
                    id=song_id, title=title,
                    artist_credit=artist_credit,
                    performer_gender=gender))
            session.commit()
        engine.dispose()

    def __write_run(
            self, run_dir: Path,
            ballots: dict[int, list[str]]) -> None:
        """Write one annotation run's ``output.jsonl``.

        :param run_dir: The run's archive directory.
        :param ballots: The selected pattern IDs of every song,
            keyed by the numeric song ID.
        :return: None.
        """
        lines: list[str] = [
            json.dumps({
                "id": f"song-{song_id}",
                "text": json.dumps(pattern_ids, ensure_ascii=False),
                "stop_reason": "end_turn"}, ensure_ascii=False)
            for song_id, pattern_ids in ballots.items()]
        (run_dir / "output.jsonl").write_text(
            "\n".join(lines) + "\n", encoding="utf-8")

    def __write_same_ballots_to_all_runs(
            self, ballots: dict[int, list[str]]) -> None:
        """Write the same ballots to all three run directories.

        :param ballots: The selected pattern IDs of every song,
            keyed by the numeric song ID.
        :return: None.
        """
        run_dir: Path
        for run_dir in self.__runs:
            self.__write_run(run_dir, ballots)

    def __run_tally(self) -> tuple[int, str]:
        """Run the tally command against the fixture archives.

        :return: The exit status and the standard error text.
        """
        stderr: io.StringIO = io.StringIO()
        status: int
        with redirect_stderr(stderr):
            status = tally_annotations.main([
                str(self.__male_synthesis),
                str(self.__female_synthesis),
                str(self.__mixed_synthesis), str(self.__db_path),
                str(self.__patterns_csv),
                str(self.__annotations_csv)]
                + [str(x) for x in self.__runs])
        return status, stderr.getvalue()

    @staticmethod
    def __read_rows(path: Path) -> list[list[str]]:
        """Read a written CSV file back as rows.

        :param path: The CSV file.
        :return: The rows, the header row included.
        """
        with open(path, encoding="utf-8", newline="") as file:
            return list(csv.reader(file))

    def test_patterns_extracted_in_group_and_section_order(
            self) -> None:
        """Test that the pattern table lists the male, then
        female, then mixed patterns, in section order, the
        numbering token stripped and the example quotes
        excluded from the description."""
        self.__write_default_synthesis_archives()
        self.__seed_songs([(1, "Song A", "Artist A", "male")])
        self.__write_same_ballots_to_all_runs({1: []})
        status: int
        status, _ = self.__run_tally()
        self.assertEqual(status, 0)
        self.assertEqual(self.__read_rows(self.__patterns_csv), [
            ["Pattern", "Group", "Name", "Description"],
            ["M1", "male", "厭女語彙的常態化", "描述一。"],
            ["M2", "male", "陰陽權力階序", "描述二。"],
            ["F1", "female", "女女敵對", "描述三。"],
            ["X1", "mixed", "佔有語法", "描述四。"]])

    def test_empty_pattern_name_fails(self) -> None:
        """Test that a heading that is only a numbering token
        fails the tally, nothing written."""
        self.__write_synthesis(self.__male_synthesis, [
            ("模式一：", ["描述。"], [])])
        self.__write_synthesis(self.__female_synthesis, [
            ("一、女女敵對", ["描述。"], [])])
        self.__write_synthesis(self.__mixed_synthesis, [
            ("模式一：佔有語法", ["描述。"], [])])
        self.__seed_songs([(1, "Song A", "Artist A", "male")])
        self.__write_same_ballots_to_all_runs({1: []})
        status: int
        stderr: str
        status, stderr = self.__run_tally()
        self.assertNotEqual(status, 0)
        self.assertIn("empty name or description", stderr)
        self.assertFalse(self.__patterns_csv.exists())

    def test_empty_pattern_description_fails(self) -> None:
        """Test that a section with no description line (only
        example quotes) fails the tally, nothing written."""
        self.__write_synthesis(self.__male_synthesis, [
            ("模式一：厭女語彙", [], ["「引文」"])])
        self.__write_synthesis(self.__female_synthesis, [
            ("一、女女敵對", ["描述。"], [])])
        self.__write_synthesis(self.__mixed_synthesis, [
            ("模式一：佔有語法", ["描述。"], [])])
        self.__seed_songs([(1, "Song A", "Artist A", "male")])
        self.__write_same_ballots_to_all_runs({1: []})
        status: int
        stderr: str
        status, stderr = self.__run_tally()
        self.assertNotEqual(status, 0)
        self.assertIn("empty name or description", stderr)
        self.assertFalse(self.__patterns_csv.exists())

    def test_song_not_appearing_three_times_fails(self) -> None:
        """Test that a song missing from one run's ballots fails
        the tally."""
        self.__write_default_synthesis_archives()
        self.__seed_songs([(1, "Song A", "Artist A", "male")])
        self.__write_run(self.__runs[0], {1: ["M1"]})
        self.__write_run(self.__runs[1], {1: ["M1"]})
        self.__write_run(self.__runs[2], {})
        status: int
        stderr: str
        status, stderr = self.__run_tally()
        self.assertNotEqual(status, 0)
        self.assertIn("song-1", stderr)
        self.assertIn("expected", stderr)
        self.assertFalse(self.__annotations_csv.exists())

    def test_ballot_missing_text_field_skipped_then_fails(
            self) -> None:
        """Test that a ballot record without "text" is skipped
        with a warning, leaving the song short of the three
        ballots the completeness check requires."""
        self.__write_default_synthesis_archives()
        self.__seed_songs([(1, "Song A", "Artist A", "male")])
        self.__write_same_ballots_to_all_runs({1: ["M1"]})
        (self.__runs[0] / "output.jsonl").write_text(
            json.dumps({"id": "song-1"}) + "\n", encoding="utf-8")
        status: int
        stderr: str
        status, stderr = self.__run_tally()
        self.assertNotEqual(status, 0)
        self.assertIn("warning:", stderr)
        self.assertIn(str(self.__runs[0]), stderr)
        self.assertIn("no \"text\" field", stderr)
        self.assertIn("song-1", stderr)
        self.assertIn("expected", stderr)

    def test_ballot_text_not_array_of_strings_skipped_then_fails(
            self) -> None:
        """Test that a "text" that is not a JSON array of strings
        is skipped with a warning, leaving the song short of the
        three ballots the completeness check requires."""
        self.__write_default_synthesis_archives()
        self.__seed_songs([(1, "Song A", "Artist A", "male")])
        self.__write_same_ballots_to_all_runs({1: ["M1"]})
        (self.__runs[0] / "output.jsonl").write_text(
            json.dumps({"id": "song-1",
                       "text": json.dumps({"M1": []})}) + "\n",
            encoding="utf-8")
        status: int
        stderr: str
        status, stderr = self.__run_tally()
        self.assertNotEqual(status, 0)
        self.assertIn("warning:", stderr)
        self.assertIn(str(self.__runs[0]), stderr)
        self.assertIn("JSON array of strings", stderr)
        self.assertIn("song-1", stderr)
        self.assertIn("expected", stderr)

    def test_dead_record_rescued_from_extra_run_dir(self) -> None:
        """Test that a dead record (malformed "text") in one run
        directory is skipped with a warning, and its ballot is
        rescued from an extra run directory, tallying
        successfully."""
        self.__write_default_synthesis_archives()
        self.__seed_songs([(1, "Song A", "Artist A", "male")])
        self.__write_same_ballots_to_all_runs({1: ["M1"]})
        (self.__runs[0] / "output.jsonl").write_text(
            json.dumps({"id": "song-1",
                       "text": json.dumps({"M1": []})}) + "\n",
            encoding="utf-8")
        rescue_dir: Path = self.__dir / "rescue"
        rescue_dir.mkdir()
        self.__write_run(rescue_dir, {1: ["M1"]})
        stderr: io.StringIO = io.StringIO()
        status: int
        with redirect_stderr(stderr):
            status = tally_annotations.main([
                str(self.__male_synthesis),
                str(self.__female_synthesis),
                str(self.__mixed_synthesis), str(self.__db_path),
                str(self.__patterns_csv),
                str(self.__annotations_csv)]
                + [str(x) for x in self.__runs]
                + [str(rescue_dir)])
        self.assertEqual(status, 0)
        self.assertIn("warning:", stderr.getvalue())
        self.assertIn("JSON array of strings", stderr.getvalue())
        self.assertEqual(self.__read_rows(self.__annotations_csv), [
            ["Song", "Artist Credit", "Pattern", "Votes"],
            ["Song A", "Artist A", "M1", "3"]])

    def test_unknown_pattern_id_dropped_with_warning(self) -> None:
        """Test that a selected ID outside the extracted patterns
        is dropped, the occurrence reported on standard error."""
        self.__write_default_synthesis_archives()
        self.__seed_songs([(1, "Song A", "Artist A", "male")])
        self.__write_same_ballots_to_all_runs(
            {1: ["M1", "hallucinated"]})
        status: int
        stderr: str
        status, stderr = self.__run_tally()
        self.assertEqual(status, 0)
        self.assertEqual(self.__read_rows(self.__annotations_csv), [
            ["Song", "Artist Credit", "Pattern", "Votes"],
            ["Song A", "Artist A", "M1", "3"]])
        self.assertEqual(
            stderr.count("dropped out-of-scope ballot item"
                         " \"hallucinated\""), 3)

    def test_out_of_scope_pattern_dropped_with_warning(
            self) -> None:
        """Test that a pattern outside the song's gendered scope
        is dropped, the occurrence reported on standard error."""
        self.__write_default_synthesis_archives()
        self.__seed_songs([(1, "Song A", "Artist A", "male")])
        self.__write_same_ballots_to_all_runs({1: ["M1", "F1"]})
        status: int
        stderr: str
        status, stderr = self.__run_tally()
        self.assertEqual(status, 0)
        self.assertEqual(self.__read_rows(self.__annotations_csv), [
            ["Song", "Artist Credit", "Pattern", "Votes"],
            ["Song A", "Artist A", "M1", "3"]])
        self.assertEqual(
            stderr.count(
                "dropped out-of-scope ballot item \"F1\""), 3)

    def test_mixed_pattern_applies_to_every_song(self) -> None:
        """Test that a mixed-group pattern ("X" prefix) is in
        scope for a male-credited song."""
        self.__write_default_synthesis_archives()
        self.__seed_songs([(1, "Song A", "Artist A", "male")])
        self.__write_same_ballots_to_all_runs({1: ["X1"]})
        status: int
        stderr: str
        status, stderr = self.__run_tally()
        self.assertEqual(status, 0)
        self.assertEqual(self.__read_rows(self.__annotations_csv), [
            ["Song", "Artist Credit", "Pattern", "Votes"],
            ["Song A", "Artist A", "X1", "3"]])

    def test_unknown_gender_takes_every_pattern_prefix(
            self) -> None:
        """Test that a song with no stored performer gender
        accepts patterns of every group."""
        self.__write_default_synthesis_archives()
        self.__seed_songs([(1, "Song A", "Artist A", None)])
        self.__write_same_ballots_to_all_runs({1: ["M1", "F1"]})
        status: int
        status, _ = self.__run_tally()
        self.assertEqual(status, 0)
        self.assertEqual(self.__read_rows(self.__annotations_csv), [
            ["Song", "Artist Credit", "Pattern", "Votes"],
            ["Song A", "Artist A", "M1", "3"],
            ["Song A", "Artist A", "F1", "3"]])

    def test_duplicate_ballot_item_dropped_with_warning(
            self) -> None:
        """Test that a pattern ID listed twice in one ballot is
        collapsed, the extra occurrence reported on standard
        error."""
        self.__write_default_synthesis_archives()
        self.__seed_songs([(1, "Song A", "Artist A", "male")])
        self.__write_run(self.__runs[0], {1: ["M1", "M1"]})
        self.__write_run(self.__runs[1], {1: []})
        self.__write_run(self.__runs[2], {1: []})
        status: int
        stderr: str
        status, stderr = self.__run_tally()
        self.assertEqual(status, 0)
        self.assertEqual(self.__read_rows(self.__annotations_csv),
                         [["Song", "Artist Credit", "Pattern",
                           "Votes"]])
        self.assertEqual(
            stderr.count(
                "dropped duplicate ballot item \"M1\""), 1)

    def test_majority_vote_settles_two_of_three(self) -> None:
        """Test that a (song, pattern) pair needs at least two of
        the three cleaned ballots to settle."""
        self.__write_default_synthesis_archives()
        self.__seed_songs([(1, "Song A", "Artist A", "male")])
        self.__write_run(self.__runs[0], {1: ["M1", "M2"]})
        self.__write_run(self.__runs[1], {1: ["M1"]})
        self.__write_run(self.__runs[2], {1: []})
        status: int
        status, _ = self.__run_tally()
        self.assertEqual(status, 0)
        self.assertEqual(self.__read_rows(self.__annotations_csv), [
            ["Song", "Artist Credit", "Pattern", "Votes"],
            ["Song A", "Artist A", "M1", "2"]])

    def test_annotations_sorted_by_song_then_pattern_order(
            self) -> None:
        """Test the row order: numeric song ID, then pattern in
        the male-then-female-then-mixed extraction order."""
        self.__write_default_synthesis_archives()
        self.__seed_songs([
            (2, "Song B", "Artist B", "female"),
            (10, "Song C", "Artist C", None)])
        self.__write_same_ballots_to_all_runs({
            10: ["X1", "M1"], 2: ["F1"]})
        status: int
        status, _ = self.__run_tally()
        self.assertEqual(status, 0)
        self.assertEqual(self.__read_rows(self.__annotations_csv), [
            ["Song", "Artist Credit", "Pattern", "Votes"],
            ["Song B", "Artist B", "F1", "3"],
            ["Song C", "Artist C", "M1", "3"],
            ["Song C", "Artist C", "X1", "3"]])

    def test_output_is_crlf_with_header(self) -> None:
        """Test the written bytes of both tables: RFC 4180, CRLF,
        header row."""
        self.__write_synthesis(self.__male_synthesis, [
            ("模式一：厭女語彙", ["描述一。"], [])])
        self.__write_synthesis(self.__female_synthesis, [
            ("一、女女敵對", ["描述二。"], [])])
        self.__write_synthesis(self.__mixed_synthesis, [
            ("模式一：佔有語法", ["描述三。"], [])])
        self.__seed_songs([(1, "Song A", "Artist A", "male")])
        self.__write_same_ballots_to_all_runs({1: ["M1"]})
        status: int
        status, _ = self.__run_tally()
        self.assertEqual(status, 0)
        self.assertEqual(
            self.__patterns_csv.read_bytes(),
            (
                "Pattern,Group,Name,Description\r\n"
                "M1,male,厭女語彙,描述一。\r\n"
                "F1,female,女女敵對,描述二。\r\n"
                "X1,mixed,佔有語法,描述三。\r\n"
            ).encode("utf-8"))
        self.assertEqual(
            self.__annotations_csv.read_bytes(),
            b"Song,Artist Credit,Pattern,Votes\r\n"
            b"Song A,Artist A,M1,3\r\n")

    def test_song_missing_from_working_store_fails(self) -> None:
        """Test that a settled song not stored in the working
        store fails the tally, nothing written."""
        self.__write_default_synthesis_archives()
        self.__seed_songs([(2, "Song B", "Artist B", "male")])
        self.__write_same_ballots_to_all_runs({1: ["M1"]})
        status: int
        stderr: str
        status, stderr = self.__run_tally()
        self.assertNotEqual(status, 0)
        self.assertIn("song-1", stderr)
        self.assertIn("not in the working store", stderr)
        self.assertFalse(self.__annotations_csv.exists())

    def test_no_pattern_sections_fails(self) -> None:
        """Test that a synthesis document with no heading fails
        the tally, nothing written."""
        (self.__male_synthesis / "output.jsonl").write_text(
            json.dumps({"id": "synthesis", "text": "no headings"})
            + "\n", encoding="utf-8")
        self.__write_synthesis(self.__female_synthesis, [
            ("一、女女敵對", ["描述。"], [])])
        self.__write_synthesis(self.__mixed_synthesis, [
            ("模式一：佔有語法", ["描述。"], [])])
        self.__seed_songs([(1, "Song A", "Artist A", "male")])
        self.__write_same_ballots_to_all_runs({1: []})
        status: int
        stderr: str
        status, stderr = self.__run_tally()
        self.assertNotEqual(status, 0)
        self.assertIn("no pattern sections", stderr)
        self.assertFalse(self.__patterns_csv.exists())

    def test_summary_line_reports_counts(self) -> None:
        """Test that the closing summary reports the settled
        pair, song, and dropped vote counts."""
        self.__write_default_synthesis_archives()
        self.__seed_songs([(1, "Song A", "Artist A", "male")])
        self.__write_same_ballots_to_all_runs(
            {1: ["M1", "hallucinated"]})
        status: int
        stderr: str
        status, stderr = self.__run_tally()
        self.assertEqual(status, 0)
        self.assertIn("Tallied 1 settled pairs across 1 songs",
                      stderr)
        self.assertIn("3 votes dropped", stderr)
