# Tools for A Feminist Audit of Pop Music.
# Copyright 2026 imacat.  All rights reserved.
# Authors:
#   imacat@mail.imacat.idv.tw (imacat), 2026/8/6
"""The majority tally of the three coding runs.

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
follows the text alone.  The three
archives must cover exactly the same set of song IDs, every
record must be a successful result, and every record's "text"
must parse to a JSON object; otherwise the tally fails and
nothing is written.

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
                 run_dir_3: Path) -> None:
        """Set up the tallier of the three coding runs.

        :param run_dir_1: The first run's archive directory,
            containing ``output.jsonl``.
        :param run_dir_2: The second run's archive directory,
            containing ``output.jsonl``.
        :param run_dir_3: The third run's archive directory,
            containing ``output.jsonl``.
        """
        self.__run_dirs: list[Path] = [
            run_dir_1, run_dir_2, run_dir_3]
        """The three runs' archive directories, in the given
        order."""

    def run(self) -> TalliedCodings:
        """Load the three coding runs and tally their votes.

        Every record of every run must be a successful result
        whose "text" parses to a JSON object of keywords mapped to
        their lyric quote lists, and the three runs must cover
        exactly the same set of song IDs.  Only the keyword keys
        are counted; the quotes of a settled code are pooled for
        the output.  Nothing is written.

        :return: The keywords at least two of the three runs
            assign, with their joined quotes, of every song the
            runs cover.
        :raises TallyError: When an ``output.jsonl`` cannot be
            read, a line is not a well-formed output record, a
            record is not a successful result, a "text" does not
            parse to a JSON object of quote string lists, a JSON
            document has a duplicate key, a run has two records of
            one song, or the three runs do not cover the same
            songs.
        """
        runs: list[dict[int, dict[str, list[str]]]]
        try:
            runs = [self.__load_run(x) for x in self.__run_dirs]
            self.__check_same_songs(self.__run_dirs, runs)
        except (OSError, ValueError) as error:
            raise TallyError(str(error)) from error
        return TalliedCodings(codings=self.__tally(runs))

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
        """Write the coding table CSV file.

        Writes an RFC 4180 CSV file, UTF-8, with CRLF line
        endings, carrying the header row
        ``Song,Artist Credit,Keyword,Quote`` and one row per
        settled keyword, in the row order.  The parent directory
        is created when it does not exist.

        :param output_csv: The output CSV file.
        :return: None.
        :raises OSError: When the file cannot be written.
        """
        output_csv.parent.mkdir(parents=True, exist_ok=True)
        with open(output_csv, "w", encoding="utf-8",
                  newline="") as file:
            writer: Any = csv.writer(file)
            writer.writerow(self.__HEADER)
            writer.writerows(self.rows)


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
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Settle the coding by a majority of the three coding runs.

    Writes the final coding table as the given CSV file, holding
    the header row ``Song,Artist Credit,Keyword,Quote`` and one
    row per keyword at least two of the three runs assign, the
    song named by its title and its stored artist credit from the
    SQLite working store, and the keyword carrying the pooled,
    deduplicated, and sorted lyric quotes of the runs that
    assigned it, joined with a single ``|``.  Nothing is written
    when the three archives do not cover the same songs, a record
    is not a successful result, a record's "text" does not parse
    to a JSON object of quote string lists, or a song is not in
    the working store; the error message names what failed.

    :param argv: The command-line arguments, or None for
        ``sys.argv``.
    :return: The exit status: 0 on success, non-zero on failure.
    """
    started: float = time.monotonic()
    args: argparse.Namespace = parse_args(argv)
    try:
        codings: TalliedCodings = CodingTallier(
            args.run_dir_1, args.run_dir_2, args.run_dir_3).run()
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
