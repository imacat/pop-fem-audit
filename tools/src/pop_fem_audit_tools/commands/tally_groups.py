# Tools for A Feminist Audit of Pop Music.
# Copyright 2026 imacat.  All rights reserved.
# Authors:
#   imacat@mail.imacat.idv.tw (imacat), 2026/8/15
# AI assistance: Claude Code (Anthropic)
"""The majority tally of the three group-selection runs.

Settles the semantic code groups of step 4: the same group
selection definition file is run three times independently, and
this command counts the votes and writes the final group table
the paper cites.  A (group, keyword) pair is written out when at
least two of the three runs select it.  When an input is
malformed, the tally fails and nothing is written; the error
message names what failed.
"""
import argparse
import csv
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

from ..utils import format_duration


class TallyError(Exception):
    """An error that fails the group tally."""


@dataclass(frozen=True)
class TalliedGroups:
    """The outcome of settling the group table."""

    codes: int
    """The number of settled (group, keyword) pairs."""
    groups: int
    """The number of groups the three runs cover."""


class GroupTallier:
    """The tallier of the three group-selection runs' votes."""

    __GROUP_ID_PREFIX: ClassVar[str] = "group-"
    """The prefix every group record ID must carry; the group
    name is the rest of the ID."""
    __MAJORITY: ClassVar[int] = 2
    """The number of runs that must select a keyword for a group
    for that pair to be settled."""
    __HEADER: ClassVar[tuple[str, str, str]] \
        = ("Group", "Keyword", "Votes")
    """The header row of the group table CSV file."""

    def __init__(self, run_dir_1: Path, run_dir_2: Path,
                 run_dir_3: Path, valid_keywords_txt: Path,
                 output_csv: Path) -> None:
        """Set up the tallier of the three selection runs.

        :param run_dir_1: The first selection run's archive
            directory, containing ``output.jsonl``.
        :param run_dir_2: The second selection run's archive
            directory, containing ``output.jsonl``.
        :param run_dir_3: The third selection run's archive
            directory, containing ``output.jsonl``.
        :param valid_keywords_txt: The plain text file of the
            allowed keywords, one per line.
        :param output_csv: The output group table CSV file.
        """
        self.__run_dirs: list[Path] = [
            run_dir_1, run_dir_2, run_dir_3]
        """The three runs' archive directories, in the given
        order."""
        self.__valid_keywords_txt: Path = valid_keywords_txt
        """The plain text file of the allowed keywords, one per
        line."""
        self.__output_csv: Path = output_csv
        """The output group table CSV file."""

    def run(self) -> TalliedGroups:
        """Load the three runs, tally their votes, and write the
        table.

        :return: The settled code count and the group count.
        :raises TallyError: When a file cannot be read, a line is
            not a well-formed output record, a record is not a
            successful result, an ID lacks the ``group-`` prefix,
            a group has two records, a "text" does not parse to a
            JSON array of strings, or the three runs do not cover
            the same set of groups.
        :raises OSError: When the output file cannot be written.
        """
        valid: set[str] = self.__load_valid_keywords(
            self.__valid_keywords_txt)
        runs: list[dict[str, set[str]]] = [
            self.__load_run(x) for x in self.__run_dirs]
        self.__drop_invalid(runs, self.__run_dirs, valid)
        rows: list[tuple[str, str, int]] = self.__tally(runs)
        self.__write_csv(rows)
        return TalliedGroups(codes=len(rows), groups=len(runs[0]))

    @staticmethod
    def __load_valid_keywords(path: Path) -> set[str]:
        """Load the valid keyword list.

        :param path: The plain text file of the allowed keywords,
            one per line.
        :return: The allowed keywords.
        :raises TallyError: When the file cannot be read or holds
            no keyword.
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

    @classmethod
    def __load_run(cls, run_dir: Path) -> dict[str, set[str]]:
        """Load and validate the selection records of one run.

        :param run_dir: The run's archive directory, containing
            ``output.jsonl``.
        :return: The selected keywords of every group of the run,
            keyed by the group name, the duplicates within one
            record's selection collapsed.
        :raises TallyError: When the file cannot be read, a line
            is not a well-formed output record, a record is not a
            successful result, an ID lacks the ``group-`` prefix,
            a group has two records, or a "text" does not parse
            to a JSON array of strings.
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
            item_id: Any = record["id"]
            if "text" not in record:
                raise TallyError(
                    f"{path}: id {item_id}: not a successful"
                    " result")
            if not isinstance(item_id, str) \
                    or not item_id.startswith(
                        cls.__GROUP_ID_PREFIX) \
                    or item_id == cls.__GROUP_ID_PREFIX:
                raise TallyError(
                    f"{path}: id {item_id}: not in the"
                    f" \"{cls.__GROUP_ID_PREFIX}<name>\" form")
            group: str = item_id[len(cls.__GROUP_ID_PREFIX):]
            if group in records:
                raise TallyError(
                    f"{path}: id {item_id}: duplicate record")
            records[group] = cls.__parse_selection(
                record["text"], f"{path}: id {item_id}")
        return records

    @staticmethod
    def __parse_selection(text: Any, label: str) -> set[str]:
        """Parse and validate the selected keywords of one record.

        :param text: The "text" field of the record.
        :param label: The location of the record, for the error
            message.
        :return: The selected keywords, the duplicates collapsed.
        :raises TallyError: When the text does not parse to a
            JSON array of strings.
        """
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
                f"{label}: \"text\" does not parse to a JSON"
                " array of strings")
        return set(selected)

    @staticmethod
    def __drop_invalid(runs: list[dict[str, set[str]]],
                       run_dirs: list[Path],
                       valid: set[str]) -> None:
        """Drop the out-of-vocabulary selections of every run.

        Every dropped occurrence is reported on standard error as
        an observable side effect.

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

    @classmethod
    def __tally(cls, runs: list[dict[str, set[str]]]) \
            -> list[tuple[str, str, int]]:
        """Tally the keyword votes of the runs, group by group.

        :param runs: The runs' records, all covering the same set
            of groups.
        :return: The settled rows, each the group name, the
            keyword, and the number of votes, ordered by the
            group name and then by the keyword, by Unicode code
            point.
        :raises TallyError: When the runs do not cover the same
            set of groups.
        """
        groups: set[str] = set(runs[0])
        records: dict[str, set[str]]
        for records in runs[1:]:
            if set(records) != groups:
                raise TallyError(
                    "the three runs do not cover the same"
                    " groups: " + ", ".join(sorted(
                        groups.symmetric_difference(
                            set(records)))))
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
                for x in sorted(votes) if votes[x] >= cls.__MAJORITY)
        return rows

    def __write_csv(self, rows: list[tuple[str, str, int]]) \
            -> None:
        """Write the group table CSV file.

        Writes an RFC 4180 CSV file, UTF-8, with CRLF line
        endings, carrying the header row ``Group,Keyword,Votes``
        and one row per settled (group, keyword) pair, in the row
        order.  The parent directory is created when it does not
        exist.

        :param rows: The settled rows, in the output order.
        :return: None.
        :raises OSError: When the file cannot be written.
        """
        self.__output_csv.parent.mkdir(parents=True, exist_ok=True)
        with open(self.__output_csv, "w", encoding="utf-8",
                  newline="") as file:
            writer: Any = csv.writer(file)
            writer.writerow(self.__HEADER)
            writer.writerows(rows)


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
        "output_csv", type=Path,
        help="the output CSV file")
    parser.add_argument(
        "--valid-keywords", type=Path, required=True,
        help="a plain text file of the allowed keywords, one per"
             " line")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Settle the code groups by a majority of the three runs.

    :param argv: The command-line arguments, or None for
        ``sys.argv``.
    :return: The exit status: 0 on success, non-zero on failure.
    """
    started: float = time.monotonic()
    args: argparse.Namespace = parse_args(argv)
    try:
        tallied: TalliedGroups = GroupTallier(
            args.run_dir_1, args.run_dir_2, args.run_dir_3,
            args.valid_keywords, args.output_csv).run()
    except (TallyError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    elapsed: str = format_duration(time.monotonic() - started)
    print(
        f"Done.  Settled {tallied.codes} codes across"
        f" {tallied.groups} groups.  {elapsed} elapsed.",
        file=sys.stderr)
    return 0
