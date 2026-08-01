# Tools for A Feminist Audit of Pop Music.
# Copyright 2026 imacat.  All rights reserved.
# Authors:
#   imacat@mail.imacat.idv.tw (imacat), 2026/7/31
"""The fetcher of the missing song lyrics.

Fetches the lyrics of the songs without a cache file from the
public lyrics APIs, Lyrics.ovh and LRCLIB, into the capture
layer: the lyrics cache directory and the provenance CSV.  The
working store is only read, never written; the ``build-db``
subcommand assembles the captured files into the store on the
next rebuild.

A song that every API misses is reported in the missing lyrics
CSV, which is rewritten on every run to reflect the current
status.  Misses are expected and do not fail the run.

Run from the repository root; the data paths are relative to the
current working directory.
"""
import argparse
import csv
import datetime
import json
import sys
import time
import urllib.parse
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from .database import ds
from .models import (
    Artist,
    Role,
    Song,
    SongArtist,
)

LYRICS_DIR: Path = Path("data/lyrics")
"""The lyrics cache directory."""
PROVENANCE_CSV: Path = Path("data/lyrics_provenance.csv")
"""The lyrics provenance CSV file."""
MISSING_CSV: Path = Path("data/lyrics_missing.csv")
"""The missing lyrics report CSV file."""
PROVENANCE_FIELDS: Sequence[str] = (
    "song_id", "source", "method", "acquired_at", "note")
"""The header columns of the lyrics provenance CSV file."""
MISSING_FIELDS: Sequence[str] = (
    "song_id", "title", "artist_credit", "reason")
"""The header columns of the missing lyrics report CSV file."""
USER_AGENT: str = ("pop-fem-audit-tools"
                   " (https://github.com/imacat/pop-fem-audit)")
"""The User-Agent header sent on every HTTP request."""
TIMEOUT: float = 30.0
"""The timeout of an HTTP request, in seconds."""
SLEEP_SECONDS: float = 1.0
"""The delay between consecutive HTTP requests, in seconds."""


@dataclass
class MissingLyrics:
    """One row of the missing lyrics report CSV file."""

    song_id: int
    """The song ID."""
    title: str
    """The song title."""
    artist_credit: str
    """The artist credit of the song."""
    reason: str
    """The reason the lyrics are missing."""

    def to_row(self) -> list[str]:
        """Return this report entry as a CSV row.

        :return: The row values, in the column order.
        """
        return [str(self.song_id), self.title,
                self.artist_credit, self.reason]


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Parse the command-line arguments.

    :param argv: The command-line arguments, or None for
        ``sys.argv``.
    :return: The parsed arguments.
    """
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description="Fetch the missing song lyrics from the"
                    " public lyrics APIs into the capture layer.")
    return parser.parse_args(argv)


class LyricsFetcher:
    """A fetcher of song lyrics from the public lyrics APIs."""

    def __init__(self) -> None:
        """Construct the fetcher."""
        self.__sent: int = 0
        """The number of the HTTP requests already sent."""

    def fetch(self, artist: str, title: str) \
            -> tuple[str, str] | None:
        """Fetch the lyrics of a song.

        The APIs are tried in order, Lyrics.ovh and then LRCLIB,
        stopping at the first hit.  An HTTP or network error on
        an API counts as a miss on that API.

        :param artist: The artist name to query with.
        :param title: The song title to query with.
        :return: The lyrics text and the source name, or None
            when every API misses.
        """
        lyrics: str | None = self.__fetch_ovh(artist, title)
        if lyrics is not None:
            return lyrics, "lyrics.ovh"
        lyrics = self.__fetch_lrclib(artist, title)
        if lyrics is not None:
            return lyrics, "lrclib"
        return None

    def __fetch_ovh(self, artist: str, title: str) -> str | None:
        """Fetch the lyrics of a song from Lyrics.ovh.

        :param artist: The artist name to query with.
        :param title: The song title to query with.
        :return: The lyrics text, or None on a miss.
        """
        url: str = ("https://api.lyrics.ovh/v1/"
                    f"{urllib.parse.quote(artist, safe='')}/"
                    f"{urllib.parse.quote(title, safe='')}")
        data: Any = self.__get_json(url)
        if isinstance(data, dict) \
                and isinstance(data.get("lyrics"), str) \
                and data["lyrics"] != "":
            return data["lyrics"]
        return None

    def __fetch_lrclib(self, artist: str, title: str) \
            -> str | None:
        """Fetch the lyrics of a song from LRCLIB.

        :param artist: The artist name to query with.
        :param title: The song title to query with.
        :return: The plain lyrics text, or None on a miss.
        """
        query: str = urllib.parse.urlencode(
            {"artist_name": artist, "track_name": title})
        url: str = f"https://lrclib.net/api/get?{query}"
        data: Any = self.__get_json(url)
        if isinstance(data, dict) \
                and isinstance(data.get("plainLyrics"), str) \
                and data["plainLyrics"] != "":
            return data["plainLyrics"]
        return None

    def __get_json(self, url: str) -> Any:
        """Send a GET request and return the parsed JSON body.

        Consecutive requests are separated by a fixed delay.

        :param url: The URL to request.
        :return: The parsed JSON body, or None on any HTTP,
            network, or decoding error.
        """
        if self.__sent > 0:
            time.sleep(SLEEP_SECONDS)
        self.__sent += 1
        request: urllib.request.Request = urllib.request.Request(
            url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(
                    request, timeout=TIMEOUT) as response:
                return json.load(response)
        except (OSError, ValueError):
            return None


def query_artist(session: Session, song_id: int) -> str:
    """Find the artist name to query the APIs with.

    :param session: The database session.
    :param song_id: The song ID.
    :return: The name of the primary-role artist with the lowest
        position.
    """
    name: str | None = session.scalar(
        sa.select(Artist.name)
        .join(SongArtist, SongArtist.artist_id == Artist.id)
        .where(SongArtist.song_id == song_id,
               SongArtist.role == Role.PRIMARY)
        .order_by(SongArtist.position)
        .limit(1))
    assert name is not None
    return name


def save_lyrics(song_id: int, lyrics: str) -> None:
    """Write the lyrics of a song into the cache directory.

    The cache directory is created when missing.

    :param song_id: The song ID.
    :param lyrics: The lyrics text.
    :return: None.
    :raises OSError: When the file cannot be written.
    """
    LYRICS_DIR.mkdir(parents=True, exist_ok=True)
    (LYRICS_DIR / f"{song_id}.txt").write_text(
        lyrics, encoding="utf-8")


def append_provenance(song_id: int, source: str) -> None:
    """Append a provenance row for a fetched lyrics file.

    The CSV file is created with the header row when missing.

    :param song_id: The song ID.
    :param source: The source name of the fetched lyrics.
    :return: None.
    :raises OSError: When the file cannot be written.
    """
    is_new: bool = not PROVENANCE_CSV.exists()
    PROVENANCE_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(PROVENANCE_CSV, "a", encoding="utf-8",
              newline="") as file:
        writer: Any = csv.writer(file)
        if is_new:
            writer.writerow(PROVENANCE_FIELDS)
        writer.writerow([song_id, source, "api-fetch",
                         datetime.date.today().isoformat(), ""])


def write_missing(misses: Sequence[MissingLyrics]) -> None:
    """Rewrite the missing lyrics report CSV file.

    The previous content is replaced, so the file reflects the
    current misses only.

    :param misses: The report entries of the songs still without
        lyrics.
    :return: None.
    :raises OSError: When the file cannot be written.
    """
    MISSING_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(MISSING_CSV, "w", encoding="utf-8",
              newline="") as file:
        writer: Any = csv.writer(file)
        writer.writerow(MISSING_FIELDS)
        writer.writerows(x.to_row() for x in misses)


def main(argv: list[str] | None = None) -> int:
    """Fetch the missing song lyrics from the public APIs.

    :param argv: The command-line arguments, or None for
        ``sys.argv``.
    :return: The exit status: 0 on success, misses included,
        non-zero on a setup error.
    """
    parse_args(argv)
    fetcher: LyricsFetcher = LyricsFetcher()
    fetched: int = 0
    misses: list[MissingLyrics] = []
    session: Session = ds.get_db()
    try:
        song: Song
        for song in session.scalars(
                sa.select(Song).order_by(Song.id)):
            if (LYRICS_DIR / f"{song.id}.txt").exists():
                continue
            artist: str = query_artist(session, song.id)
            result: tuple[str, str] | None = fetcher.fetch(
                artist, song.title)
            if result is None:
                misses.append(MissingLyrics(
                    song_id=song.id, title=song.title,
                    artist_credit=song.artist_credit,
                    reason="not found"))
                print(f"song {song.id} \"{song.title}\": miss",
                      file=sys.stderr)
                continue
            lyrics: str
            source: str
            lyrics, source = result
            save_lyrics(song.id, lyrics)
            append_provenance(song.id, source)
            fetched += 1
            print(f"song {song.id} \"{song.title}\": {source}",
                  file=sys.stderr)
        write_missing(misses)
    except (OSError, sa.exc.SQLAlchemyError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    finally:
        session.close()
    print(f"done: {fetched} fetched, {len(misses)} missed",
          file=sys.stderr)
    return 0
