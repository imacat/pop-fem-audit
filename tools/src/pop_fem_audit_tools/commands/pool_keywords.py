# Tools for A Feminist Audit of Pop Music.
# Copyright 2026 imacat.  All rights reserved.
# Authors:
#   imacat@mail.imacat.idv.tw (imacat), 2026/8/5
"""The deterministic pooler of the tagging runs' keywords.

Pools the keywords produced by the two runs of the tagging step
into the clustering step's input, given as the third positional
command-line argument, per the project's handoff contract: the
pool is the plain union of every keyword key observed across both
runs' valid records, exact-string deduplicated and sorted, written
as a plain text file with one keyword per line.  The provenance
mapping, given as the fourth positional argument, records where
every keyword came from for audit purposes as a CSV file; it never
enters any LLM input.
"""
import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

type Records = list[tuple[int, dict[str, Any]]]
"""The valid records of one run: (song ID, keyword mapping) pairs."""

type Provenance = dict[str, list[tuple[str, int]]]
"""The occurrences of every keyword, keyed by the keyword."""


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Parse the command-line arguments.

    :param argv: The command-line arguments, or None for
        ``sys.argv``.
    :return: The parsed arguments.
    """
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description="Pool the keywords of the two tagging runs"
                    " into the clustering step's input.")
    parser.add_argument(
        "run_dir_1", type=Path,
        help="the first tagging run's archive directory")
    parser.add_argument(
        "run_dir_2", type=Path,
        help="the second tagging run's archive directory")
    parser.add_argument(
        "pool_txt", type=Path,
        help="the pooled keyword text output file, one keyword"
             " per line")
    parser.add_argument(
        "provenance_csv", type=Path,
        help="the keyword provenance CSV output file")
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


def parse_song_id(item_id: str, path: Path) -> int:
    """Parse the integer song ID out of an item ID.

    :param item_id: The item ID, expected as ``song-<ID>``.
    :param path: The output file the ID came from, for the error
        message.
    :return: The parsed song ID.
    :raises ValueError: When the item ID is not ``song-<ID>``.
    """
    prefix: str = "song-"
    if not item_id.startswith(prefix) \
            or not item_id[len(prefix):].isdigit():
        raise ValueError(
            f"{path}: id \"{item_id}\": not in \"song-<ID>\" form")
    return int(item_id[len(prefix):])


def load_run(run_dir: Path) -> tuple[str, Records]:
    """Load and validate the keyword records of one tagging run.

    Records carrying an "error" field are skipped.  A "text"
    field that fails to parse as JSON is a refusal and is
    skipped; a "text" field that parses to anything other than a
    JSON object, or whose keys are not unique, fails the run.

    :param run_dir: The run's archive directory, containing
        ``output.jsonl``.
    :return: The run label (the directory's basename) and its
        valid records, each the song ID and the parsed keyword
        mapping, in file order.
    :raises OSError: When ``output.jsonl`` cannot be read.
    :raises ValueError: When a line is not a well-formed output
        record, or a "text" field is invalid per the rules above.
    """
    path: Path = run_dir / "output.jsonl"
    text: str = path.read_text(encoding="utf-8")
    records: Records = []
    line: str
    for line in text.split("\n"):
        if line.strip() == "":
            continue
        record: Any = json.loads(line)
        if not isinstance(record, dict) or "id" not in record:
            raise ValueError(
                f"{path}: record without \"id\": {line}")
        if "error" in record:
            continue
        if "text" not in record:
            raise ValueError(
                f"{path}: id {record['id']}: record without"
                " \"text\" or \"error\"")
        song_id: int = parse_song_id(record["id"], path)
        try:
            keywords: Any = json.loads(
                record["text"],
                object_pairs_hook=reject_duplicate_keys)
        except json.JSONDecodeError:
            continue
        if not isinstance(keywords, dict):
            raise ValueError(
                f"{path}: id {record['id']}: \"text\" does not"
                " parse to a JSON object")
        records.append((song_id, keywords))
    return run_dir.name, records


def pool_keywords(runs: list[tuple[str, Records]],
                  ) -> tuple[list[str], Provenance]:
    """Pool the keywords of the given tagging runs.

    :param runs: The runs, each the run label and its valid
        records (song ID, keyword mapping).
    :return: The sorted, exact-string-deduplicated keyword list
        and the provenance mapping from each keyword to its
        occurrences, sorted by (run label, song ID).
    """
    provenance: Provenance = {}
    label: str
    records: Records
    for label, records in runs:
        song_id: int
        keywords: dict[str, Any]
        for song_id, keywords in records:
            keyword: str
            for keyword in keywords:
                provenance.setdefault(keyword, []).append(
                    (label, song_id))
    for occurrences in provenance.values():
        occurrences.sort()
    return sorted(provenance.keys()), provenance


def write_pool(path: Path, keywords: list[str]) -> None:
    """Write the pooled keyword list as the clustering input.

    Writes a plain text file, one keyword per line, in the given
    order, UTF-8, LF line endings, with a trailing newline.

    :param path: The path of the pool text file to write.
    :param keywords: The sorted, deduplicated keyword list.
    :return: None.
    """
    path.write_text(
        "".join(f"{keyword}\n" for keyword in keywords),
        encoding="utf-8")


def write_provenance(path: Path, provenance: Provenance) -> None:
    """Write the keyword provenance mapping.

    Writes a CSV file with the header row
    ``Keyword,Run,Song``, one row per occurrence, long format.
    Rows are sorted by keyword lexicographically, then by run
    label, then by song ID.

    :param path: The path of the provenance CSV file to write.
    :param provenance: The provenance mapping from each keyword
        to its occurrences (run label, song ID).
    :return: None.
    :raises OSError: When the file cannot be written.
    """
    keyword: str
    with open(path, "w", encoding="utf-8", newline="") as file:
        writer: Any = csv.writer(file)
        writer.writerow(["Keyword", "Run", "Song"])
        for keyword in sorted(provenance.keys()):
            label: str
            song_id: int
            for label, song_id in provenance[keyword]:
                writer.writerow([keyword, label, song_id])


def main(argv: list[str] | None = None) -> int:
    """Pool the two tagging runs' keywords for clustering.

    :param argv: The command-line arguments, or None for
        ``sys.argv``.
    :return: The exit status: 0 on success, non-zero on failure.
    """
    args: argparse.Namespace = parse_args(argv)
    run1: tuple[str, Records]
    run2: tuple[str, Records]
    try:
        run1 = load_run(args.run_dir_1)
        run2 = load_run(args.run_dir_2)
    except (OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    keywords: list[str]
    provenance: Provenance
    keywords, provenance = pool_keywords([run1, run2])
    args.pool_txt.parent.mkdir(parents=True, exist_ok=True)
    args.provenance_csv.parent.mkdir(parents=True, exist_ok=True)
    write_pool(args.pool_txt, keywords)
    write_provenance(args.provenance_csv, provenance)
    print(
        f"done: {len(keywords)} keywords pooled from"
        f" {len(run1[1])}+{len(run2[1])} records", file=sys.stderr)
    return 0
