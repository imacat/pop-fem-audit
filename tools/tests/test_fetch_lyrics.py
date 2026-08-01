# Tools for A Feminist Audit of Pop Music.
# Copyright 2026 imacat.  All rights reserved.
# Authors:
#   imacat@mail.imacat.idv.tw (imacat), 2026/7/31
"""Unit tests for the lyrics fetcher module."""
import csv
import io
import json
import os
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stderr
from pathlib import Path
from typing import Any
from unittest import mock

from sqlalchemy.orm import Session

from pop_fem_audit_tools import config, fetch_lyrics
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
    MISSING_HEADER: list[str] = [
        "song_id", "title", "artist_credit", "reason"]
    """The expected header row of the missing report CSV file."""

    def setUp(self) -> None:
        """Create a temporary working directory with the store."""
        tmp: tempfile.TemporaryDirectory[str] \
            = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.__dir: Path = Path(tmp.name)
        old_cwd: str = os.getcwd()
        self.addCleanup(os.chdir, old_cwd)
        os.chdir(self.__dir)
        Path("data").mkdir()
        url: str = f"sqlite:///{self.__dir}/store.sqlite3"
        config.set_settings(config.Settings(
            SQLALCHEMY_DATABASE_URL=url,
            ANTHROPIC_API_KEY="test-key"))
        self.__ds: DataSource = DataSource()
        patchers: list[Any] = [
            mock.patch.object(fetch_lyrics, "ds", self.__ds),
            mock.patch.object(fetch_lyrics, "SLEEP_SECONDS", 0.0)]
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
        Base.metadata.create_all(self.__ds.engine)
        session: Session = self.__ds.get_db()
        try:
            artists: dict[str, Artist] = {}
            title: str
            artist: str
            for title, artist in songs:
                if artist not in artists:
                    artists[artist] = Artist(name=artist)
                song: Song = Song(title=title,
                                  artist_credit=artist)
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

    @staticmethod
    def __not_found() -> urllib.error.HTTPError:
        """Build an HTTP 404 error.

        :return: The HTTP 404 error.
        """
        return urllib.error.HTTPError(
            "https://example.com/", 404, "Not Found", None, None)

    @staticmethod
    def __run_fetch() -> tuple[int, str]:
        """Run the fetcher with the standard error captured.

        :return: A tuple of the exit status and the standard
            error.
        """
        stderr: io.StringIO = io.StringIO()
        with redirect_stderr(stderr):
            status: int = fetch_lyrics.main([])
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
        self.assertEqual(request.get_header("User-agent"),
                         fetch_lyrics.USER_AGENT)
        self.assertEqual(
            Path("data/lyrics/1.txt").read_text(encoding="utf-8"),
            "Hello, it's me\n")
        rows: list[list[str]] = self.__read_rows(
            Path("data/lyrics_provenance.csv"))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0], self.PROVENANCE_HEADER)
        self.assertEqual(rows[1][:3],
                         ["1", "lyrics.ovh", "api-fetch"])
        self.assertNotEqual(rows[1][3], "")
        self.assertEqual(rows[1][4], "")
        self.assertIn("1 fetched, 0 missed", stderr)

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
            Path("data/lyrics/1.txt").read_text(encoding="utf-8"),
            "Hello\n")
        rows: list[list[str]] = self.__read_rows(
            Path("data/lyrics_provenance.csv"))
        self.assertEqual(rows[1][:2], ["1", "lrclib"])

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
        self.assertFalse(Path("data/lyrics/1.txt").exists())
        self.assertFalse(
            Path("data/lyrics_provenance.csv").exists())
        rows: list[list[str]] = self.__read_rows(
            Path("data/lyrics_missing.csv"))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0], self.MISSING_HEADER)
        self.assertEqual(rows[1][:3], ["1", "Hello", "Adele"])
        self.assertIn("0 fetched, 1 missed", stderr)

    def test_cached_song_skipped(self) -> None:
        """Test that a cached song triggers no HTTP request."""
        self.__seed([("Hello", "Adele")])
        Path("data/lyrics").mkdir()
        Path("data/lyrics/1.txt").write_text(
            "cached\n", encoding="utf-8")
        urlopen: mock.Mock
        with mock.patch("urllib.request.urlopen") as urlopen:
            status: int = self.__run_fetch()[0]
        self.assertEqual(status, 0)
        urlopen.assert_not_called()
        self.assertEqual(
            Path("data/lyrics/1.txt").read_text(encoding="utf-8"),
            "cached\n")
        rows: list[list[str]] = self.__read_rows(
            Path("data/lyrics_missing.csv"))
        self.assertEqual(rows, [self.MISSING_HEADER])

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
        provenance: Path = Path("data/lyrics_provenance.csv")
        rows: list[list[str]] = self.__read_rows(provenance)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0], self.PROVENANCE_HEADER)
        Path("data/lyrics/2.txt").unlink()
        with mock.patch(
                "urllib.request.urlopen",
                side_effect=[
                    self.__response({"lyrics": "two again\n"})]):
            self.assertEqual(self.__run_fetch()[0], 0)
        rows = self.__read_rows(provenance)
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[0], self.PROVENANCE_HEADER)
        self.assertNotIn(self.PROVENANCE_HEADER, rows[1:])
        self.assertEqual([x[0] for x in rows[1:]],
                         ["1", "2", "2"])

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
