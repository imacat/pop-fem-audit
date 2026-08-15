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
    CodeGroup,
    Coding,
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
        self.__codings: Path = self.__dir / "codings.csv"
        self.__groups: Path = self.__dir / "groups.csv"
        self.__gender_corrections: Path = \
            self.__dir / "gender_corrections.csv"
        self.__write_chart(self.CHART_CSV)
        config.set_settings(config.Settings(
            SQLALCHEMY_DATABASE_URL="sqlite://",
            ANTHROPIC_API_KEY="test-key"))
        self.__ds: DataSource = DataSource()
        self.addCleanup(self.__ds.engine.dispose)
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

    def __write_wikidata(self, content: str) -> None:
        """Write the Wikidata artist snapshot CSV fixture.

        :param content: The CSV content.
        :return: None.
        """
        self.__wikidata.write_text(content, encoding="utf-8")

    def __write_codings(self, content: str) -> None:
        """Write the coding CSV fixture.

        :param content: The CSV content.
        :return: None.
        """
        self.__codings.write_text(content, encoding="utf-8")

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
        self.assertIn("4 artists", stderr)

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

    def test_canonical_pinkfong_resolves_to_hope_segoine(
            self) -> None:
        """Test that a "Pinkfong" credit stores the artist named
        "Hope Segoine", leaving the printed credit untouched."""
        self.__write_chart(
            "year,rank,title,artist\n"
            "2016,1,Baby Shark,Pinkfong\n"
            "2016,2,filler,Filler Artist\n"
            "2017,1,filler2,Filler Artist Two\n"
            "2017,2,filler3,Filler Artist Three\n")
        status: int
        stderr: str
        status, stderr = self.__run_build()
        self.assertEqual(status, 0)
        session: Session = self.__session()
        song: Song | None = session.scalar(
            sa.select(Song).where(Song.title == "Baby Shark"))
        assert song is not None
        self.assertEqual(song.artist_credit, "Pinkfong")
        self.assertEqual(
            [x.artist.name for x in song.song_artists],
            ["Hope Segoine"])

    GENDER_CHART_CSV: str = (
        "year,rank,title,artist\n"
        "2016,1,Mixed Song,\"Adele, Drake & Nobody\"\n"
        "2016,2,Female Song,Adele & Taylor Swift\n"
        "2017,1,Unknown Song,Adele featuring Nobody\n"
        "2017,2,No Gender Song,Nobody Else\n")
    """The chart CSV fixture exercising the performer gender: a
    disagreement with an unknown artist, an all-known agreement, an
    agreement with an unknown artist, and no known gender."""

    GENDER_WIKIDATA_CSV: str = (
        "name,qid,gender,type,genre,country,note\n"
        "Adele,Q2831,female,solo,pop,GB,\n"
        "Drake,Q33240,male,solo,hip-hop,CA,\n"
        "Taylor Swift,Q26876,female,solo,pop,US,\n"
        "Nobody,,,solo,pop,US,\n"
        "Nobody Else,,,solo,pop,US,\n")
    """The artist snapshot fixture for the performer gender, giving
    "Nobody" and "Nobody Else" a performing type without a
    gender."""

    def __performer_genders(self) -> dict[str, str | None]:
        """Read the stored performer genders keyed by the titles.

        :return: The stored performer genders, keyed by the song
            titles.
        """
        session: Session = self.__session()
        return {x.title: x.performer_gender
                for x in session.scalars(sa.select(Song))}

    def test_performer_gender_derived(self) -> None:
        """Test the performer gender of every song: a disagreement
        gives "mixed" even with an unknown artist, an all-known
        agreement gives that gender, and an unknown artist otherwise
        leaves it unset."""
        self.__write_chart(self.GENDER_CHART_CSV)
        self.__write_wikidata(self.GENDER_WIKIDATA_CSV)
        status: int
        stderr: str
        status, stderr = self.__run_build(
            "--wikidata-csv", str(self.__wikidata))
        self.assertEqual(status, 0)
        self.assertEqual(
            self.__performer_genders(),
            {"Mixed Song": "mixed",
             "Female Song": "female",
             "Unknown Song": None,
             "No Gender Song": None})

    def test_performer_gender_in_songs_csv(self) -> None:
        """Test that songs.csv mirrors the performer gender, empty
        when it is unset."""
        self.__write_chart(self.GENDER_CHART_CSV)
        self.__write_wikidata(self.GENDER_WIKIDATA_CSV)
        self.assertEqual(
            self.__run_build("--wikidata-csv",
                             str(self.__wikidata))[0], 0)
        rows: list[list[str]] = self.__read_csv_rows("songs.csv")
        self.assertEqual(
            [(row[0], row[3]) for row in rows],
            [("Female Song", "female"),
             ("Mixed Song", "mixed"),
             ("No Gender Song", ""),
             ("Unknown Song", "")])

    NON_PERFORMING_CHART_CSV: str = (
        "year,rank,title,artist\n"
        "2016,1,Lemonade,"
        "Internet Money & Gunna Featuring Don Toliver\n"
        "2016,2,Bruno,\"Adassa, Rhenzy Feliz & Encanto Cast\"\n"
        "2017,1,Label Song,Internet Money & Encanto Cast\n"
        "2017,2,filler,Filler Artist\n")
    """The chart CSV fixture exercising the non-performing credits:
    a non-performing credit alongside agreeing performers, one
    alongside disagreeing performers, and a song credited to
    non-performing artists only."""

    NON_PERFORMING_WIKIDATA_CSV: str = (
        "name,qid,gender,type,genre,country,note\n"
        "Gunna,Q55613105,male,solo,hip-hop,US,\n"
        "Don Toliver,Q56513383,male,solo,hip-hop,US,\n"
        "Adassa,Q576181,female,solo,pop,US,\n"
        "Rhenzy Feliz,Q34344805,male,solo,pop,US,\n"
        "Internet Money,Q99691610,,,hip-hop,US,\n"
        "Encanto Cast,Q140814124,,,,US,\n")
    """The artist snapshot fixture for the non-performing credits,
    leaving "Internet Money" and "Encanto Cast" without a gender and
    without a type."""

    def __build_non_performing(self) -> dict[str, str | None]:
        """Build the non-performing credit fixture and read back the
        performer genders.

        :return: The stored performer genders, keyed by the song
            titles.
        """
        self.__write_chart(self.NON_PERFORMING_CHART_CSV)
        self.__write_wikidata(self.NON_PERFORMING_WIKIDATA_CSV)
        self.assertEqual(
            self.__run_build("--wikidata-csv",
                             str(self.__wikidata))[0], 0)
        return self.__performer_genders()

    def test_non_performing_credit_does_not_block(self) -> None:
        """Test that a credited artist without a type does not block
        the agreement of the performing artists."""
        self.assertEqual(
            self.__build_non_performing()["Lemonade"], "male")

    def test_non_performing_credit_keeps_mixed(self) -> None:
        """Test that a credited artist without a type leaves a
        disagreement among the performing artists as "mixed"."""
        self.assertEqual(
            self.__build_non_performing()["Bruno"], "mixed")

    def test_all_non_performing_credits_unset(self) -> None:
        """Test that a song credited to artists without a type only
        leaves the performer gender unset."""
        self.assertIsNone(
            self.__build_non_performing()["Label Song"])

    def test_first_run_on_fresh_store(self) -> None:
        """Test that a build on a fresh store creates the tables."""
        self.assertEqual(
            sa.inspect(self.__ds.engine).get_table_names(), [])
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
            ["Title", "Artists", "Positions", "Performer Gender"])
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

    CODINGS_CSV: str = (
        "Song,Artist Credit,Keyword,Quote\n"
        "Hello,Adele,longing,\"Hello from the other side / I must"
        " have called a thousand times\"\n"
        "Hello,Adele,regret,I'm sorry|It's no secret\n"
        "One Dance,Drake featuring Wizkid,desire,\n")
    """The coding CSV fixture: a quote carrying the " / "
    line-break convention, two quotes joined by "|", and an empty
    quote."""

    def __stored_codings(self) -> dict[tuple[str, str], str]:
        """Read the stored codings keyed by the song and keyword.

        :return: The stored quotes, keyed by the song title and the
            keyword.
        """
        session: Session = self.__session()
        return {(x.song.title, x.keyword): x.quotes
                for x in session.scalars(sa.select(Coding))}

    def test_codings_imported(self) -> None:
        """Test that the coding CSV imports one row per song and
        keyword, storing the quote column verbatim."""
        self.__write_codings(self.CODINGS_CSV)
        status: int
        stderr: str
        status, stderr = self.__run_build(
            "--codings", str(self.__codings))
        self.assertEqual(status, 0)
        self.assertIn("3 codings", stderr)
        self.assertEqual(
            self.__stored_codings(),
            {("Hello", "longing"):
                "Hello from the other side / I must have called"
                " a thousand times",
             ("Hello", "regret"): "I'm sorry|It's no secret",
             ("One Dance", "desire"): ""})

    def test_codings_reach_the_song(self) -> None:
        """Test that a stored coding reaches its song through the
        relationship."""
        self.__write_codings(self.CODINGS_CSV)
        self.assertEqual(
            self.__run_build("--codings", str(self.__codings))[0], 0)
        session: Session = self.__session()
        song: Song | None = session.get(Song, 1)
        assert song is not None
        self.assertEqual(sorted(x.keyword for x in song.codings),
                         ["longing", "regret"])

    def test_omitted_codings_leaves_table_empty(self) -> None:
        """Test that an omitted coding option leaves no codings."""
        self.__write_codings(self.CODINGS_CSV)
        status: int
        stderr: str
        status, stderr = self.__run_build()
        self.assertEqual(status, 0)
        self.assertIn("0 codings", stderr)
        self.assertEqual(self.__stored_codings(), {})

    def test_codings_unknown_song_fails(self) -> None:
        """Test that a coding row naming an unknown song fails the
        build, leaving the previous store contents intact."""
        self.assertEqual(self.__run_build()[0], 0)
        titles: dict[int, str] = self.__song_titles()
        self.__write_codings(
            "Song,Artist Credit,Keyword,Quote\n"
            "Nowhere,Nobody,longing,a line\n")
        status: int
        stderr: str
        status, stderr = self.__run_build(
            "--codings", str(self.__codings))
        self.assertNotEqual(status, 0)
        self.assertIn("no song \"Nowhere\" by \"Nobody\"", stderr)
        self.assertEqual(self.__song_titles(), titles)
        self.assertEqual(self.__stored_codings(), {})

    def test_codings_duplicated_keyword_fails(self) -> None:
        """Test that two rows naming the same song and keyword fail
        the build, without partial data."""
        self.__write_codings(
            "Song,Artist Credit,Keyword,Quote\n"
            "Hello,Adele,longing,a line\n"
            "Hello,Adele,longing,another line\n")
        status: int
        stderr: str
        status, stderr = self.__run_build(
            "--codings", str(self.__codings))
        self.assertNotEqual(status, 0)
        self.assertIn("duplicated coding", stderr)
        session: Session = self.__session()
        self.assertEqual(list(session.scalars(sa.select(Song))), [])

    def test_codings_missing_column_fails(self) -> None:
        """Test that a coding CSV missing a required column fails
        the build."""
        self.__write_codings(
            "Song,Artist Credit,Keyword\n"
            "Hello,Adele,longing\n")
        status: int
        stderr: str
        status, stderr = self.__run_build(
            "--codings", str(self.__codings))
        self.assertNotEqual(status, 0)
        self.assertIn("missing column(s): Quote", stderr)
        self.assertEqual(self.__stored_codings(), {})

    def test_missing_codings_csv_fails(self) -> None:
        """Test that a given but missing coding CSV fails."""
        status: int
        stderr: str
        status, stderr = self.__run_build(
            "--codings", str(self.__codings))
        self.assertNotEqual(status, 0)
        self.assertIn("error:", stderr)
        self.assertIn(str(self.__codings), stderr)
        session: Session = self.__session()
        self.assertEqual(list(session.scalars(sa.select(Song))), [])

    def test_codings_replaced_on_rebuild(self) -> None:
        """Test that a rebuild replaces the previous codings rather
        than adding to them."""
        self.__write_codings(self.CODINGS_CSV)
        self.assertEqual(
            self.__run_build("--codings", str(self.__codings))[0], 0)
        self.__write_codings(
            "Song,Artist Credit,Keyword,Quote\n"
            "Shape of You,Ed Sheeran,attraction,I'm in love with"
            " your body\n")
        status: int
        stderr: str
        status, stderr = self.__run_build(
            "--codings", str(self.__codings))
        self.assertEqual(status, 0)
        self.assertIn("1 codings", stderr)
        self.assertEqual(
            self.__stored_codings(),
            {("Shape of You", "attraction"):
                "I'm in love with your body"})

    GROUPS_CSV: str = (
        "Group,Keyword,Votes\n"
        "masculine,dominance-and-power,3\n"
        "masculine,family-and-fatherhood,2\n"
        "women-power,women-power,3\n")
    """The group CSV fixture: two groups, one two-vote member."""

    def __write_groups(self, content: str) -> None:
        """Write the group CSV fixture.

        :param content: The CSV content.
        :return: None.
        """
        self.__groups.write_text(content, encoding="utf-8")

    def __stored_groups(self) -> dict[tuple[str, str], int]:
        """Read the stored group members keyed by group and keyword.

        :return: The stored votes, keyed by the group name and the
            keyword.
        """
        session: Session = self.__session()
        return {(x.group, x.keyword): x.votes
                for x in session.scalars(sa.select(CodeGroup))}

    def test_groups_imported(self) -> None:
        """Test that the group CSV imports one row per group and
        keyword, the votes stored as integers."""
        self.__write_groups(self.GROUPS_CSV)
        status: int
        stderr: str
        status, stderr = self.__run_build(
            "--groups", str(self.__groups))
        self.assertEqual(status, 0)
        self.assertIn("3 group members", stderr)
        self.assertEqual(
            self.__stored_groups(),
            {("masculine", "dominance-and-power"): 3,
             ("masculine", "family-and-fatherhood"): 2,
             ("women-power", "women-power"): 3})

    def test_groups_replaced_on_rebuild(self) -> None:
        """Test that a rebuild replaces the previous groups rather
        than adding to them."""
        self.__write_groups(self.GROUPS_CSV)
        self.assertEqual(
            self.__run_build("--groups", str(self.__groups))[0], 0)
        self.__write_groups(
            "Group,Keyword,Votes\n"
            "vulnerable,longing-and-loss,3\n")
        status: int
        stderr: str
        status, stderr = self.__run_build(
            "--groups", str(self.__groups))
        self.assertEqual(status, 0)
        self.assertIn("1 group members", stderr)
        self.assertEqual(
            self.__stored_groups(),
            {("vulnerable", "longing-and-loss"): 3})

    def test_duplicated_group_member_fails(self) -> None:
        """Test that two rows naming the same group and keyword
        fail the build."""
        self.__write_groups(
            "Group,Keyword,Votes\n"
            "masculine,dominance-and-power,3\n"
            "masculine,dominance-and-power,2\n")
        status: int
        stderr: str
        status, stderr = self.__run_build(
            "--groups", str(self.__groups))
        self.assertNotEqual(status, 0)
        self.assertIn("duplicated group member", stderr)

    def test_group_votes_not_an_integer_fails(self) -> None:
        """Test that a non-integer votes field fails the build."""
        self.__write_groups(
            "Group,Keyword,Votes\n"
            "masculine,dominance-and-power,three\n")
        status: int
        stderr: str
        status, stderr = self.__run_build(
            "--groups", str(self.__groups))
        self.assertNotEqual(status, 0)
        self.assertIn("is not an integer", stderr)

    def test_groups_missing_column_fails(self) -> None:
        """Test that a group CSV without a required column fails
        the build."""
        self.__write_groups(
            "Group,Keyword\n"
            "masculine,dominance-and-power\n")
        status: int
        stderr: str
        status, stderr = self.__run_build(
            "--groups", str(self.__groups))
        self.assertNotEqual(status, 0)
        self.assertIn("missing column(s): Votes", stderr)

    def __write_gender_corrections(self, content: str) -> None:
        """Write the gender correction CSV fixture.

        :param content: The CSV content.
        :return: None.
        """
        self.__gender_corrections.write_text(
            content, encoding="utf-8")

    def test_gender_correction_overrides_derived_gender(
            self) -> None:
        """Test that a correction row overrides an already-derived
        performer gender, stored verbatim."""
        self.__write_chart(self.GENDER_CHART_CSV)
        self.__write_wikidata(self.GENDER_WIKIDATA_CSV)
        self.__write_gender_corrections(
            "Title,Artist Credit,Performer Gender,Note\n"
            "Female Song,Adele & Taylor Swift,mixed,reviewed\n")
        status: int
        stderr: str
        status, stderr = self.__run_build(
            "--wikidata-csv", str(self.__wikidata),
            "--gender-corrections", str(self.__gender_corrections))
        self.assertEqual(status, 0)
        self.assertEqual(
            self.__performer_genders()["Female Song"], "mixed")

    def test_gender_correction_sets_undetermined_gender(
            self) -> None:
        """Test that a correction row sets the performer gender of
        a song the derivation left undetermined."""
        self.__write_chart(self.GENDER_CHART_CSV)
        self.__write_wikidata(self.GENDER_WIKIDATA_CSV)
        self.__write_gender_corrections(
            "Title,Artist Credit,Performer Gender,Note\n"
            "Unknown Song,Adele featuring Nobody,female,"
            "reviewed\n")
        status: int
        stderr: str
        status, stderr = self.__run_build(
            "--wikidata-csv", str(self.__wikidata),
            "--gender-corrections", str(self.__gender_corrections))
        self.assertEqual(status, 0)
        self.assertEqual(
            self.__performer_genders()["Unknown Song"], "female")

    def test_gender_correction_in_songs_csv(self) -> None:
        """Test that songs.csv mirrors the corrected performer
        gender."""
        self.__write_chart(self.GENDER_CHART_CSV)
        self.__write_wikidata(self.GENDER_WIKIDATA_CSV)
        self.__write_gender_corrections(
            "Title,Artist Credit,Performer Gender,Note\n"
            "Female Song,Adele & Taylor Swift,mixed,reviewed\n")
        self.assertEqual(
            self.__run_build(
                "--wikidata-csv", str(self.__wikidata),
                "--gender-corrections",
                str(self.__gender_corrections))[0], 0)
        rows: list[list[str]] = self.__read_csv_rows("songs.csv")
        self.assertIn(("Female Song", "mixed"),
                      {(row[0], row[3]) for row in rows})

    def test_omitted_gender_corrections_leaves_derived_gender(
            self) -> None:
        """Test that an omitted correction option leaves the
        derived performer genders untouched."""
        self.__write_chart(self.GENDER_CHART_CSV)
        self.__write_wikidata(self.GENDER_WIKIDATA_CSV)
        self.__write_gender_corrections(
            "Title,Artist Credit,Performer Gender,Note\n"
            "Female Song,Adele & Taylor Swift,mixed,reviewed\n")
        status: int
        stderr: str
        status, stderr = self.__run_build(
            "--wikidata-csv", str(self.__wikidata))
        self.assertEqual(status, 0)
        self.assertEqual(
            self.__performer_genders()["Female Song"], "female")

    def test_gender_correction_unknown_song_fails(self) -> None:
        """Test that a correction row naming an unknown song fails
        the build, naming the file and the offending title and
        credit."""
        self.__write_chart(self.GENDER_CHART_CSV)
        self.__write_wikidata(self.GENDER_WIKIDATA_CSV)
        self.__write_gender_corrections(
            "Title,Artist Credit,Performer Gender,Note\n"
            "Nowhere,Nobody,female,reviewed\n")
        status: int
        stderr: str
        status, stderr = self.__run_build(
            "--wikidata-csv", str(self.__wikidata),
            "--gender-corrections", str(self.__gender_corrections))
        self.assertNotEqual(status, 0)
        self.assertIn(str(self.__gender_corrections), stderr)
        self.assertIn("no song \"Nowhere\" by \"Nobody\"", stderr)

    def test_gender_corrections_missing_column_fails(self) -> None:
        """Test that a gender correction CSV missing a required
        column fails the build."""
        self.__write_gender_corrections(
            "Title,Artist Credit,Performer Gender\n"
            "Hello,Adele,female\n")
        status: int
        stderr: str
        status, stderr = self.__run_build(
            "--gender-corrections", str(self.__gender_corrections))
        self.assertNotEqual(status, 0)
        self.assertIn("missing column(s): Note", stderr)

    def test_missing_gender_corrections_csv_fails(self) -> None:
        """Test that a given but missing gender correction CSV
        fails the build."""
        status: int
        stderr: str
        status, stderr = self.__run_build(
            "--gender-corrections", str(self.__gender_corrections))
        self.assertNotEqual(status, 0)
        self.assertIn("error:", stderr)
        self.assertIn(str(self.__gender_corrections), stderr)
        session: Session = self.__session()
        self.assertEqual(list(session.scalars(sa.select(Song))), [])
