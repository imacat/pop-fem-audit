# Tools for A Feminist Audit of Pop Music.
# Copyright 2026 imacat.  All rights reserved.
# Authors:
#   imacat@mail.imacat.idv.tw (imacat), 2026/8/5
"""The deterministic clusterer of the pooled keywords.

Builds the coding groups from the pooled keyword list, given as
the first positional command-line argument, by sentence-embedding
every keyword and clustering the embeddings: the group membership,
given as the second positional argument, is written as a CSV file
holding the clustering result alone.  The group name keywords
alone, given as the third positional argument, are written as a
text file, one per line.  The coding keyword set for
``export-llm-input --extras``, given as the fourth positional
argument, is written as a JSON file holding the group name
keywords plus the researcher's a-priori topic term (see
:data:`EXTRA_KEYWORD`).  The step is fully deterministic; no LLM
call is made.
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
DEFAULT_CLUSTERS: int = 50
CLUSTER_EXTRA_MESSAGE: str = (
    "cluster-keywords requires the optional \"cluster\""
    " dependency group; install it with"
    " pip install -e \"tools/[cluster]\"")
"""The error message shown when the heavy clustering dependencies
are not installed."""
EXTRA_KEYWORD: str = "women-power"
"""The researcher's a-priori topic term, included in the coding
keyword set although it is not a clustering result."""


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Parse the command-line arguments.

    :param argv: The command-line arguments, or None for
        ``sys.argv``.
    :return: The parsed arguments.
    """
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description="Build the coding groups by clustering the"
                    " sentence embeddings of the pooled"
                    " keywords.")
    parser.add_argument(
        "pool_txt", type=Path,
        help="the pooled keyword list, one keyword per line")
    parser.add_argument(
        "groups_csv", type=Path,
        help="the group membership CSV output file")
    parser.add_argument(
        "keywords_txt", type=Path,
        help="the group name keyword text output file")
    parser.add_argument(
        "keywords_to_merge_json", type=Path,
        help="the coding keyword set JSON output file")
    parser.add_argument(
        "--model", default=MODEL,
        help=f"the sentence embedding model (default \"{MODEL}\")")
    parser.add_argument(
        "--revision", default=None,
        help="the model revision to pin (default: unpinned)")
    parser.add_argument(
        "--clusters", type=int, default=DEFAULT_CLUSTERS,
        help=f"the number of clusters (default {DEFAULT_CLUSTERS})")
    return parser.parse_args(argv)


def load_keywords(path: Path) -> list[str]:
    """Load and validate the pooled keyword list.

    :param path: The path of the pooled keyword text file, one
        keyword per line.
    :return: The keywords, in file order.
    :raises OSError: When the file cannot be read.
    :raises ValueError: When the file has no keyword, or a
        keyword is duplicated.
    """
    text: str = path.read_text(encoding="utf-8")
    lines: list[str] = text.split("\n")
    if len(lines) > 0 and lines[-1] == "":
        lines = lines[:-1]
    if len(lines) == 0:
        raise ValueError(f"{path}: no keywords")
    seen: set[str] = set()
    keyword: str
    for keyword in lines:
        if keyword in seen:
            raise ValueError(
                f"{path}: duplicate keyword \"{keyword}\"")
        seen.add(keyword)
    return lines


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
    :data:`EXTRA_KEYWORD`.

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
    alone; it holds no :data:`EXTRA_KEYWORD` line.

    :param path: The path of the keyword text file to write.
    :param groups: The keyword members of every group, keyed by
        the group's medoid name.
    :return: None.
    :raises OSError: When the file cannot be written.
    """
    names: list[str] = sorted(groups.keys())
    path.write_text(
        "".join(f"{x}\n" for x in names), encoding="utf-8")


def write_keywords_to_merge(path: Path,
                            groups: dict[str, list[str]]) -> None:
    """Write the coding keyword set JSON file.

    Writes a JSON file holding a single object with one
    ``keywords`` key, whose value is the lexicographically
    sorted list of the group names plus :data:`EXTRA_KEYWORD`,
    UTF-8, with a trailing newline.  This is the file
    ``export-llm-input --extras`` consumes.

    :param path: The path of the keyword JSON file to write.
    :param groups: The keyword members of every group, keyed by
        the group's medoid name.
    :return: None.
    :raises OSError: When the file cannot be written.
    """
    keywords: list[str] = sorted(
        [*groups.keys(), EXTRA_KEYWORD])
    data: dict[str, list[str]] = {"keywords": keywords}
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    """Cluster the pooled keywords into the coding groups.

    Writes the group membership CSV file, holding the clustering
    result alone; the group name keyword text file, holding the
    same group names as a readable list; and the coding keyword
    set JSON file, holding the group names plus
    :data:`EXTRA_KEYWORD`.

    :param argv: The command-line arguments, or None for
        ``sys.argv``.
    :return: The exit status: 0 on success, non-zero on failure.
    """
    started: float = time.monotonic()
    args: argparse.Namespace = parse_args(argv)
    try:
        keywords: list[str] = load_keywords(args.pool_txt)
    except (OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    try:
        embeddings: Any = encode_keywords(
            keywords, args.model, args.revision)
        labels: Any = cluster_embeddings(embeddings, args.clusters)
        groups: dict[str, list[str]] = build_groups(
            keywords, embeddings, labels)
    except (RuntimeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    args.groups_csv.parent.mkdir(parents=True, exist_ok=True)
    args.keywords_txt.parent.mkdir(parents=True, exist_ok=True)
    args.keywords_to_merge_json.parent.mkdir(
        parents=True, exist_ok=True)
    write_groups(args.groups_csv, groups)
    write_keyword_names(args.keywords_txt, groups)
    write_keywords_to_merge(args.keywords_to_merge_json, groups)
    elapsed: str = format_duration(time.monotonic() - started)
    print(
        f"done: {len(keywords)} keywords clustered into"
        f" {len(groups)} groups.  {elapsed} elapsed.",
        file=sys.stderr)
    return 0
