# Tools for A Feminist Audit of Pop Music.
# Copyright 2026 imacat.  All rights reserved.
# Authors:
#   imacat@mail.imacat.idv.tw (imacat), 2026/8/6
"""The coding run comparison step.

Compares the two independent coding runs of the same songs and
exports their per-song disagreements, writing one fixed-named
artifact under the output directory given as the third positional
command-line argument.  The two runs are compared by their keyword
key sets alone: a keyword assigned to a song by exactly one of the
two runs is a disagreement, and a keyword assigned by both is
agreed.  The quotes supporting a keyword never take part in the
comparison; they are carried along as the evidence of the disagreed
keyword they support.  The disagreements are written as a JSON file,
as :data:`DISAGREEMENTS_JSON`, holding only the songs the two runs
disagree on; it is what the arbitration step of the coding
procedure settles.  The agreed half is not written; it is returned
by :func:`compare_codings`, as the keyword names alone, for later
steps to consume.  The step is fully deterministic; no LLM call is
made.
"""
import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

from ..utils import format_duration

DISAGREEMENTS_JSON: str = "disagreements.json"
"""The disagreement JSON file's fixed name under the output
directory."""

type Coding = dict[str, list[str]]
"""The keywords assigned to one song, each with its lyric quotes."""

type Codings = dict[str, Coding]
"""The coding of every song of one run, keyed by the song ID."""

type AgreedKeywords = dict[str, list[str]]
"""The keywords both runs assigned to a song, keyed by the song
ID."""


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Parse the command-line arguments.

    :param argv: The command-line arguments, or None for
        ``sys.argv``.
    :return: The parsed arguments.
    """
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description="Compare the two coding runs of the same songs"
                    " and export their per-song disagreements for"
                    " the arbitration step.")
    parser.add_argument(
        "run_dir_1", type=Path,
        help="the first coding run's archive directory")
    parser.add_argument(
        "run_dir_2", type=Path,
        help="the second coding run's archive directory")
    parser.add_argument(
        "output_dir", type=Path,
        help="the output directory, created if missing, that"
             f" receives {DISAGREEMENTS_JSON}")
    return parser.parse_args(argv)


def reject_duplicate_keys(
        pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Build a mapping from key-value pairs, rejecting duplicates.

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


def song_number(song_id: str) -> int:
    """Return the song number carried by a song ID.

    :param song_id: The song ID, expected as ``song-<N>``.
    :return: The song number.
    :raises ValueError: When the song ID is not ``song-<N>``.
    """
    prefix: str = "song-"
    if not song_id.startswith(prefix) \
            or not song_id[len(prefix):].isdigit():
        raise ValueError(
            f"id \"{song_id}\": not in \"song-<N>\" form")
    return int(song_id[len(prefix):])


def load_run(run_dir: Path) -> Codings:
    """Load and validate the coding of one coding run.

    Every record must carry a "text" field parsing to a JSON
    object; a record that does not fails the run.  Lines are split
    on the newline character alone, as the quoted lyrics may carry
    other control characters that are not line breaks here.

    :param run_dir: The run's archive directory, containing
        ``output.jsonl``.
    :return: The keyword assignments of every song, keyed by the
        song ID, in file order.
    :raises OSError: When ``output.jsonl`` cannot be read.
    :raises ValueError: When a line is not a well-formed output
        record, a "text" field does not parse to a JSON object, a
        JSON document holds a duplicate key, or a song ID appears
        more than once.
    """
    path: Path = run_dir / "output.jsonl"
    text: str = path.read_text(encoding="utf-8")
    codings: Codings = {}
    line: str
    for line in text.split("\n"):
        if line.strip() == "":
            continue
        record: Any = json.loads(
            line, object_pairs_hook=reject_duplicate_keys)
        if not isinstance(record, dict) or "id" not in record:
            raise ValueError(
                f"{path}: record without \"id\": {line}")
        song_id: str = record["id"]
        try:
            song_number(song_id)
        except ValueError as error:
            raise ValueError(f"{path}: {error}") from error
        if "text" not in record:
            raise ValueError(
                f"{path}: id {song_id}: record without \"text\"")
        if song_id in codings:
            raise ValueError(
                f"{path}: id {song_id}: duplicate song ID")
        try:
            coding: Any = json.loads(
                record["text"],
                object_pairs_hook=reject_duplicate_keys)
        except json.JSONDecodeError as error:
            raise ValueError(
                f"{path}: id {song_id}: \"text\" does not parse as"
                f" JSON: {error}") from error
        if not isinstance(coding, dict):
            raise ValueError(
                f"{path}: id {song_id}: \"text\" does not parse to"
                " a JSON object")
        codings[song_id] = coding
    return codings


def compare_codings(
        codings1: Codings,
        codings2: Codings) -> tuple[AgreedKeywords, Codings]:
    """Compare the codings of two runs of the same songs.

    The comparison is by keyword key set alone; the quotes never
    take part in it.  A keyword assigned by both runs is agreed,
    and is returned by its name alone, without quotes.  A keyword
    assigned by exactly one run is a disagreement, and carries the
    quotes of the run that assigned it.  A song with no agreed
    keyword has no entry in the agreed half, and a song the two
    runs fully agree on has no entry in the disagreement half.
    Both halves are ordered by ascending song number, and every
    song's keywords lexicographically.

    :param codings1: The first run's coding of every song, keyed
        by the song ID.
    :param codings2: The second run's coding of every song, keyed
        by the song ID.
    :return: The per-song agreed keyword names and the per-song
        disagreed keywords with their quotes.
    :raises ValueError: When the two runs do not cover exactly the
        same set of song IDs, or a song ID is not ``song-<N>``.
    """
    only1: set[str] = set(codings1) - set(codings2)
    only2: set[str] = set(codings2) - set(codings1)
    if len(only1) > 0 or len(only2) > 0:
        raise ValueError(
            "the two runs do not cover the same songs:"
            f" {len(only1)} only in the first run"
            f" ({', '.join(sorted(only1)[:5])}),"
            f" {len(only2)} only in the second run"
            f" ({', '.join(sorted(only2)[:5])})")
    agreed: AgreedKeywords = {}
    disagreed: Codings = {}
    song_id: str
    for song_id in sorted(codings1, key=song_number):
        coding1: Coding = codings1[song_id]
        coding2: Coding = codings2[song_id]
        song_agreed: list[str] = []
        song_disagreed: Coding = {}
        keyword: str
        for keyword in sorted(set(coding1) | set(coding2)):
            if keyword in coding1 and keyword in coding2:
                song_agreed.append(keyword)
            elif keyword in coding1:
                song_disagreed[keyword] = coding1[keyword]
            else:
                song_disagreed[keyword] = coding2[keyword]
        if len(song_agreed) > 0:
            agreed[song_id] = song_agreed
        if len(song_disagreed) > 0:
            disagreed[song_id] = song_disagreed
    return agreed, disagreed


def count_keywords(codings: Codings) -> int:
    """Count the keywords of every song of a coding.

    :param codings: The keyword assignments of every song, keyed
        by the song ID.
    :return: The total number of keyword assignments.
    """
    return sum(len(x) for x in codings.values())


def write_disagreements(path: Path,
                        disagreements: Codings) -> None:
    """Write the per-song disagreement JSON file.

    Writes a JSON file holding a single object mapping the song ID
    to the disagreed keywords of that song, each with the quotes of
    the run that assigned it, in the given order, UTF-8, with a
    trailing newline.  Only the songs the two runs disagree on are
    written.

    :param path: The path of the disagreement JSON file to write.
    :param disagreements: The disagreed keywords of every song,
        keyed by the song ID.
    :return: None.
    :raises OSError: When the file cannot be written.
    """
    path.write_text(
        json.dumps(disagreements, ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    """Compare the two coding runs and export the disagreements.

    Writes the disagreement JSON file under the output directory,
    creating it (with parents) if it does not exist.  When the
    input is rejected, the file is not written.

    :param argv: The command-line arguments, or None for
        ``sys.argv``.
    :return: The exit status: 0 on success, non-zero on failure.
    """
    started: float = time.monotonic()
    args: argparse.Namespace = parse_args(argv)
    codings1: Codings
    disagreements: Codings
    try:
        codings1 = load_run(args.run_dir_1)
        codings2: Codings = load_run(args.run_dir_2)
        disagreements = compare_codings(codings1, codings2)[1]
    except (OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_disagreements(
        args.output_dir / DISAGREEMENTS_JSON, disagreements)
    elapsed: str = format_duration(time.monotonic() - started)
    print(
        f"Done.  {len(disagreements)} of {len(codings1)} songs"
        f" disagree on {count_keywords(disagreements)} keywords."
        f"  {elapsed} elapsed.",
        file=sys.stderr)
    return 0
