# Tools for A Feminist Audit of Pop Music.
# Copyright 2026 imacat.  All rights reserved.
# Authors:
#   imacat@mail.imacat.idv.tw (imacat), 2026/7/31
"""The fetcher of the missing song lyrics.

Fetches the lyrics of the songs without a cache file from the
public lyrics APIs, Lyrics.ovh and LRCLIB, into the capture
layer: the lyrics cache directory and the provenance CSV, each
given as a positional command-line argument.  The working store
is only read, never written; the ``build-db`` subcommand
assembles the captured files into the store on the next rebuild.

Each song is first queried with the name of its primary-role
artist with the lowest position.  When every API misses that
query and the song's full artist credit differs from that
artist name, the same APIs are queried again with the artist
credit, to catch songs cataloged only under a joint credit such
as "Dan + Shay".

A song that every API misses on both queries is reported on the
standard error, but does not fail the run; misses are expected.
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
from typing import Any, ClassVar

import sqlalchemy as sa
from sqlalchemy.orm import Session

from ..database import ds
from ..models import (
    Artist,
    Role,
    Song,
    SongArtist,
)
from ..utils import format_duration


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Parse the command-line arguments.

    :param argv: The command-line arguments, or None for
        ``sys.argv``.
    :return: The parsed arguments.
    """
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description="Fetch the missing song lyrics from the"
                    " public lyrics APIs into the capture layer.")
    parser.add_argument(
        "lyrics_dir", type=Path,
        help="the lyrics cache directory")
    parser.add_argument(
        "provenance_csv", type=Path,
        help="the lyrics provenance CSV file")
    return parser.parse_args(argv)


class LyricsFetcher:
    """A fetcher of song lyrics from the public lyrics APIs."""

    __USER_AGENT: ClassVar[str] = (
        "pop-fem-audit-tools"
        " (https://github.com/imacat/pop-fem-audit)")
    """The User-Agent header sent on every HTTP request."""
    __TIMEOUT: ClassVar[float] = 30.0
    """The timeout of an HTTP request, in seconds."""
    __SLEEP_SECONDS: ClassVar[float] = 1.0
    """The delay between consecutive HTTP requests, in
    seconds."""

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
            time.sleep(self.__SLEEP_SECONDS)
        self.__sent += 1
        request: urllib.request.Request = urllib.request.Request(
            url, headers={"User-Agent": self.__USER_AGENT})
        try:
            with urllib.request.urlopen(
                    request, timeout=self.__TIMEOUT) as response:
                return json.load(response)
        except (OSError, ValueError):
            return None


@dataclass(frozen=True)
class LyricsFetchCounts:
    """The outcome of one run of fetching the missing lyrics."""

    fetched: int
    """The number of songs newly fetched."""
    missed: int
    """The number of songs every API missed."""


class LyricsFetchRunner:
    """The orchestrator of one run of fetching missing lyrics."""

    __PROVENANCE_FIELDS: ClassVar[Sequence[str]] = (
        "song_id", "source", "method", "acquired_at", "note")
    """The header columns of the lyrics provenance CSV file."""

    @staticmethod
    def __build_normalization() -> dict[int, str | None]:
        """Build the lyrics normalization translation table.

        :return: The codepoint-to-replacement mapping, a
            replacement of None meaning removal.
        """
        table: dict[int, str | None] = {}
        codepoint: int
        for codepoint in range(0x80, 0xa0):
            try:
                table[codepoint] = bytes(
                    [codepoint]).decode("cp1252")
            except UnicodeDecodeError:
                table[codepoint] = None
        table[0x0435] = "e"
        table[0x03cc] = "ó"
        for codepoint in (0x2005, 0x205f, 0x200a):
            table[codepoint] = " "
        for codepoint in (0x200b, 0x200c, 0x200d, 0xfeff):
            table[codepoint] = None
        return table

    __NORMALIZATION: ClassVar[dict[int, str | None]] \
        = __build_normalization()
    """The codepoint-to-replacement mapping applied to fetched
    lyrics: cp1252-mojibake restoration for U+0080-U+009F (with
    the five byte values undefined in cp1252 removed), homoglyph
    restoration for the Cyrillic "e" and the Greek "o" with
    tonos, ASCII-space restoration for exotic space variants, and
    removal of zero-width characters.  A replacement of None
    removes the codepoint."""

    def __init__(self, lyrics_dir: Path,
                provenance_csv: Path) -> None:
        """Set up the fetch run.

        :param lyrics_dir: The lyrics cache directory.
        :param provenance_csv: The lyrics provenance CSV file.
        """
        self.__lyrics_dir: Path = lyrics_dir
        """The lyrics cache directory."""
        self.__provenance_csv: Path = provenance_csv
        """The lyrics provenance CSV file."""
        self.__fetcher: LyricsFetcher = LyricsFetcher()
        """The fetcher of the public lyrics APIs."""

    def run(self) -> LyricsFetchCounts:
        """Fetch the missing lyrics of every song in the store.

        Every song fetched or missed is reported on the standard
        error as an observable side effect.

        :return: The number of songs fetched and missed.
        :raises OSError: When a cache file or the provenance CSV
            cannot be written.
        :raises sqlalchemy.exc.SQLAlchemyError: On a database
            error.
        """
        fetched: int = 0
        missed: int = 0
        session: Session = ds.get_db()
        try:
            song: Song
            for song in session.scalars(
                    sa.select(Song).order_by(Song.id)):
                if (self.__lyrics_dir
                        / f"{song.id}.txt").exists():
                    continue
                if self.__fetch_one(session, song):
                    fetched += 1
                else:
                    missed += 1
        finally:
            session.close()
        return LyricsFetchCounts(fetched=fetched, missed=missed)

    def __fetch_one(self, session: Session, song: Song) -> bool:
        """Fetch and save the lyrics of one song.

        The song is queried by its primary-role artist name; when
        every API misses and the song's full artist credit
        differs from that name, the same APIs are queried again
        with the artist credit.

        :param session: The database session.
        :param song: The song to fetch.
        :return: True when a lyrics text was fetched and saved,
            False when every API missed on both queries.
        :raises OSError: When the cache file or the provenance
            CSV cannot be written.
        """
        artist: str = self.__query_artist(session, song.id)
        result: tuple[str, str] | None = self.__fetcher.fetch(
            artist, song.title)
        if result is None and song.artist_credit != artist:
            result = self.__fetcher.fetch(
                song.artist_credit, song.title)
        if result is None:
            print(f"song {song.id} \"{song.title}\": miss",
                  file=sys.stderr)
            return False
        lyrics: str
        source: str
        lyrics, source = result
        self.__save_lyrics(song.id, lyrics)
        self.__append_provenance(song.id, source)
        print(f"song {song.id} \"{song.title}\": {source}",
              file=sys.stderr)
        return True

    @staticmethod
    def __query_artist(session: Session, song_id: int) -> str:
        """Find the artist name to query the APIs with.

        :param session: The database session.
        :param song_id: The song ID.
        :return: The name of the primary-role artist with the
            lowest position.
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

    def __save_lyrics(self, song_id: int, lyrics: str) -> None:
        """Write the lyrics of a song into the cache directory.

        The cache directory is created when missing.

        The lyrics text is normalized with
        :meth:`normalize_lyrics` before being written.

        :param song_id: The song ID.
        :param lyrics: The lyrics text.
        :return: None.
        :raises OSError: When the file cannot be written.
        """
        self.__lyrics_dir.mkdir(parents=True, exist_ok=True)
        (self.__lyrics_dir / f"{song_id}.txt").write_text(
            self.normalize_lyrics(lyrics), encoding="utf-8")

    def __append_provenance(self, song_id: int,
                            source: str) -> None:
        """Append a provenance row for a fetched lyrics file.

        The CSV file is created with the header row when
        missing.

        :param song_id: The song ID.
        :param source: The source name of the fetched lyrics.
        :return: None.
        :raises OSError: When the file cannot be written.
        """
        is_new: bool = not self.__provenance_csv.exists()
        self.__provenance_csv.parent.mkdir(
            parents=True, exist_ok=True)
        with open(self.__provenance_csv, "a", encoding="utf-8",
                  newline="") as file:
            writer: Any = csv.writer(file)
            if is_new:
                writer.writerow(self.__PROVENANCE_FIELDS)
            writer.writerow(
                [song_id, source, "api-fetch",
                 datetime.date.today().isoformat(), ""])

    @classmethod
    def normalize_lyrics(cls, text: str) -> str:
        """Restore or remove watermark and mojibake characters.

        :param text: The lyrics text as fetched from an API.
        :return: The text with the codepoints of the
            normalization table replaced or removed; every other
            character is unchanged.
        """
        return text.translate(cls.__NORMALIZATION)


def main(argv: list[str] | None = None) -> int:
    """Fetch the missing song lyrics from the public APIs.

    :param argv: The command-line arguments, or None for
        ``sys.argv``.
    :return: The exit status: 0 on success, misses included,
        non-zero on a setup error.
    """
    started: float = time.monotonic()
    args: argparse.Namespace = parse_args(argv)
    try:
        counts: LyricsFetchCounts = LyricsFetchRunner(
            args.lyrics_dir, args.provenance_csv).run()
    except (OSError, sa.exc.SQLAlchemyError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    attempted: int = counts.fetched + counts.missed
    elapsed: str = format_duration(time.monotonic() - started)
    print(f"Done.  Fetched lyrics for {counts.fetched}/"
          f"{attempted} songs.  {elapsed} elapsed.",
          file=sys.stderr)
    return 0
