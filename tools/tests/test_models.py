# Tools for A Feminist Audit of Pop Music.
# Copyright 2026 imacat.  All rights reserved.
# Authors:
#   imacat@mail.imacat.idv.tw (imacat), 2026/7/31
# AI assistance: Claude Code (Anthropic)
"""Unit tests for the data models."""
import unittest

import sqlalchemy as sa
from sqlalchemy.orm import Session

from pop_fem_audit_tools import config
from pop_fem_audit_tools.database import Base, DataSource
from pop_fem_audit_tools.models import (
    Artist,
    ChartEntry,
    Coding,
    Role,
    Song,
    SongArtist,
)


class TestModels(unittest.TestCase):
    """Test cases for the data models."""

    def setUp(self) -> None:
        """Create the schema on an in-memory SQLite database."""
        config.set_settings(config.Settings(
            SQLALCHEMY_DATABASE_URL="sqlite://",
            ANTHROPIC_API_KEY="test-key"))
        self.__ds: DataSource = DataSource()
        self.addCleanup(self.__ds.engine.dispose)
        Base.metadata.create_all(self.__ds.engine)
        self.__session: Session = self.__ds.get_db()
        self.addCleanup(self.__session.close)

    def __add_song(self) -> None:
        """Add a song with chart entries, artists, and lyrics.

        :return: None.
        """
        song: Song = Song(title="One Dance",
                          artist_credit="Drake featuring Wizkid")
        song.chart_entries = [ChartEntry(year=2016, rank=4)]
        song.song_artists = [
            SongArtist(artist=Artist(name="Drake"),
                       role=Role.PRIMARY, position=0),
            SongArtist(artist=Artist(name="Wizkid"),
                       role=Role.FEATURED, position=1)]
        song.lyrics = "Baby, I like your style"
        song.codings = [
            Coding(keyword="desire",
                   quotes="Baby, I like your style|One dance"),
            Coding(keyword="nightlife", quotes="")]
        self.__session.add(song)
        self.__session.commit()

    def test_song_graph(self) -> None:
        """Test reading a song graph back through relationships."""
        self.__add_song()
        self.__session.expunge_all()
        song: Song | None = self.__session.scalar(
            sa.select(Song).where(Song.title == "One Dance"))
        assert song is not None
        self.assertEqual(song.artist_credit,
                         "Drake featuring Wizkid")
        self.assertEqual([(x.year, x.rank)
                          for x in song.chart_entries],
                         [(2016, 4)])
        self.assertEqual([(x.artist.name, x.role, x.position)
                          for x in song.song_artists],
                         [("Drake", Role.PRIMARY, 0),
                          ("Wizkid", Role.FEATURED, 1)])
        self.assertEqual(song.lyrics,
                         "Baby, I like your style")
        artist: Artist | None = self.__session.scalar(
            sa.select(Artist).where(Artist.name == "Wizkid"))
        assert artist is not None
        self.assertEqual([x.song.title for x in artist.song_artists],
                         ["One Dance"])

    def test_duplicated_song_rejected(self) -> None:
        """Test that a duplicated title and artist credit fails."""
        self.__add_song()
        self.__session.add(
            Song(title="One Dance",
                 artist_credit="Drake featuring Wizkid"))
        with self.assertRaises(sa.exc.IntegrityError):
            self.__session.commit()

    def test_song_codings(self) -> None:
        """Test reading a song's codings back through the
        relationship."""
        self.__add_song()
        self.__session.expunge_all()
        song: Song | None = self.__session.scalar(
            sa.select(Song).where(Song.title == "One Dance"))
        assert song is not None
        self.assertEqual(
            {(x.keyword, x.quotes) for x in song.codings},
            {("desire", "Baby, I like your style|One dance"),
             ("nightlife", "")})
        coding: Coding | None = self.__session.scalar(
            sa.select(Coding).where(Coding.keyword == "desire"))
        assert coding is not None
        self.assertEqual(coding.song.title, "One Dance")

    def test_duplicated_coding_rejected(self) -> None:
        """Test that a repeated song and keyword fails."""
        self.__add_song()
        song: Song | None = self.__session.scalar(
            sa.select(Song).where(Song.title == "One Dance"))
        assert song is not None
        self.__session.add(
            Coding(song_id=song.id, keyword="desire",
                   quotes="another line"))
        with self.assertRaises(sa.exc.IntegrityError):
            self.__session.commit()

    def test_invalid_role_rejected(self) -> None:
        """Test that an invalid song-artist role fails."""
        self.__add_song()
        song: Song | None = self.__session.scalar(
            sa.select(Song).where(Song.title == "One Dance"))
        assert song is not None
        self.__session.add(
            SongArtist(song=song, artist=Artist(name="Kyla"),
                       role="cover", position=2))
        with self.assertRaises(sa.exc.IntegrityError):
            self.__session.commit()
