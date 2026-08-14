# Tools for A Feminist Audit of Pop Music.
# Copyright 2026 imacat.  All rights reserved.
# Authors:
#   imacat@mail.imacat.idv.tw (imacat), 2026/8/15
# AI assistance: Claude Code (Anthropic)
"""The majority tally of the three group-selection runs.

Settles the semantic code groups of step 4: the same group
selection definition file is run three times independently, and
this command counts the votes and writes the final group table
the paper cites, as the CSV file given as the last positional
command-line argument.  A (group, keyword) pair is written out
when at least two of the three runs select it, so three votes
never tie.  A selected item that is not in the valid keyword
list is invalid and casts no vote; every dropped occurrence is
reported on standard error.  The group name is the record ID
with its ``group-`` prefix dropped.  The rows are ordered by the
group name and then by the keyword, by Unicode code point, and
the file carries the header row ``Group,Keyword,Votes`` with
CRLF line endings per RFC 4180.

The three archives must cover exactly the same set of group IDs,
every record ID must carry the ``group-`` prefix, and every
record's "text" must parse to a JSON array of strings; otherwise
the tally fails and nothing is written.
"""
import argparse
import csv
import json
import sys
import time
from pathlib import Path
from typing import Any

from ..utils import format_duration

GROUP_ID_PREFIX: str = "group-"
"""The prefix every group record ID must carry; the group name
is the rest of the ID."""
MAJORITY: int = 2
"""The number of runs that must select a keyword for a group for
that pair to be settled."""
HEADER: tuple[str, str, str] = ("Group", "Keyword", "Votes")
"""The header row of the group table CSV file."""


class TallyError(Exception):
    """An error that fails the group tally."""


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Parse the command-line arguments.

    :param argv: The command-line arguments, or None for
        ``sys.argv``.
    :return: The parsed arguments.
    """
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description="Settle the semantic code groups by a"
                    " majority of the three selection runs.")
    parser.add_argument(
        "run_dir_1", type=Path,
        help="the first selection run's archive directory")
    parser.add_argument(
        "run_dir_2", type=Path,
        help="the second selection run's archive directory")
    parser.add_argument(
        "run_dir_3", type=Path,
        help="the third selection run's archive directory")
    parser.add_argument(
        "valid_keywords", type=Path,
        help="a plain text file of the allowed keywords, one per"
             " line")
    parser.add_argument(
        "output_csv", type=Path,
        help="the output CSV file, by convention"
             " results/groups.csv")
    return parser.parse_args(argv)


def load_valid_keywords(path: Path) -> set[str]:
    """Load the valid keyword list.

    :param path: The plain text file of the allowed keywords, one
        per line.
    :return: The allowed keywords.
    :raises TallyError: When the file cannot be read or holds no
        keyword.
    """
    text: str
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise TallyError(str(error)) from error
    keywords: set[str] = {x.strip() for x in text.split("\n")
                          if x.strip() != ""}
    if len(keywords) == 0:
        raise TallyError(f"{path}: no keywords")
    return keywords


def load_run(run_dir: Path) -> dict[str, set[str]]:
    """Load and validate the selection records of one run.

    :param run_dir: The run's archive directory, containing
        ``output.jsonl``.
    :return: The selected keywords of every group of the run,
        keyed by the group name, the duplicates within one
        record's selection collapsed.
    :raises TallyError: When the file cannot be read, a line is
        not a well-formed output record, a record is not a
        successful result, an ID lacks the ``group-`` prefix, a
        group has two records, or a "text" does not parse to a
        JSON array of strings.
    """
    path: Path = run_dir / "output.jsonl"
    text: str
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise TallyError(str(error)) from error
    records: dict[str, set[str]] = {}
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
        item_id: Any = record["id"]
        if "error" in record or "text" not in record:
            raise TallyError(
                f"{path}: id {item_id}: not a successful result")
        if not isinstance(item_id, str) \
                or not item_id.startswith(GROUP_ID_PREFIX) \
                or item_id == GROUP_ID_PREFIX:
            raise TallyError(
                f"{path}: id {item_id}: not in the"
                f" \"{GROUP_ID_PREFIX}<name>\" form")
        group: str = item_id[len(GROUP_ID_PREFIX):]
        if group in records:
            raise TallyError(
                f"{path}: id {item_id}: duplicate record")
        records[group] = _selection(
            record["text"], f"{path}: id {item_id}")
    if len(records) == 0:
        raise TallyError(f"{path}: no records")
    return records


def _selection(text: Any, label: str) -> set[str]:
    """Parse and validate the selected keywords of one record.

    :param text: The "text" field of the record.
    :param label: The location of the record, for the error
        message.
    :return: The selected keywords, the duplicates collapsed.
    :raises TallyError: When the text does not parse to a JSON
        array of strings.
    """
    if not isinstance(text, str):
        raise TallyError(f"{label}: \"text\" is not a string")
    selected: Any
    try:
        selected = json.loads(text)
    except json.JSONDecodeError as error:
        raise TallyError(
            f"{label}: \"text\" is malformed JSON:"
            f" {error}") from error
    if not isinstance(selected, list) \
            or not all(isinstance(x, str) for x in selected):
        raise TallyError(
            f"{label}: \"text\" does not parse to a JSON array"
            " of strings")
    return set(selected)


def drop_invalid(runs: list[dict[str, set[str]]],
                 run_dirs: list[Path],
                 valid: set[str]) -> None:
    """Drop the out-of-vocabulary selections of every run.

    Every dropped occurrence is reported on standard error as an
    observable side effect.

    :param runs: The runs' records, filtered in place.
    :param run_dirs: The run directories, for the messages.
    :param valid: The allowed keywords.
    :return: None.
    """
    records: dict[str, set[str]]
    run_dir: Path
    for records, run_dir in zip(runs, run_dirs):
        group: str
        selected: set[str]
        for group, selected in records.items():
            keyword: str
            for keyword in sorted(selected - valid):
                print(
                    f"note: {run_dir.name} group-{group}:"
                    f" dropped out-of-vocabulary item"
                    f" \"{keyword}\"", file=sys.stderr)
            records[group] = selected & valid


def tally(runs: list[dict[str, set[str]]]) \
        -> list[tuple[str, str, int]]:
    """Tally the keyword votes of the runs, group by group.

    :param runs: The runs' records, all covering the same set of
        groups.
    :return: The settled rows, each the group name, the keyword,
        and the number of votes, ordered by the group name and
        then by the keyword, by Unicode code point.
    :raises TallyError: When the runs do not cover the same set
        of groups.
    """
    groups: set[str] = set(runs[0])
    records: dict[str, set[str]]
    for records in runs[1:]:
        if set(records) != groups:
            raise TallyError(
                "the three runs do not cover the same groups: "
                + ", ".join(sorted(
                    groups.symmetric_difference(set(records)))))
    rows: list[tuple[str, str, int]] = []
    group: str
    for group in sorted(groups):
        votes: dict[str, int] = {}
        for records in runs:
            keyword: str
            for keyword in records[group]:
                votes[keyword] = votes.get(keyword, 0) + 1
        rows.extend(
            (group, x, votes[x])
            for x in sorted(votes) if votes[x] >= MAJORITY)
    return rows


def write_csv(output_csv: Path,
              rows: list[tuple[str, str, int]]) -> None:
    """Write the group table CSV file.

    Writes an RFC 4180 CSV file, UTF-8, with CRLF line endings,
    carrying the header row ``Group,Keyword,Votes`` and one row
    per settled (group, keyword) pair, in the row order.  The
    parent directory is created when it does not exist.

    :param output_csv: The output CSV file.
    :param rows: The settled rows, in the output order.
    :return: None.
    :raises OSError: When the file cannot be written.
    """
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with open(output_csv, "w", encoding="utf-8",
              newline="") as file:
        writer: Any = csv.writer(file)
        writer.writerow(HEADER)
        writer.writerows(rows)


def main(argv: list[str] | None = None) -> int:
    """Settle the code groups by a majority of the three runs.

    Writes the final group table as the given CSV file, holding
    the header row ``Group,Keyword,Votes`` and one row per
    (group, keyword) pair at least two of the three runs select,
    ordered by the group name and then by the keyword.  A
    selected item that is not in the valid keyword list casts no
    vote, each dropped occurrence reported on standard error.
    Nothing is written when the three archives do not cover the
    same groups, a record is not a successful result, an ID lacks
    the ``group-`` prefix, or a record's "text" does not parse to
    a JSON array of strings; the error message names what failed.

    :param argv: The command-line arguments, or None for
        ``sys.argv``.
    :return: The exit status: 0 on success, non-zero on failure.
    """
    started: float = time.monotonic()
    args: argparse.Namespace = parse_args(argv)
    run_dirs: list[Path] = [
        args.run_dir_1, args.run_dir_2, args.run_dir_3]
    try:
        valid: set[str] = load_valid_keywords(args.valid_keywords)
        runs: list[dict[str, set[str]]] = [
            load_run(x) for x in run_dirs]
        drop_invalid(runs, run_dirs, valid)
        rows: list[tuple[str, str, int]] = tally(runs)
        write_csv(args.output_csv, rows)
    except (TallyError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    elapsed: str = format_duration(time.monotonic() - started)
    print(
        f"Done.  Settled {len(rows)} codes across"
        f" {len(runs[0])} groups.  {elapsed} elapsed.",
        file=sys.stderr)
    return 0
