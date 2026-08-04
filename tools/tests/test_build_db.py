# Tools for A Feminist Audit of Pop Music.
# Copyright 2026 imacat.  All rights reserved.
# Authors:
#   imacat@mail.imacat.idv.tw (imacat), 2026/7/31
"""Unit tests for the working store builder module."""
import csv
import io
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from typing import Any
from unittest import mock

import sqlalchemy as sa
from sqlalchemy.orm import Session

from pop_fem_audit_tools import config
from pop_fem_audit_tools.commands import build_db
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
        self.assertEqual(
            build_db.ArtistImporter.parse_artist_credit("Adele"),
            [("Adele", Role.PRIMARY)])

    def test_featuring_with_and(self) -> None:
        """Test a featuring credit with an "and" delimiter."""
        self.assertEqual(
            build_db.ArtistImporter.parse_artist_credit(
                "Drake featuring Wizkid and Kyla"),
            [("Drake", Role.PRIMARY),
             ("Wizkid", Role.FEATURED),
             ("Kyla", Role.FEATURED)])

    def test_comma_and_ampersand(self) -> None:
        """Test a credit with comma and ampersand delimiters."""
        self.assertEqual(
            build_db.ArtistImporter.parse_artist_credit(
                "Lady Gaga, Bradley Cooper & BloodPop"),
            [("Lady Gaga", Role.PRIMARY),
             ("Bradley Cooper", Role.PRIMARY),
             ("BloodPop", Role.PRIMARY)])

    def test_x_delimiter(self) -> None:
        """Test the "x" delimiter."""
        self.assertEqual(
            build_db.ArtistImporter.parse_artist_credit(
                "KAROL G x Nicki Minaj"),
            [("KAROL G", Role.PRIMARY),
             ("Nicki Minaj", Role.PRIMARY)])

    def test_plus_delimiter(self) -> None:
        """Test the "+" delimiter."""
        self.assertEqual(
            build_db.ArtistImporter.parse_artist_credit(
                "Marshmello + Halsey"),
            [("Marshmello", Role.PRIMARY),
             ("Halsey", Role.PRIMARY)])

    def test_with_delimiter(self) -> None:
        """Test the "with" delimiter."""
        self.assertEqual(
            build_db.ArtistImporter.parse_artist_credit(
                "Kane Brown with Lauren Alaina"),
            [("Kane Brown", Role.PRIMARY),
             ("Lauren Alaina", Role.PRIMARY)])

    def test_feat_abbreviation(self) -> None:
        """Test that "Feat." splits the featured side."""
        self.assertEqual(
            build_db.ArtistImporter.parse_artist_credit(
                "Ariana Grande Feat. Doja Cat"
                " & Megan Thee Stallion"),
            [("Ariana Grande", Role.PRIMARY),
             ("Doja Cat", Role.FEATURED),
             ("Megan Thee Stallion", Role.FEATURED)])

    def test_case_insensitive_featuring(self) -> None:
        """Test that "Featuring" splits case-insensitively."""
        self.assertEqual(
            build_db.ArtistImporter.parse_artist_credit(
                "24kGoldn Featuring iann dior"),
            [("24kGoldn", Role.PRIMARY),
             ("iann dior", Role.FEATURED)])

    def test_colon_prefix_group(self) -> None:
        """Test that a colon-prefixed group name is dropped."""
        self.assertEqual(
            build_db.ArtistImporter.parse_artist_credit(
                "¥$: Ye & Ty Dolla $ign Featuring Rich The Kid"
                " & Playboi Carti"),
            [("Ye", Role.PRIMARY),
             ("Ty Dolla $ign", Role.PRIMARY),
             ("Rich The Kid", Role.FEATURED),
             ("Playboi Carti", Role.FEATURED)])

    def test_colon_prefix_with_ampersand_in_prefix(self) -> None:
        """Test a colon prefix that itself contains "&"."""
        self.assertEqual(
            build_db.ArtistImporter.parse_artist_credit(
                "Rumi & JINU: EJAE & Andrew Choi"),
            [("EJAE", Role.PRIMARY),
             ("Andrew Choi", Role.PRIMARY)])

    def test_colon_prefix_comma_list(self) -> None:
        """Test a colon-prefixed comma-separated member list."""
        self.assertEqual(
            build_db.ArtistImporter.parse_artist_credit(
                "HUNTR/X: EJAE, Audrey Nuna & REI AMI"),
            [("EJAE", Role.PRIMARY),
             ("Audrey Nuna", Role.PRIMARY),
             ("REI AMI", Role.PRIMARY)])

    def test_colon_prefix_five_members(self) -> None:
        """Test a colon-prefixed five-member list."""
        self.assertEqual(
            build_db.ArtistImporter.parse_artist_credit(
                "Saja Boys: Andrew Choi, Neckwav, Danny Chung,"
                " Kevin Woo & samUIL Lee"),
            [("Andrew Choi", Role.PRIMARY),
             ("Neckwav", Role.PRIMARY),
             ("Danny Chung", Role.PRIMARY),
             ("Kevin Woo", Role.PRIMARY),
             ("samUIL Lee", Role.PRIMARY)])

    def test_colon_prefix_duo(self) -> None:
        """Test a colon-prefixed two-member list."""
        self.assertEqual(
            build_db.ArtistImporter.parse_artist_credit(
                "THE ANXIETY: WILLOW & Tyler Cole"),
            [("WILLOW", Role.PRIMARY),
             ("Tyler Cole", Role.PRIMARY)])

    def test_parenthesized_members(self) -> None:
        """Test that a parenthesized member list replaces the
        group name spanning the whole credit."""
        self.assertEqual(
            build_db.ArtistImporter.parse_artist_credit(
                "Silk Sonic (Bruno Mars & Anderson .Paak)"),
            [("Bruno Mars", Role.PRIMARY),
             ("Anderson .Paak", Role.PRIMARY)])

    def test_duet_with_connector(self) -> None:
        """Test that "Duet With" is a co-billing connector like
        "with", dropping the word "Duet" entirely."""
        self.assertEqual(
            build_db.ArtistImporter.parse_artist_credit(
                "Blake Shelton Duet With Gwen Stefani"),
            [("Blake Shelton", Role.PRIMARY),
             ("Gwen Stefani", Role.PRIMARY)])
        self.assertEqual(
            build_db.ArtistImporter.parse_artist_credit(
                "Keith Urban Duet With P!nk"),
            [("Keith Urban", Role.PRIMARY),
             ("P!nk", Role.PRIMARY)])

    def test_slash_delimiter(self) -> None:
        """Test the " / " co-billing delimiter."""
        self.assertEqual(
            build_db.ArtistImporter.parse_artist_credit(
                "Cole Swindell / Lainey Wilson"),
            [("Cole Swindell", Role.PRIMARY),
             ("Lainey Wilson", Role.PRIMARY)])
        self.assertEqual(
            build_db.ArtistImporter.parse_artist_credit(
                "Zayn / Taylor Swift"),
            [("Zayn", Role.PRIMARY),
             ("Taylor Swift", Role.PRIMARY)])

    def test_protected_name_lil_nas_x(self) -> None:
        """Test that "Lil Nas X" is guarded from the " x "
        delimiter split."""
        self.assertEqual(
            build_db.ArtistImporter.parse_artist_credit(
                "Lil Nas X & Jack Harlow"),
            [("Lil Nas X", Role.PRIMARY),
             ("Jack Harlow", Role.PRIMARY)])

    def test_protected_name_tyler_the_creator(self) -> None:
        """Test that "Tyler, The Creator" is guarded from the
        comma delimiter split."""
        self.assertEqual(
            build_db.ArtistImporter.parse_artist_credit(
                "Tyler, The Creator Featuring GloRilla, Sexyy Red"
                " & Lil Wayne"),
            [("Tyler, The Creator", Role.PRIMARY),
             ("GloRilla", Role.FEATURED),
             ("Sexyy Red", Role.FEATURED),
             ("Lil Wayne", Role.FEATURED)])

    def test_protected_name_tones_and_i(self) -> None:
        """Test that "Tones And I" is guarded from the " and "
        delimiter split."""
        self.assertEqual(
            build_db.ArtistImporter.parse_artist_credit(
                "Tones And I"),
            [("Tones And I", Role.PRIMARY)])

    def test_exception_spotemgottem(self) -> None:
        """Test the SpotemGottem exception-table credit."""
        self.assertEqual(
            build_db.ArtistImporter.parse_artist_credit(
                "SpotemGottem Featuring Pooh Shiesty Or DaBaby"),
            [("SpotemGottem", Role.PRIMARY),
             ("Pooh Shiesty", Role.FEATURED),
             ("DaBaby", Role.FEATURED)])

    def test_exception_the_scotts(self) -> None:
        """Test the THE SCOTTS exception-table credit."""
        self.assertEqual(
            build_db.ArtistImporter.parse_artist_credit(
                "THE SCOTTS, Travis Scott & Kid Cudi"),
            [("Travis Scott", Role.PRIMARY),
             ("Kid Cudi", Role.PRIMARY)])

    def test_exception_drake_featuring_the_throne(self) -> None:
        """Test the Drake Featuring The Throne exception-table
        credit."""
        self.assertEqual(
            build_db.ArtistImporter.parse_artist_credit(
                "Drake Featuring The Throne"),
            [("Drake", Role.PRIMARY),
             ("Jay Z", Role.FEATURED),
             ("Kanye West", Role.FEATURED)])

    def test_plus_delimiter_unaffected(self) -> None:
        """Test that the existing "+" delimiter split is
        unaffected by the new rules."""
        self.assertEqual(
            build_db.ArtistImporter.parse_artist_credit(
                "Dan + Shay"),
            [("Dan", Role.PRIMARY), ("Shay", Role.PRIMARY)])


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
        self.__derived: Path = self.__dir / "derived"
        self.__lyrics: Path = self.__dir / "lyrics"
        self.__wikidata: Path = \
            self.__dir / "artists_wikidata.csv"
        self.__write_chart(self.CHART_CSV)
        url: str = f"sqlite:///{self.__dir}/store.sqlite3"
        config.set_settings(config.Settings(
            SQLALCHEMY_DATABASE_URL=url,
            ANTHROPIC_API_KEY="test-key"))
        self.__ds: DataSource = DataSource()
        patchers: list[Any] = [
            mock.patch.object(build_db, "ds", self.__ds),
            mock.patch.object(
                build_db.SongImporter, "YEARS", [2016, 2017]),
            mock.patch.object(
                build_db.SongImporter, "RANKS_PER_YEAR", 2)]
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
                [str(self.__chart), str(self.__derived), *options])
        return status, stderr.getvalue()

    def __read_csv_rows(self, name: str) -> list[list[str]]:
        """Read the data rows of a derived CSV file.

        :param name: The CSV file name under the derived directory.
        :return: The data rows, the header row excluded.
        """
        with open(self.__derived / name, encoding="utf-8",
                  newline="") as file:
            rows: list[list[str]] = list(csv.reader(file))
        return rows[1:]

    def __read_csv_header(self, name: str) -> list[str]:
        """Read the header row of a derived CSV file.

        :param name: The CSV file name under the derived directory.
        :return: The header row.
        """
        with open(self.__derived / name, encoding="utf-8",
                  newline="") as file:
            return next(csv.reader(file))

    @staticmethod
    def __split_joined_field(value: str,
                             separator: str = "|") -> list[str]:
        """Split a joined field into its entries.

        :param value: The joined field value.
        :param separator: The join separator.
        :return: The entries, in the given order.
        """
        return value.split(separator)

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

    def test_dedup_credit_variant(self) -> None:
        """Test that a credit variant listed in
        ``CANONICAL_ARTIST_CREDITS`` merges into one song, storing
        the canonical credit, with the canonical artist spelling
        applied to the artist listed in ``CANONICAL_ARTIST_NAMES``."""
        self.__write_chart(
            "year,rank,title,artist\n"
            "2016,1,Eastside,\"benny blanco, Halsey & Khalid\"\n"
            "2016,2,filler,Filler Artist\n"
            "2017,1,Eastside,\"Benny Blanco, Halsey & Khalid\"\n"
            "2017,2,filler,Filler Artist\n")
        status: int
        stderr: str
        status, stderr = self.__run_build()
        self.assertEqual(status, 0)
        session: Session = self.__session()
        songs: list[Song] = list(session.scalars(
            sa.select(Song).where(Song.title == "Eastside")))
        self.assertEqual(len(songs), 1)
        self.assertEqual(songs[0].artist_credit,
                         "Benny Blanco, Halsey & Khalid")
        self.assertEqual(
            sorted((x.year, x.rank)
                   for x in songs[0].chart_entries),
            [(2016, 1), (2017, 1)])
        self.assertEqual(
            [x.artist.name for x in songs[0].song_artists],
            ["benny blanco", "Halsey", "Khalid"])

    def test_dedup_artist_name_case_variant(self) -> None:
        """Test that an artist name case variant merges into one
        artist, keeping the first-seen spelling."""
        self.__write_chart(
            "year,rank,title,artist\n"
            "2016,1,Song One,Marshmello\n"
            "2016,2,filler,Filler Artist\n"
            "2017,1,Song Two,marshmello\n"
            "2017,2,filler,Filler Artist\n")
        status: int
        stderr: str
        status, stderr = self.__run_build()
        self.assertEqual(status, 0)
        session: Session = self.__session()
        artists: list[Artist] = list(session.scalars(
            sa.select(Artist).where(Artist.name.ilike("marsh%"))))
        self.assertEqual(len(artists), 1)
        self.assertEqual(artists[0].name, "Marshmello")
        self.assertEqual(
            {x.title for x in
             {y.song for y in artists[0].song_artists}},
            {"Song One", "Song Two"})

    def test_canonical_artist_name_restored(self) -> None:
        """Test that a canonical spelling is stored even for a
        single, non-canonically spelled occurrence."""
        self.__write_chart(
            "year,rank,title,artist\n"
            "2016,1,Beggin',Maneskin\n"
            "2016,2,filler,Filler Artist\n"
            "2017,1,filler2,Filler Artist Two\n"
            "2017,2,filler3,Filler Artist Three\n")
        status: int
        stderr: str
        status, stderr = self.__run_build()
        self.assertEqual(status, 0)
        session: Session = self.__session()
        artist: Artist | None = session.scalar(
            sa.select(Artist).where(Artist.name.ilike("m%nesk%")))
        assert artist is not None
        self.assertEqual(artist.name, "Måneskin")

    def test_canonical_ye_resolves_to_kanye_west(self) -> None:
        """Test that a "Ye" credit and a "Kanye West" credit merge
        into a single artist row named "Kanye West", credited on
        both songs."""
        self.__write_chart(
            "year,rank,title,artist\n"
            "2016,1,Song One,Ye\n"
            "2016,2,Song Two,Kanye West\n"
            "2017,1,filler2,Filler Artist Two\n"
            "2017,2,filler3,Filler Artist Three\n")
        status: int
        stderr: str
        status, stderr = self.__run_build()
        self.assertEqual(status, 0)
        session: Session = self.__session()
        artists: list[Artist] = list(session.scalars(
            sa.select(Artist).where(Artist.name == "Kanye West")))
        self.assertEqual(len(artists), 1)
        self.assertEqual(
            {x.title for x in
             {y.song for y in artists[0].song_artists}},
            {"Song One", "Song Two"})

    def test_canonical_silento_restores_diacritic(self) -> None:
        """Test that a "Silento" credit stores the diacritic-
        restored canonical spelling "Silentó"."""
        self.__write_chart(
            "year,rank,title,artist\n"
            "2016,1,Watch Me,Silento\n"
            "2016,2,filler,Filler Artist\n"
            "2017,1,filler2,Filler Artist Two\n"
            "2017,2,filler3,Filler Artist Three\n")
        status: int
        stderr: str
        status, stderr = self.__run_build()
        self.assertEqual(status, 0)
        session: Session = self.__session()
        artist: Artist | None = session.scalar(
            sa.select(Artist).where(Artist.name.ilike("silent%")))
        assert artist is not None
        self.assertEqual(artist.name, "Silentó")

    def test_canonical_dan_and_shay_full_names(self) -> None:
        """Test that a "Dan + Shay" credit stores the canonical
        full names "Dan Smyers" and "Shay Mooney"."""
        self.__write_chart(
            "year,rank,title,artist\n"
            "2016,1,Tequila,Dan + Shay\n"
            "2016,2,filler,Filler Artist\n"
            "2017,1,filler2,Filler Artist Two\n"
            "2017,2,filler3,Filler Artist Three\n")
        status: int
        stderr: str
        status, stderr = self.__run_build()
        self.assertEqual(status, 0)
        session: Session = self.__session()
        song: Song | None = session.scalar(
            sa.select(Song).where(Song.title == "Tequila"))
        assert song is not None
        self.assertEqual(
            [x.artist.name for x in song.song_artists],
            ["Dan Smyers", "Shay Mooney"])

    def test_canonical_surf_mesa_case_restored(self) -> None:
        """Test that a "surf mesa" credit stores the canonical
        case styling "Surf Mesa"."""
        self.__write_chart(
            "year,rank,title,artist\n"
            "2016,1,Ily,surf mesa\n"
            "2016,2,filler,Filler Artist\n"
            "2017,1,filler2,Filler Artist Two\n"
            "2017,2,filler3,Filler Artist Three\n")
        status: int
        stderr: str
        status, stderr = self.__run_build()
        self.assertEqual(status, 0)
        session: Session = self.__session()
        artist: Artist | None = session.scalar(
            sa.select(Artist).where(Artist.name.ilike("surf%")))
        assert artist is not None
        self.assertEqual(artist.name, "Surf Mesa")

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

    def test_duplicate_chart_entry_fails(self) -> None:
        """Test that a duplicated (year, rank) row fails without
        partial data, even though the set of distinct (year, rank)
        pairs still covers the expected grid exactly."""
        self.__write_chart(
            "year,rank,title,artist\n"
            "2016,1,Hello,Adele\n"
            "2016,1,Hello,Adele\n"
            "2016,2,One Dance,Drake featuring Wizkid\n"
            "2017,1,One Dance,Drake featuring Wizkid\n"
            "2017,2,Shape of You,Ed Sheeran\n")
        status: int
        stderr: str
        status, stderr = self.__run_build()
        self.assertNotEqual(status, 0)
        self.assertIn(
            "duplicated chart entry: year 2016 rank 1", stderr)
        session: Session = self.__session()
        self.assertEqual(
            list(session.scalars(sa.select(ChartEntry))), [])
        self.assertEqual(list(session.scalars(sa.select(Song))), [])

    def test_blank_artist_name_fails(self) -> None:
        """Test that a parsed credit with a name blank after
        stripping fails the build."""
        with mock.patch.object(
                build_db.ArtistImporter, "parse_artist_credit",
                return_value=[("Adele", Role.PRIMARY),
                              ("  ", Role.FEATURED)]):
            status: int
            stderr: str
            status, stderr = self.__run_build()
        self.assertNotEqual(status, 0)
        self.assertIn("blank artist name parsed", stderr)

    def test_no_primary_artist_fails(self) -> None:
        """Test that a parsed credit without a primary artist
        fails the build."""
        with mock.patch.object(
                build_db.ArtistImporter, "parse_artist_credit",
                return_value=[("Wizkid", Role.FEATURED)]):
            status: int
            stderr: str
            status, stderr = self.__run_build()
        self.assertNotEqual(status, 0)
        self.assertIn("no primary artist parsed", stderr)

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

    REVIEW_CHART_CSV: str = (
        "year,rank,title,artist\n"
        "2016,1,banana,Artist B\n"
        "2016,2,\"Me, Myself & I\",Billie\n"
        "2017,1,\"Me, Myself & I\",Billie\n"
        "2017,2,Apple,Artist A\n")
    """The chart CSV fixture exercising the review CSV ordering,
    positions, and the outer-field comma quoting."""

    def test_derived_dir_created_when_missing(self) -> None:
        """Test that the derived directory is created when
        missing."""
        self.assertFalse(self.__derived.exists())
        self.assertEqual(self.__run_build()[0], 0)
        self.assertTrue(self.__derived.is_dir())
        self.assertTrue((self.__derived / "songs.csv").is_file())
        self.assertTrue((self.__derived / "artists.csv").is_file())

    def test_songs_csv_written(self) -> None:
        """Test the songs.csv header, the rows, the title
        ordering, and the "/"-joined "positions" value."""
        self.__write_chart(self.REVIEW_CHART_CSV)
        self.assertEqual(self.__run_build()[0], 0)
        self.assertEqual(
            self.__read_csv_header("songs.csv"),
            ["Title", "Artists", "Positions"])
        rows: list[list[str]] = self.__read_csv_rows("songs.csv")
        self.assertEqual(
            [row[:2] for row in rows],
            [["Apple", "Artist A"],
             ["banana", "Artist B"],
             ["Me, Myself & I", "Billie"]])
        self.assertEqual(
            [self.__split_joined_field(row[2], "/") for row in rows],
            [["2017#2"], ["2016#1"], ["2016#2", "2017#1"]])

    def test_songs_csv_uses_minimal_quoting(self) -> None:
        """Test that songs.csv uses normal minimal CSV quoting: a
        numeric-looking title is written unquoted, like every other
        field not otherwise requiring quoting."""
        self.__write_chart(
            "year,rank,title,artist\n"
            "2016,1,679,Artist A\n"
            "2016,2,filler,Filler Artist\n"
            "2017,1,filler2,Filler Artist Two\n"
            "2017,2,filler3,Filler Artist Three\n")
        self.assertEqual(self.__run_build()[0], 0)
        content: str = (self.__derived / "songs.csv").read_text(
            encoding="utf-8")
        self.assertIn("679,Artist A,2016#1", content)

    def test_artists_csv_written(self) -> None:
        """Test the artists.csv header, the rows, the name
        ordering, and the "|"-joined "TITLE (YEAR#RANK...)" song
        encoding."""
        self.__write_chart(self.REVIEW_CHART_CSV)
        self.assertEqual(self.__run_build()[0], 0)
        self.assertEqual(
            self.__read_csv_header("artists.csv"),
            ["Name", "Wikidata QID", "Gender", "Type", "Genre",
             "Country", "Songs"])
        rows: list[list[str]] = self.__read_csv_rows("artists.csv")
        self.assertEqual(
            [row[0] for row in rows],
            ["Artist A", "Artist B", "Billie"])
        self.assertEqual(
            [self.__split_joined_field(row[6]) for row in rows],
            [["Apple (2017#2)"],
             ["banana (2016#1)"],
             ["Me, Myself & I (2016#2/2017#1)"]])

    def test_artists_csv_songs_field_quoted_for_comma_title(
            self) -> None:
        """Test that the outer "Songs" field is CSV-quoted as a
        whole when the joined value contains a comma, from a
        comma-bearing credited title."""
        self.__write_chart(self.REVIEW_CHART_CSV)
        self.assertEqual(self.__run_build()[0], 0)
        content: str = (self.__derived / "artists.csv").read_text(
            encoding="utf-8")
        self.assertIn(
            '"Me, Myself & I (2016#2/2017#1)"', content)
        self.assertIn("Apple (2017#2)\n", content)

    def test_derived_csvs_have_no_ids(self) -> None:
        """Test that neither derived CSV file exposes a song or an
        artist ID column."""
        self.assertEqual(self.__run_build()[0], 0)
        self.assertNotIn(
            "id", self.__read_csv_header("songs.csv"))
        self.assertNotIn(
            "id", self.__read_csv_header("artists.csv"))

    def test_derived_csvs_have_crlf_line_endings(self) -> None:
        """Test that the derived CSV files use CRLF line
        endings."""
        self.assertEqual(self.__run_build()[0], 0)
        raw: bytes = (self.__derived / "songs.csv").read_bytes()
        self.assertGreater(raw.count(b"\r\n"), 0)
        self.assertEqual(raw.count(b"\r"), raw.count(b"\r\n"))
        self.assertEqual(raw.count(b"\n"), raw.count(b"\r\n"))

    def test_failed_build_leaves_derived_csvs_untouched(self) -> None:
        """Test that a failed build does not touch the existing
        derived CSV files."""
        self.assertEqual(self.__run_build()[0], 0)
        songs_before: str = (self.__derived / "songs.csv").read_text(
            encoding="utf-8")
        artists_before: str = \
            (self.__derived / "artists.csv").read_text(
                encoding="utf-8")
        self.__write_chart(
            "year,rank,title,artist\n"
            "2016,1,Hello,Adele\n")
        status: int
        stderr: str
        status, stderr = self.__run_build()
        self.assertNotEqual(status, 0)
        self.assertEqual(
            (self.__derived / "songs.csv").read_text(
                encoding="utf-8"),
            songs_before)
        self.assertEqual(
            (self.__derived / "artists.csv").read_text(
                encoding="utf-8"),
            artists_before)
