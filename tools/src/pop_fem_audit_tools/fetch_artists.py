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
description of the search hit is recorded in the note column so
that a bad match can be spotted.  A search miss or an error on
one artist is noted on its row and does not fail the run.
"""
import argparse
import csv
import enum
import json
import sys
import time
import urllib.parse
import urllib.request
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, Literal

import sqlalchemy as sa
from sqlalchemy.orm import Session

from .database import ds
from .models import Artist

API_URL: str = "https://www.wikidata.org/w/api.php"
"""The URL of the Wikidata API endpoint."""
USER_AGENT: str = ("pop-fem-audit-tools"
                   " (https://github.com/imacat/pop-fem-audit)")
"""The User-Agent header sent on every HTTP request."""
TIMEOUT: float = 30.0
"""The timeout of an HTTP request, in seconds."""
SLEEP_SECONDS: float = 1.0
"""The delay between consecutive HTTP requests, in seconds."""
HUMAN_QID: str = "Q5"
"""The Wikidata item ID of "human"."""
GROUP_KEYWORDS: Sequence[str] = ("band", "group", "duo", "trio")
"""The label keywords that suggest a musical ensemble, covering
labels like "boy band" and "girl group"."""
NOTE_NOT_FOUND: str = "not found"
"""The note sentinel of an artist without a Wikidata search hit,
written to the snapshot and read back for the classification."""


class ArtistType(enum.StrEnum):
    """The decided artist type of a snapshot row."""

    SOLO = "solo"
    """A solo artist: a human."""
    GROUP = "group"
    """A musical ensemble."""
    MIXED = "mixed"
    """A mixed act, assigned manually via the overrides; never
    derived by the fetcher."""


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
    search hit, ``not found``, or ``error: <reason>``."""

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
    """The item-ID claim targets of a Wikidata artist item."""

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
    """A fetcher of artist metadata from Wikidata."""

    def __init__(self) -> None:
        """Construct the fetcher."""
        self.__sent: int = 0
        """The number of the HTTP requests already sent."""

    def fetch(self, name: str) -> ArtistSnapshot:
        """Fetch the metadata of an artist.

        The note carries the description of the search hit for
        human verification.  A search miss yields a snapshot with
        the note ``not found``.  An HTTP, network, or decoding
        error yields a snapshot with what was resolved so far and
        the note ``error: <reason>``.

        :param name: The artist name to query with.
        :return: The snapshot of the artist.
        """
        snapshot: ArtistSnapshot = ArtistSnapshot(name=name)
        try:
            hit: tuple[str, str] | None = self.__search(name)
            if hit is None:
                snapshot.note = NOTE_NOT_FOUND
                return snapshot
            snapshot.qid, snapshot.note = hit
            self.__resolve(snapshot)
        except (OSError, ValueError) as error:
            snapshot.note = f"error: {error}"
        return snapshot

    def __search(self, name: str) -> tuple[str, str] | None:
        """Search Wikidata for an artist.

        :param name: The artist name to search for.
        :return: The QID and the description of the first hit, or
            None when there is no hit.
        :raises OSError: On an HTTP or network error.
        :raises ValueError: On a JSON decoding error.
        """
        data: Any = self.__get_json({
            "action": "wbsearchentities", "search": name,
            "language": "en", "type": "item", "format": "json"})
        hits: Any = data.get("search") \
            if isinstance(data, dict) else None
        if not isinstance(hits, list) or len(hits) == 0:
            return None
        hit: Any = hits[0]
        if not isinstance(hit, dict) \
                or not isinstance(hit.get("id"), str):
            return None
        description: Any = hit.get("description")
        return hit["id"], \
            description if isinstance(description, str) else ""

    def __resolve(self, snapshot: ArtistSnapshot) -> None:
        """Resolve the claims of an artist into the snapshot.

        :param snapshot: The snapshot, with the QID set.
        :return: None.
        :raises OSError: On an HTTP or network error.
        :raises ValueError: On a JSON decoding error.
        """
        claims: ArtistClaims = self.__get_claims(snapshot.qid)
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
        """Fetch the item-ID claim targets of a Wikidata item.

        :param qid: The item ID.
        :return: The item-ID targets of the gender, instance-of,
            genre, and country properties.
        :raises OSError: On an HTTP or network error.
        :raises ValueError: On a JSON decoding error.
        """
        data: Any = self.__get_json({
            "action": "wbgetentities", "ids": qid,
            "props": "claims", "format": "json"})
        claims: Any = None
        if isinstance(data, dict) \
                and isinstance(data.get("entities"), dict) \
                and isinstance(data["entities"].get(qid), dict):
            claims = data["entities"][qid].get("claims")
        if not isinstance(claims, dict):
            return ArtistClaims()
        return ArtistClaims(
            gender_ids=self.__targets(claims.get("P21")),
            instance_of_ids=self.__targets(claims.get("P31")),
            genre_ids=self.__targets(claims.get("P136")),
            country_ids=self.__targets(claims.get("P27")),
            origin_country_ids=self.__targets(claims.get("P495")))

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
        :raises OSError: On an HTTP or network error.
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

    def __get_json(self, params: dict[str, str]) -> Any:
        """Send a GET request to the API and return the JSON body.

        Consecutive requests are separated by a fixed delay.

        :param params: The query parameters.
        :return: The parsed JSON body.
        :raises OSError: On an HTTP or network error.
        :raises ValueError: On a JSON decoding error.
        """
        if self.__sent > 0:
            time.sleep(SLEEP_SECONDS)
        self.__sent += 1
        url: str = f"{API_URL}?{urllib.parse.urlencode(params)}"
        request: urllib.request.Request = urllib.request.Request(
            url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(
                request, timeout=TIMEOUT) as response:
            return json.load(response)


def read_snapshot_names(path: Path) -> set[str]:
    """Read the artist names already in the snapshot CSV file.

    :param path: The Wikidata artist snapshot CSV file.
    :return: The artist names, or an empty set when the file is
        missing.
    :raises OSError: When the file cannot be read.
    """
    if not path.exists():
        return set()
    with open(path, encoding="utf-8",
              newline="") as file:
        reader: csv.DictReader[str] = csv.DictReader(file)
        return {x["name"] for x in reader}


def append_row(path: Path, snapshot: ArtistSnapshot) -> None:
    """Append a snapshot row to the snapshot CSV file.

    The CSV file is created with the header row when missing; the
    existing rows are preserved.

    :param path: The Wikidata artist snapshot CSV file.
    :param snapshot: The snapshot of an artist.
    :return: None.
    :raises OSError: When the file cannot be written.
    """
    is_new: bool = not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8",
              newline="") as file:
        writer: csv.DictWriter[str] = csv.DictWriter(
            file, SNAPSHOT_FIELDS)
        if is_new:
            writer.writeheader()
        writer.writerow(snapshot.to_row())


def main(argv: list[str] | None = None) -> int:
    """Fetch the artist metadata from Wikidata.

    :param argv: The command-line arguments, or None for
        ``sys.argv``.
    :return: The exit status: 0 on success, misses and errors
        included, non-zero on a setup error.
    """
    args: argparse.Namespace = parse_args(argv)
    fetcher: ArtistFetcher = ArtistFetcher()
    fetched: int = 0
    not_found: int = 0
    errors: int = 0
    skipped: int = 0
    session: Session = ds.get_db()
    try:
        done: set[str] = read_snapshot_names(args.wikidata_csv)
        name: str
        for name in session.scalars(
                sa.select(Artist.name).order_by(Artist.id)):
            if name in done:
                skipped += 1
                continue
            snapshot: ArtistSnapshot = fetcher.fetch(name)
            append_row(args.wikidata_csv, snapshot)
            status: str = snapshot.qid
            if snapshot.note == NOTE_NOT_FOUND:
                not_found += 1
                status = "not found"
            elif snapshot.note.startswith("error: "):
                errors += 1
                status = snapshot.note
            else:
                fetched += 1
            print(f"artist \"{name}\": {status}",
                  file=sys.stderr)
    except (OSError, sa.exc.SQLAlchemyError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    finally:
        session.close()
    print(f"done: {fetched} fetched, {not_found} not found,"
          f" {errors} errors, {skipped} skipped",
          file=sys.stderr)
    return 0
