# Tools for A Feminist Audit of Pop Music.
# Copyright 2026 imacat.  All rights reserved.
# Authors:
#   imacat@mail.imacat.idv.tw (imacat), 2026/8/6
r"""The majority tally of the three coding runs.

Settles the coding step: the same coding definition file is run
three times independently, and this command counts the votes and
writes the final coding table the paper cites, as the CSV file
given as the fourth positional command-line argument.  Only the
keyword key sets of the three runs' archived ``output.jsonl``
files take part in the tally; the lyric quotes never do.  A
(song, keyword) pair is written out when at least two of the
three runs assign it, so three votes never tie, and it carries
the lyric quotes of every run that assigned it, pooled,
deduplicated, sorted by Unicode code point, and joined with a
single ``|``: the three runs are peers, so the quote order
follows the text alone.  The written quote carries the two
characters ``\n`` where the lyric has a newline, the mirror of
the unescaping the correction table loader does, so the coding
table holds one row per line.  The three
archives must cover exactly the same set of song IDs, every
record must be a successful result, and every record's "text"
must parse to a JSON object; otherwise the tally fails and
nothing is written.

Two optional inputs guard the tally.  ``--corrections`` names a
CSV file of researcher-reviewed repairs, applied to each run's
records before anything else happens: a keyword row renames or
drops one keyword assignment of one song in one run, and an
evidence row rewrites or drops one lyric quote string wherever it
appears in that song's record for that run.  Its two text fields
carry the two characters ``\n`` where the text has a newline, so
the file holds one row per line.  Every row must match, so a
stale row fails the run.  ``--valid-keywords`` names a
plain text file of the allowed keywords, one per line; once the
corrections are in, every keyword left in any record must appear
in it.  The order is fixed and matters: the corrections come
first, so a repair may reunite the votes of a misspelled keyword
that the check would otherwise reject.  With neither option, no
record is touched and no vocabulary is checked.

The archives identify a song as ``song-<ID>``, where ``<ID>`` is
the song's ID in the SQLite working store.  The output table does
not carry that ID: every song is looked up in the working store
and written as its title and its stored artist credit instead, so
this command runs after ``build-db``.  The step is fully
deterministic; no LLM call is made.
"""
import argparse
import csv
import json
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
    """An error that fails the tally."""


@dataclass(frozen=True)
class Correction:
    """One researcher-reviewed repair of one run's record."""

    KEYWORD: ClassVar[str] = "keyword"
    """The type of a row that repairs a keyword assignment."""
    EVIDENCE: ClassVar[str] = "evidence"
    """The type of a row that repairs a lyric quote."""
    REMOVE: ClassVar[str] = "**REMOVE**"
    """The correct term that drops what the row names instead of
    replacing it."""
    __MAX_QUOTED: ClassVar[int] = 40
    """The number of characters of the replaced text an error
    message shows before cutting it short."""

    line: int
    """The line of the corrections file the row ends on."""
    song_id: int
    """The numeric part of the song ID the row repairs."""
    run: str
    """The basename of the run directory the row repairs."""
    type: str
    """The type of the row, :attr:`KEYWORD` or :attr:`EVIDENCE`."""
    to_be_replaced: str
    """The keyword or the lyric quote string the row replaces."""
    correct_term: str
    """The replacement, or :attr:`REMOVE` to drop what the row
    names."""

    @property
    def is_removal(self) -> bool:
        """Whether the row drops what it names.

        :return: True when the correct term is :attr:`REMOVE`,
            False otherwise.
        """
        return self.correct_term == self.REMOVE

    @property
    def label(self) -> str:
        """The identity of the row, for an error message.

        :return: The song ID, the run, the type, and the replaced
            text, the text cut short when it is long.
        """
        text: str = self.to_be_replaced
        if len(text) > self.__MAX_QUOTED:
            text = f"{text[:self.__MAX_QUOTED]}..."
        return (f"song-{self.song_id} {self.run} {self.type}"
                f" \"{text}\"")


@dataclass
class CorrectionTable:
    """The researcher-reviewed repairs of the runs' records."""

    MANUAL_CORRECTIONS_CSV: ClassVar[str] \
        = "coding-corrections.csv"
    """The correction table CSV file's conventional name under
    ``data/manual/``."""

    path: Path
    """The correction table CSV file the repairs came from."""
    corrections: list[Correction]
    """The repairs, in file order."""


class CorrectionsLoader:
    """The loader of the researcher-reviewed correction table."""

    __HEADER: tuple[str, str, str, str, str] = (
        "Song ID", "Run", "Type", "To Be Replaced", "Correct Term")
    """The header row the correction table CSV file must carry."""

    def __init__(self, path: Path, run_names: list[str]) -> None:
        """Set up the loader of the correction table.

        :param path: The correction table CSV file.
        :param run_names: The basenames of the run directories the
            command was given, in the given order.
        """
        self.__path: Path = path
        """The correction table CSV file."""
        self.__run_names: set[str] = set(run_names)
        """The basenames of the given run directories."""

    def run(self) -> CorrectionTable:
        r"""Load and validate the correction table.

        Every row must name a song in the ``song-<ID>`` form, one
        of the runs the command was given, and a known type.  The
        file is read with the CSV reader, so a quoted field may
        hold a comma or a double quote.  No field holds a line
        break: the two text fields carry the two characters
        ``\n`` where the text has a newline, so the file holds one
        row per line, and each of them is unescaped to a single LF
        before the repair is matched or applied, as that is what
        the archived records carry.  Nothing is written.

        :return: The repairs, in file order.
        :raises TallyError: When the file cannot be read, the
            header row is not the expected one, a row does not
            have the expected number of fields, a song ID is not
            in the ``song-<ID>`` form, a row names a run the
            command was not given, or a row has an unknown type.
        """
        try:
            return CorrectionTable(
                path=self.__path,
                corrections=self.__load(
                    self.__path, self.__run_names))
        except (OSError, ValueError) as error:
            raise TallyError(str(error)) from error

    @classmethod
    def __load(cls, path: Path, run_names: set[str]) \
            -> list[Correction]:
        """Read the rows of the correction table CSV file.

        :param path: The correction table CSV file.
        :param run_names: The basenames of the given run
            directories.
        :return: The repairs, in file order.
        :raises OSError: When the file cannot be read.
        :raises ValueError: When the file is empty, the header row
            is not the expected one, or a row is invalid.
        """
        corrections: list[Correction] = []
        with open(path, encoding="utf-8", newline="") as file:
            reader: Any = csv.reader(file)
            header: list[str] | None = None
            row: list[str]
            for row in reader:
                if len(row) == 0:
                    continue
                if header is None:
                    header = row
                    if tuple(row) != cls.__HEADER:
                        raise ValueError(
                            f"{path}: the header row is not"
                            f" \"{','.join(cls.__HEADER)}\"")
                    continue
                corrections.append(cls.__parse_row(
                    row, reader.line_num, path, run_names))
        if header is None:
            raise ValueError(f"{path}: no header row")
        return corrections

    @classmethod
    def __parse_row(cls, row: list[str], line: int, path: Path,
                    run_names: set[str]) -> Correction:
        """Validate one row of the correction table.

        :param row: The row's fields, in file order.
        :param line: The line the row ends on.
        :param path: The correction table CSV file, for the error
            message.
        :param run_names: The basenames of the given run
            directories.
        :return: The repair the row states, its two text fields
            unescaped.
        :raises ValueError: When the row does not have the
            expected number of fields, its song ID is not in the
            ``song-<ID>`` form, it names a run the command was not
            given, or its type is unknown.
        """
        label: str = f"{path}: line {line}"
        if len(row) != len(cls.__HEADER):
            raise ValueError(
                f"{label}: expected {len(cls.__HEADER)} fields,"
                f" got {len(row)}")
        song_id: int = cls.__parse_song_id(row[0], label)
        if row[1] not in run_names:
            given: str = ", ".join(sorted(run_names))
            raise ValueError(
                f"{label}: run \"{row[1]}\" is not among the given"
                f" runs {given}")
        if row[2] not in (Correction.KEYWORD, Correction.EVIDENCE):
            raise ValueError(f"{label}: unknown type \"{row[2]}\"")
        return Correction(
            line=line, song_id=song_id, run=row[1], type=row[2],
            to_be_replaced=cls.__unescape(row[3]),
            correct_term=cls.__unescape(row[4]))

    @staticmethod
    def __unescape(text: str) -> str:
        r"""Unescape the newlines of a text field.

        The mirror of the escaping :meth:`CodingTable.write` does
        to the ``Quote`` field it writes out.

        :param text: The field as the CSV reader gave it.
        :return: The field with every two-character ``\n``
            sequence turned into a single LF.
        """
        return text.replace("\\n", "\n")

    @staticmethod
    def __parse_song_id(item_id: str, label: str) -> int:
        """Parse the integer song ID out of a song ID field.

        :param item_id: The song ID field, expected as
            ``song-<ID>``.
        :param label: The location of the field, for the error
            message.
        :return: The parsed song ID.
        :raises ValueError: When the field is not ``song-<ID>``.
        """
        prefix: str = "song-"
        if not item_id.startswith(prefix) \
                or not item_id[len(prefix):].isdigit():
            raise ValueError(
                f"{label}: song ID \"{item_id}\": not in"
                " \"song-<ID>\" form")
        return int(item_id[len(prefix):])


@dataclass
class ValidKeywords:
    """The keywords the coding records may carry."""

    path: Path
    """The keyword list file the keywords came from."""
    keywords: set[str]
    """The allowed keywords."""


class ValidKeywordsLoader:
    """The loader of the valid keyword list."""

    def __init__(self, path: Path) -> None:
        """Set up the loader of the valid keyword list.

        :param path: The keyword list text file, one keyword per
            line.
        """
        self.__path: Path = path
        """The keyword list text file."""

    def run(self) -> ValidKeywords:
        """Load the valid keyword list.

        Blank lines are ignored and every keyword is stripped of
        its surrounding whitespace; the file order carries no
        meaning.  Nothing is written.

        :return: The allowed keywords.
        :raises TallyError: When the file cannot be read.
        """
        text: str
        try:
            text = self.__path.read_text(encoding="utf-8")
        except OSError as error:
            raise TallyError(str(error)) from error
        return ValidKeywords(
            path=self.__path,
            keywords={x.strip() for x in text.split("\n")
                      if x.strip() != ""})


@dataclass
class TalliedCodings:
    """The codes settled by a majority of the three coding runs."""

    codings: dict[int, dict[str, str]]
    """The joined lyric quotes of every settled keyword of every
    song the three runs cover, keyed by the numeric part of the
    song ID and then by the keyword, the keywords
    lexicographically sorted; a song with no settled keyword maps
    to an empty mapping."""

    @property
    def song_count(self) -> int:
        """The number of songs the three runs cover.

        :return: The number of songs, those with no settled
            keyword included.
        """
        return len(self.codings)


class CodingTallier:
    """The tallier of the three coding runs' keyword votes."""

    __MAJORITY: int = 2
    """The number of runs that must assign a keyword to a song for
    that code to be settled."""
    __MAX_REPORTED_IDS: int = 10
    """The number of song IDs an error message lists before
    summarizing the rest as a count."""
    __QUOTE_SEPARATOR: str = "|"
    """The separator between the distinct lyric quotes of one
    settled code."""

    def __init__(self, run_dir_1: Path, run_dir_2: Path,
                 run_dir_3: Path,
                 valid_keywords_txt: Path | None = None,
                 corrections_csv: Path | None = None) -> None:
        """Set up the tallier of the three coding runs.

        :param run_dir_1: The first run's archive directory,
            containing ``output.jsonl``.
        :param run_dir_2: The second run's archive directory,
            containing ``output.jsonl``.
        :param run_dir_3: The third run's archive directory,
            containing ``output.jsonl``.
        :param valid_keywords_txt: The valid keyword list text
            file, or None to check no keyword.
        :param corrections_csv: The researcher-reviewed correction
            table CSV file, or None to repair no record.
        """
        self.__run_dirs: list[Path] = [
            run_dir_1, run_dir_2, run_dir_3]
        """The three runs' archive directories, in the given
        order."""
        self.__valid_keywords_txt: Path | None = valid_keywords_txt
        """The valid keyword list text file, or None to check no
        keyword."""
        self.__corrections_csv: Path | None = corrections_csv
        """The correction table CSV file, or None to repair no
        record."""

    def run(self) -> TalliedCodings:
        """Load the three coding runs and tally their votes.

        Every record of every run must be a successful result
        whose "text" parses to a JSON object of keywords mapped to
        their lyric quote lists, and the three runs must cover
        exactly the same set of song IDs.  The researcher-reviewed
        repairs, when given, are applied to the records first, and
        every one of them must match something; the valid keyword
        list, when given, is checked against the repaired records
        next.  Only the keyword keys are counted; the quotes of a
        settled code are pooled for the output.  Nothing is
        written.

        :return: The keywords at least two of the three runs
            assign, with their joined quotes, of every song the
            runs cover.
        :raises TallyError: When an ``output.jsonl`` cannot be
            read, a line is not a well-formed output record, a
            record is not a successful result, a "text" does not
            parse to a JSON object of quote string lists, a JSON
            document has a duplicate key, a run has two records of
            one song, the three runs do not cover the same songs,
            the correction table or the valid keyword list cannot
            be read or is invalid, a correction matches nothing,
            or a keyword is not in the valid keyword list.
        """
        corrections: CorrectionTable | None = self.__load_corrections()
        valid: ValidKeywords | None = self.__load_valid_keywords()
        runs: list[dict[int, dict[str, list[str]]]]
        try:
            runs = [self.__load_run(x) for x in self.__run_dirs]
            self.__check_same_songs(self.__run_dirs, runs)
            if corrections is not None:
                self.__correct(runs, self.__run_dirs, corrections)
            if valid is not None:
                self.__check_keywords(self.__run_dirs, runs, valid)
        except (OSError, ValueError) as error:
            raise TallyError(str(error)) from error
        return TalliedCodings(codings=self.__tally(runs))

    def __load_corrections(self) -> CorrectionTable | None:
        """Load the researcher-reviewed correction table.

        :return: The repairs, or None when the caller gave no
            correction table.
        :raises TallyError: When the correction table cannot be
            read or is invalid.
        """
        if self.__corrections_csv is None:
            return None
        return CorrectionsLoader(
            self.__corrections_csv,
            [x.name for x in self.__run_dirs]).run()

    def __load_valid_keywords(self) -> ValidKeywords | None:
        """Load the valid keyword list.

        :return: The allowed keywords, or None when the caller
            gave no keyword list.
        :raises TallyError: When the keyword list cannot be read.
        """
        if self.__valid_keywords_txt is None:
            return None
        return ValidKeywordsLoader(self.__valid_keywords_txt).run()

    @classmethod
    def __correct(cls, runs: list[dict[int, dict[str, list[str]]]],
                  run_dirs: list[Path],
                  corrections: CorrectionTable) -> None:
        """Apply the researcher-reviewed repairs to the records.

        Each repair is applied to the runs whose directory
        basename it names, in file order.  The table is
        hand-curated and is expected to be reconciled with the
        records, so a repair that matches nothing fails the run.

        :param runs: The runs' records, in the given order,
            repaired in place.
        :param run_dirs: The runs' archive directories, in the
            same order.
        :param corrections: The repairs to apply.
        :return: None.
        :raises ValueError: When a repair matches nothing.
        """
        applied: set[int] = set()
        index: int
        records: dict[int, dict[str, list[str]]]
        for index, records in enumerate(runs):
            position: int
            correction: Correction
            for position, correction \
                    in enumerate(corrections.corrections):
                if correction.run != run_dirs[index].name:
                    continue
                if cls.__correct_one(records, correction):
                    applied.add(position)
        for position, correction in enumerate(
                corrections.corrections):
            if position not in applied:
                raise ValueError(
                    f"{corrections.path}: line {correction.line}:"
                    f" {correction.label}: matches nothing")

    @classmethod
    def __correct_one(
            cls, records: dict[int, dict[str, list[str]]],
            correction: Correction) -> bool:
        """Apply one repair to one run's records.

        :param records: The run's records, keyed by the numeric
            part of the song ID, repaired in place.
        :param correction: The repair to apply.
        :return: Whether the repair matched anything.
        """
        if correction.song_id not in records:
            return False
        keywords: dict[str, list[str]] = records[correction.song_id]
        if correction.type == Correction.KEYWORD:
            return cls.__correct_keyword(keywords, correction)
        return cls.__correct_evidence(keywords, correction)

    @staticmethod
    def __correct_keyword(keywords: dict[str, list[str]],
                          correction: Correction) -> bool:
        """Rename or drop one keyword assignment of one record.

        A rename onto a keyword the record already carries pools
        the two quote lists under the one keyword, which casts the
        one vote the record now states.

        :param keywords: The song's assigned keywords and their
            lyric quotes, repaired in place.
        :param correction: The keyword repair to apply.
        :return: Whether the record carries the named keyword.
        """
        if correction.to_be_replaced not in keywords:
            return False
        quotes: list[str] = keywords.pop(correction.to_be_replaced)
        if not correction.is_removal:
            keywords.setdefault(
                correction.correct_term, []).extend(quotes)
        return True

    @staticmethod
    def __correct_evidence(keywords: dict[str, list[str]],
                           correction: Correction) -> bool:
        """Rewrite or drop one lyric quote of one record.

        The quote string is repaired under every keyword of the
        record that carries it, as one quote often grounds several
        keywords.  Dropping the last quote of a keyword leaves the
        assignment standing with no quote at all.

        :param keywords: The song's assigned keywords and their
            lyric quotes, repaired in place.
        :param correction: The evidence repair to apply.
        :return: Whether any keyword of the record carries the
            named quote.
        """
        matched: bool = False
        keyword: str
        quotes: list[str]
        for keyword, quotes in keywords.items():
            if correction.to_be_replaced not in quotes:
                continue
            matched = True
            if correction.is_removal:
                keywords[keyword] = [
                    x for x in quotes
                    if x != correction.to_be_replaced]
                continue
            keywords[keyword] = [
                correction.correct_term
                if x == correction.to_be_replaced else x
                for x in quotes]
        return matched

    @staticmethod
    def __check_keywords(
            run_dirs: list[Path],
            runs: list[dict[int, dict[str, list[str]]]],
            valid: ValidKeywords) -> None:
        """Check every keyword against the valid keyword list.

        :param run_dirs: The runs' archive directories, in the
            given order.
        :param runs: The runs' records, in the same order, the
            repairs already applied.
        :param valid: The allowed keywords.
        :return: None.
        :raises ValueError: When a record carries a keyword the
            list does not have.
        """
        index: int
        records: dict[int, dict[str, list[str]]]
        for index, records in enumerate(runs):
            song_id: int
            for song_id in sorted(records):
                keyword: str
                for keyword in records[song_id]:
                    if keyword in valid.keywords:
                        continue
                    raise ValueError(
                        f"{run_dirs[index]}: song-{song_id}:"
                        f" keyword \"{keyword}\": not in"
                        f" {valid.path}")

    @classmethod
    def __load_run(cls, run_dir: Path) \
            -> dict[int, dict[str, list[str]]]:
        """Load and validate the keyword records of one run.

        :param run_dir: The run's archive directory, containing
            ``output.jsonl``.
        :return: The lyric quotes of every keyword of every song
            of the run, keyed by the numeric part of the song ID
            and then by the keyword.
        :raises OSError: When ``output.jsonl`` cannot be read.
        :raises ValueError: When a line is not a well-formed
            output record, a record is not a successful result, a
            "text" does not parse to a JSON object of quote string
            lists, a JSON document has a duplicate key, or the run
            has two records of one song.
        """
        path: Path = run_dir / "output.jsonl"
        text: str = path.read_text(encoding="utf-8")
        records: dict[int, dict[str, list[str]]] = {}
        line: str
        for line in text.split("\n"):
            if line.strip() == "":
                continue
            record: Any = cls.__parse_json(line, str(path))
            if not isinstance(record, dict) or "id" not in record:
                raise ValueError(
                    f"{path}: record without \"id\": {line}")
            item_id: Any = record["id"]
            if "error" in record or "text" not in record:
                raise ValueError(
                    f"{path}: id {item_id}: not a successful"
                    " result")
            song_id: int = cls.__parse_song_id(item_id, path)
            if song_id in records:
                raise ValueError(
                    f"{path}: id {item_id}: duplicate record")
            keywords: Any = cls.__parse_json(
                record["text"], f"{path}: id {item_id}: \"text\"")
            if not isinstance(keywords, dict):
                raise ValueError(
                    f"{path}: id {item_id}: \"text\" does not"
                    " parse to a JSON object")
            records[song_id] = cls.__quote_lists(
                keywords, f"{path}: id {item_id}")
        return records

    @staticmethod
    def __quote_lists(keywords: dict[str, Any], label: str) \
            -> dict[str, list[str]]:
        """Validate the lyric quote list of every keyword.

        :param keywords: The parsed "text" object of one record.
        :param label: The location of the record, for the error
            message.
        :return: The lyric quotes of every keyword, in the given
            order.
        :raises ValueError: When a keyword's value is not a list
            of strings.
        """
        quotes: dict[str, list[str]] = {}
        keyword: str
        value: Any
        for keyword, value in keywords.items():
            if not isinstance(value, list) \
                    or not all(isinstance(x, str) for x in value):
                raise ValueError(
                    f"{label}: keyword \"{keyword}\": the quotes"
                    " are not a list of strings")
            quotes[keyword] = value
        return quotes

    @classmethod
    def __parse_json(cls, text: str, label: str) -> Any:
        """Parse a JSON document, rejecting duplicate keys.

        :param text: The JSON document.
        :param label: The location of the document, for the error
            message.
        :return: The parsed value.
        :raises ValueError: When the document is not valid JSON,
            or a key appears more than once in one of its
            objects.
        """
        try:
            return json.loads(
                text,
                object_pairs_hook=cls.__reject_duplicate_keys)
        except ValueError as error:
            raise ValueError(f"{label}: {error}") from error

    @staticmethod
    def __reject_duplicate_keys(
            pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        """Build a mapping from key-value pairs, rejecting
        duplicates.

        :param pairs: The key-value pairs, in document order.
        :return: The mapping built from the pairs.
        :raises ValueError: When a key appears more than once.
        """
        result: dict[str, Any] = {}
        key: str
        value: Any
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate key \"{key}\"")
            result[key] = value
        return result

    @staticmethod
    def __parse_song_id(item_id: Any, path: Path) -> int:
        """Parse the integer song ID out of an item ID.

        :param item_id: The item ID, expected as ``song-<ID>``.
        :param path: The output file the ID came from, for the
            error message.
        :return: The parsed song ID.
        :raises ValueError: When the item ID is not
            ``song-<ID>``.
        """
        prefix: str = "song-"
        if not isinstance(item_id, str) \
                or not item_id.startswith(prefix) \
                or not item_id[len(prefix):].isdigit():
            raise ValueError(
                f"{path}: id \"{item_id}\": not in \"song-<ID>\""
                " form")
        return int(item_id[len(prefix):])

    @classmethod
    def __check_same_songs(
            cls, run_dirs: list[Path],
            runs: list[dict[int, dict[str, list[str]]]]) -> None:
        """Check that the runs cover exactly the same songs.

        :param run_dirs: The runs' archive directories, in the
            given order.
        :param runs: The runs' records, in the same order.
        :return: None.
        :raises ValueError: When two runs do not cover the same
            set of song IDs.
        """
        first: set[int] = set(runs[0])
        index: int
        records: dict[int, dict[str, list[str]]]
        for index, records in enumerate(runs):
            song_ids: set[int] = set(records)
            if song_ids == first:
                continue
            parts: list[str] = []
            missing: list[int] = sorted(first - song_ids)
            if len(missing) > 0:
                parts.append(
                    f"missing {cls.__format_ids(missing)}")
            extra: list[int] = sorted(song_ids - first)
            if len(extra) > 0:
                parts.append(f"extra {cls.__format_ids(extra)}")
            raise ValueError(
                f"{run_dirs[index]} does not cover the same songs"
                f" as {run_dirs[0]}: {'; '.join(parts)}")

    @classmethod
    def __format_ids(cls, song_ids: list[int]) -> str:
        """Format a list of song IDs for an error message.

        :param song_ids: The numeric song IDs, in ascending
            order.
        :return: The IDs as ``song-<ID>``, comma-separated, with
            the tail beyond the reporting limit summarized as a
            count.
        """
        shown: list[int] = song_ids[:cls.__MAX_REPORTED_IDS]
        text: str = ", ".join(f"song-{x}" for x in shown)
        rest: int = len(song_ids) - len(shown)
        if rest > 0:
            text = f"{text} and {rest} more"
        return text

    @classmethod
    def __tally(cls, runs: list[dict[int, dict[str, list[str]]]]) \
            -> dict[int, dict[str, str]]:
        """Tally the keyword votes of the runs, song by song.

        The quotes of a settled keyword are those of every run
        that assigned it, pooled, deduplicated by exact string,
        sorted by Unicode code point, and joined with a single
        separator; the three runs are peers, so the order follows
        the quotes themselves.

        :param runs: The runs' records, all covering the same set
            of song IDs.
        :return: The joined quotes of the keywords at least two of
            the three runs assign, keyed by the numeric part of
            the song ID and then by the keyword, the keywords
            lexicographically sorted.
        """
        codings: dict[int, dict[str, str]] = {}
        song_id: int
        for song_id in sorted(runs[0]):
            counts: dict[str, int] = {}
            quotes: dict[str, list[str]] = {}
            records: dict[int, dict[str, list[str]]]
            for records in runs:
                keyword: str
                given: list[str]
                for keyword, given in records[song_id].items():
                    counts[keyword] = counts.get(keyword, 0) + 1
                    quotes.setdefault(keyword, []).extend(given)
            codings[song_id] = {
                x: cls.__QUOTE_SEPARATOR.join(sorted(set(quotes[x])))
                for x in sorted(counts)
                if counts[x] >= cls.__MAJORITY}
        return codings


@dataclass
class CodingTable:
    """The final coding table the paper cites."""

    RESULT_CODINGS_CSV: ClassVar[str] = "codings.csv"
    """The coding table CSV file's conventional name under
    ``results/``."""
    __HEADER: ClassVar[tuple[str, str, str, str]] \
        = ("Song", "Artist Credit", "Keyword", "Quote")
    """The header row of the coding table CSV file."""

    rows: list[tuple[str, str, str, str]]
    """The data rows, each the song title, the song's stored
    artist credit, the settled keyword, and the keyword's joined
    lyric quotes, ordered by title, then artist credit, then
    keyword, by Unicode code point."""

    def write(self, output_csv: Path) -> None:
        r"""Write the coding table CSV file.

        Writes an RFC 4180 CSV file, UTF-8, with CRLF line
        endings, carrying the header row
        ``Song,Artist Credit,Keyword,Quote`` and one row per
        settled keyword, in the row order.  The ``Quote`` field
        carries the two characters ``\n`` where the quotes have a
        newline, so no field holds a line break and the file
        holds one row per line; the correction table loader
        unescapes its own two text fields the same way, and
        restoring a single LF gives the lyric text back.  The
        parent directory is created when it does not exist.

        :param output_csv: The output CSV file.
        :return: None.
        :raises OSError: When the file cannot be written.
        """
        output_csv.parent.mkdir(parents=True, exist_ok=True)
        with open(output_csv, "w", encoding="utf-8",
                  newline="") as file:
            writer: Any = csv.writer(file)
            writer.writerow(self.__HEADER)
            writer.writerows(
                (*x[:3], self.__escape(x[3])) for x in self.rows)

    @staticmethod
    def __escape(text: str) -> str:
        r"""Escape the newlines of the quote field.

        The mirror of the unescaping the correction table loader
        does to its own two text fields.

        :param text: The joined lyric quotes of one settled
            keyword.
        :return: The quotes with every LF turned into the two
            characters ``\n``.
        """
        return text.replace("\n", "\\n")


class CodingTableBuilder:
    """The builder of the final coding table."""

    def __init__(self, codings: TalliedCodings,
                 output_csv: Path) -> None:
        """Set up the builder of the final coding table.

        :param codings: The settled codes of the three coding
            runs.
        :param output_csv: The output CSV file that receives the
            coding table.
        """
        self.__codings: dict[int, dict[str, str]] = codings.codings
        """The joined quotes of every settled keyword of every
        song, keyed by the numeric part of the song ID and then by
        the keyword."""
        self.__output_csv: Path = output_csv
        """The output CSV file."""

    def run(self) -> CodingTable:
        """Name the songs from the working store and write the
        table.

        Every song of the tally is looked up in the SQLite working
        store and written as its title and its stored artist
        credit.  Writes the coding table CSV file before
        returning; nothing is written when the run fails.

        :return: The coding table.
        :raises TallyError: When the working store cannot be read,
            or a song of the tally is not in it.
        :raises OSError: When the output file cannot be written.
        """
        table: CodingTable
        try:
            songs: dict[int, tuple[str, str]] = self.__load_songs()
            table = CodingTable(
                rows=self.__build_rows(self.__codings, songs))
        except (sa.exc.SQLAlchemyError, ValueError) as error:
            raise TallyError(str(error)) from error
        table.write(self.__output_csv)
        return table

    @staticmethod
    def __load_songs() -> dict[int, tuple[str, str]]:
        """Load the title and artist credit of every stored song.

        :return: The title and the stored artist credit of every
            song, keyed by the song ID.
        :raises sqlalchemy.exc.SQLAlchemyError: When the working
            store cannot be read.
        """
        session: Session = ds.get_db()
        try:
            song: Song
            return {
                song.id: (song.title, song.artist_credit)
                for song in session.scalars(sa.select(Song))}
        finally:
            session.close()

    @staticmethod
    def __build_rows(codings: dict[int, dict[str, str]],
                     songs: dict[int, tuple[str, str]]) \
            -> list[tuple[str, str, str, str]]:
        """Build the ordered data rows of the coding table.

        :param codings: The joined quotes of every settled keyword
            of every song, keyed by the numeric part of the song
            ID and then by the keyword.
        :param songs: The title and the stored artist credit of
            every stored song, keyed by the song ID.
        :return: The rows, each the song title, the artist credit,
            the keyword, and the keyword's joined quotes, ordered
            by title, then artist credit, then keyword, by Unicode
            code point.
        :raises ValueError: When a song of the tally is not in the
            working store.
        """
        quotes: dict[tuple[str, str, str], str] = {}
        song_id: int
        keywords: dict[str, str]
        for song_id, keywords in codings.items():
            if song_id not in songs:
                raise ValueError(
                    f"song-{song_id}: not in the working store")
            title: str
            artist_credit: str
            title, artist_credit = songs[song_id]
            keyword: str
            quote: str
            for keyword, quote in keywords.items():
                quotes[(title, artist_credit, keyword)] = quote
        key: tuple[str, str, str]
        return [(*key, quotes[key]) for key in sorted(quotes)]


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Parse the command-line arguments.

    :param argv: The command-line arguments, or None for
        ``sys.argv``.
    :return: The parsed arguments.
    """
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description="Settle the coding step by a majority of the"
                    " three coding runs and write the final"
                    " coding table.")
    parser.add_argument(
        "run_dir_1", type=Path,
        help="the first coding run's archive directory")
    parser.add_argument(
        "run_dir_2", type=Path,
        help="the second coding run's archive directory")
    parser.add_argument(
        "run_dir_3", type=Path,
        help="the third coding run's archive directory")
    parser.add_argument(
        "output_csv", type=Path,
        help="the output CSV file, by convention"
             f" results/{CodingTable.RESULT_CODINGS_CSV}")
    parser.add_argument(
        "--valid-keywords", type=Path, default=None,
        help="a plain text file of the allowed keywords, one per"
             " line, that every keyword left after the"
             " corrections must appear in (default: no check)")
    parser.add_argument(
        "--corrections", type=Path, default=None,
        help="the researcher-reviewed correction table CSV file,"
             " by convention"
             f" data/manual/{CorrectionTable.MANUAL_CORRECTIONS_CSV},"
             " applied to the runs' records before the tally"
             " (default: no repair)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    r"""Settle the coding by a majority of the three coding runs.

    Writes the final coding table as the given CSV file, holding
    the header row ``Song,Artist Credit,Keyword,Quote`` and one
    row per keyword at least two of the three runs assign, the
    song named by its title and its stored artist credit from the
    SQLite working store, and the keyword carrying the pooled,
    deduplicated, and sorted lyric quotes of the runs that
    assigned it, joined with a single ``|`` and written with the
    two characters ``\n`` where the quotes have a newline, so the
    table holds one row per line.  The records are
    repaired from the ``--corrections`` table and then checked
    against the ``--valid-keywords`` list, when either is given.
    Nothing is written when the three archives do not cover the
    same songs, a record is not a successful result, a record's
    "text" does not parse to a JSON object of quote string lists,
    a correction is invalid or matches nothing, a keyword is not
    in the valid keyword list, or a song is not in the working
    store; the error message names what failed.

    :param argv: The command-line arguments, or None for
        ``sys.argv``.
    :return: The exit status: 0 on success, non-zero on failure.
    """
    started: float = time.monotonic()
    args: argparse.Namespace = parse_args(argv)
    try:
        codings: TalliedCodings = CodingTallier(
            args.run_dir_1, args.run_dir_2, args.run_dir_3,
            args.valid_keywords, args.corrections).run()
        table: CodingTable = CodingTableBuilder(
            codings, args.output_csv).run()
        elapsed: str = format_duration(time.monotonic() - started)
        print(
            f"Done.  Tallied {len(table.rows)} codes across"
            f" {codings.song_count} songs.  {elapsed} elapsed.",
            file=sys.stderr)
    except TallyError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0
