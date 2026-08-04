# Tools for A Feminist Audit of Pop Music.
# Copyright 2026 imacat.  All rights reserved.
# Authors:
#   imacat@mail.imacat.idv.tw (imacat), 2026/7/31
"""The builder of the SQLite working store.

Rebuilds the working store from scratch out of the committed
inputs: the year-end chart CSV and the output directory for the
review CSV files, given as the two positional command-line
arguments, and the optional capture inputs, each given as an
option: the lyrics cache directory and the Wikidata artist
snapshot CSV.  An omitted option
leaves its capture layer unloaded; a given option whose path does
not exist fails the build.  Missing tables
are created on a fresh store; existing tables are never altered,
as the schema lifecycle belongs to the migrations.  Every rebuild
deletes all the rows, loads the data, and validates it in one
transaction, committed only after the data passes the validation
invariants; a failed build leaves the previous store contents
intact.

The rebuild is deterministic: the builder assigns the song and
artist IDs itself, as 1, 2, 3, ... in the first-occurrence file
order, so the IDs are reproducible across rebuilds on every
database engine, given the frozen input file.

A song is identified by its raw title together with its artist
credit, the credit canonicalized through
``SongImporter.CANONICAL_ARTIST_CREDITS``; a credit listed there
collapses onto the same song as its canonical form, and the
stored artist credit is always the canonical form.  Artist
deduplication is by the identity key resolved from the parsed
artist name (see `ArtistImporter.resolve_artist_identity`): the
case-folded name, or, when that case-folded name is listed in
``ArtistImporter.CANONICAL_ARTIST_NAMES``, the case-folded
canonical spelling, so letter-case variants and alternate
spellings mapped to the same canonical name all collapse onto a
single artist row.  The stored artist name is the first-seen
spelling, except for the names listed in
``ArtistImporter.CANONICAL_ARTIST_NAMES``, which always store the
canonical spelling regardless of which variant is seen first.

On a successful build, two review CSV files, ``songs.csv`` and
``artists.csv``, are (re)written under the given output directory,
mirroring the stored songs and artists without their IDs; see
`CSVExporter`.  A failed build leaves any existing review CSV
files untouched, matching the store rollback.
"""
import argparse
import csv
import re
import sys
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Self

import sqlalchemy as sa
from sqlalchemy.orm import Session

from ..database import Base, ds
from ..models import (
    Artist,
    ChartEntry,
    Role,
    Song,
    SongArtist,
)

ARTIST_FIELDS: dict[str, str] = {
    "qid": "wikidata_qid",
    "gender": "gender",
    "type": "type",
    "genre": "genre",
    "country": "country",
}
"""The artist CSV columns mapped to the Artist attributes."""


class BuildError(Exception):
    """An error that fails the build."""


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Parse the command-line arguments.

    :param argv: The command-line arguments, or None for
        ``sys.argv``.
    :return: The parsed arguments.
    """
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description="Rebuild the SQLite working store from the"
                    " committed inputs.")
    parser.add_argument(
        "chart_csv", type=Path,
        help="the year-end chart CSV file")
    parser.add_argument(
        "derived_dir", type=Path,
        help="the output directory for the review CSV files")
    parser.add_argument(
        "--lyrics-dir", type=Path, default=None,
        help="the lyrics cache directory to load")
    parser.add_argument(
        "--wikidata-csv", type=Path, default=None,
        help="the Wikidata artist snapshot CSV file to apply")
    return parser.parse_args(argv)


class SongImporter:
    """The song-import job: loads the chart CSV into songs and
    chart entries."""

    YEARS: Sequence[int] = range(2016, 2026)
    """The expected chart years."""
    RANKS_PER_YEAR: int = 100
    """The expected number of ranks on the chart of each year."""
    CANONICAL_ARTIST_CREDITS: dict[str, str] = {
        "benny blanco, Halsey & Khalid": "Benny Blanco, Halsey"
                                         " & Khalid",
    }
    """The canonical artist credit spellings, keyed by a variant
    credit string."""

    def __init__(self, session: Session) -> None:
        """Initialize the importer.

        :param session: The database session.
        """
        self.__session: Session = session
        self.__songs: dict[tuple[str, str], Song] = {}

    def import_songs(self, path: Path) -> None:
        """Load the chart CSV into songs and chart entries.

        A song repeated across the rows is stored once, matched by
        its identity key (see `song_identity`); every row yields
        one chart entry.  The stored title is the raw title; the
        stored artist credit is the canonical credit from the
        identity key.  The songs take the IDs 1, 2, 3, ... in the
        first-occurrence row order.  When the method returns, the
        imported songs and chart entries are queryable in the
        session.

        :param path: The chart CSV file with the columns year,
            rank, title, and artist.
        :return: None.
        :raises BuildError: When the chart entries do not cover
            each of ``YEARS`` and each rank from 1 to
            ``RANKS_PER_YEAR`` exactly once.
        :raises OSError: When the file cannot be read.
        """
        counts: Counter[tuple[int, int]] = Counter()
        with open(path, encoding="utf-8", newline="") as file:
            row: dict[str, str]
            for row in csv.DictReader(file):
                key: tuple[str, str] = self.song_identity(
                    row["title"], row["artist"])
                if key not in self.__songs:
                    title: str
                    credit: str
                    title, credit = key
                    song: Song = Song(
                        id=len(self.__songs) + 1, title=title,
                        artist_credit=credit)
                    self.__session.add(song)
                    self.__songs[key] = song
                year: int = int(row["year"])
                rank: int = int(row["rank"])
                counts[(year, rank)] += 1
                if counts[(year, rank)] == 1:
                    self.__session.add(ChartEntry(
                        year=year, rank=rank,
                        song=self.__songs[key]))
        self.__session.flush()
        self.__check_chart_coverage(counts)

    @classmethod
    def __check_chart_coverage(
            cls, counts: Counter[tuple[int, int]]) -> None:
        """Verify the chart entries cover the expected grid exactly.

        :param counts: The number of chart entries seen for each
            (year, rank) pair.
        :return: None.
        :raises BuildError: When a (year, rank) pair from the
            expected grid is missing, an unexpected pair is
            present, or a pair is duplicated.
        """
        expected: set[tuple[int, int]] = {
            (year, rank) for year in cls.YEARS
            for rank in range(1, cls.RANKS_PER_YEAR + 1)}
        actual: set[tuple[int, int]] = set(counts)
        violations: list[str] = []
        year: int
        rank: int
        for year, rank in sorted(expected - actual):
            violations.append(
                f"missing chart entry: year {year} rank {rank}")
        for year, rank in sorted(actual - expected):
            violations.append(
                f"unexpected chart entry: year {year} rank {rank}")
        for year, rank in sorted(counts):
            if counts[(year, rank)] > 1:
                violations.append(
                    f"duplicated chart entry: year {year} rank"
                    f" {rank}")
        if len(violations) > 0:
            raise BuildError("\n".join(violations))

    @staticmethod
    def song_identity(title: str, credit: str) -> tuple[str, str]:
        """Compute the identity key of a chart row.

        The key pairs the raw title with the artist credit,
        canonicalized through ``CANONICAL_ARTIST_CREDITS``; a
        credit absent from the table maps to itself.  Two chart
        rows denote the same song iff their identity keys are
        equal.

        :param title: The song title as printed on the chart.
        :param credit: The combined artist credit string.
        :return: The identity key: the raw title paired with the
            canonical artist credit.
        """
        return title, SongImporter.CANONICAL_ARTIST_CREDITS.get(
            credit, credit)


class ArtistImporter:
    """The artist-import job: parses the stored songs' artist
    credits into artists and song-artist credits."""

    FEATURING_PATTERN: re.Pattern[str] = re.compile(
        r" featuring | feat\. ", re.IGNORECASE)
    """The pattern splitting the primary and featured sides."""
    DELIMITER_PATTERN: re.Pattern[str] = re.compile(
        r", | & | \+ | / |(?i: and | x | with )")
    """The pattern splitting the artist names within a side."""
    COLON_PATTERN: re.Pattern[str] = re.compile(r": ")
    """The pattern separating a group prefix from its members in a
    "<group>: <members>" credit."""
    PAREN_MEMBERS_PATTERN: re.Pattern[str] = re.compile(
        r"^.+ \((?P<members>.+)\)$")
    """The pattern separating a group name from its members in a
    "<group> (<members>)" credit spanning the whole credit."""
    DUET_WITH_PATTERN: re.Pattern[str] = re.compile(
        r" Duet With ", re.IGNORECASE)
    """The pattern normalizing the "Duet With" co-billing connector
    to the plain "with" delimiter."""
    PROTECTED_ARTIST_NAMES: tuple[str, ...] = (
        "Tyler, The Creator",
        "Lil Nas X",
        "Tones And I",
    )
    """The exact artist names guarded from the delimiter splitting,
    because each contains a delimiter word or punctuation as part
    of the name itself."""
    EXCEPTION_CREDITS: dict[str, list[tuple[str, Role]]] = {
        "SpotemGottem Featuring Pooh Shiesty Or DaBaby": [
            ("SpotemGottem", Role.PRIMARY),
            ("Pooh Shiesty", Role.FEATURED),
            ("DaBaby", Role.FEATURED),
        ],
        "THE SCOTTS, Travis Scott & Kid Cudi": [
            ("Travis Scott", Role.PRIMARY),
            ("Kid Cudi", Role.PRIMARY),
        ],
        "Drake Featuring The Throne": [
            ("Drake", Role.PRIMARY),
            ("Jay Z", Role.FEATURED),
            ("Kanye West", Role.FEATURED),
        ],
    }
    """The single-credit exceptions parsed by an explicit lookup
    rather than by the general rules, because the credit text alone
    does not spell out the correct member split."""
    CANONICAL_ARTIST_NAMES: dict[str, str] = {
        "beyonce": "Beyoncé",
        "5 seconds of summer": "5 Seconds of Summer",
        "a boogie wit da hoodie": "A Boogie wit da Hoodie",
        "benny blanco": "benny blanco",
        "blackbear": "blackbear",
        "chance the rapper": "Chance the Rapper",
        "xxxtentacion": "XXXTENTACION",
        "maneskin": "Måneskin",
        "rose": "ROSÉ",
        "mo": "MØ",
        "wizkid": "Wizkid",
        "ye": "Kanye West",
        "amine": "Aminé",
        "bomba estereo": "Bomba Estéreo",
        "carolina gaitan": "Carolina Gaitán",
        "casper magico": "Casper Mágico",
        "eslabon armado": "Eslabón Armado",
        "jhene aiko": "Jhené Aiko",
        "neton vega": "Netón Vega",
        "nio garcia": "Nio García",
        "oscar maydon": "Óscar Maydon",
        "silento": "Silentó",
        "the marias": "The Marías",
        "victoria monet": "Victoria Monét",
        "dan": "Dan Smyers",
        "shay": "Shay Mooney",
        "cris mj": "Cris MJ",
        "mariah the scientist": "Mariah the Scientist",
        "surf mesa": "Surf Mesa",
    }
    """The canonical artist spellings, keyed by the case-folded
    identity."""

    def __init__(self, session: Session) -> None:
        """Initialize the importer.

        :param session: The database session.
        """
        self.__session: Session = session
        self.__artists: dict[str, Artist] = {}

    def import_artists(self) -> None:
        """Parse the stored songs' credits into artists and
        song-artist credits.

        Reads the songs back from the database in ``Song.id`` order,
        including any songs pending in the same session, and for
        each song parses ``Song.artist_credit`` (see
        `parse_artist_credit`).  An artist parsed out of a credit is
        matched against the known artists by its identity key (see
        `resolve_artist_identity`); a newly seen one takes the ID
        following the known artists, keyed by its identity key,
        assigned in first-seen order across the songs, and its
        stored name is the resolved stored spelling.  An artist
        duplicated within one song's credit, by its identity key,
        is kept only at its first occurrence within that credit,
        with a warning to the standard error.  When the method
        returns, the imported artists and credits are queryable in
        the session.

        :return: None.
        """
        song: Song
        for song in self.__session.scalars(
                sa.select(Song).order_by(Song.id)):
            self.__import_song_artists(song)
        self.__session.flush()

    def __import_song_artists(self, song: Song) -> None:
        """Parse and store the artist credits of one song.

        :param song: The song with its stored artist credit.
        :return: None.
        :raises BuildError: When the parsed credit has no primary
            artist or contains a blank artist name (see
            `__check_parsed_credit`).
        """
        parsed: list[tuple[str, Role]] = self.parse_artist_credit(
            song.artist_credit)
        self.__check_parsed_credit(song, parsed)
        seen: set[str] = set()
        position: int = 0
        name: str
        role: Role
        for name, role in parsed:
            key: str
            stored_name: str
            key, stored_name = self.resolve_artist_identity(name)
            if key in seen:
                print(f"warning: {song.artist_credit}: duplicated"
                      f" artist \"{name}\"", file=sys.stderr)
                continue
            seen.add(key)
            if key not in self.__artists:
                self.__artists[key] = Artist(
                    id=len(self.__artists) + 1, name=stored_name)
            self.__session.add(SongArtist(
                song=song, artist=self.__artists[key], role=role,
                position=position))
            position += 1

    @staticmethod
    def __check_parsed_credit(
            song: Song, parsed: list[tuple[str, Role]]) -> None:
        """Verify a song's parsed artist credit is well-formed.

        :param song: The song whose credit was parsed.
        :param parsed: The (name, role) pairs parsed from
            ``song.artist_credit``.
        :return: None.
        :raises BuildError: When ``parsed`` is empty, has no
            ``Role.PRIMARY`` entry, or contains a name blank after
            stripping.
        """
        role: Role
        if len(parsed) == 0 or not any(
                role == Role.PRIMARY for _, role in parsed):
            raise BuildError(
                f"song {song.id} \"{song.artist_credit}\": no"
                " primary artist parsed")
        name: str
        for name, role in parsed:
            if name.strip() == "":
                raise BuildError(
                    f"song {song.id} \"{song.artist_credit}\":"
                    " blank artist name parsed")

    @staticmethod
    def parse_artist_credit(credit: str) -> list[tuple[str, Role]]:
        """Parse a combined artist credit into artists and roles.

        A credit listed in ``EXCEPTION_CREDITS`` is looked up
        verbatim, because its correct split is not derivable from
        the credit text alone.  Otherwise the credit first reduces
        to an effective credit: a "<group>: <members>" prefix
        (split at the first ": ") drops the group and keeps the
        members; failing that, a "<group> (<members>)" suffix
        spanning the whole credit drops the group and keeps the
        members.  The "Duet With" connector, case-insensitively,
        then normalizes to "with".  The effective credit splits
        into a primary side and a featured side on the word
        "featuring" or "feat.", case-insensitively; without them,
        every artist is primary.  Each side splits into artist
        names on the delimiters ", ", " & ", " + ", " / "
        (literally) and " and ", " x ", " with "
        (case-insensitively), except for the names listed in
        ``PROTECTED_ARTIST_NAMES``, which are never split even
        though each contains a delimiter word or punctuation.

        Known limitation: a compound act name that contains one of
        the delimiters, other than the protected names, is
        over-split.

        :param credit: The combined artist credit string.
        :return: The (name, role) pairs in credit order, primary
            side first, with the role ``Role.PRIMARY`` or
            ``Role.FEATURED``.
        """
        if credit in ArtistImporter.EXCEPTION_CREDITS:
            return list(ArtistImporter.EXCEPTION_CREDITS[credit])
        effective: str = credit
        colon_match: re.Match[str] | None = \
            ArtistImporter.COLON_PATTERN.search(effective)
        if colon_match is not None:
            effective = effective[colon_match.end():]
        else:
            paren_match: re.Match[str] | None = \
                ArtistImporter.PAREN_MEMBERS_PATTERN.match(
                    effective)
            if paren_match is not None:
                effective = paren_match.group("members")
        effective = ArtistImporter.DUET_WITH_PATTERN.sub(
            " with ", effective)
        placeholders: dict[str, str] = {}
        index: int
        protected: str
        for index, protected in enumerate(
                ArtistImporter.PROTECTED_ARTIST_NAMES):
            if protected in effective:
                placeholder: str = f"{index}"
                placeholders[placeholder] = protected
                effective = effective.replace(protected, placeholder)
        sides: list[str] = ArtistImporter.FEATURING_PATTERN.split(
            effective, maxsplit=1)
        pairs: list[tuple[str, Role]] = []
        role: Role
        side: str
        for side, role in zip(sides, (Role.PRIMARY, Role.FEATURED)):
            token: str
            for token in ArtistImporter.DELIMITER_PATTERN.split(
                    side):
                name: str = token.strip()
                placeholder = ""
                original: str
                for placeholder, original in placeholders.items():
                    name = name.replace(placeholder, original)
                if name != "":
                    pairs.append((name, role))
        return pairs

    @staticmethod
    def resolve_artist_identity(name: str) -> tuple[str, str]:
        """Resolve the dedup key and the stored spelling of a name.

        The name's case-folded form is looked up in
        ``CANONICAL_ARTIST_NAMES`` first; when it is listed there,
        the dedup key is the canonical spelling case-folded and the
        stored spelling is the canonical spelling, so every variant
        of the name, canonical or not, resolves to the same
        identity.  Otherwise the dedup key is the name case-folded
        and the stored spelling is the given name.

        :param name: An artist name, as parsed from a credit.
        :return: A tuple of the dedup key and the stored spelling.
        """
        folded: str = name.casefold()
        canonical: str | None = \
            ArtistImporter.CANONICAL_ARTIST_NAMES.get(folded)
        if canonical is not None:
            return canonical.casefold(), canonical
        return folded, name


class CaptureImporter:
    """The capture-import job: applies the optional capture-layer
    inputs onto the stored songs and artists."""

    def __init__(self, session: Session) -> None:
        """Initialize the importer.

        :param session: The database session.
        """
        self.__session: Session = session

    def import_captures(self, lyrics_dir: Path | None,
                        wikidata_csv: Path | None) -> None:
        """Apply the optional capture-layer inputs onto the store.

        A None input leaves its capture layer unloaded.  When
        ``lyrics_dir`` is given, its cached lyrics files load into
        the matching songs (see `__load_lyrics`).  When
        ``wikidata_csv`` is given, it applies onto the artist rows
        (see `__apply_artist_csv`).  When the method returns, the
        applied changes are queryable in the session.

        :param lyrics_dir: The lyrics cache directory to load, or
            None to skip the lyrics capture layer.
        :param wikidata_csv: The Wikidata artist snapshot CSV file
            to apply, or None to skip the artist capture layer.
        :return: None.
        :raises BuildError: When ``lyrics_dir`` does not exist, or
            a name in ``wikidata_csv`` matches no artist.
        :raises OSError: When a capture file cannot be read.
        """
        if lyrics_dir is not None:
            if not lyrics_dir.is_dir():
                raise BuildError(
                    f"{lyrics_dir}: no such directory")
            self.__load_lyrics(lyrics_dir)
        if wikidata_csv is not None:
            self.__apply_artist_csv(wikidata_csv)
        self.__session.flush()

    def __load_lyrics(self, directory: Path) -> None:
        """Load the cached lyrics files into the matching songs.

        A file whose stem is not an existing song ID is skipped
        with a warning to the standard error.

        :param directory: The existing lyrics cache directory with
            one ``<song_id>.txt`` file per song.
        :return: None.
        :raises OSError: When a lyrics file cannot be read.
        """
        for path in sorted(directory.glob("*.txt")):
            song: Song | None = None
            if path.stem.isdigit():
                song = self.__session.get(Song, int(path.stem))
            if song is None:
                print(f"warning: {path}: no song with ID"
                      f" \"{path.stem}\"", file=sys.stderr)
                continue
            song.lyrics = path.read_text(encoding="utf-8")

    def __apply_artist_csv(self, path: Path) -> None:
        """Apply an artist attribute CSV onto the artist rows.

        Artists match by exact name.  Only the non-empty cells are
        applied, field by field.  The note column is ignored.

        :param path: The CSV file with the columns name, qid,
            gender, type, genre, country, and note.
        :return: None.
        :raises BuildError: When a name matches no artist.
        :raises OSError: When the file cannot be read.
        """
        with open(path, encoding="utf-8", newline="") as file:
            row: dict[str, str]
            for row in csv.DictReader(file):
                artist: Artist | None = self.__session.scalar(
                    sa.select(Artist)
                    .where(Artist.name == row["name"]))
                if artist is None:
                    raise BuildError(
                        f"{path}: no artist named"
                        f" \"{row['name']}\"")
                column: str
                attribute: str
                for column, attribute in ARTIST_FIELDS.items():
                    if row.get(column):
                        setattr(artist, attribute, row[column])


@dataclass
class StoreCounts:
    """The row counts of the working store, for the build summary."""

    songs: int
    """The number of the songs."""
    chart_entries: int
    """The number of the chart entries."""
    artists: int
    """The number of the artists."""
    credits: int
    """The number of the song-artist credits."""
    songs_with_lyrics: int
    """The number of the songs with lyrics."""

    @classmethod
    def get_instance(cls, session: Session) -> Self:
        """Counts the loaded rows and returns the counts.

        :param session: The database session with the loaded data
            flushed.
        :return: The row counts of the working store.
        """
        def count(selectable: sa.Select[tuple[int]]) -> int:
            value: int | None = session.scalar(selectable)
            assert value is not None
            return value

        return cls(
            songs=count(
                sa.select(sa.func.count()).select_from(Song)),
            chart_entries=count(
                sa.select(sa.func.count())
                .select_from(ChartEntry)),
            artists=count(
                sa.select(sa.func.count()).select_from(Artist)),
            credits=count(
                sa.select(sa.func.count())
                .select_from(SongArtist)),
            songs_with_lyrics=count(
                sa.select(sa.func.count()).select_from(Song)
                .where(Song.lyrics.is_not(None))))


def reset_store(session: Session) -> None:
    """Delete all the rows from every table of the store.

    :param session: The database session.
    :return: None.
    """
    model: type[Base]
    for model in (SongArtist, ChartEntry, Song, Artist):
        session.execute(sa.delete(model))


class CSVExporter:
    """Writes the review CSV files mirroring the working store."""

    __SONGS_HEADER: tuple[str, ...] = ("Title", "Artists", "Positions")
    """The header row of ``songs.csv``, for human readers."""
    __ARTISTS_HEADER: tuple[str, ...] = (
        "Name", "Wikidata QID", "Gender", "Type", "Genre", "Country",
        "Songs")
    """The header row of ``artists.csv``, for human readers."""

    def __init__(self, session: Session, derived_dir: Path) -> None:
        """Initialize the exporter.

        :param session: The database session with the loaded data
            flushed.
        :param derived_dir: The output directory for the review CSV
            files.
        """
        self.__session: Session = session
        self.__derived_dir: Path = derived_dir

    def write(self) -> None:
        """Write the review CSV files mirroring the loaded data.

        Fully overwrites ``songs.csv`` and ``artists.csv`` under the
        output directory, creating it when missing, with normal
        minimal CSV quoting.  Neither file carries a song or an
        artist ID; a multi-valued field is a plain joined string,
        itself CSV-quoted as a whole only when its content requires
        it: "/" joins the chart appearances of one song, and "|"
        joins the distinct songs credited to one artist.

        :return: None.
        :raises OSError: When a CSV file cannot be written.
        """
        self.__derived_dir.mkdir(parents=True, exist_ok=True)
        self.__write_csv(
            self.__derived_dir / "songs.csv", self.__SONGS_HEADER,
            self.__songs_rows())
        self.__write_csv(
            self.__derived_dir / "artists.csv", self.__ARTISTS_HEADER,
            self.__artists_rows())

    @staticmethod
    def __write_csv(path: Path, header: Sequence[str],
                    rows: Iterable[Sequence[str]]) -> None:
        """Write a CSV file with LF line endings, fully overwritten.

        :param path: The output CSV file.
        :param header: The header row.
        :param rows: The data rows, in the given order.
        :return: None.
        :raises OSError: When the file cannot be written.
        """
        with open(path, "w", encoding="utf-8", newline="") as file:
            writer: Any = csv.writer(file)
            writer.writerow(header)
            writer.writerows(rows)

    @staticmethod
    def __sorted_chart_entries(song: Song) -> list[ChartEntry]:
        """Sort the chart entries of a song by year then rank.

        :param song: The song with its chart entries loaded.
        :return: The chart entries, ordered by year then rank.
        """
        return sorted(
            song.chart_entries, key=lambda x: (x.year, x.rank))

    @classmethod
    def __song_positions(cls, song: Song) -> str:
        """Format the chart positions of a song for the songs.csv
        value.

        :param song: The song with its chart entries loaded.
        :return: The "YEAR#RANK" tokens, ordered by year then rank,
            joined by "/".
        """
        entries: list[ChartEntry] = cls.__sorted_chart_entries(song)
        return "/".join(f"{x.year}#{x.rank}" for x in entries)

    @classmethod
    def __formatted_song_positions(cls, song: Song) -> str:
        """Format the chart positions of a song for the artists.csv
        value.

        :param song: The song with its chart entries loaded.
        :return: The "YEAR#RANK" tokens, ordered by year then rank,
            joined by "/".
        """
        entries: list[ChartEntry] = cls.__sorted_chart_entries(song)
        return "/".join(f"{x.year}#{x.rank}" for x in entries)

    def __songs_rows(self) -> list[list[str]]:
        """Build the sorted data rows of ``songs.csv``.

        :return: The rows, sorted by the case-folded title, then
            the case-folded artist credit.
        """
        songs: list[Song] = sorted(
            self.__session.scalars(sa.select(Song)),
            key=lambda x: (x.title.casefold(),
                           x.artist_credit.casefold()))
        rows: list[list[str]] = []
        song: Song
        for song in songs:
            row: list[str] = [
                song.title, song.artist_credit,
                self.__song_positions(song)]
            rows.append(row)
        return rows

    @classmethod
    def __artist_songs(cls, artist: Artist) -> str:
        """Format the credited songs for the artists.csv value.

        :param artist: The artist with its song credits loaded.
        :return: The credited songs, each formatted as
            "TITLE (YEAR#RANK[/YEAR#RANK...])" with its chart
            appearances, sorted alphabetically case-folded by
            title, joined by "|".
        """
        songs: list[Song] = sorted(
            (x.song for x in artist.song_artists),
            key=lambda x: x.title.casefold())
        entries: list[str] = [
            f"{song.title} ({cls.__formatted_song_positions(song)})"
            for song in songs]
        return "|".join(entries)

    def __artists_rows(self) -> list[list[str]]:
        """Build the sorted data rows of ``artists.csv``.

        :return: The rows, sorted by the case-folded name.
        """
        artists: list[Artist] = sorted(
            self.__session.scalars(sa.select(Artist)),
            key=lambda x: x.name.casefold())
        rows: list[list[str]] = []
        artist: Artist
        for artist in artists:
            row: list[str] = [
                artist.name, artist.wikidata_qid or "",
                artist.gender or "", artist.type or "",
                artist.genre or "", artist.country or "",
                self.__artist_songs(artist)]
            rows.append(row)
        return rows


def main(argv: list[str] | None = None) -> int:
    """Rebuild the SQLite working store from the inputs.

    :param argv: The command-line arguments, or None for
        ``sys.argv``.
    :return: The exit status: 0 on success, non-zero on failure.
    """
    args: argparse.Namespace = parse_args(argv)
    Base.metadata.create_all(ds.engine)
    session: Session = ds.get_db()
    counts: StoreCounts
    try:
        reset_store(session)
        SongImporter(session).import_songs(args.chart_csv)
        ArtistImporter(session).import_artists()
        CaptureImporter(session).import_captures(
            args.lyrics_dir, args.wikidata_csv)
        counts = StoreCounts.get_instance(session)
        CSVExporter(session, args.derived_dir).write()
        session.commit()
    except (OSError, BuildError) as error:
        session.rollback()
        print(f"error: {error}", file=sys.stderr)
        return 1
    finally:
        session.close()
    print(f"done: {counts.songs} songs,"
          f" {counts.chart_entries} chart entries,"
          f" {counts.artists} artists,"
          f" {counts.credits} credits,"
          f" {counts.songs_with_lyrics} songs with lyrics",
          file=sys.stderr)
    return 0
