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
:attr:`PooledKeywords.SOURCE_KEYWORDS_TXT`.  Then the coding groups
are built from the pooled keyword list by sentence-embedding every
keyword and clustering the embeddings into the number of groups
given by the required ``--clusters`` command-line option: the
group membership is written as a CSV file holding the clustering
result alone, as :attr:`KeywordGroups.RESULT_GROUPS_CSV`.  The
group name keywords alone are written as a text file, one per
line, as :attr:`KeywordGroups.RESULT_KEYWORDS_TXT`.  The coding
keyword set for ``export-llm-input --extras`` is written as a JSON
file holding the group name keywords plus every extra a-priori
keyword the caller gives with the repeatable ``--extra-keyword``
command-line option, as
:attr:`KeywordsToMerge.KEYWORDS_TO_MERGE_JSON`.  No default
extra keyword is ever injected; the caller supplies each one
consciously.  Finally, the command-line choices and the
environment that produced the numbers -- neither recoverable from
the committed inputs and outputs -- are written as a JSON file, as
:attr:`RunMeta.META_JSON`.  The step is fully deterministic; no LLM
call is made.
"""
import argparse
import csv
import json
import platform
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

import numpy as np
import sentence_transformers
import sklearn
import torch
import transformers
from sentence_transformers import SentenceTransformer
from sklearn.cluster import AgglomerativeClustering

from ..utils import format_duration


class ClusterError(Exception):
    """An error that fails the clustering."""


@dataclass
class PooledKeywords:
    """The keywords pooled from the two tagging runs."""

    SOURCE_KEYWORDS_TXT: ClassVar[str] = "source-keywords.txt"
    """The pooled keyword text file's fixed name under the output
    directory."""

    keywords: list[str]
    """The union of every keyword key observed across both runs'
    valid records, exact-string deduplicated and lexicographically
    sorted."""
    record_counts: list[int]
    """The number of valid records of the first and the second run,
    in that order."""

    def write(self, output_dir: Path) -> None:
        """Write the pooled keyword list as the clustering input.

        Writes a plain text file, one keyword per line, in the
        pooled order, UTF-8, LF line endings, with a trailing
        newline.

        :param output_dir: The existing output directory.
        :return: None.
        :raises OSError: When the file cannot be written.
        """
        (output_dir / self.SOURCE_KEYWORDS_TXT).write_text(
            "".join(f"{x}\n" for x in self.keywords),
            encoding="utf-8")


class KeywordPooler:
    """The pooler of the two tagging runs' keywords."""

    def __init__(self, run_dir_1: Path, run_dir_2: Path,
                 output_dir: Path) -> None:
        """Set up the pooler of the two tagging runs.

        :param run_dir_1: The first run's archive directory,
            containing ``output.jsonl``.
        :param run_dir_2: The second run's archive directory,
            containing ``output.jsonl``.
        :param output_dir: The existing output directory that
            receives :attr:`PooledKeywords.SOURCE_KEYWORDS_TXT`.
        """
        self.__run_dirs: list[Path] = [run_dir_1, run_dir_2]
        """The two runs' archive directories, in the given
        order."""
        self.__output_dir: Path = output_dir
        """The existing output directory."""

    def run(self) -> PooledKeywords:
        """Load the two tagging runs and pool their keywords.

        Records carrying an "error" field are skipped.  A "text"
        field that fails to parse as JSON is a refusal and is
        skipped; a "text" field that parses to anything other than
        a JSON object, or whose keys are not unique, fails the
        run.  Writes the pooled keyword text file under the output
        directory before returning; nothing is written when the
        run fails.

        :return: The pooled keywords and the two runs' valid
            record counts.
        :raises ClusterError: When an ``output.jsonl`` cannot be
            read, a line is not a well-formed output record, or a
            "text" field is invalid per the rules above.
        :raises OSError: When the output file cannot be written.
        """
        runs: list[list[tuple[int, dict[str, Any]]]]
        try:
            runs = [self.__load_run(x) for x in self.__run_dirs]
        except (OSError, ValueError) as error:
            raise ClusterError(str(error)) from error
        pooled: PooledKeywords = PooledKeywords(
            keywords=self.__pool(runs),
            record_counts=[len(x) for x in runs])
        pooled.write(self.__output_dir)
        return pooled

    @classmethod
    def __load_run(cls, run_dir: Path) \
            -> list[tuple[int, dict[str, Any]]]:
        """Load and validate the keyword records of one run.

        :param run_dir: The run's archive directory, containing
            ``output.jsonl``.
        :return: The run's valid records, each the song ID and the
            parsed keyword mapping, in file order.
        :raises OSError: When ``output.jsonl`` cannot be read.
        :raises ValueError: When a line is not a well-formed
            output record, or a "text" field is invalid.
        """
        path: Path = run_dir / "output.jsonl"
        text: str = path.read_text(encoding="utf-8")
        records: list[tuple[int, dict[str, Any]]] = []
        line: str
        for line in text.split("\n"):
            if line.strip() == "":
                continue
            record: Any = json.loads(line)
            if "error" in record:
                continue
            song_id: int = cls.__parse_song_id(record["id"], path)
            try:
                keywords: Any = json.loads(
                    record["text"],
                    object_pairs_hook=cls.__reject_duplicate_keys)
            except json.JSONDecodeError:
                continue
            if not isinstance(keywords, dict):
                raise ValueError(
                    f"{path}: id {record['id']}: \"text\" does not"
                    " parse to a JSON object")
            records.append((song_id, keywords))
        return records

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
    def __parse_song_id(item_id: str, path: Path) -> int:
        """Parse the integer song ID out of an item ID.

        :param item_id: The item ID, expected as ``song-<ID>``.
        :param path: The output file the ID came from, for the
            error message.
        :return: The parsed song ID.
        :raises ValueError: When the item ID is not
            ``song-<ID>``.
        """
        prefix: str = "song-"
        if not item_id.startswith(prefix) \
                or not item_id[len(prefix):].isdigit():
            raise ValueError(
                f"{path}: id \"{item_id}\": not in \"song-<ID>\""
                " form")
        return int(item_id[len(prefix):])

    @staticmethod
    def __pool(runs: list[list[tuple[int, dict[str, Any]]]]) \
            -> list[str]:
        """Pool the keywords of the given tagging runs.

        :param runs: The runs, each its valid records (song ID,
            keyword mapping).
        :return: The sorted, exact-string-deduplicated keyword
            list.
        """
        pool: set[str] = set()
        records: list[tuple[int, dict[str, Any]]]
        for records in runs:
            keywords: dict[str, Any]
            for _, keywords in records:
                pool.update(keywords)
        return sorted(pool)


@dataclass
class KeywordGroups:
    """The coding groups of the clustered keywords."""

    RESULT_KEYWORDS_TXT: ClassVar[str] = "result-keywords.txt"
    """The group name keyword text file's fixed name under the
    output directory."""
    RESULT_GROUPS_CSV: ClassVar[str] = "groups.csv"
    """The group membership CSV file's fixed name under the output
    directory."""

    groups: dict[str, list[str]]
    """The keyword members of every group, keyed by the group's
    medoid name."""

    @property
    def names(self) -> list[str]:
        """The names of the coding groups.

        :return: The medoid name of every group,
            lexicographically sorted.
        """
        return sorted(self.groups.keys())

    def write(self, output_dir: Path) -> None:
        """Write the group membership and group name files.

        The group membership CSV file carries the header row
        ``Group,Keyword`` and one row per member keyword, sorted
        by group name lexicographically, then by keyword
        lexicographically.  The group name keyword text file
        carries the lexicographically sorted group names, one per
        line, UTF-8, LF line endings, with a trailing newline.
        Both files record the clustering result alone; neither
        holds any ``--extra-keyword`` given on the command line.

        :param output_dir: The existing output directory.
        :return: None.
        :raises OSError: When a file cannot be written.
        """
        group: str
        with open(output_dir / self.RESULT_GROUPS_CSV, "w",
                  encoding="utf-8", newline="") as file:
            writer: Any = csv.writer(file)
            writer.writerow(["Group", "Keyword"])
            for group in self.names:
                keyword: str
                for keyword in sorted(self.groups[group]):
                    writer.writerow([group, keyword])
        (output_dir / self.RESULT_KEYWORDS_TXT).write_text(
            "".join(f"{x}\n" for x in self.names),
            encoding="utf-8")


class KeywordClusterer:
    """The clusterer of the pooled keywords into coding groups."""

    DEFAULT_MODEL: ClassVar[str] \
        = "sentence-transformers/all-mpnet-base-v2"
    """The sentence embedding model used when the caller names
    none."""

    def __init__(self, source: PooledKeywords, model: str,
                 revision: str | None, clusters: int,
                 output_dir: Path) -> None:
        """Set up the clusterer of the pooled keywords.

        :param source: The pooled keywords to cluster.
        :param model: The sentence embedding model name.
        :param revision: The model revision to pin, or None to use
            the model's default revision.
        :param clusters: The number of clusters to form.
        :param output_dir: The existing output directory that
            receives :attr:`KeywordGroups.RESULT_GROUPS_CSV` and
            :attr:`KeywordGroups.RESULT_KEYWORDS_TXT`.
        """
        self.__keywords: list[str] = source.keywords
        """The keywords to cluster, in the pooled order."""
        self.__model: str = model
        """The sentence embedding model name."""
        self.__revision: str | None = revision
        """The model revision to pin, or None to use the model's
        default revision."""
        self.__clusters: int = clusters
        """The number of clusters to form."""
        self.__output_dir: Path = output_dir
        """The existing output directory."""

    def run(self) -> KeywordGroups:
        """Embed the keywords and cluster them into coding groups.

        Writes the group membership CSV file and the group name
        keyword text file under the output directory before
        returning; nothing is written when the run fails.

        :return: The coding groups.
        :raises ClusterError: When the embedding model cannot be
            loaded or run, or two clusters yield the same medoid
            name.
        :raises OSError: When an output file cannot be written.
        """
        groups: KeywordGroups
        try:
            embeddings: Any = self.__encode(
                self.__keywords, self.__model, self.__revision)
            labels: Any = self.__cluster(
                embeddings, self.__clusters)
            groups = KeywordGroups(groups=self.__build_groups(
                self.__keywords, embeddings, labels))
        except (RuntimeError, ValueError) as error:
            raise ClusterError(str(error)) from error
        groups.write(self.__output_dir)
        return groups

    @classmethod
    def __encode(cls, keywords: list[str], model_name: str,
                 revision: str | None) -> Any:
        """Encode the keywords into L2-normalized embeddings.

        :param keywords: The keywords to encode.
        :param model_name: The sentence embedding model name.
        :param revision: The model revision to pin, or None to use
            the model's default revision.
        :return: The float32 embeddings, one row per keyword, in
            the given order.
        """
        kwargs: dict[str, Any] = {}
        if revision is not None:
            kwargs["revision"] = revision
        model: Any = SentenceTransformer(
            model_name, device="cpu", **kwargs)
        texts: list[str] = [x.replace("-", " ") for x in keywords]
        embeddings: Any = model.encode(
            texts, normalize_embeddings=True)
        return np.asarray(embeddings, dtype=np.float32)

    @classmethod
    def __cluster(cls, embeddings: Any, n_clusters: int) -> Any:
        """Cluster the embeddings with ward-linkage agglomeration.

        :param embeddings: The float32 embeddings, one row per
            keyword.
        :param n_clusters: The number of clusters to form.
        :return: The cluster label of each embedding, in the given
            order.
        """
        clustering: Any = AgglomerativeClustering(
            n_clusters=n_clusters, linkage="ward")
        return clustering.fit_predict(embeddings)

    @classmethod
    def __build_groups(cls, keywords: list[str], embeddings: Any,
                       labels: Any) -> dict[str, list[str]]:
        """Group the keywords by cluster label, named by their
        medoid.

        The group name is its medoid: the member whose embedding
        has the highest dot product with the cluster's mean vector
        re-normalized to unit length.  Ties break toward the
        lexicographically smallest member.

        :param keywords: The keywords, in embedding row order.
        :param embeddings: The float32 embeddings, one row per
            keyword.
        :param labels: The cluster label of each keyword, in the
            same order.
        :return: The keyword members of every group, keyed by the
            group's medoid name.
        :raises ValueError: When two clusters yield the same
            medoid name.
        """
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


@dataclass
class KeywordsToMerge:
    """The coding keyword set for the coding step."""

    KEYWORDS_TO_MERGE_JSON: ClassVar[str] \
        = "keywords-to-merge.json"
    """The coding keyword set JSON file's fixed name under the
    output directory."""

    keywords: list[str]
    """The lexicographically sorted group names plus every given
    extra keyword."""

    def write(self, output_dir: Path) -> None:
        """Write the coding keyword set JSON file.

        Writes a JSON file holding a single object with one
        ``keywords`` key, whose value is the lexicographically
        sorted list of the group names plus every given extra
        keyword, UTF-8, with a trailing newline.  With no extra
        keyword, the list holds the group names alone.  This is
        the file ``export-llm-input --extras`` consumes.

        :param output_dir: The existing output directory.
        :return: None.
        :raises OSError: When the file cannot be written.
        """
        data: dict[str, list[str]] = {"keywords": self.keywords}
        (output_dir / self.KEYWORDS_TO_MERGE_JSON).write_text(
            json.dumps(data, ensure_ascii=False, indent=1) + "\n",
            encoding="utf-8")


class KeywordsToMergeBuilder:
    """The builder of the coding keyword set."""

    def __init__(self, groups: KeywordGroups,
                 extra_keywords: list[str],
                 output_dir: Path) -> None:
        """Set up the builder of the coding keyword set.

        :param groups: The clustered coding groups.
        :param extra_keywords: The extra a-priori keywords given
            via ``--extra-keyword``, in the given order.
        :param output_dir: The existing output directory that
            receives
            :attr:`KeywordsToMerge.KEYWORDS_TO_MERGE_JSON`.
        """
        self.__group_names: list[str] = groups.names
        """The clustered group names."""
        self.__extra_keywords: list[str] = extra_keywords
        """The extra a-priori keywords, in the given order."""
        self.__output_dir: Path = output_dir
        """The existing output directory."""

    def run(self) -> KeywordsToMerge:
        """Combine the group names with the extra keywords.

        Writes the coding keyword set JSON file under the output
        directory before returning; nothing is written when the
        run fails.

        :return: The coding keyword set.
        :raises ClusterError: When an extra keyword duplicates a
            clustered group name or another extra keyword.
        :raises OSError: When the output file cannot be written.
        """
        try:
            self.__validate(
                self.__group_names, self.__extra_keywords)
        except ValueError as error:
            raise ClusterError(str(error)) from error
        merged: KeywordsToMerge = KeywordsToMerge(keywords=sorted(
            [*self.__group_names, *self.__extra_keywords]))
        merged.write(self.__output_dir)
        return merged

    @staticmethod
    def __validate(group_names: list[str],
                   extra_keywords: list[str]) -> None:
        """Validate the extra keywords given on the command line.

        :param group_names: The clustered group names.
        :param extra_keywords: The extra keywords given via
            ``--extra-keyword``, in the given order.
        :return: None.
        :raises ValueError: When an extra keyword duplicates a
            clustered group name or another extra keyword.
        """
        names: set[str] = set(group_names)
        seen: set[str] = set()
        keyword: str
        for keyword in extra_keywords:
            if keyword in names:
                raise ValueError(
                    f"extra keyword \"{keyword}\" duplicates a"
                    " clustered group name")
            if keyword in seen:
                raise ValueError(
                    f"extra keyword \"{keyword}\" given more than"
                    " once")
            seen.add(keyword)


@dataclass
class RunMeta:
    """The execution record of the run."""

    META_JSON: ClassVar[str] = "meta.json"
    """The run metadata JSON file's fixed name under the output
    directory."""

    meta: dict[str, Any]
    """The run metadata, in the documented key order."""

    def write(self, output_dir: Path) -> None:
        """Write the run metadata JSON file.

        Writes a JSON file holding the researcher's command-line
        choices and the environment that produced the numbers --
        neither recoverable from the committed inputs and outputs
        -- UTF-8, with a trailing newline.  No timestamp or input
        digest is recorded, so re-running in the same environment
        reproduces the file byte for byte.

        :param output_dir: The existing output directory.
        :return: None.
        :raises OSError: When the file cannot be written.
        """
        (output_dir / self.META_JSON).write_text(
            json.dumps(
                self.meta, ensure_ascii=False, indent=1) + "\n",
            encoding="utf-8")


class MetaBuilder:
    """The builder of the run metadata record."""

    __SCRIPT_VERSION: str = "cluster_keywords.py 1.0.0"
    """The script version recorded into
    :attr:`RunMeta.META_JSON`."""

    def __init__(self, args: argparse.Namespace,
                 source: PooledKeywords,
                 extra_keywords: list[str],
                 output_dir: Path) -> None:
        """Set up the builder of the run metadata record.

        :param args: The parsed command-line arguments.
        :param source: The pooled keywords of the two source runs.
        :param extra_keywords: The extra a-priori keywords given
            via ``--extra-keyword``, in the given order.
        :param output_dir: The existing output directory that
            receives :attr:`RunMeta.META_JSON`.
        """
        self.__args: argparse.Namespace = args
        """The parsed command-line arguments."""
        self.__source: PooledKeywords = source
        """The pooled keywords of the two source runs."""
        self.__extra_keywords: list[str] = extra_keywords
        """The extra a-priori keywords, in the given order."""
        self.__output_dir: Path = output_dir
        """The existing output directory."""

    def run(self) -> RunMeta:
        """Assemble the execution record of the run.

        Writes the run metadata JSON file under the output
        directory before returning.

        :return: The run metadata record.
        :raises OSError: When the output file cannot be written.
        """
        args: argparse.Namespace = self.__args
        meta: RunMeta = RunMeta(meta={
            "script_version": self.__SCRIPT_VERSION,
            "source_runs": [
                str(args.run_dir_1), str(args.run_dir_2)],
            "source_records": self.__source.record_counts,
            "embedding": {
                "model": args.model, "revision": args.revision},
            "clustering": {
                "algorithm": "AgglomerativeClustering",
                "linkage": "ward", "metric": "euclidean",
                "clusters": args.clusters},
            "extra_keywords": self.__extra_keywords,
            "keyword_count": len(self.__source.keywords),
            "versions": self.__collect_versions(),
        })
        meta.write(self.__output_dir)
        return meta

    @classmethod
    def __collect_versions(cls) -> dict[str, str]:
        """Collect the versions of the running environment.

        :return: The version strings, keyed by "python", "torch",
            "transformers", "sentence-transformers",
            "scikit-learn", and "numpy".
        """
        return {
            "python": platform.python_version(),
            "torch": str(torch.__version__),
            "transformers": str(transformers.__version__),
            "sentence-transformers": str(
                sentence_transformers.__version__),
            "scikit-learn": str(sklearn.__version__),
            "numpy": str(np.__version__),
        }


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Parse the command-line arguments.

    :param argv: The command-line arguments, or None for
        ``sys.argv``.
    :return: The parsed arguments.
    """
    model: str = KeywordClusterer.DEFAULT_MODEL
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
             " receives the run's output artifacts")
    parser.add_argument(
        "--model", default=model,
        help=f"the sentence embedding model (default \"{model}\")")
    parser.add_argument(
        "--revision", default=None,
        help="the model revision to pin (default: unpinned)")
    parser.add_argument(
        "--clusters", type=int, required=True,
        help="the number of clusters; required, as the study's"
             " chosen cluster count must be stated on every"
             " invocation")
    parser.add_argument(
        "--extra-keyword", dest="extra_keywords", action="append",
        default=[],
        help="an extra a-priori keyword to add to"
             f" {KeywordsToMerge.KEYWORDS_TO_MERGE_JSON}"
             " alongside the clustered group names; repeatable;"
             " may be given any number of times; not added to any"
             " other output file (default: none)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Pool the two tagging runs' keywords and cluster them.

    Creates the output directory (with parents) if it does not
    exist.  Each output artifact is written as soon as its
    content is computed, so when the input is rejected, or an
    extra keyword duplicates a group name or another extra
    keyword, the output directory holds whatever the steps before
    the failing one produced, and the error message names what
    failed.

    :param argv: The command-line arguments, or None for
        ``sys.argv``.
    :return: The exit status: 0 on success, non-zero on failure.
    """
    started: float = time.monotonic()
    args: argparse.Namespace = parse_args(argv)
    try:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        source: PooledKeywords = KeywordPooler(
            args.run_dir_1, args.run_dir_2, args.output_dir).run()
        clusters: KeywordGroups = KeywordClusterer(
            source, args.model, args.revision, args.clusters,
            args.output_dir).run()
        KeywordsToMergeBuilder(
            clusters, args.extra_keywords, args.output_dir).run()
        MetaBuilder(
            args, source, args.extra_keywords, args.output_dir).run()
        elapsed: str = format_duration(time.monotonic() - started)
        print(
            f"Done.  Clustered {len(source.keywords)} keywords into"
            f" {len(clusters.names)}.  {elapsed} elapsed.",
            file=sys.stderr)
    except (ClusterError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0
