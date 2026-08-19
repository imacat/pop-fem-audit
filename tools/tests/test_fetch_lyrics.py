# Tools for A Feminist Audit of Pop Music.
# Copyright 2026 imacat.  All rights reserved.
# Authors:
#   imacat@mail.imacat.idv.tw (imacat), 2026/7/31
"""Unit tests for the lyrics fetcher module."""
import csv
import io
import json
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stderr
from pathlib import Path
from typing import Any
from unittest import mock

from sqlalchemy.orm import Session

from pop_fem_audit_tools import config
from pop_fem_audit_tools.commands import fetch_lyrics
from pop_fem_audit_tools.database import Base, DataSource
from pop_fem_audit_tools.models import (
    Artist,
    Role,
    Song,
    SongArtist,
)


class TestFetchLyrics(unittest.TestCase):
    """Test cases for the lyrics fetcher."""

    PROVENANCE_HEADER: list[str] = [
        "song_id", "source", "method", "acquired_at", "note"]
    """The expected header row of the provenance CSV file."""

    def setUp(self) -> None:
        """Create a temporary capture directory with the store."""
        tmp: tempfile.TemporaryDirectory[str] \
            = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.__dir: Path = Path(tmp.name)
        self.__lyrics: Path = self.__dir / "lyrics"
        self.__provenance: Path = \
            self.__dir / "lyrics-provenance.csv"
        config.set_settings(config.Settings(
            SQLALCHEMY_DATABASE_URL="sqlite://",
            ANTHROPIC_API_KEY="test-key"))
        self.__ds: DataSource = DataSource()
        self.addCleanup(self.__ds.engine.dispose)
        patchers: list[Any] = [
            mock.patch.object(fetch_lyrics, "ds", self.__ds),
            mock.patch.object(
                fetch_lyrics.LyricsFetcher,
                "_LyricsFetcher__SLEEP_SECONDS", 0.0)]
        for patcher in patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

    def __seed(self, songs: list[tuple[str, str]]) -> None:
        """Create the schema and the fixture songs.

        Each song gets a single primary artist at position 0;
        the song IDs are assigned in list order starting from 1.

        :param songs: The (title, artist) pairs.
        :return: None.
        """
        self.__seed_with_credit(
            [(title, artist, artist) for title, artist in songs])

    def __seed_with_credit(
            self, songs: list[tuple[str, str, str]]) -> None:
        """Create the schema and the fixture songs.

        Each song gets a single primary artist at position 0 and
        an independently given artist credit; the song IDs are
        assigned in list order starting from 1.

        :param songs: The (title, artist, artist_credit) triples.
        :return: None.
        """
        Base.metadata.create_all(self.__ds.engine)
        session: Session = self.__ds.get_db()
        try:
            artists: dict[str, Artist] = {}
            title: str
            artist: str
            credit: str
            for title, artist, credit in songs:
                if artist not in artists:
                    artists[artist] = Artist(name=artist)
                song: Song = Song(title=title,
                                  artist_credit=credit)
                session.add(song)
                session.add(SongArtist(song=song,
                                       artist=artists[artist],
                                       role=Role.PRIMARY,
                                       position=0))
            session.commit()
        finally:
            session.close()

    @staticmethod
    def __response(payload: dict[str, Any]) -> mock.MagicMock:
        """Build a fake HTTP response with a JSON body.

        :param payload: The JSON payload of the response body.
        :return: The fake response, usable as a context manager.
        """
        response: mock.MagicMock = mock.MagicMock()
        response.__enter__.return_value = response
        response.read.return_value \
            = json.dumps(payload).encode("utf-8")
        return response

    def __not_found(self) -> urllib.error.HTTPError:
        """Build an HTTP 404 error, closed when the test ends.

        :return: The HTTP 404 error.
        """
        error: urllib.error.HTTPError = urllib.error.HTTPError(
            "https://example.com/", 404, "Not Found", None, None)
        self.addCleanup(error.close)
        return error

    def __run_fetch(self) -> tuple[int, str]:
        """Run the fetcher with the standard error captured.

        :return: A tuple of the exit status and the standard
            error.
        """
        stderr: io.StringIO = io.StringIO()
        with redirect_stderr(stderr):
            status: int = fetch_lyrics.main(
                [str(self.__lyrics), str(self.__provenance)])
        return status, stderr.getvalue()

    @staticmethod
    def __read_rows(path: Path) -> list[list[str]]:
        """Read the rows of a CSV file.

        :param path: The CSV file.
        :return: The rows, the header included.
        """
        with open(path, encoding="utf-8", newline="") as file:
            return list(csv.reader(file))

    def test_ovh_hit(self) -> None:
        """Test that a Lyrics.ovh hit writes the cache files."""
        self.__seed([("Hello", "Adele")])
        urlopen: mock.Mock
        with mock.patch(
                "urllib.request.urlopen",
                side_effect=[self.__response(
                    {"lyrics": "Hello, it's me\n"})]) as urlopen:
            status: int
            stderr: str
            status, stderr = self.__run_fetch()
        self.assertEqual(status, 0)
        self.assertEqual(urlopen.call_count, 1)
        request: Any = urlopen.call_args[0][0]
        self.assertEqual(
            request.get_header("User-agent"),
            fetch_lyrics.LyricsFetcher._LyricsFetcher__USER_AGENT)
        self.assertEqual(
            (self.__lyrics / "1.txt")
            .read_text(encoding="utf-8"),
            "Hello, it's me\n")
        rows: list[list[str]] = self.__read_rows(
            self.__provenance)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0], self.PROVENANCE_HEADER)
        self.assertEqual(rows[1][:3],
                         ["1", "lyrics.ovh", "api-fetch"])
        self.assertNotEqual(rows[1][3], "")
        self.assertEqual(rows[1][4], "")
        self.assertIn(
            "Done.  Fetched lyrics for 1/1 songs.", stderr)

    def test_lrclib_fallback(self) -> None:
        """Test that an ovh miss falls back to an LRCLIB hit."""
        self.__seed([("Hello", "Adele")])
        urlopen: mock.Mock
        with mock.patch(
                "urllib.request.urlopen",
                side_effect=[
                    self.__not_found(),
                    self.__response({"plainLyrics": "Hello\n"})]
                ) as urlopen:
            status: int = self.__run_fetch()[0]
        self.assertEqual(status, 0)
        self.assertEqual(urlopen.call_count, 2)
        self.assertEqual(
            (self.__lyrics / "1.txt")
            .read_text(encoding="utf-8"),
            "Hello\n")
        rows: list[list[str]] = self.__read_rows(
            self.__provenance)
        self.assertEqual(rows[1][:2], ["1", "lrclib"])

    def test_credit_fallback_hit(self) -> None:
        """Test that a joint credit is queried after both miss."""
        self.__seed_with_credit(
            [("Tequila", "Dan", "Dan + Shay")])
        urlopen: mock.Mock
        with mock.patch(
                "urllib.request.urlopen",
                side_effect=[
                    self.__not_found(),
                    self.__not_found(),
                    self.__not_found(),
                    self.__response(
                        {"plainLyrics": "Tequila\n"})]) as urlopen:
            status: int = self.__run_fetch()[0]
        self.assertEqual(status, 0)
        self.assertEqual(urlopen.call_count, 4)
        urls: list[str] = [x[0][0].full_url
                           for x in urlopen.call_args_list]
        self.assertIn("Dan%20%2B%20Shay", urls[2])
        self.assertIn("artist_name=Dan+%2B+Shay", urls[3])
        self.assertEqual(
            (self.__lyrics / "1.txt")
            .read_text(encoding="utf-8"),
            "Tequila\n")
        rows: list[list[str]] = self.__read_rows(
            self.__provenance)
        self.assertEqual(rows[1][:2], ["1", "lrclib"])

    def test_credit_fallback_skipped_when_same(self) -> None:
        """Test that a matching credit skips the second round."""
        self.__seed([("Hello", "Adele")])
        urlopen: mock.Mock
        with mock.patch(
                "urllib.request.urlopen",
                side_effect=[self.__not_found(),
                             self.__not_found()]) as urlopen:
            status: int = self.__run_fetch()[0]
        self.assertEqual(status, 0)
        self.assertEqual(urlopen.call_count, 2)

    def test_both_miss(self) -> None:
        """Test that a double miss reports the song as missing."""
        self.__seed([("Hello", "Adele")])
        with mock.patch(
                "urllib.request.urlopen",
                side_effect=[self.__not_found(),
                             self.__not_found()]):
            status: int
            stderr: str
            status, stderr = self.__run_fetch()
        self.assertEqual(status, 0)
        self.assertFalse((self.__lyrics / "1.txt").exists())
        self.assertFalse(self.__provenance.exists())
        self.assertIn("song 1 \"Hello\": miss", stderr)
        self.assertIn(
            "Done.  Fetched lyrics for 0/1 songs.", stderr)

    def test_cached_song_skipped(self) -> None:
        """Test that a cached song triggers no HTTP request."""
        self.__seed([("Hello", "Adele")])
        self.__lyrics.mkdir()
        (self.__lyrics / "1.txt").write_text(
            "cached\n", encoding="utf-8")
        urlopen: mock.Mock
        with mock.patch("urllib.request.urlopen") as urlopen:
            status: int = self.__run_fetch()[0]
        self.assertEqual(status, 0)
        urlopen.assert_not_called()
        self.assertEqual(
            (self.__lyrics / "1.txt")
            .read_text(encoding="utf-8"),
            "cached\n")

    def test_url_encoding(self) -> None:
        """Test the percent-encoding of the artist and title."""
        self.__seed([("What's Up? / Down", "AC/DC & Friends")])
        urlopen: mock.Mock
        with mock.patch(
                "urllib.request.urlopen",
                side_effect=[self.__not_found(),
                             self.__not_found()]) as urlopen:
            self.__run_fetch()
        self.assertEqual(urlopen.call_count, 2)
        urls: list[str] = [x[0][0].full_url
                           for x in urlopen.call_args_list]
        self.assertEqual(
            urls[0],
            "https://api.lyrics.ovh/v1/AC%2FDC%20%26%20Friends/"
            "What%27s%20Up%3F%20%2F%20Down")
        self.assertEqual(
            urls[1],
            "https://lrclib.net/api/get"
            "?artist_name=AC%2FDC+%26+Friends"
            "&track_name=What%27s+Up%3F+%2F+Down")

    def test_provenance_single_header(self) -> None:
        """Test that the provenance keeps one header across runs."""
        self.__seed([("Hello", "Adele"),
                     ("Umbrella", "Rihanna")])
        with mock.patch(
                "urllib.request.urlopen",
                side_effect=[
                    self.__response({"lyrics": "one\n"}),
                    self.__response({"lyrics": "two\n"})]):
            self.assertEqual(self.__run_fetch()[0], 0)
        rows: list[list[str]] = self.__read_rows(
            self.__provenance)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0], self.PROVENANCE_HEADER)
        (self.__lyrics / "2.txt").unlink()
        with mock.patch(
                "urllib.request.urlopen",
                side_effect=[
                    self.__response({"lyrics": "two again\n"})]):
            self.assertEqual(self.__run_fetch()[0], 0)
        rows = self.__read_rows(self.__provenance)
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[0], self.PROVENANCE_HEADER)
        self.assertNotIn(self.PROVENANCE_HEADER, rows[1:])
        self.assertEqual([x[0] for x in rows[1:]],
                         ["1", "2", "2"])

    def test_normalize_cp1252_mojibake(self) -> None:
        """Test that cp1252 mojibake codepoints are restored."""
        self.assertEqual(
            fetch_lyrics.LyricsFetchRunner.normalize_lyrics("wait"),
            "wait…")
        self.assertEqual(
            fetch_lyrics.LyricsFetchRunner.normalize_lyrics(
                "quote"),
            "‘quote’")
        self.assertEqual(
            fetch_lyrics.LyricsFetchRunner.normalize_lyrics(
                "quote"),
            "“quote”")
        self.assertEqual(
            fetch_lyrics.LyricsFetchRunner.normalize_lyrics("dashline"),
            "dash—line")

    def test_normalize_undefined_cp1252_removed(self) -> None:
        """Test that undefined cp1252 byte values are removed."""
        text: str = ("abcdef")
        self.assertEqual(
            fetch_lyrics.LyricsFetchRunner.normalize_lyrics(text), "abcdef")

    def test_normalize_homoglyphs(self) -> None:
        """Test that watermark homoglyphs are restored."""
        self.assertEqual(
            fetch_lyrics.LyricsFetchRunner.normalize_lyrics("likе that"),
            "like that")
        self.assertEqual(
            fetch_lyrics.LyricsFetchRunner.normalize_lyrics("lό que soy"),
            "ló que soy")

    def test_normalize_space_variants(self) -> None:
        """Test that exotic space variants become ASCII space."""
        self.assertEqual(
            fetch_lyrics.LyricsFetchRunner.normalize_lyrics(
                "a b c d"),
            "a b c d")

    def test_normalize_zero_width_removed(self) -> None:
        """Test that zero-width characters are removed."""
        text: str = (
            "a​b‌c‍d﻿e")
        self.assertEqual(
            fetch_lyrics.LyricsFetchRunner.normalize_lyrics(text), "abcde")

    def test_normalize_ascii_unchanged(self) -> None:
        """Test that plain ASCII text passes through unchanged."""
        text: str = "Hello, it's me\n"
        self.assertEqual(
            fetch_lyrics.LyricsFetchRunner.normalize_lyrics(text), text)

    def test_normalize_legitimate_non_ascii_unchanged(self) -> None:
        """Test that legitimate non-ASCII content is unchanged."""
        text: str = "¿cómo estás? 안녕하세요\n"
        self.assertEqual(
            fetch_lyrics.LyricsFetchRunner.normalize_lyrics(text), text)

    def test_fetched_lyrics_saved_normalized(self) -> None:
        """Test that a fetched lyric is normalized before saving."""
        self.__seed([("Hello", "Adele")])
        with mock.patch(
                "urllib.request.urlopen",
                side_effect=[self.__response(
                    {"lyrics": "wait likе"
                               " that now​\n"})]):
            status: int = self.__run_fetch()[0]
        self.assertEqual(status, 0)
        self.assertEqual(
            (self.__lyrics / "1.txt")
            .read_text(encoding="utf-8"),
            "wait… like that now\n")

    def test_no_store_fails(self) -> None:
        """Test that a missing working store fails the run."""
        urlopen: mock.Mock
        with mock.patch("urllib.request.urlopen") as urlopen:
            status: int
            stderr: str
            status, stderr = self.__run_fetch()
        self.assertNotEqual(status, 0)
        urlopen.assert_not_called()
        self.assertIn("error:", stderr)
