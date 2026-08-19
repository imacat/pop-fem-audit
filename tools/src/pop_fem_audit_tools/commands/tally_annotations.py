# Tools for A Feminist Audit of Pop Music.
# Copyright 2026 imacat.  All rights reserved.
# Authors:
#   imacat@mail.imacat.idv.tw (imacat), 2026/8/15
# AI assistance: Claude Code (Anthropic)
"""The majority tally of the three step-5d annotation runs.

Settles the pattern annotation step: extracts the pattern table
from the three gendered synthesis archives (step 5c), tallies the
three annotation runs' ballots by majority, and writes the two
final tables the paper cites: the pattern table and the per-song
annotation table.  A dead ballot record is skipped with a
warning, so a rescue archive of replacement ballots may be passed
as an additional run directory.  The songs are named from the
configured working store, so this command runs after
``build-db``.  When any input is malformed, the tally fails and
nothing is written; the error message names what failed.
"""
import argparse
import csv
import json
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

import sqlalchemy as sa
from sqlalchemy.orm import Session

from ..database import ds
from ..models import Song
from ..utils import format_duration


class TallyError(Exception):
    """An error that fails the annotation tally."""


@dataclass(frozen=True)
class Pattern:
    """One extracted pattern of a gendered synthesis document."""

    id: str
    """The pattern ID, the group's prefix and its 1-based section
    number."""
    group: str
    """The synthesis group the pattern came from: "male",
    "female", or "mixed"."""
    name: str
    """The pattern name, its numbering token stripped."""
    description: str
    """The pattern description, its example quotes excluded."""


class AnnotationTallier:
    """The tallier of the three annotation runs' pattern votes."""

    __MAJORITY: ClassVar[int] = 2
    """The number of ballots that must carry a pattern for a
    (song, pattern) pair to be settled."""
    __BALLOTS_PER_SONG: ClassVar[int] = 3
    """The number of times a song must appear in the pooled
    ballots."""
    __SONG_ID_PREFIX: ClassVar[str] = "song-"
    """The prefix every annotation record ID must carry; the
    numeric song ID is the rest of the ID."""
    __PATTERNS_HEADER: ClassVar[tuple[str, str, str, str]] = (
        "Pattern", "Group", "Name", "Description")
    """The header row of the pattern table CSV file."""
    __ANNOTATIONS_HEADER: ClassVar[tuple[str, str, str, str]] = (
        "Song", "Artist Credit", "Pattern", "Votes")
    """The header row of the annotation table CSV file."""
    __GROUP_PREFIXES: ClassVar[tuple[tuple[str, str], ...]] = (
        ("male", "M"), ("female", "F"), ("mixed", "X"))
    """The synthesis group name and its pattern ID prefix, in the
    order the three synthesis archives are given."""
    __APPLICABLE_PREFIXES: ClassVar[dict[str, set[str]]] = {
        "male": {"M", "X"}, "female": {"F", "X"}}
    """The pattern ID prefixes applicable to a song, keyed by the
    song's stored performer gender; a gender missing here
    (including None) takes every prefix."""
    __NUMBERING_RE: ClassVar[re.Pattern[str]] = re.compile(
        r"^(?:模式[一二三四五六七八九十]+|[一二三四五六七八九十]+)[：、]")
    """The leading numbering token of a pattern heading, stripped
    to yield the pattern name."""
    __HEADING_RE: ClassVar[re.Pattern[str]] = re.compile(
        r"^#+\s*(.*)$")
    """A Markdown heading line, the heading text captured."""

    def __init__(self, male_synthesis: Path, female_synthesis: Path,
                 mixed_synthesis: Path, patterns_csv: Path,
                 annotations_csv: Path,
                 run_dirs: list[Path]) -> None:
        """Set up the tallier of the three annotation runs.

        :param male_synthesis: The male-group synthesis run's
            archive directory.
        :param female_synthesis: The female-group synthesis run's
            archive directory.
        :param mixed_synthesis: The mixed-group synthesis run's
            archive directory.
        :param patterns_csv: The output pattern table CSV file.
        :param annotations_csv: The output annotation table CSV
            file.
        :param run_dirs: The annotation runs' archive directories.
        """
        self.__synthesis_dirs: tuple[Path, Path, Path] = (
            male_synthesis, female_synthesis, mixed_synthesis)
        """The three synthesis archive directories, in the group
        order."""
        self.__patterns_csv: Path = patterns_csv
        """The output pattern table CSV file."""
        self.__annotations_csv: Path = annotations_csv
        """The output annotation table CSV file."""
        self.__run_dirs: list[Path] = run_dirs
        """The annotation runs' archive directories."""

    def run(self) -> int:
        """Extract the patterns, tally the ballots, and write the
        two tables.

        :return: The number of settled (song, pattern) pairs.
        :raises TallyError: When an input is malformed, or a
            settled song is not in the working store.
        :raises OSError: When an output file cannot be written.
        """
        patterns: list[Pattern] = self.__extract_all_patterns()
        self.__write_patterns_csv(patterns)
        pattern_ids: set[str] = {x.id for x in patterns}
        pooled: dict[int, list[list[str]]] = self.__load_ballots()
        songs: dict[int, tuple[str, str, str | None]]
        try:
            songs = self.__load_songs()
        except sa.exc.SQLAlchemyError as error:
            raise TallyError(str(error)) from error
        genders: dict[int, str | None] \
            = {x: y[2] for x, y in songs.items()}
        cleaned: dict[int, list[set[str]]] = self.__clean_ballots(
            pooled, pattern_ids, genders)
        tallied: dict[int, dict[str, int]] \
            = self.__tally_votes(cleaned)
        rows: list[tuple[str, str, str, int]] \
            = self.__build_annotation_rows(tallied, songs, patterns)
        self.__write_annotations_csv(rows)
        return len(rows)

    def __extract_all_patterns(self) -> list[Pattern]:
        """Extract the patterns of the three synthesis archives.

        :return: The patterns, in the group order and then each
            document's section order.
        :raises TallyError: When an archive cannot be loaded,
            holds no pattern section, or a section yields an
            empty name or description.
        """
        patterns: list[Pattern] = []
        synthesis_dir: Path
        group: str
        prefix: str
        for synthesis_dir, (group, prefix) in zip(
                self.__synthesis_dirs, self.__GROUP_PREFIXES):
            patterns.extend(self.__extract_patterns(
                synthesis_dir, group, prefix))
        return patterns

    @classmethod
    def __extract_patterns(
            cls, synthesis_dir: Path, group: str, prefix: str) \
            -> list[Pattern]:
        """Extract the numbered patterns of one synthesis document.

        :param synthesis_dir: The synthesis run's archive
            directory.
        :param group: The synthesis group name: "male", "female",
            or "mixed".
        :param prefix: The pattern ID prefix of the group.
        :return: The patterns, in the document's section order,
            IDs ``<prefix>1``, ``<prefix>2``, ...
        :raises TallyError: When the archive cannot be loaded,
            holds no pattern section, or a section yields an
            empty name or description.
        """
        text: str = cls.__load_synthesis_text(synthesis_dir)
        sections: list[tuple[str, str]] \
            = cls.__parse_sections(text)
        if len(sections) == 0:
            raise TallyError(
                f"{synthesis_dir}: no pattern sections found")
        patterns: list[Pattern] = []
        index: int
        name: str
        description: str
        for index, (name, description) in enumerate(
                sections, start=1):
            if name == "" or description == "":
                raise TallyError(
                    f"{synthesis_dir}: section {index}: empty"
                    " name or description")
            patterns.append(Pattern(
                id=f"{prefix}{index}", group=group, name=name,
                description=description))
        return patterns

    @staticmethod
    def __load_synthesis_text(synthesis_dir: Path) -> str:
        """Load the Markdown pattern document of one synthesis
        archive.

        :param synthesis_dir: The synthesis run's archive
            directory, containing ``output.jsonl``.
        :return: The "text" field of the archive's single record.
        :raises TallyError: When the file cannot be read, does
            not hold exactly one JSON record, or the record is
            not a successful result.
        """
        path: Path = synthesis_dir / "output.jsonl"
        text: str
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as error:
            raise TallyError(str(error)) from error
        lines: list[str] = [
            x for x in text.split("\n") if x.strip() != ""]
        if len(lines) != 1:
            raise TallyError(
                f"{path}: expected exactly one record, found"
                f" {len(lines)}")
        record: Any
        try:
            record = json.loads(lines[0])
        except json.JSONDecodeError as error:
            raise TallyError(
                f"{path}: malformed JSON: {error}") from error
        if "text" not in record:
            raise TallyError(f"{path}: not a successful result")
        return record["text"]

    @classmethod
    def __parse_sections(cls, text: str) -> list[tuple[str, str]]:
        """Split a pattern document into its numbered sections.

        :param text: The synthesis document.
        :return: The sections' (name, description) pairs, in
            document order; the text before the first heading is
            discarded.
        """
        lines: list[str] = text.split("\n")
        headings: list[int] = [
            i for i, x in enumerate(lines)
            if cls.__HEADING_RE.match(x)]
        sections: list[tuple[str, str]] = []
        position: int
        start: int
        for position, start in enumerate(headings):
            end: int = headings[position + 1] \
                if position + 1 < len(headings) else len(lines)
            heading: re.Match[str] | None = cls.__HEADING_RE.match(
                lines[start])
            assert heading is not None
            name: str = cls.__NUMBERING_RE.sub(
                "", heading.group(1).strip(), count=1).strip()
            body: list[str] = [
                x.strip() for x in lines[start + 1:end]]
            description: str = " ".join(
                x for x in body
                if x != "" and not x.startswith("- "))
            sections.append((name, description))
        return sections

    def __write_patterns_csv(self, patterns: list[Pattern]) -> None:
        """Write the pattern table CSV file.

        Writes an RFC 4180 CSV file, UTF-8, with CRLF line
        endings, one row per extracted pattern, in the given
        order.  The parent directory is created when it does not
        exist.

        :param patterns: The extracted patterns, in the output
            order.
        :return: None.
        :raises OSError: When the file cannot be written.
        """
        self.__patterns_csv.parent.mkdir(
            parents=True, exist_ok=True)
        with open(self.__patterns_csv, "w", encoding="utf-8",
                  newline="") as file:
            writer: Any = csv.writer(file)
            writer.writerow(self.__PATTERNS_HEADER)
            writer.writerows(
                (x.id, x.group, x.name, x.description)
                for x in patterns)

    def __load_ballots(self) -> dict[int, list[list[str]]]:
        """Load and pool the annotation ballots of the given runs.

        A record whose "text" field is missing, or does not parse
        to a JSON array of strings, is skipped, a warning naming
        the run directory and song reported on standard error, as
        an observable side effect.

        :return: The raw ballots (the selected pattern IDs,
            duplicates not yet collapsed) of every song, keyed by
            the numeric song ID, in the pooled record order.
        :raises TallyError: When an ``output.jsonl`` cannot be
            read, a line is malformed JSON, or a song does not
            appear exactly :attr:`__BALLOTS_PER_SONG` times in
            the pool once malformed-"text" records are skipped.
        """
        pooled: dict[int, list[list[str]]] = {}
        run_dir: Path
        for run_dir in self.__run_dirs:
            path: Path = run_dir / "output.jsonl"
            text: str
            try:
                text = path.read_text(encoding="utf-8")
            except OSError as error:
                raise TallyError(str(error)) from error
            line: str
            for line in text.split("\n"):
                if line.strip() == "":
                    continue
                record: Any
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as error:
                    raise TallyError(
                        f"{path}: malformed JSON: {error}") \
                        from error
                song_id: int = self.__parse_song_id(
                    record["id"], run_dir)
                if "text" not in record:
                    print(
                        f"warning: {run_dir}: song-{song_id}: no"
                        " \"text\" field, skipped",
                        file=sys.stderr)
                    continue
                ballot: list[str] | None = self.__parse_ballot(
                    record["text"], run_dir, song_id)
                if ballot is None:
                    continue
                pooled.setdefault(song_id, []).append(ballot)
        song_id: int
        ballots: list[list[str]]
        for song_id, ballots in pooled.items():
            if len(ballots) != self.__BALLOTS_PER_SONG:
                raise TallyError(
                    f"song-{song_id}: appears {len(ballots)}"
                    f" times in the pool, expected"
                    f" {self.__BALLOTS_PER_SONG}")
        return pooled

    @classmethod
    def __parse_song_id(cls, item_id: Any, run_dir: Path) -> int:
        """Parse the numeric song ID out of an annotation record
        ID.

        :param item_id: The record's "id" field.
        :param run_dir: The run directory the record came from,
            for the error message.
        :return: The parsed numeric song ID.
        :raises TallyError: When the ID is not in the
            ``song-<ID>`` form.
        """
        prefix: str = cls.__SONG_ID_PREFIX
        if not isinstance(item_id, str) \
                or not item_id.startswith(prefix) \
                or not item_id[len(prefix):].isdigit():
            raise TallyError(
                f"{run_dir}: id \"{item_id}\": not in"
                f" \"{prefix}<ID>\" form")
        return int(item_id[len(prefix):])

    @staticmethod
    def __parse_ballot(text: Any, run_dir: Path, song_id: int) \
            -> list[str] | None:
        """Parse and validate one song's ballot "text" field.

        A "text" field that is not well-formed JSON, or does not
        parse to a JSON array of strings, is reported on standard
        error as a warning naming the run directory and song, and
        the record is skipped.

        :param text: The record's "text" field.
        :param run_dir: The run directory the record came from,
            for the warning message.
        :param song_id: The numeric song ID, for the warning
            message.
        :return: The selected pattern IDs, in the given order,
            duplicates not collapsed; None when the "text" field
            is malformed.
        """
        selected: Any
        try:
            selected = json.loads(text)
        except json.JSONDecodeError:
            print(
                f"warning: {run_dir}: song-{song_id}: \"text\" is"
                " malformed JSON, skipped", file=sys.stderr)
            return None
        if not isinstance(selected, list) \
                or not all(isinstance(x, str) for x in selected):
            print(
                f"warning: {run_dir}: song-{song_id}: \"text\""
                " does not parse to a JSON array of strings,"
                " skipped", file=sys.stderr)
            return None
        return selected

    @staticmethod
    def __load_songs() -> dict[int, tuple[str, str, str | None]]:
        """Load the title, artist credit, and gender of every
        stored song.

        :return: The title, the stored artist credit, and the
            stored performer gender of every song, keyed by the
            song ID.
        :raises sqlalchemy.exc.SQLAlchemyError: When the working
            store cannot be read.
        """
        session: Session = ds.get_db()
        try:
            song: Song
            return {
                song.id: (
                    song.title, song.artist_credit,
                    song.performer_gender)
                for song in session.scalars(sa.select(Song))}
        finally:
            session.close()

    @classmethod
    def __clean_ballots(
            cls, pooled: dict[int, list[list[str]]],
            pattern_ids: set[str],
            genders: dict[int, str | None]) \
            -> dict[int, list[set[str]]]:
        """Drop the out-of-scope and duplicate items of every
        ballot.

        Every dropped occurrence is reported on standard error as
        an observable side effect.

        :param pooled: The raw ballots of every song, keyed by
            the numeric song ID.
        :param pattern_ids: The extracted pattern IDs.
        :param genders: The stored performer gender of every song
            known to the working store, keyed by the song ID; a
            song missing here takes every pattern ID prefix.
        :return: The cleaned ballots (the applicable,
            deduplicated pattern IDs) of every song, keyed by the
            numeric song ID.
        """
        cleaned: dict[int, list[set[str]]] = {}
        song_id: int
        ballots: list[list[str]]
        for song_id, ballots in pooled.items():
            applicable: set[str] = cls.__APPLICABLE_PREFIXES.get(
                genders.get(song_id), {"M", "F", "X"})
            cleaned_ballots: list[set[str]] = []
            ballot: list[str]
            for ballot in ballots:
                cleaned_ballots.append(cls.__clean_one_ballot(
                    ballot, song_id, pattern_ids, applicable))
            cleaned[song_id] = cleaned_ballots
        return cleaned

    @staticmethod
    def __clean_one_ballot(
            ballot: list[str], song_id: int, pattern_ids: set[str],
            applicable: set[str]) -> set[str]:
        """Drop the out-of-scope and duplicate items of one
        ballot.

        :param ballot: The raw selected pattern IDs, in the given
            order.
        :param song_id: The numeric song ID, for the warning
            messages.
        :param pattern_ids: The extracted pattern IDs.
        :param applicable: The pattern ID prefixes applicable to
            the song.
        :return: The applicable, deduplicated pattern IDs.
        """
        kept: set[str] = set()
        pattern_id: str
        for pattern_id in ballot:
            if pattern_id in kept:
                print(
                    f"warning: song-{song_id}: dropped duplicate"
                    f" ballot item \"{pattern_id}\"",
                    file=sys.stderr)
                continue
            if pattern_id not in pattern_ids \
                    or pattern_id[:1] not in applicable:
                print(
                    f"warning: song-{song_id}: dropped"
                    f" out-of-scope ballot item \"{pattern_id}\"",
                    file=sys.stderr)
                continue
            kept.add(pattern_id)
        return kept

    @classmethod
    def __tally_votes(
            cls, cleaned: dict[int, list[set[str]]]) \
            -> dict[int, dict[str, int]]:
        """Tally the pattern votes of the cleaned ballots, song by
        song.

        :param cleaned: The cleaned ballots of every song, keyed
            by the numeric song ID.
        :return: The settled pattern votes of every song (at
            least :attr:`__MAJORITY` of its cleaned ballots),
            keyed by the numeric song ID and then by the pattern
            ID; a song with no settled pattern maps to an empty
            mapping.
        """
        tallied: dict[int, dict[str, int]] = {}
        song_id: int
        ballots: list[set[str]]
        for song_id, ballots in cleaned.items():
            counts: dict[str, int] = {}
            ballot: set[str]
            for ballot in ballots:
                pattern_id: str
                for pattern_id in ballot:
                    counts[pattern_id] = counts.get(
                        pattern_id, 0) + 1
            tallied[song_id] = {
                x: y for x, y in counts.items()
                if y >= cls.__MAJORITY}
        return tallied

    @staticmethod
    def __build_annotation_rows(
            tallied: dict[int, dict[str, int]],
            songs: dict[int, tuple[str, str, str | None]],
            patterns: list[Pattern]) \
            -> list[tuple[str, str, str, int]]:
        """Build the ordered data rows of the annotation table.

        :param tallied: The settled pattern votes of every song,
            keyed by the numeric song ID and then by the pattern
            ID.
        :param songs: The title, the stored artist credit, and
            the stored performer gender of every stored song,
            keyed by the song ID.
        :param patterns: The extracted patterns, in the pattern
            table order.
        :return: The rows, each the song title, the artist
            credit, the pattern ID, and the number of votes,
            ordered by the numeric song ID and then by the
            pattern table order.
        :raises TallyError: When a settled song is not in the
            working store.
        """
        order: dict[str, int] = {
            x.id: i for i, x in enumerate(patterns)}
        rows: list[tuple[str, str, str, int]] = []
        song_id: int
        for song_id in sorted(tallied):
            votes: dict[str, int] = tallied[song_id]
            if len(votes) == 0:
                continue
            if song_id not in songs:
                raise TallyError(
                    f"song-{song_id}: not in the working store")
            title: str
            artist_credit: str
            title, artist_credit, _ = songs[song_id]
            pattern_id: str
            for pattern_id in sorted(
                    votes, key=lambda x: order[x]):
                rows.append((
                    title, artist_credit, pattern_id,
                    votes[pattern_id]))
        return rows

    def __write_annotations_csv(
            self, rows: list[tuple[str, str, str, int]]) -> None:
        """Write the annotation table CSV file.

        Writes an RFC 4180 CSV file, UTF-8, with CRLF line
        endings, one row per settled (song, pattern) pair, in the
        given order.  The parent directory is created when it
        does not exist.

        :param rows: The settled rows, in the output order.
        :return: None.
        :raises OSError: When the file cannot be written.
        """
        self.__annotations_csv.parent.mkdir(
            parents=True, exist_ok=True)
        with open(self.__annotations_csv, "w", encoding="utf-8",
                  newline="") as file:
            writer: Any = csv.writer(file)
            writer.writerow(self.__ANNOTATIONS_HEADER)
            writer.writerows(rows)


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Parse the command-line arguments.

    :param argv: The command-line arguments, or None for
        ``sys.argv``.
    :return: The parsed arguments.
    """
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description="Settle the step-5 pattern annotations by a"
                    " majority of the three annotation runs.")
    parser.add_argument(
        "--female", type=Path, required=True,
        help="the female-group synthesis run's archive directory")
    parser.add_argument(
        "--male", type=Path, required=True,
        help="the male-group synthesis run's archive directory")
    parser.add_argument(
        "--mixed", type=Path, required=True,
        help="the mixed-group synthesis run's archive directory")
    parser.add_argument(
        "patterns_csv", type=Path,
        help="the output pattern table CSV file")
    parser.add_argument(
        "annotations_csv", type=Path,
        help="the output annotation table CSV file")
    parser.add_argument(
        "run_dir", type=Path, nargs="+",
        help="an annotation run's archive directory, one or more")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Settle the pattern annotations by a majority of the runs.

    Writes the pattern table CSV file and the annotation table
    CSV file described in the module docstring.  Nothing is
    written when a synthesis section yields an empty name or
    description, a run record is malformed, a song does not
    appear exactly three times in the pool, or a settled song is
    not in the working store; the error message names what
    failed.

    :param argv: The command-line arguments, or None for
        ``sys.argv``.
    :return: The exit status: 0 on success, non-zero on failure.
    """
    started: float = time.monotonic()
    args: argparse.Namespace = parse_args(argv)
    try:
        count: int = AnnotationTallier(
            args.male, args.female, args.mixed, args.patterns_csv,
            args.annotations_csv, args.run_dir).run()
    except (TallyError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    elapsed: str = format_duration(time.monotonic() - started)
    print(
        f"Done.  Tallied {count} annotations.  {elapsed} elapsed.",
        file=sys.stderr)
    return 0
