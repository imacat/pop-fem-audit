# Tools for A Feminist Audit of Pop Music.
# Copyright 2026 imacat.  All rights reserved.
# Authors:
#   imacat@mail.imacat.idv.tw (imacat), 2026/7/31
"""Unit tests for the working store builder module."""
import io
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from typing import Any
from unittest import mock

import sqlalchemy as sa
from sqlalchemy.orm import Session

from pop_fem_audit_tools import build_db, config
from pop_fem_audit_tools.database import DataSource
from pop_fem_audit_tools.models import (
    Artist,
    ChartEntry,
    Role,
    Song,
)


class TestParseArtistCredit(unittest.TestCase):
    """Test cases for the artist credit parser."""

    def test_plain_solo(self) -> None:
        """Test a plain solo artist credit."""
        self.assertEqual(build_db.parse_artist_credit("Adele"),
                         [("Adele", Role.PRIMARY)])

    def test_featuring_with_and(self) -> None:
        """Test a featuring credit with an "and" delimiter."""
        self.assertEqual(
            build_db.parse_artist_credit(
                "Drake featuring Wizkid and Kyla"),
            [("Drake", Role.PRIMARY),
             ("Wizkid", Role.FEATURED),
             ("Kyla", Role.FEATURED)])

    def test_comma_and_ampersand(self) -> None:
        """Test a credit with comma and ampersand delimiters."""
        self.assertEqual(
            build_db.parse_artist_credit(
                "Lady Gaga, Bradley Cooper & BloodPop"),
            [("Lady Gaga", Role.PRIMARY),
             ("Bradley Cooper", Role.PRIMARY),
             ("BloodPop", Role.PRIMARY)])

    def test_x_delimiter(self) -> None:
        """Test the "x" delimiter."""
        self.assertEqual(
            build_db.parse_artist_credit("KAROL G x Nicki Minaj"),
            [("KAROL G", Role.PRIMARY),
             ("Nicki Minaj", Role.PRIMARY)])

    def test_plus_delimiter(self) -> None:
        """Test the "+" delimiter."""
        self.assertEqual(
            build_db.parse_artist_credit("Marshmello + Halsey"),
            [("Marshmello", Role.PRIMARY),
             ("Halsey", Role.PRIMARY)])

    def test_with_delimiter(self) -> None:
        """Test the "with" delimiter."""
        self.assertEqual(
            build_db.parse_artist_credit(
                "Kane Brown with Lauren Alaina"),
            [("Kane Brown", Role.PRIMARY),
             ("Lauren Alaina", Role.PRIMARY)])

    def test_feat_abbreviation(self) -> None:
        """Test that "Feat." splits the featured side."""
        self.assertEqual(
            build_db.parse_artist_credit(
                "Ariana Grande Feat. Doja Cat"
                " & Megan Thee Stallion"),
            [("Ariana Grande", Role.PRIMARY),
             ("Doja Cat", Role.FEATURED),
             ("Megan Thee Stallion", Role.FEATURED)])

    def test_case_insensitive_featuring(self) -> None:
        """Test that "Featuring" splits case-insensitively."""
        self.assertEqual(
            build_db.parse_artist_credit(
                "24kGoldn Featuring iann dior"),
            [("24kGoldn", Role.PRIMARY),
             ("iann dior", Role.FEATURED)])


class TestBuildDB(unittest.TestCase):
    """Test cases for the working store build."""

    CHART_CSV: str = (
        "year,rank,title,artist\n"
        "2016,1,Hello,Adele\n"
        "2016,2,One Dance,Drake featuring Wizkid\n"
        "2017,1,One Dance,Drake featuring Wizkid\n"
        "2017,2,Shape of You,Ed Sheeran\n")
    """The default chart CSV fixture: 2 years with 2 ranks each."""

    def setUp(self) -> None:
        """Create a temporary data directory with the fixtures."""
        tmp: tempfile.TemporaryDirectory[str] \
            = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.__dir: Path = Path(tmp.name)
        self.__chart: Path = self.__dir / "chart.csv"
        self.__lyrics: Path = self.__dir / "lyrics"
        self.__wikidata: Path = \
            self.__dir / "artists_wikidata.csv"
        self.__overrides: Path = \
            self.__dir / "artists_overrides.csv"
        self.__write_chart(self.CHART_CSV)
        url: str = f"sqlite:///{self.__dir}/store.sqlite3"
        config.set_settings(config.Settings(
            SQLALCHEMY_DATABASE_URL=url,
            ANTHROPIC_API_KEY="test-key"))
        self.__ds: DataSource = DataSource()
        patchers: list[Any] = [
            mock.patch.object(build_db, "ds", self.__ds),
            mock.patch.object(build_db, "YEARS", [2016, 2017]),
            mock.patch.object(build_db, "RANKS_PER_YEAR", 2)]
        for patcher in patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

    def __write_chart(self, content: str) -> None:
        """Write the chart CSV fixture.

        :param content: The CSV content.
        :return: None.
        """
        self.__chart.write_text(content, encoding="utf-8")

    def __run_build(self, *options: str) -> tuple[int, str]:
        """Run the build with the standard error captured.

        :param options: The additional command-line options.
        :return: A tuple of the exit status and the standard
            error.
        """
        stderr: io.StringIO = io.StringIO()
        with redirect_stderr(stderr):
            status: int = build_db.main(
                [str(self.__chart), *options])
        return status, stderr.getvalue()

    def __session(self) -> Session:
        """Open a database session closed on test cleanup.

        :return: The database session.
        """
        session: Session = self.__ds.get_db()
        self.addCleanup(session.close)
        return session

    def __song_titles(self) -> dict[int, str]:
        """Read the song titles keyed by their IDs.

        :return: The song titles, keyed by the song IDs.
        """
        session: Session = self.__session()
        return {x.id: x.title
                for x in session.scalars(sa.select(Song))}

    def test_dedup_repeated_song(self) -> None:
        """Test that a song repeated across years is stored once."""
        status: int
        stderr: str
        status, stderr = self.__run_build()
        self.assertEqual(status, 0)
        session: Session = self.__session()
        self.assertEqual(
            len(list(session.scalars(sa.select(Song)))), 3)
        song: Song | None = session.scalar(
            sa.select(Song).where(Song.title == "One Dance"))
        assert song is not None
        self.assertEqual(sorted((x.year, x.rank)
                                for x in song.chart_entries),
                         [(2016, 2), (2017, 1)])
        self.assertEqual([(x.artist.name, x.role, x.position)
                          for x in song.song_artists],
                         [("Drake", Role.PRIMARY, 0),
                          ("Wizkid", Role.FEATURED, 1)])
        self.assertIn("3 songs", stderr)
        self.assertIn("4 chart entries", stderr)
        self.assertIn("4 artists", stderr)
        self.assertIn("4 credits", stderr)

    def test_first_run_on_fresh_store(self) -> None:
        """Test that a build on a fresh store creates the tables."""
        self.assertFalse((self.__dir / "store.sqlite3").exists())
        self.assertEqual(self.__run_build()[0], 0)
        session: Session = self.__session()
        self.assertEqual(
            len(list(session.scalars(sa.select(Song)))), 3)

    def test_deterministic_ids(self) -> None:
        """Test that two rebuilds assign the same song IDs."""
        self.assertEqual(self.__run_build()[0], 0)
        titles: dict[int, str] = self.__song_titles()
        self.assertEqual(titles, {1: "Hello", 2: "One Dance",
                                  3: "Shape of You"})
        self.assertEqual(self.__run_build()[0], 0)
        self.assertEqual(self.__song_titles(), titles)

    def test_failed_build_keeps_previous(self) -> None:
        """Test that a failed build keeps the previous contents."""
        self.assertEqual(self.__run_build()[0], 0)
        titles: dict[int, str] = self.__song_titles()
        self.__write_chart(
            "year,rank,title,artist\n"
            "2016,1,Hello,Adele\n")
        status: int
        stderr: str
        status, stderr = self.__run_build()
        self.assertNotEqual(status, 0)
        self.assertIn("year 2016 rank 2", stderr)
        self.assertEqual(self.__song_titles(), titles)
        session: Session = self.__session()
        self.assertEqual(
            len(list(session.scalars(sa.select(ChartEntry)))), 4)

    def test_missing_rank_fails(self) -> None:
        """Test that a missing rank fails without partial data."""
        self.__write_chart(
            "year,rank,title,artist\n"
            "2016,1,Hello,Adele\n"
            "2016,2,One Dance,Drake featuring Wizkid\n"
            "2017,1,One Dance,Drake featuring Wizkid\n")
        status: int
        stderr: str
        status, stderr = self.__run_build()
        self.assertNotEqual(status, 0)
        self.assertIn("year 2017 rank 2", stderr)
        session: Session = self.__session()
        self.assertEqual(
            list(session.scalars(sa.select(ChartEntry))), [])
        self.assertEqual(list(session.scalars(sa.select(Song))), [])

    def test_overrides_apply_over_wikidata(self) -> None:
        """Test that the overrides win over the Wikidata snapshot."""
        self.__wikidata.write_text(
            "name,qid,gender,type,genre,country,note\n"
            "Adele,Q2831,female,solo,pop,GB,\n",
            encoding="utf-8")
        self.__overrides.write_text(
            "name,qid,gender,type,genre,country,note\n"
            "Adele,,,,soul,,manually checked\n",
            encoding="utf-8")
        self.assertEqual(self.__run_build(
            "--wikidata-csv", str(self.__wikidata),
            "--overrides-csv", str(self.__overrides))[0], 0)
        session: Session = self.__session()
        artist: Artist | None = session.scalar(
            sa.select(Artist).where(Artist.name == "Adele"))
        assert artist is not None
        self.assertEqual(artist.genre, "soul")
        self.assertEqual(artist.gender, "female")
        self.assertEqual(artist.wikidata_qid, "Q2831")
        self.assertEqual(artist.country, "GB")

    def test_unknown_override_name_fails(self) -> None:
        """Test that an unknown override name fails the build."""
        self.__overrides.write_text(
            "name,qid,gender,type,genre,country,note\n"
            "Adel,,female,,,,typo\n", encoding="utf-8")
        status: int
        stderr: str
        status, stderr = self.__run_build(
            "--overrides-csv", str(self.__overrides))
        self.assertNotEqual(status, 0)
        self.assertIn("Adel", stderr)
        session: Session = self.__session()
        self.assertEqual(list(session.scalars(sa.select(Song))), [])

    def test_lyrics_loaded(self) -> None:
        """Test loading the lyrics cache into the songs."""
        self.__lyrics.mkdir()
        (self.__lyrics / "1.txt").write_text(
            "Hello, it's me\n", encoding="utf-8")
        (self.__lyrics / "999.txt").write_text(
            "orphan\n", encoding="utf-8")
        status: int
        stderr: str
        status, stderr = self.__run_build(
            "--lyrics-dir", str(self.__lyrics))
        self.assertEqual(status, 0)
        self.assertIn("999", stderr)
        self.assertIn("1 songs with lyrics", stderr)
        session: Session = self.__session()
        song: Song | None = session.get(Song, 1)
        assert song is not None
        self.assertEqual(song.title, "Hello")
        self.assertEqual(song.lyrics, "Hello, it's me\n")

    def test_omitted_options_skip_capture_layers(self) -> None:
        """Test that omitted options leave the layers unloaded."""
        self.__lyrics.mkdir()
        (self.__lyrics / "1.txt").write_text(
            "Hello, it's me\n", encoding="utf-8")
        self.__wikidata.write_text(
            "name,qid,gender,type,genre,country,note\n"
            "Adele,Q2831,female,solo,pop,GB,\n",
            encoding="utf-8")
        status: int
        stderr: str
        status, stderr = self.__run_build()
        self.assertEqual(status, 0)
        self.assertIn("0 songs with lyrics", stderr)
        session: Session = self.__session()
        song: Song | None = session.get(Song, 1)
        assert song is not None
        self.assertIsNone(song.lyrics)
        artist: Artist | None = session.scalar(
            sa.select(Artist).where(Artist.name == "Adele"))
        assert artist is not None
        self.assertIsNone(artist.wikidata_qid)
        self.assertIsNone(artist.gender)

    def test_missing_lyrics_dir_fails(self) -> None:
        """Test that a given but missing lyrics directory fails."""
        status: int
        stderr: str
        status, stderr = self.__run_build(
            "--lyrics-dir", str(self.__lyrics))
        self.assertNotEqual(status, 0)
        self.assertIn(f"error: {self.__lyrics}", stderr)
        session: Session = self.__session()
        self.assertEqual(list(session.scalars(sa.select(Song))), [])

    def test_missing_wikidata_csv_fails(self) -> None:
        """Test that a given but missing snapshot CSV fails."""
        status: int
        stderr: str
        status, stderr = self.__run_build(
            "--wikidata-csv", str(self.__wikidata))
        self.assertNotEqual(status, 0)
        self.assertIn("error:", stderr)
        self.assertIn(str(self.__wikidata), stderr)
        session: Session = self.__session()
        self.assertEqual(list(session.scalars(sa.select(Song))), [])

    def test_missing_overrides_csv_fails(self) -> None:
        """Test that a given but missing override CSV fails."""
        status: int
        stderr: str
        status, stderr = self.__run_build(
            "--overrides-csv", str(self.__overrides))
        self.assertNotEqual(status, 0)
        self.assertIn("error:", stderr)
        self.assertIn(str(self.__overrides), stderr)
        session: Session = self.__session()
        self.assertEqual(list(session.scalars(sa.select(Song))), [])
