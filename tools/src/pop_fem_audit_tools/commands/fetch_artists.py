# Tools for A Feminist Audit of Pop Music.
# Copyright 2026 imacat.  All rights reserved.
# Authors:
#   imacat@mail.imacat.idv.tw (imacat), 2026/7/31
"""The fetcher of the artist metadata.

Fetches the metadata of the artists without a snapshot row from
Wikidata into the capture layer: the Wikidata artist snapshot
CSV, given as the positional command-line argument.  The working
store is only read, never written; the ``build-db`` subcommand
assembles the captured files into the store on the next rebuild.

Every fetched row is meant for later human verification: the
description of the resolved item is recorded in the note column
so that a bad match can be spotted.  An unresolved artist or an
error on one artist is noted on its row and does not fail the
run.
"""
import argparse
import csv
import enum
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, Literal, TextIO

import sqlalchemy as sa
from sqlalchemy.orm import Session

from .. import VERSION
from ..database import ds
from ..models import Artist, Song, SongArtist
from ..utils import format_duration

API_URL: str = "https://www.wikidata.org/w/api.php"
"""The URL of the Wikidata API endpoint."""
SPARQL_URL: str = "https://query.wikidata.org/sparql"
"""The URL of the Wikidata Query Service SPARQL endpoint."""
USER_AGENT: str = (
    f"pop-fem-audit-tools/{VERSION}"
    " (https://github.com/imacat/pop-fem-audit;"
    " mailto:imacat@mail.imacat.idv.tw)")
"""The User-Agent header sent on every HTTP request."""
TIMEOUT: float = 30.0
"""The timeout of an API HTTP request, in seconds."""
SPARQL_TIMEOUT: float = 90.0
"""The timeout of a SPARQL HTTP request, in seconds.

Higher than the API timeout: the WDQS server aborts a slow
query at 60 seconds, and a lower client timeout would race
that server-side abort and misclassify a slow-but-answerable
query as a client-side timeout instead of letting the server's
own HTTP error response arrive and enter the retry path."""
SLEEP_SECONDS: float = 1.0
"""The delay between consecutive HTTP requests, in seconds."""
MAX_ATTEMPTS: int = 5
"""The maximum number of attempts on a transient error."""
RETRY_SECONDS: float = 15.0
"""The back-off unit on a transient error, in seconds;
multiplied by the attempt number already made."""
RETRY_STATUSES: frozenset[int] = frozenset({429, 500, 502, 503})
"""The HTTP statuses that are retried with a back-off."""
MAX_STAGE1_TITLES: int = 3
"""The maximum number of charted titles used for the stage-1 song
corroboration."""
HUMAN_QID: str = "Q5"
"""The Wikidata item ID of "human"."""
ENSEMBLE_QID: str = "Q2088357"
"""The Wikidata item ID of "musical ensemble"."""
ORIGINAL_CAST_QID: str = "Q106497009"
"""The Wikidata item ID of "original cast"."""
GROUP_KEYWORDS: Sequence[str] = ("band", "group", "duo", "trio")
"""The label keywords that suggest a musical ensemble, covering
labels like "boy band" and "girl group"."""
NOTE_NOT_FOUND: str = "not found"
"""The note sentinel of an artist without a resolved Wikidata
item, written to the snapshot and read back for the
classification."""
PINNED_QIDS: dict[str, str] = {
    "Pinkfong": "Q55735607",
}
"""The last-resort pinned item IDs, keyed by the artist name.

Each entry is for an artist the algorithm documented on
``ArtistFetcher`` is structurally unable to resolve, with its
justification recorded here:

- "Pinkfong": the only charting act whose item is typed as a
  brand (P31 = Q431289), which the type gate (human / musical
  ensemble / original cast) excludes by design.

A pinned name skips the candidate retrieval and corroboration
steps; its item ID is used directly."""


class ArtistType(enum.StrEnum):
    """The decided artist type of a snapshot row."""

    SOLO = "solo"
    """A solo artist: a human."""
    GROUP = "group"
    """A musical ensemble."""


@dataclass
class ArtistSnapshot:
    """One row of the Wikidata artist snapshot CSV file."""

    name: str
    """The artist name."""
    qid: str = ""
    """The Wikidata item ID, or empty when unresolved."""
    gender: str = ""
    """The gender label, or empty when unresolved."""
    type: str = ""
    """The artist type, an ``ArtistType`` value, or empty for the
    human to decide."""
    genre: str = ""
    """The genre labels, joined with ``; ``."""
    country: str = ""
    """The country label, or empty when unresolved."""
    note: str = ""
    """The note for human verification: the description of the
    resolved item, ``not found``, or ``error: <reason>``."""

    def to_row(self) -> dict[str, str]:
        """Return this snapshot as a CSV row.

        :return: The row values, keyed by the column name.
        """
        return asdict(self)


SNAPSHOT_FIELDS: Sequence[str] = tuple(
    x.name for x in fields(ArtistSnapshot))
"""The header columns of the Wikidata artist snapshot CSV file."""


@dataclass
class ArtistClaims:
    """The item-ID claim targets and description of a Wikidata
    artist item."""

    gender_ids: list[str] = field(default_factory=list)
    """The item IDs of the gender targets."""
    instance_of_ids: list[str] = field(default_factory=list)
    """The item IDs of the instance-of targets."""
    genre_ids: list[str] = field(default_factory=list)
    """The item IDs of the genre targets."""
    country_ids: list[str] = field(default_factory=list)
    """The item IDs of the country-of-citizenship targets."""
    origin_country_ids: list[str] = field(default_factory=list)
    """The item IDs of the country-of-origin targets."""
    description: str = ""
    """The English description of the item, or empty when
    absent."""


class RetryExhausted(Exception):
    """The retries on a transient error are exhausted.

    A transient error is a retryable HTTP status (429, 500,
    502, or 503) or a read timeout.
    """


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Parse the command-line arguments.

    :param argv: The command-line arguments, or None for
        ``sys.argv``.
    :return: The parsed arguments.
    """
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description="Fetch the artist metadata from Wikidata"
                    " into the capture layer.")
    parser.add_argument(
        "wikidata_csv", type=Path,
        help="the Wikidata artist snapshot CSV file")
    return parser.parse_args(argv)


class ArtistFetcher:
    """A fetcher of artist metadata from Wikidata.

    An artist name is resolved to a Wikidata item ID through the
    Wikidata Query Service (SPARQL), not the search API, so that
    every step is a deterministic indexed lookup with no ranking
    and no case folding of the label text itself:

    1. Candidate retrieval: the items whose ``rdfs:label`` or
       ``skos:altLabel`` exactly equals the artist name at
       ``@en`` or ``@mul`` (the multilingual default layer),
       restricted to a human (P31 = Q5), a musical ensemble
       (P31/P279* = Q2088357), or an original cast
       (P31 = Q106497009).
    2. A single candidate is selected outright.
    3. With multiple candidates, stage 1 corroborates with up to
       the first 3 charted titles: the song items whose label or
       alias exactly equals a title at ``@en`` or ``@mul`` are
       looked up with their P175 performers and, optionally,
       those performers' P527 members.  The candidates are
       intersected with the performers, and, only when that
       intersection is empty, with the members; a stage succeeds
       only when the intersection has exactly one item.
    4. Stage 2 is an anchored, case-insensitive fallback: every
       song performed by a candidate, directly or via a parent
       group, is compared against the charted titles with a
       casefold match on the song label, without a language
       restriction; a single matching candidate is selected.
    5. Zero candidates, or no stage narrowing to exactly one
       item, leaves the artist unresolved.

    As a last resort, a name listed in ``PINNED_QIDS`` uses its
    pinned item ID directly, skipping every step above.
    """

    def __init__(self) -> None:
        """Construct the fetcher."""
        self.__sent: int = 0
        """The number of the HTTP requests already sent."""

    def fetch(self, name: str,
              titles: Sequence[str]) -> ArtistSnapshot:
        """Fetch the metadata of an artist.

        The note carries the description of the resolved item
        for human verification.  ``not found`` is reserved for
        the algorithm genuinely finding nothing for the artist.
        Any HTTP, network, or decoding error -- including the
        retries on a transient error being exhausted -- yields a
        snapshot with what was resolved so far and the note
        ``error: <reason>``.

        :param name: The artist name to resolve.
        :param titles: The charted song titles credited to the
            artist, used for the multi-candidate resolution.
        :return: The snapshot of the artist.
        """
        snapshot: ArtistSnapshot = ArtistSnapshot(name=name)
        try:
            qid: str | None = self.__resolve_qid(name, titles)
            if qid is None:
                snapshot.note = NOTE_NOT_FOUND
                return snapshot
            snapshot.qid = qid
            self.__resolve(snapshot)
        except (RetryExhausted, OSError, ValueError) as error:
            snapshot.note = f"error: {error}"
        return snapshot

    def __resolve_qid(self, name: str,
                      titles: Sequence[str]) -> str | None:
        """Resolve an artist name to a Wikidata item ID.

        :param name: The artist name.
        :param titles: The charted song titles credited to the
            artist.
        :return: The pinned item ID from ``PINNED_QIDS`` when the
            name is listed there; otherwise the resolved item
            ID, or None when the algorithm documented on this
            class does not narrow to exactly one item.
        :raises OSError: On a non-retryable HTTP or network
            error.
        :raises RetryExhausted: When the retries on a
            transient error are exhausted.
        :raises ValueError: On a JSON decoding error.
        """
        if name in PINNED_QIDS:
            return PINNED_QIDS[name]
        candidates: list[str] = self.__candidates(name)
        if len(candidates) == 0:
            return None
        if len(candidates) == 1:
            return candidates[0]
        selected: str | None = self.__stage1(candidates, titles)
        if selected is not None:
            return selected
        return self.__stage2(candidates, titles)

    def __candidates(self, name: str) -> list[str]:
        """Retrieve the Wikidata items matching an artist name.

        :param name: The artist name.
        :return: The item IDs of the human, musical-ensemble, or
            original-cast items whose label or alias exactly
            equals the name.
        :raises OSError: On a non-retryable HTTP or network
            error.
        :raises RetryExhausted: When the retries on a
            transient error are exhausted.
        :raises ValueError: On a JSON decoding error.
        """
        query: str = f"""
        SELECT DISTINCT ?item WHERE {{
          VALUES ?name {{ {self.__literals([name])} }}
          {{ ?item rdfs:label ?name }}
          UNION {{ ?item skos:altLabel ?name }}
          {{
            ?item wdt:P31 wd:{HUMAN_QID}
          }} UNION {{
            ?item wdt:P31/wdt:P279* wd:{ENSEMBLE_QID}
          }} UNION {{
            ?item wdt:P31 wd:{ORIGINAL_CAST_QID}
          }}
        }}
        """
        rows: list[dict[str, str]] = self.__sparql(query)
        return [self.__qid(x["item"]) for x in rows
                if "item" in x]

    def __stage1(self, candidates: Sequence[str],
                 titles: Sequence[str]) -> str | None:
        """Corroborate the candidates with the charted titles.

        :param candidates: The candidate item IDs.
        :param titles: The charted song titles credited to the
            artist.
        :return: The single candidate among the performers of a
            matching song, or, only when no such single
            candidate exists, among those performers' group
            members; None when neither intersection has exactly
            one item, or there are no titles to try.
        :raises OSError: On a non-retryable HTTP or network
            error.
        :raises RetryExhausted: When the retries on a
            transient error are exhausted.
        :raises ValueError: On a JSON decoding error.
        """
        subset: Sequence[str] = titles[:MAX_STAGE1_TITLES]
        if len(subset) == 0:
            return None
        query: str = f"""
        SELECT DISTINCT ?performer ?member WHERE {{
          VALUES ?title {{ {self.__literals(subset)} }}
          {{ ?song rdfs:label ?title }}
          UNION {{ ?song skos:altLabel ?title }}
          ?song wdt:P175 ?performer .
          OPTIONAL {{ ?performer wdt:P527 ?member . }}
        }}
        """
        rows: list[dict[str, str]] = self.__sparql(query)
        performers: set[str] = {
            self.__qid(x["performer"]) for x in rows
            if "performer" in x}
        hit: set[str] = set(candidates) & performers
        if len(hit) == 1:
            return next(iter(hit))
        members: set[str] = {
            self.__qid(x["member"]) for x in rows
            if "member" in x}
        hit = set(candidates) & members
        if len(hit) == 1:
            return next(iter(hit))
        return None

    def __stage2(self, candidates: Sequence[str],
                 titles: Sequence[str]) -> str | None:
        """Rescue a single candidate by a case-insensitive match.

        :param candidates: The candidate item IDs.
        :param titles: The charted song titles credited to the
            artist.
        :return: The single candidate with a charted song among
            the songs it, or a parent group, performs, matched
            case-insensitively against the song label; None when
            no such single candidate exists.
        :raises OSError: On a non-retryable HTTP or network
            error.
        :raises RetryExhausted: When the retries on a
            transient error are exhausted.
        :raises ValueError: On a JSON decoding error.
        """
        values: str = " ".join(f"wd:{x}" for x in candidates)
        query: str = f"""
        SELECT DISTINCT ?cand ?label WHERE {{
          VALUES ?cand {{ {values} }}
          {{ ?song wdt:P175 ?cand }}
          UNION {{ ?g wdt:P527 ?cand . ?song wdt:P175 ?g }}
          ?song rdfs:label ?label .
        }}
        """
        rows: list[dict[str, str]] = self.__sparql(query)
        folded: set[str] = {x.casefold() for x in titles}
        hits: set[str] = {
            self.__qid(x["cand"]) for x in rows
            if "cand" in x and "label" in x
            and x["label"].casefold() in folded}
        if len(hits) == 1:
            return next(iter(hits))
        return None

    def __resolve(self, snapshot: ArtistSnapshot) -> None:
        """Resolve the claims of an artist into the snapshot.

        :param snapshot: The snapshot, with the QID set.
        :return: None.
        :raises OSError: On a non-retryable HTTP or network
            error.
        :raises RetryExhausted: When the retries on a
            transient error are exhausted.
        :raises ValueError: On a JSON decoding error.
        """
        claims: ArtistClaims = self.__get_claims(snapshot.qid)
        snapshot.note = claims.description
        country_ids: list[str] = claims.country_ids
        if len(country_ids) == 0:
            country_ids = claims.origin_country_ids
        labels: dict[str, str] = self.__get_labels(
            claims.gender_ids + claims.instance_of_ids
            + claims.genre_ids + country_ids)
        if len(claims.gender_ids) > 0:
            snapshot.gender = labels.get(claims.gender_ids[0], "")
        snapshot.type = self.__artist_type(
            claims.instance_of_ids, labels)
        snapshot.genre = "; ".join(
            labels[x] for x in claims.genre_ids if x in labels)
        if len(country_ids) > 0:
            snapshot.country = labels.get(country_ids[0], "")

    def __get_claims(self, qid: str) -> ArtistClaims:
        """Fetch the claims and the description of a Wikidata
        item.

        :param qid: The item ID.
        :return: The item-ID targets of the gender, instance-of,
            genre, and country properties, and the English
            description.
        :raises OSError: On a non-retryable HTTP or network
            error.
        :raises RetryExhausted: When the retries on a
            transient error are exhausted.
        :raises ValueError: On a JSON decoding error.
        """
        data: Any = self.__get_json({
            "action": "wbgetentities", "ids": qid,
            "props": "claims|descriptions", "languages": "en",
            "format": "json"})
        entity: Any = None
        if isinstance(data, dict) \
                and isinstance(data.get("entities"), dict):
            entity = data["entities"].get(qid)
        claims: Any = entity.get("claims") \
            if isinstance(entity, dict) else None
        if not isinstance(claims, dict):
            claims = {}
        return ArtistClaims(
            gender_ids=self.__targets(claims.get("P21")),
            instance_of_ids=self.__targets(claims.get("P31")),
            genre_ids=self.__targets(claims.get("P136")),
            country_ids=self.__targets(claims.get("P27")),
            origin_country_ids=self.__targets(claims.get("P495")),
            description=self.__description(entity))

    @staticmethod
    def __description(entity: Any) -> str:
        """Extract the English description of a Wikidata entity.

        :param entity: The entity data, or None.
        :return: The description, or the empty string when
            absent.
        """
        descriptions: Any = entity.get("descriptions") \
            if isinstance(entity, dict) else None
        if not isinstance(descriptions, dict):
            return ""
        description: Any = descriptions.get("en")
        if isinstance(description, dict) \
                and isinstance(description.get("value"), str):
            return description["value"]
        return ""

    @staticmethod
    def __targets(statements: Any) -> list[str]:
        """Extract the item-ID targets of the property statements.

        :param statements: The statements of a property, or None.
        :return: The item IDs of the statement targets.
        """
        if not isinstance(statements, list):
            return []
        ids: list[str] = []
        statement: Any
        for statement in statements:
            if not isinstance(statement, dict):
                continue
            snak: Any = statement.get("mainsnak")
            if not isinstance(snak, dict):
                continue
            datavalue: Any = snak.get("datavalue")
            if not isinstance(datavalue, dict):
                continue
            value: Any = datavalue.get("value")
            if isinstance(value, dict) \
                    and isinstance(value.get("id"), str):
                ids.append(value["id"])
        return ids

    def __get_labels(self, qids: Sequence[str]) \
            -> dict[str, str]:
        """Resolve item IDs to their English labels in one batch.

        :param qids: The item IDs, duplicates allowed.
        :return: The English labels, keyed by the item ID; the
            items without an English label are left out.
        :raises OSError: On a non-retryable HTTP or network
            error.
        :raises RetryExhausted: When the retries on a
            transient error are exhausted.
        :raises ValueError: On a JSON decoding error.
        """
        unique: list[str] = list(dict.fromkeys(qids))
        if len(unique) == 0:
            return {}
        data: Any = self.__get_json({
            "action": "wbgetentities", "ids": "|".join(unique),
            "props": "labels", "languages": "en",
            "format": "json"})
        entities: Any = data.get("entities") \
            if isinstance(data, dict) else None
        if not isinstance(entities, dict):
            return {}
        labels: dict[str, str] = {}
        qid: str
        for qid in unique:
            entity: Any = entities.get(qid)
            if not isinstance(entity, dict) \
                    or not isinstance(entity.get("labels"), dict):
                continue
            label: Any = entity["labels"].get("en")
            if isinstance(label, dict) \
                    and isinstance(label.get("value"), str):
                labels[qid] = label["value"]
        return labels

    @staticmethod
    def __artist_type(type_ids: Sequence[str],
                      labels: dict[str, str]) \
            -> ArtistType | Literal[""]:
        """Derive the artist type from the instance-of targets.

        :param type_ids: The item IDs of the instance-of targets.
        :param labels: The English labels, keyed by the item ID.
        :return: ``ArtistType.SOLO`` for a human,
            ``ArtistType.GROUP`` for a musical ensemble, or the
            empty string for the human to decide.
        """
        if HUMAN_QID in type_ids:
            return ArtistType.SOLO
        qid: str
        for qid in type_ids:
            label: str = labels.get(qid, "").lower()
            if any(x in label for x in GROUP_KEYWORDS):
                return ArtistType.GROUP
        return ""

    def __sparql(self, query: str) -> list[dict[str, str]]:
        """Run a SPARQL query against the Wikidata Query Service.

        :param query: The SPARQL query text.
        :return: The result bindings, each variable name mapped
            to its bound value.
        :raises OSError: On a non-retryable HTTP or network
            error.
        :raises RetryExhausted: When the retries on a
            transient error are exhausted.
        :raises ValueError: On a JSON decoding error.
        """
        url: str = (f"{SPARQL_URL}?"
                    f"{urllib.parse.urlencode({'query': query})}")
        request: urllib.request.Request = urllib.request.Request(
            url, headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/sparql-results+json"})
        body: bytes = self.__send(
            request, timeout=SPARQL_TIMEOUT)
        data: Any = json.loads(body)
        bindings: Any = None
        if isinstance(data, dict) \
                and isinstance(data.get("results"), dict):
            bindings = data["results"].get("bindings")
        if not isinstance(bindings, list):
            return []
        rows: list[dict[str, str]] = []
        binding: Any
        for binding in bindings:
            if not isinstance(binding, dict):
                continue
            row: dict[str, str] = {}
            key: str
            cell: Any
            for key, cell in binding.items():
                if isinstance(cell, dict) \
                        and isinstance(cell.get("value"), str):
                    row[key] = cell["value"]
            rows.append(row)
        return rows

    def __get_json(self, params: dict[str, str]) -> Any:
        """Send a GET request to the API and return the JSON body.

        :param params: The query parameters.
        :return: The parsed JSON body.
        :raises OSError: On a non-retryable HTTP or network
            error.
        :raises RetryExhausted: When the retries on a
            transient error are exhausted.
        :raises ValueError: On a JSON decoding error.
        """
        url: str = f"{API_URL}?{urllib.parse.urlencode(params)}"
        request: urllib.request.Request = urllib.request.Request(
            url, headers={"User-Agent": USER_AGENT})
        return json.loads(self.__send(request))

    def __send(self, request: urllib.request.Request,
               timeout: float = TIMEOUT) -> bytes:
        """Send an HTTP request, retrying on a transient error.

        Consecutive requests are separated by a fixed delay.  A
        transient error -- a response with a retryable HTTP
        status, or a read timeout -- is retried with an
        increasing back-off, up to ``MAX_ATTEMPTS`` attempts in
        total.

        :param request: The prepared HTTP request.
        :param timeout: The read timeout, in seconds.
        :return: The raw response body.
        :raises OSError: On a non-retryable HTTP or network
            error.
        :raises RetryExhausted: When the retries on a
            transient error are exhausted.
        """
        if self.__sent > 0:
            time.sleep(SLEEP_SECONDS)
        self.__sent += 1
        attempt: int = 1
        reason: str | None
        while True:
            try:
                with urllib.request.urlopen(
                        request, timeout=timeout) as response:
                    return response.read()
            except (urllib.error.HTTPError, TimeoutError,
                    urllib.error.URLError) as error:
                reason = self.__retry_reason(error)
                if reason is None:
                    raise
                if attempt >= MAX_ATTEMPTS:
                    raise RetryExhausted(
                        f"retries exhausted ({reason})") from error
            time.sleep(RETRY_SECONDS * attempt)
            attempt += 1

    @staticmethod
    def __retry_reason(
            error: urllib.error.URLError | TimeoutError) \
            -> str | None:
        """Tell whether an error is transient, and why.

        :param error: The HTTP or network error raised by the
            request.
        :return: The reason to report on the error, or None when
            the error is not transient and must not be retried.
        """
        if isinstance(error, urllib.error.HTTPError):
            if error.code not in RETRY_STATUSES:
                return None
            return str(error)
        if isinstance(error, TimeoutError):
            return str(error) or "timed out"
        if not isinstance(error.reason, TimeoutError):
            return None
        return str(error.reason) or "timed out"

    @staticmethod
    def __literals(texts: Sequence[str]) -> str:
        """Build the SPARQL literals of texts at both languages.

        :param texts: The texts to embed as string literals.
        :return: The literals, each text once tagged ``@en`` and
            once tagged ``@mul``, space-separated.
        """
        parts: list[str] = []
        text: str
        for text in texts:
            escaped: str = ArtistFetcher.__escape(text)
            parts.append(f'"{escaped}"@en')
            parts.append(f'"{escaped}"@mul')
        return " ".join(parts)

    @staticmethod
    def __escape(text: str) -> str:
        """Escape a text for embedding as a SPARQL string literal.

        :param text: The text to embed.
        :return: The text with the backslashes and double quotes
            escaped.
        """
        return text.replace("\\", "\\\\").replace('"', '\\"')

    @staticmethod
    def __qid(uri: str) -> str:
        """Extract the item ID from a Wikidata entity URI.

        :param uri: The entity URI.
        :return: The item ID, the last path segment of the URI.
        """
        return uri.rsplit("/", 1)[-1]


def read_snapshot_rows(file: TextIO) -> list[dict[str, str]]:
    """Read the current rows of a snapshot CSV file handle.

    :param file: The open, seekable snapshot CSV file.
    :return: The rows, keyed by the column name.
    :raises OSError: When the file cannot be read.
    """
    file.seek(0)
    reader: csv.DictReader[str] = csv.DictReader(file)
    return list(reader)


def read_artist_titles(session: Session,
                       artist_id: int) -> list[str]:
    """Read the charted song titles credited to an artist.

    :param session: The database session.
    :param artist_id: The artist ID.
    :return: The song titles credited to the artist, ordered by
        the song ID, with the duplicate titles removed.
    """
    titles: Sequence[str] = session.scalars(
        sa.select(Song.title)
        .join(SongArtist, SongArtist.song_id == Song.id)
        .where(SongArtist.artist_id == artist_id)
        .order_by(Song.id)).all()
    return list(dict.fromkeys(titles))


def ensure_snapshot_header(file: TextIO) -> None:
    """Write the snapshot CSV header row if the file is empty.

    :param file: The open, seekable snapshot CSV file.
    :return: None.
    :raises OSError: When the file cannot be written.
    """
    file.seek(0, os.SEEK_END)
    if file.tell() == 0:
        csv.writer(file).writerow(SNAPSHOT_FIELDS)
        file.flush()


def append_row(file: TextIO, snapshot: ArtistSnapshot) -> None:
    """Append a snapshot row to a snapshot CSV file handle.

    :param file: The open snapshot CSV file, opened for append.
    :param snapshot: The snapshot of an artist.
    :return: None.
    :raises OSError: When the file cannot be written.
    """
    csv.DictWriter(file, SNAPSHOT_FIELDS).writerow(
        snapshot.to_row())
    file.flush()


def write_snapshot(file: TextIO) -> None:
    """Rewrite a snapshot CSV file handle sorted by artist name.

    Reads back the current rows and rewrites the header and the
    rows ordered by the case-folded artist name, matching the
    convention of the derived ``artists.csv``.

    :param file: The open, seekable snapshot CSV file.
    :return: None.
    :raises OSError: When the file cannot be read or written.
    """
    ordered: list[dict[str, str]] = sorted(
        read_snapshot_rows(file),
        key=lambda row: row["name"].casefold())
    file.seek(0)
    file.truncate()
    writer: csv.DictWriter[str] = csv.DictWriter(
        file, SNAPSHOT_FIELDS)
    writer.writeheader()
    writer.writerows(ordered)


def main(argv: list[str] | None = None) -> int:
    """Fetch the artist metadata from Wikidata.

    :param argv: The command-line arguments, or None for
        ``sys.argv``.
    :return: The exit status: 0 on success, misses and errors
        included, non-zero on a setup error.
    """
    started: float = time.monotonic()
    args: argparse.Namespace = parse_args(argv)
    fetcher: ArtistFetcher = ArtistFetcher()
    fetched: int = 0
    not_found: int = 0
    errors: int = 0
    session: Session = ds.get_db()
    try:
        args.wikidata_csv.parent.mkdir(
            parents=True, exist_ok=True)
        with open(args.wikidata_csv, "a+", encoding="utf-8",
                  newline="") as csv_file:
            done: set[str] = {x["name"] for x in
                              read_snapshot_rows(csv_file)}
            ensure_snapshot_header(csv_file)
            artist: Artist
            for artist in session.scalars(
                    sa.select(Artist).order_by(Artist.id)):
                if artist.name in done:
                    continue
                titles: list[str] = read_artist_titles(
                    session, artist.id)
                snapshot: ArtistSnapshot = fetcher.fetch(
                    artist.name, titles)
                append_row(csv_file, snapshot)
                status: str = snapshot.qid
                if snapshot.note == NOTE_NOT_FOUND:
                    not_found += 1
                    status = "not found"
                elif snapshot.note.startswith("error: "):
                    errors += 1
                    status = snapshot.note
                else:
                    fetched += 1
                print(f"artist \"{artist.name}\": {status}",
                      file=sys.stderr)
            write_snapshot(csv_file)
    except (OSError, sa.exc.SQLAlchemyError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    finally:
        session.close()
    attempted: int = fetched + not_found + errors
    elapsed: str = format_duration(time.monotonic() - started)
    print(f"Done.  Resolved {fetched}/{attempted} artists."
          f"  {elapsed} elapsed.",
          file=sys.stderr)
    return 0
