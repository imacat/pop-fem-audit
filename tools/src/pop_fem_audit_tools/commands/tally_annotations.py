# Tools for A Feminist Audit of Pop Music.
# Copyright 2026 imacat.  All rights reserved.
# Authors:
#   imacat@mail.imacat.idv.tw (imacat), 2026/8/15
# AI assistance: Claude Code (Anthropic)
"""The majority tally of the three step-5 annotation runs.

Settles the per-song pattern annotation step: the pattern
vocabulary comes from the three gendered synthesis archives (the
male-group, female-group, and mixed-group runs of step
5-03-synthesize), and the same annotation definition file is run
three times independently over every song to select which
patterns apply.  This command extracts the pattern table from the
synthesis archives, tallies the three annotation runs' votes, and
writes the two final tables the paper cites: the pattern table
(the "patterns" CSV argument) and the per-song annotation table
(the "annotations" CSV argument).

Each synthesis archive's ``output.jsonl`` holds a single record
whose "text" field is a Markdown document, one section per
pattern, each section starting with a heading line.  The pattern
name is the heading text with its leading numbering token (for
example ``模式一：`` or ``一、``) stripped; the pattern
description is the section's non-empty lines that are not example
quotes (a line starting with ``- ``), joined with a single space.
The male synthesis yields the pattern IDs ``M1``, ``M2``, ...; the
female synthesis ``F1``, ``F2``, ...; the mixed synthesis ``X1``,
``X2``, ..., every set numbered in the section order of its own
document.

Each annotation run's ``output.jsonl`` holds one record per song,
the ID ``song-<ID>`` and the "text" field a JSON array of the
pattern IDs the song was annotated with.  The records of every
given run directory are pooled.  A record whose "text" field is
missing, or does not parse to a JSON array of strings, is
skipped, a warning naming the run directory and song reported on
standard error; this lets a rescue archive of replacement ballots
be passed as an additional run directory when a run archive holds
a dead record.  Every song must appear exactly three times in the
pool once such records are skipped.  A pattern ID that is not one of
the extracted IDs, or whose gendered prefix does not apply to the
song's stored performer gender (male songs take ``M``/``X``,
female songs take ``F``/``X``, every other song takes all three),
is dropped from its ballot, as is a duplicate within the one
ballot; every drop is reported on standard error.  A (song,
pattern) pair is settled when at least two of the three cleaned
ballots carry it, so three votes never tie.

The song's title and stored artist credit are looked up in the
given SQLite working store by the numeric song ID, so this
command runs after ``build-db``.  Nothing is written when a
synthesis section yields an empty name or description, a run
record is malformed, a song does not appear exactly three times
in the pool, or a settled song is not in the working store; the
error message names what failed.
"""
import argparse
import csv
import json
import re
import sqlite3
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..utils import format_duration

MAJORITY: int = 2
"""The number of cleaned ballots that must carry a pattern for a
(song, pattern) pair to be settled."""
BALLOTS_PER_SONG: int = 3
"""The number of times a song must appear in the pooled ballots."""
SONG_ID_PREFIX: str = "song-"
"""The prefix every annotation record ID must carry; the numeric
song ID is the rest of the ID."""
PATTERNS_HEADER: tuple[str, str, str, str] = (
    "Pattern", "Group", "Name", "Description")
"""The header row of the pattern table CSV file."""
ANNOTATIONS_HEADER: tuple[str, str, str, str] = (
    "Song", "Artist Credit", "Pattern", "Votes")
"""The header row of the annotation table CSV file."""
_GROUP_PREFIXES: tuple[tuple[str, str], ...] = (
    ("male", "M"), ("female", "F"), ("mixed", "X"))
"""The synthesis group name and its pattern ID prefix, in the
order the three synthesis archives are given."""
_APPLICABLE_PREFIXES: dict[str, set[str]] = {
    "male": {"M", "X"}, "female": {"F", "X"}}
"""The pattern ID prefixes applicable to a song, keyed by the
song's stored performer gender; a gender missing here (including
None) takes every prefix."""
_NUMBERING_RE: re.Pattern[str] = re.compile(
    r"^(?:模式[一二三四五六七八九十]+|[一二三四五六七八九十]+)[：、]")
"""The leading numbering token of a pattern heading, stripped to
yield the pattern name."""
_HEADING_RE: re.Pattern[str] = re.compile(r"^#+\s*(.*)$")
"""A Markdown heading line, the heading text captured."""


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
        "male_synthesis", type=Path,
        help="the male-group synthesis run's archive directory")
    parser.add_argument(
        "female_synthesis", type=Path,
        help="the female-group synthesis run's archive directory")
    parser.add_argument(
        "mixed_synthesis", type=Path,
        help="the mixed-group synthesis run's archive directory")
    parser.add_argument(
        "db_path", type=Path,
        help="the SQLite working database")
    parser.add_argument(
        "patterns_csv", type=Path,
        help="the output pattern table CSV file, by convention"
             " results/patterns.csv")
    parser.add_argument(
        "annotations_csv", type=Path,
        help="the output annotation table CSV file, by convention"
             " results/annotations.csv")
    parser.add_argument(
        "run_dir", type=Path, nargs="+",
        help="an annotation run's archive directory, one or more")
    return parser.parse_args(argv)


def load_synthesis_text(synthesis_dir: Path) -> str:
    """Load the Markdown pattern document of one synthesis archive.

    :param synthesis_dir: The synthesis run's archive directory,
        containing ``output.jsonl``.
    :return: The "text" field of the archive's single record.
    :raises TallyError: When the file cannot be read, does not
        hold exactly one JSON record, the record is not a
        successful result, or its "text" is not a string.
    """
    path: Path = synthesis_dir / "output.jsonl"
    text: str
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise TallyError(str(error)) from error
    lines: list[str] = [x for x in text.split("\n")
                        if x.strip() != ""]
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
    if not isinstance(record, dict) or "error" in record \
            or "text" not in record:
        raise TallyError(f"{path}: not a successful result")
    body: Any = record["text"]
    if not isinstance(body, str):
        raise TallyError(f"{path}: \"text\" is not a string")
    return body


def extract_patterns(
        synthesis_dir: Path, group: str, prefix: str) \
        -> list[Pattern]:
    """Extract the numbered patterns of one synthesis document.

    :param synthesis_dir: The synthesis run's archive directory.
    :param group: The synthesis group name: "male", "female", or
        "mixed".
    :param prefix: The pattern ID prefix of the group.
    :return: The patterns, in the document's section order, IDs
        ``<prefix>1``, ``<prefix>2``, ...
    :raises TallyError: When the archive cannot be loaded, holds
        no pattern section, or a section yields an empty name or
        description.
    """
    text: str = load_synthesis_text(synthesis_dir)
    sections: list[tuple[str, str]] = _parse_sections(text)
    if len(sections) == 0:
        raise TallyError(
            f"{synthesis_dir}: no pattern sections found")
    patterns: list[Pattern] = []
    index: int
    name: str
    description: str
    for index, (name, description) in enumerate(sections, start=1):
        if name == "" or description == "":
            raise TallyError(
                f"{synthesis_dir}: section {index}: empty name"
                " or description")
        patterns.append(Pattern(
            id=f"{prefix}{index}", group=group, name=name,
            description=description))
    return patterns


def _parse_sections(text: str) -> list[tuple[str, str]]:
    """Split a pattern document into its numbered sections.

    :param text: The synthesis document.
    :return: The sections' (name, description) pairs, in document
        order; the text before the first heading is discarded.
    """
    lines: list[str] = text.split("\n")
    headings: list[int] = [
        i for i, x in enumerate(lines) if _HEADING_RE.match(x)]
    sections: list[tuple[str, str]] = []
    position: int
    start: int
    for position, start in enumerate(headings):
        end: int = headings[position + 1] \
            if position + 1 < len(headings) else len(lines)
        heading: re.Match[str] | None = _HEADING_RE.match(
            lines[start])
        assert heading is not None
        name: str = _NUMBERING_RE.sub(
            "", heading.group(1).strip(), count=1).strip()
        body: list[str] = [x.strip() for x in lines[start + 1:end]]
        description: str = " ".join(
            x for x in body if x != "" and not x.startswith("- "))
        sections.append((name, description))
    return sections


def load_ballots(run_dirs: list[Path]) -> dict[int, list[list[str]]]:
    """Load and pool the annotation ballots of the given runs.

    A record whose "text" field is missing, or does not parse to
    a JSON array of strings, is skipped, a warning naming the run
    directory and song reported on standard error, as an
    observable side effect.

    :param run_dirs: The annotation runs' archive directories.
    :return: The raw ballots (the selected pattern IDs, duplicates
        not yet collapsed) of every song, keyed by the numeric
        song ID, in the pooled record order.
    :raises TallyError: When an ``output.jsonl`` cannot be read, a
        line is not a well-formed record, or a song does not
        appear exactly :data:`BALLOTS_PER_SONG` times in the pool
        once malformed-"text" records are skipped.
    """
    pooled: dict[int, list[list[str]]] = {}
    run_dir: Path
    for run_dir in run_dirs:
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
                    f"{path}: malformed JSON: {error}") from error
            if not isinstance(record, dict) or "id" not in record:
                raise TallyError(
                    f"{path}: record without \"id\": {line}")
            song_id: int = _parse_song_id(record["id"], run_dir)
            if "text" not in record:
                print(
                    f"warning: {run_dir}: song-{song_id}: no"
                    " \"text\" field, skipped", file=sys.stderr)
                continue
            ballot: list[str] | None = _parse_ballot(
                record["text"], run_dir, song_id)
            if ballot is None:
                continue
            pooled.setdefault(song_id, []).append(ballot)
    song_id: int
    ballots: list[list[str]]
    for song_id, ballots in pooled.items():
        if len(ballots) != BALLOTS_PER_SONG:
            raise TallyError(
                f"song-{song_id}: appears {len(ballots)} times"
                f" in the pool, expected {BALLOTS_PER_SONG}")
    return pooled


def _parse_song_id(item_id: Any, run_dir: Path) -> int:
    """Parse the numeric song ID out of an annotation record ID.

    :param item_id: The record's "id" field.
    :param run_dir: The run directory the record came from, for
        the error message.
    :return: The parsed numeric song ID.
    :raises TallyError: When the ID is not in the ``song-<ID>``
        form.
    """
    if not isinstance(item_id, str) \
            or not item_id.startswith(SONG_ID_PREFIX) \
            or not item_id[len(SONG_ID_PREFIX):].isdigit():
        raise TallyError(
            f"{run_dir}: id \"{item_id}\": not in"
            f" \"{SONG_ID_PREFIX}<ID>\" form")
    return int(item_id[len(SONG_ID_PREFIX):])


def _parse_ballot(text: Any, run_dir: Path, song_id: int) \
        -> list[str] | None:
    """Parse and validate one song's ballot "text" field.

    A "text" field that is not a string, is not well-formed JSON,
    or does not parse to a JSON array of strings is reported on
    standard error as a warning naming the run directory and
    song, and the record is skipped.

    :param text: The record's "text" field.
    :param run_dir: The run directory the record came from, for
        the warning message.
    :param song_id: The numeric song ID, for the warning message.
    :return: The selected pattern IDs, in the given order,
        duplicates not collapsed; None when the "text" field is
        malformed.
    """
    if not isinstance(text, str):
        print(
            f"warning: {run_dir}: song-{song_id}: \"text\" is not"
            " a string, skipped", file=sys.stderr)
        return None
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
            f"warning: {run_dir}: song-{song_id}: \"text\" does"
            " not parse to a JSON array of strings, skipped",
            file=sys.stderr)
        return None
    return selected


def load_genders(db_path: Path) -> dict[int, str | None]:
    """Load the stored performer gender of every song.

    :param db_path: The SQLite working database.
    :return: The stored performer gender, keyed by the song ID.
    :raises TallyError: When the database cannot be read.
    """
    songs: dict[int, tuple[str, str, str | None]] \
        = _load_songs(db_path)
    return {x: y[2] for x, y in songs.items()}


def _load_songs(db_path: Path) \
        -> dict[int, tuple[str, str, str | None]]:
    """Load the title, artist credit, and gender of every song.

    :param db_path: The SQLite working database.
    :return: The title, the stored artist credit, and the stored
        performer gender of every song, keyed by the song ID.
    :raises TallyError: When the database cannot be read.
    """
    try:
        connection: sqlite3.Connection = sqlite3.connect(
            f"file:{db_path.resolve()}?mode=ro", uri=True)
    except sqlite3.Error as error:
        raise TallyError(str(error)) from error
    try:
        rows: Any = connection.execute(
            "SELECT id, title, artist_credit, performer_gender"
            " FROM songs")
        return {x[0]: (x[1], x[2], x[3]) for x in rows}
    except sqlite3.Error as error:
        raise TallyError(str(error)) from error
    finally:
        connection.close()


def clean_ballots(
        pooled: dict[int, list[list[str]]],
        pattern_ids: set[str],
        genders: dict[int, str | None]) \
        -> tuple[dict[int, list[set[str]]], int]:
    """Drop the out-of-scope and duplicate items of every ballot.

    Every dropped occurrence is reported on standard error as an
    observable side effect.

    :param pooled: The raw ballots of every song, keyed by the
        numeric song ID.
    :param pattern_ids: The extracted pattern IDs.
    :param genders: The stored performer gender of every song
        known to the working store, keyed by the song ID; a song
        missing here takes every pattern ID prefix.
    :return: The cleaned ballots (the applicable, deduplicated
        pattern IDs) of every song, keyed by the numeric song ID,
        and the total number of dropped occurrences.
    """
    cleaned: dict[int, list[set[str]]] = {}
    dropped: int = 0
    song_id: int
    ballots: list[list[str]]
    for song_id, ballots in pooled.items():
        applicable: set[str] = _APPLICABLE_PREFIXES.get(
            genders.get(song_id), {"M", "F", "X"})
        cleaned_ballots: list[set[str]] = []
        ballot: list[str]
        for ballot in ballots:
            kept: set[str]
            count: int
            kept, count = _clean_one_ballot(
                ballot, song_id, pattern_ids, applicable)
            cleaned_ballots.append(kept)
            dropped += count
        cleaned[song_id] = cleaned_ballots
    return cleaned, dropped


def _clean_one_ballot(
        ballot: list[str], song_id: int, pattern_ids: set[str],
        applicable: set[str]) -> tuple[set[str], int]:
    """Drop the out-of-scope and duplicate items of one ballot.

    :param ballot: The raw selected pattern IDs, in the given
        order.
    :param song_id: The numeric song ID, for the warning messages.
    :param pattern_ids: The extracted pattern IDs.
    :param applicable: The pattern ID prefixes applicable to the
        song.
    :return: The applicable, deduplicated pattern IDs, and the
        number of dropped occurrences.
    """
    kept: set[str] = set()
    dropped: int = 0
    pattern_id: str
    for pattern_id in ballot:
        if pattern_id in kept:
            print(
                f"warning: song-{song_id}: dropped duplicate"
                f" ballot item \"{pattern_id}\"", file=sys.stderr)
            dropped += 1
            continue
        if pattern_id not in pattern_ids \
                or pattern_id[:1] not in applicable:
            print(
                f"warning: song-{song_id}: dropped out-of-scope"
                f" ballot item \"{pattern_id}\"", file=sys.stderr)
            dropped += 1
            continue
        kept.add(pattern_id)
    return kept, dropped


def tally_votes(cleaned: dict[int, list[set[str]]]) \
        -> dict[int, dict[str, int]]:
    """Tally the pattern votes of the cleaned ballots, song by song.

    :param cleaned: The cleaned ballots of every song, keyed by
        the numeric song ID.
    :return: The settled pattern votes of every song (at least
        :data:`MAJORITY` of its cleaned ballots), keyed by the
        numeric song ID and then by the pattern ID; a song with no
        settled pattern maps to an empty mapping.
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
                counts[pattern_id] = counts.get(pattern_id, 0) + 1
        tallied[song_id] = {
            x: y for x, y in counts.items() if y >= MAJORITY}
    return tallied


def write_patterns_csv(
        output_csv: Path, patterns: list[Pattern]) -> None:
    """Write the pattern table CSV file.

    Writes an RFC 4180 CSV file, UTF-8, with CRLF line endings,
    carrying the header row ``Pattern,Group,Name,Description`` and
    one row per extracted pattern, in the given order.  The parent
    directory is created when it does not exist.

    :param output_csv: The output CSV file.
    :param patterns: The extracted patterns, in the output order.
    :return: None.
    :raises OSError: When the file cannot be written.
    """
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with open(output_csv, "w", encoding="utf-8",
              newline="") as file:
        writer: Any = csv.writer(file)
        writer.writerow(PATTERNS_HEADER)
        writer.writerows(
            (x.id, x.group, x.name, x.description)
            for x in patterns)


def build_annotation_rows(
        tallied: dict[int, dict[str, int]],
        songs: dict[int, tuple[str, str, str | None]],
        patterns: list[Pattern]) \
        -> list[tuple[str, str, str, int]]:
    """Build the ordered data rows of the annotation table.

    :param tallied: The settled pattern votes of every song, keyed
        by the numeric song ID and then by the pattern ID.
    :param songs: The title, the stored artist credit, and the
        stored performer gender of every stored song, keyed by the
        song ID.
    :param patterns: The extracted patterns, in the pattern table
        order.
    :return: The rows, each the song title, the artist credit, the
        pattern ID, and the number of votes, ordered by the
        numeric song ID and then by the pattern table order.
    :raises TallyError: When a settled song is not in the working
        store.
    """
    order: dict[str, int] = {x.id: i for i, x in enumerate(patterns)}
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
        for pattern_id in sorted(votes, key=lambda x: order[x]):
            rows.append((
                title, artist_credit, pattern_id,
                votes[pattern_id]))
    return rows


def write_annotations_csv(
        output_csv: Path, rows: list[tuple[str, str, str, int]]) \
        -> None:
    """Write the annotation table CSV file.

    Writes an RFC 4180 CSV file, UTF-8, with CRLF line endings,
    carrying the header row ``Song,Artist Credit,Pattern,Votes``
    and one row per settled (song, pattern) pair, in the given
    order.  The parent directory is created when it does not
    exist.

    :param output_csv: The output CSV file.
    :param rows: The settled rows, in the output order.
    :return: None.
    :raises OSError: When the file cannot be written.
    """
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with open(output_csv, "w", encoding="utf-8",
              newline="") as file:
        writer: Any = csv.writer(file)
        writer.writerow(ANNOTATIONS_HEADER)
        writer.writerows(rows)


def main(argv: list[str] | None = None) -> int:
    """Settle the pattern annotations by a majority of the runs.

    Writes the pattern table CSV file and the annotation table CSV
    file described in the module docstring.  Nothing is written
    when a synthesis section yields an empty name or description,
    a run record is malformed, a song does not appear exactly
    :data:`BALLOTS_PER_SONG` times in the pool, or a settled song
    is not in the working store; the error message names what
    failed.

    :param argv: The command-line arguments, or None for
        ``sys.argv``.
    :return: The exit status: 0 on success, non-zero on failure.
    """
    started: float = time.monotonic()
    args: argparse.Namespace = parse_args(argv)
    try:
        patterns: list[Pattern] = []
        synthesis_dirs: tuple[Path, Path, Path] = (
            args.male_synthesis, args.female_synthesis,
            args.mixed_synthesis)
        synthesis_dir: Path
        group: str
        prefix: str
        for synthesis_dir, (group, prefix) in zip(
                synthesis_dirs, _GROUP_PREFIXES):
            patterns.extend(
                extract_patterns(synthesis_dir, group, prefix))
        write_patterns_csv(args.patterns_csv, patterns)
        pattern_ids: set[str] = {x.id for x in patterns}
        pooled: dict[int, list[list[str]]] \
            = load_ballots(args.run_dir)
        songs: dict[int, tuple[str, str, str | None]] \
            = _load_songs(args.db_path)
        genders: dict[int, str | None] \
            = {x: y[2] for x, y in songs.items()}
        cleaned: dict[int, list[set[str]]]
        dropped: int
        cleaned, dropped = clean_ballots(pooled, pattern_ids,
                                         genders)
        tallied: dict[int, dict[str, int]] = tally_votes(cleaned)
        rows: list[tuple[str, str, str, int]] \
            = build_annotation_rows(tallied, songs, patterns)
        write_annotations_csv(args.annotations_csv, rows)
    except (TallyError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    elapsed: str = format_duration(time.monotonic() - started)
    print(
        f"Done.  Tallied {len(rows)} settled pairs across"
        f" {len(tallied)} songs, {dropped} votes dropped."
        f"  {elapsed} elapsed.", file=sys.stderr)
    return 0
