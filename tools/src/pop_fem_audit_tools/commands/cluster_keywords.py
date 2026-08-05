# Tools for A Feminist Audit of Pop Music.
# Copyright 2026 imacat.  All rights reserved.
# Authors:
#   imacat@mail.imacat.idv.tw (imacat), 2026/8/5
"""The deterministic vocabulary-building step.

Goes from the two tagging runs' archives straight to the coding
vocabulary, writing five fixed-named artifacts under the output
directory given as the third positional command-line argument.
First, the keywords produced by the two runs of the tagging step
are pooled into the pooled keyword list, per the project's handoff
contract: the pool is the plain union of every keyword key observed
across both runs' valid records, exact-string deduplicated and
sorted, written as a plain text file with one keyword per line, as
:data:`SOURCE_KEYWORDS_TXT`.  The provenance mapping records where
every keyword came from for audit purposes as a CSV file, as
:data:`SOURCE_PROVENANCE_CSV`; it never enters any LLM input.  Then
the coding groups are built from the pooled keyword list by
sentence-embedding every keyword and clustering the embeddings: the
group membership is written as a CSV file holding the clustering
result alone, as :data:`RESULT_GROUPS_CSV`.  The group name
keywords alone are written as a text file, one per line, as
:data:`RESULT_KEYWORDS_TXT`.  The coding keyword set for
``export-llm-input --extras`` is written as a JSON file holding the
group name keywords plus every extra a-priori keyword the caller
gives with the repeatable ``--extra-keyword`` command-line option,
as :data:`KEYWORDS_TO_MERGE_JSON`; with no ``--extra-keyword``, it
holds the group names alone.  No default extra keyword is ever
injected; the caller supplies each one consciously.  The step is
fully deterministic; no LLM call is made.
"""
import argparse
import csv
import json
import sys
import time
from pathlib import Path
from typing import Any

from ..utils import format_duration

MODEL: str = "sentence-transformers/all-mpnet-base-v2"
CLUSTER_EXTRA_MESSAGE: str = (
    "cluster-keywords requires the optional \"cluster\""
    " dependency group; install it with"
    " pip install -e \"tools/[cluster]\"")
"""The error message shown when the heavy clustering dependencies
are not installed."""
SOURCE_KEYWORDS_TXT: str = "source-keywords.txt"
"""The pooled keyword text file's fixed name under the output
directory."""
SOURCE_PROVENANCE_CSV: str = "source-provenance.csv"
"""The keyword provenance CSV file's fixed name under the output
directory."""
RESULT_KEYWORDS_TXT: str = "result-keywords.txt"
"""The group name keyword text file's fixed name under the output
directory."""
RESULT_GROUPS_CSV: str = "groups.csv"
"""The group membership CSV file's fixed name under the output
directory."""
KEYWORDS_TO_MERGE_JSON: str = "keywords-to-merge.json"
"""The coding keyword set JSON file's fixed name under the output
directory."""

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
        description="Pool the keywords of the two tagging runs and"
                    " build the coding groups by clustering their"
                    " sentence embeddings.")
    parser.add_argument(
        "run_dir_1", type=Path,
        help="the first tagging run's archive directory")
    parser.add_argument(
        "run_dir_2", type=Path,
        help="the second tagging run's archive directory")
    parser.add_argument(
        "output_dir", type=Path,
        help="the output directory, created if missing, that"
             f" receives {SOURCE_KEYWORDS_TXT},"
             f" {SOURCE_PROVENANCE_CSV}, {RESULT_KEYWORDS_TXT},"
             f" {RESULT_GROUPS_CSV}, and"
             f" {KEYWORDS_TO_MERGE_JSON}")
    parser.add_argument(
        "--model", default=MODEL,
        help=f"the sentence embedding model (default \"{MODEL}\")")
    parser.add_argument(
        "--revision", default=None,
        help="the model revision to pin (default: unpinned)")
    parser.add_argument(
        "--clusters", type=int, required=True,
        help="the number of clusters; required, so that the\n"
             "group count is stated on every invocation")
    parser.add_argument(
        "--extra-keyword", dest="extra_keywords", action="append",
        default=None,
        help="an extra a-priori keyword to add to"
             f" {KEYWORDS_TO_MERGE_JSON} alongside the clustered"
             " group names; repeatable; may be given any number"
             " of times; not added to any other output file"
             " (default: none)")
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


def encode_keywords(keywords: list[str], model_name: str,
                    revision: str | None) -> Any:
    """Encode the keywords into L2-normalized sentence embeddings.

    :param keywords: The keywords to encode.
    :param model_name: The sentence embedding model name.
    :param revision: The model revision to pin, or None to use
        the model's default revision.
    :return: The float32 embeddings, one row per keyword, in the
        given order.
    :raises RuntimeError: When the optional clustering
        dependencies are not installed.
    """
    try:
        import numpy as np
        from sentence_transformers import SentenceTransformer
    except ImportError as error:
        raise RuntimeError(CLUSTER_EXTRA_MESSAGE) from error
    kwargs: dict[str, Any] = {}
    if revision is not None:
        kwargs["revision"] = revision
    model: Any = SentenceTransformer(
        model_name, device="cpu", **kwargs)
    texts: list[str] = [x.replace("-", " ") for x in keywords]
    embeddings: Any = model.encode(
        texts, normalize_embeddings=True)
    return np.asarray(embeddings, dtype=np.float32)


def cluster_embeddings(embeddings: Any, n_clusters: int) -> Any:
    """Cluster the embeddings with ward-linkage agglomeration.

    :param embeddings: The float32 embeddings, one row per
        keyword.
    :param n_clusters: The number of clusters to form.
    :return: The cluster label of each embedding, in the given
        order.
    :raises RuntimeError: When the optional clustering
        dependencies are not installed.
    """
    try:
        from sklearn.cluster import AgglomerativeClustering
    except ImportError as error:
        raise RuntimeError(CLUSTER_EXTRA_MESSAGE) from error
    clustering: Any = AgglomerativeClustering(
        n_clusters=n_clusters, linkage="ward")
    return clustering.fit_predict(embeddings)


def build_groups(keywords: list[str], embeddings: Any,
                 labels: Any) -> dict[str, list[str]]:
    """Group the keywords by cluster label, named by their medoid.

    The group name is its medoid: the member whose embedding has
    the highest dot product with the cluster's mean vector
    re-normalized to unit length.  Ties break toward the
    lexicographically smallest member.

    :param keywords: The keywords, in embedding row order.
    :param embeddings: The float32 embeddings, one row per
        keyword.
    :param labels: The cluster label of each keyword, in the same
        order.
    :return: The keyword members of every group, keyed by the
        group's medoid name.
    :raises RuntimeError: When the optional clustering
        dependencies are not installed.
    :raises ValueError: When two clusters yield the same medoid
        name.
    """
    try:
        import numpy as np
    except ImportError as error:
        raise RuntimeError(CLUSTER_EXTRA_MESSAGE) from error
    clusters: dict[int, list[int]] = {}
    index: int
    label: int
    for index, label in enumerate(labels):
        clusters.setdefault(int(label), []).append(index)
    groups: dict[str, list[str]] = {}
    indices: list[int]
    for indices in clusters.values():
        members: list[str] = [keywords[x] for x in indices]
        vectors: Any = embeddings[indices]
        mean_vector: Any = vectors.mean(axis=0)
        norm: float = float(np.linalg.norm(mean_vector))
        direction: Any = (
            mean_vector / norm if norm > 0 else mean_vector)
        scores: Any = vectors @ direction
        best_score: float = float(scores.max())
        medoid: str = min(
            member for member, score in zip(members, scores)
            if float(score) == best_score)
        if medoid in groups:
            raise ValueError(
                f"duplicate medoid group name \"{medoid}\"")
        groups[medoid] = members
    return groups


def write_groups(path: Path, groups: dict[str, list[str]]) -> None:
    """Write the group membership CSV file.

    Writes a CSV file with the header row ``Group,Keyword``, one
    row per member keyword.  Rows are sorted by group name
    lexicographically, then by keyword lexicographically.  The
    file records the clustering result alone; it holds no row for
    any ``--extra-keyword`` given on the command line.

    :param path: The path of the group membership CSV file to
        write.
    :param groups: The keyword members of every group, keyed by
        the group's medoid name.
    :return: None.
    :raises OSError: When the file cannot be written.
    """
    group: str
    with open(path, "w", encoding="utf-8", newline="") as file:
        writer: Any = csv.writer(file)
        writer.writerow(["Group", "Keyword"])
        for group in sorted(groups.keys()):
            keyword: str
            for keyword in sorted(groups[group]):
                writer.writerow([group, keyword])


def write_keyword_names(path: Path,
                        groups: dict[str, list[str]]) -> None:
    """Write the group name keyword text file.

    Writes a text file holding the lexicographically sorted
    group names, one per line, UTF-8, LF line endings, with a
    trailing newline.  The file records the clustering result
    alone; it holds no line for any ``--extra-keyword`` given on
    the command line.

    :param path: The path of the keyword text file to write.
    :param groups: The keyword members of every group, keyed by
        the group's medoid name.
    :return: None.
    :raises OSError: When the file cannot be written.
    """
    names: list[str] = sorted(groups.keys())
    path.write_text(
        "".join(f"{x}\n" for x in names), encoding="utf-8")


def validate_extra_keywords(
        extra_keywords: list[str],
        groups: dict[str, list[str]]) -> None:
    """Validate the extra keywords given on the command line.

    :param extra_keywords: The extra keywords given via
        ``--extra-keyword``, in the given order.
    :param groups: The keyword members of every group, keyed by
        the group's medoid name.
    :return: None.
    :raises ValueError: When an extra keyword duplicates a
        clustered group name or another extra keyword.
    """
    seen: set[str] = set()
    keyword: str
    for keyword in extra_keywords:
        if keyword in groups:
            raise ValueError(
                f"extra keyword \"{keyword}\" duplicates a"
                " clustered group name")
        if keyword in seen:
            raise ValueError(
                f"extra keyword \"{keyword}\" given more than"
                " once")
        seen.add(keyword)


def write_keywords_to_merge(path: Path,
                            groups: dict[str, list[str]],
                            extra_keywords: list[str]) -> None:
    """Write the coding keyword set JSON file.

    Writes a JSON file holding a single object with one
    ``keywords`` key, whose value is the lexicographically
    sorted list of the group names plus every given extra
    keyword, UTF-8, with a trailing newline.  With no extra
    keyword, the list holds the group names alone.  This is the
    file ``export-llm-input --extras`` consumes.

    :param path: The path of the keyword JSON file to write.
    :param groups: The keyword members of every group, keyed by
        the group's medoid name.
    :param extra_keywords: The extra a-priori keywords given via
        ``--extra-keyword``, to include alongside the group
        names.
    :return: None.
    :raises OSError: When the file cannot be written.
    """
    keywords: list[str] = sorted(
        [*groups.keys(), *extra_keywords])
    data: dict[str, list[str]] = {"keywords": keywords}
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    """Pool the two tagging runs' keywords and cluster them.

    Writes the five fixed-named artifacts under the output
    directory, creating it (with parents) if it does not exist:
    the pooled keyword text file and the keyword provenance CSV
    file; then the group membership CSV file, holding the
    clustering result alone; the group name keyword text file,
    holding the same group names as a readable list; and the
    coding keyword set JSON file, holding the group names plus
    every extra keyword given via ``--extra-keyword``.  When the
    input is rejected, or an extra keyword duplicates a group
    name or another extra keyword, none of the five files is
    written.

    :param argv: The command-line arguments, or None for
        ``sys.argv``.
    :return: The exit status: 0 on success, non-zero on failure.
    """
    started: float = time.monotonic()
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
    try:
        embeddings: Any = encode_keywords(
            keywords, args.model, args.revision)
        labels: Any = cluster_embeddings(embeddings, args.clusters)
        groups: dict[str, list[str]] = build_groups(
            keywords, embeddings, labels)
    except (RuntimeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    extra_keywords: list[str] = args.extra_keywords or []
    try:
        validate_extra_keywords(extra_keywords, groups)
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_pool(
        args.output_dir / SOURCE_KEYWORDS_TXT, keywords)
    write_provenance(
        args.output_dir / SOURCE_PROVENANCE_CSV, provenance)
    write_groups(args.output_dir / RESULT_GROUPS_CSV, groups)
    write_keyword_names(
        args.output_dir / RESULT_KEYWORDS_TXT, groups)
    write_keywords_to_merge(
        args.output_dir / KEYWORDS_TO_MERGE_JSON, groups,
        extra_keywords)
    elapsed: str = format_duration(time.monotonic() - started)
    print(
        f"done: {len(keywords)} keywords pooled from"
        f" {len(run1[1])}+{len(run2[1])} records, clustered into"
        f" {len(groups)} groups.  {elapsed} elapsed.",
        file=sys.stderr)
    return 0
