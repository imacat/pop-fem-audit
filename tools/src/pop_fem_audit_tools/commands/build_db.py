# Tools for A Feminist Audit of Pop Music.
# Copyright 2026 imacat.  All rights reserved.
# Authors:
#   imacat@mail.imacat.idv.tw (imacat), 2026/7/31
"""The builder of the SQLite working store.

Rebuilds the working store from scratch out of the committed
inputs: the year-end chart CSV and the output directory for the
review CSV files, given as the two positional command-line
arguments, and the optional capture, coding, group,
gender-correction, pattern, and annotation layers, each given as
an option.  An omitted option leaves its layer unloaded; a given
option whose path does not exist fails the build.  Missing tables
are created on a fresh store; existing tables are never altered,
as the schema lifecycle belongs to the migrations.  Every rebuild
deletes all the rows, loads the data, and validates it in one
transaction, committed only after the data passes the validation
invariants; a failed build leaves the previous store contents
intact.  See `StoreBuilder` for the pipeline, and the individual
importer, deriver, and exporter classes for the identity,
derivation, correction, and export rules.
"""
import argparse
import csv
import re
import sys
import time
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar, Self

import sqlalchemy as sa
from sqlalchemy.orm import Session

from ..database import Base, ds
from ..models import (
    Annotation,
    Artist,
    ChartEntry,
    CodeGroup,
    Coding,
    Pattern,
    Role,
    Song,
    SongArtist,
)
from ..utils import format_duration


class BuildError(Exception):
    """An error that fails the build."""


class SongImporter:
    """The song-import job: assigns every distinct chart song its
    deterministic ID and records its chart appearances.

    A song repeated across the rows is stored once, matched by its
    identity key (see `song_identity`); every row yields one chart
    entry.  The stored title is the raw title; the stored artist
    credit is the canonical credit from the identity key.  The
    songs take the IDs 1, 2, 3, ... in the first-occurrence row
    order.
    """

    __YEARS: ClassVar[Sequence[int]] = range(2016, 2026)
    """The expected chart years."""
    __RANKS_PER_YEAR: ClassVar[int] = 100
    """The expected number of ranks on the chart of each year."""
    __CANONICAL_ARTIST_CREDITS: ClassVar[dict[str, str]] = {
        "benny blanco, Halsey & Khalid": "Benny Blanco, Halsey"
                                         " & Khalid",
    }
    """The canonical artist credit spellings, keyed by a variant
    credit string."""

    def __init__(self, session: Session, chart_csv: Path) -> None:
        """Initialize the importer.

        :param session: The database session.
        :param chart_csv: The chart CSV file with the columns
            year, rank, title, and artist.
        """
        self.__session: Session = session
        self.__chart_csv: Path = chart_csv
        self.__songs: dict[tuple[str, str], Song] = {}

    def run(self) -> None:
        """Load the chart CSV into songs and chart entries.

        When the method returns, the imported songs and chart
        entries are queryable in the session.

        :return: None.
        :raises BuildError: When the chart entries do not cover
            each expected year and rank exactly once.
        :raises OSError: When the file cannot be read.
        """
        counts: Counter[tuple[int, int]] = Counter()
        with open(self.__chart_csv, encoding="utf-8",
                  newline="") as file:
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
            (year, rank) for year in cls.__YEARS
            for rank in range(1, cls.__RANKS_PER_YEAR + 1)}
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
        canonicalized through the canonical artist credit table; a
        credit absent from the table maps to itself.  Two chart
        rows denote the same song iff their identity keys are
        equal.

        :param title: The song title as printed on the chart.
        :param credit: The combined artist credit string.
        :return: The identity key: the raw title paired with the
            canonical artist credit.
        """
        return title, SongImporter.__CANONICAL_ARTIST_CREDITS.get(
            credit, credit)


class ArtistImporter:
    """The artist-import job: resolves every credited artist name
    to a deduplicated artist row and records the song-artist
    credits.

    An artist parsed out of a credit (see `parse_artist_credit`) is
    matched against the known artists by its identity key (see
    `resolve_artist_identity`); a newly seen one takes the ID
    following the known artists, assigned in first-seen order
    across the songs, and its stored name is the resolved stored
    spelling.  An artist duplicated within one song's credit, by
    its identity key, is kept only at its first occurrence within
    that credit, with a warning to the standard error.
    """

    __FEATURING_PATTERN: ClassVar[re.Pattern[str]] = re.compile(
        r" featuring | feat\. ", re.IGNORECASE)
    """The pattern splitting the primary and featured sides."""
    __DELIMITER_PATTERN: ClassVar[re.Pattern[str]] = re.compile(
        r", | & | \+ | / |(?i: and | x | with )")
    """The pattern splitting the artist names within a side."""
    __COLON_PATTERN: ClassVar[re.Pattern[str]] = re.compile(r": ")
    """The pattern separating a group prefix from its members in a
    "<group>: <members>" credit."""
    __PAREN_MEMBERS_PATTERN: ClassVar[re.Pattern[str]] = re.compile(
        r"^[^(]+ \((?P<members>[^()]+)\)$")
    """The pattern separating a group name from its members in a
    "<group> (<members>)" credit spanning the whole credit."""
    __DUET_WITH_PATTERN: ClassVar[re.Pattern[str]] = re.compile(
        r" Duet With ", re.IGNORECASE)
    """The pattern normalizing the "Duet With" co-billing connector
    to the plain "with" delimiter."""
    __PROTECTED_ARTIST_NAMES: ClassVar[tuple[str, ...]] = (
        "Tyler, The Creator",
        "Lil Nas X",
        "Tones And I",
    )
    """The exact artist names guarded from the delimiter splitting,
    because each contains a delimiter word or punctuation as part
    of the name itself."""
    __EXCEPTION_CREDITS: ClassVar[dict[str, list[tuple[str, Role]]]] \
        = {
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
    __CANONICAL_ARTIST_NAMES: ClassVar[dict[str, str]] = {
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
        "pinkfong": "Hope Segoine",
    }
    """The canonical artist spellings, keyed by the case-folded
    identity."""

    def __init__(self, session: Session) -> None:
        """Initialize the importer.

        :param session: The database session.
        """
        self.__session: Session = session
        self.__artists: dict[str, Artist] = {}

    def run(self) -> None:
        """Parse the stored songs' credits into artists and
        song-artist credits.

        Reads the songs back from the database in ``Song.id`` order,
        including any songs pending in the same session, and for
        each song parses ``Song.artist_credit``.  When the method
        returns, the imported artists and credits are queryable in
        the session.

        :return: None.
        :raises BuildError: When a parsed credit has no primary
            artist or contains a blank artist name (see
            `__check_parsed_credit`).
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
        if len(parsed) == 0 or not any(
                role == Role.PRIMARY for _, role in parsed):
            raise BuildError(
                f"song {song.id} \"{song.artist_credit}\": no"
                " primary artist parsed")
        name: str
        for name, _ in parsed:
            if name.strip() == "":
                raise BuildError(
                    f"song {song.id} \"{song.artist_credit}\":"
                    " blank artist name parsed")

    @staticmethod
    def parse_artist_credit(credit: str) -> list[tuple[str, Role]]:
        """Parse a combined artist credit into artists and roles.

        A credit listed as a single-credit exception is looked up
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
        ``__PROTECTED_ARTIST_NAMES``, which are never split even
        though each contains a delimiter word or punctuation.

        Known limitation: a compound act name that contains one of
        the delimiters, other than the protected names, is
        over-split.

        :param credit: The combined artist credit string.
        :return: The (name, role) pairs in credit order, primary
            side first, with the role ``Role.PRIMARY`` or
            ``Role.FEATURED``.
        """
        if credit in ArtistImporter.__EXCEPTION_CREDITS:
            return list(ArtistImporter.__EXCEPTION_CREDITS[credit])
        effective: str = credit
        colon_match: re.Match[str] | None = \
            ArtistImporter.__COLON_PATTERN.search(effective)
        if colon_match is not None:
            effective = effective[colon_match.end():]
        else:
            paren_match: re.Match[str] | None = \
                ArtistImporter.__PAREN_MEMBERS_PATTERN.match(
                    effective)
            if paren_match is not None:
                effective = paren_match.group("members")
        effective = ArtistImporter.__DUET_WITH_PATTERN.sub(
            " with ", effective)
        placeholders: dict[str, str] = {}
        index: int
        protected: str
        for index, protected in enumerate(
                ArtistImporter.__PROTECTED_ARTIST_NAMES):
            if protected in effective:
                placeholder: str = f"{index}"
                placeholders[placeholder] = protected
                effective = effective.replace(protected, placeholder)
        sides: list[str] = ArtistImporter.__FEATURING_PATTERN.split(
            effective, maxsplit=1)
        pairs: list[tuple[str, Role]] = []
        role: Role
        side: str
        for side, role in zip(sides, (Role.PRIMARY, Role.FEATURED)):
            token: str
            for token in ArtistImporter.__DELIMITER_PATTERN.split(
                    side):
                name: str = ArtistImporter.__restore_protected(
                    token.strip(), placeholders)
                if name != "":
                    pairs.append((name, role))
        return pairs

    @staticmethod
    def __restore_protected(
            name: str, placeholders: dict[str, str]) -> str:
        """Restore the protected artist names in a parsed name.

        :param name: A parsed artist name, possibly containing
            placeholders.
        :param placeholders: The protected artist names, keyed by
            the placeholder standing for each of them.
        :return: The name with every placeholder replaced by the
            protected artist name it stands for.
        """
        placeholder: str
        original: str
        for placeholder, original in placeholders.items():
            name = name.replace(placeholder, original)
        return name

    @staticmethod
    def resolve_artist_identity(name: str) -> tuple[str, str]:
        """Resolve the dedup key and the stored spelling of a name.

        The name's case-folded form is looked up in the canonical
        artist name table first; when it is listed there, the
        dedup key is the canonical spelling case-folded and the
        stored spelling is the canonical spelling, so every variant
        of the name, canonical or not, resolves to the same
        identity.  Otherwise the dedup key is the name case-folded
        and the stored spelling is the given name.

        :param name: An artist name, as parsed from a credit.
        :return: A tuple of the dedup key and the stored spelling.
        """
        folded: str = name.casefold()
        canonical: str | None = \
            ArtistImporter.__CANONICAL_ARTIST_NAMES.get(folded)
        if canonical is not None:
            return canonical.casefold(), canonical
        return folded, name


class CaptureImporter:
    """The capture-import job: applies the optional capture-layer
    inputs -- the lyrics cache and the Wikidata artist snapshot --
    onto the stored songs and artists.

    A None input leaves its capture layer unloaded.  A given
    artist snapshot applies only its non-empty cells, field by
    field; the note column is ignored.
    """

    __ARTIST_FIELDS: ClassVar[dict[str, str]] = {
        "qid": "wikidata_qid",
        "gender": "gender",
        "type": "type",
        "genre": "genre",
        "country": "country",
    }
    """The artist CSV columns mapped to the Artist attributes."""

    def __init__(self, session: Session, lyrics_dir: Path | None,
                 wikidata_csv: Path | None) -> None:
        """Initialize the importer.

        :param session: The database session.
        :param lyrics_dir: The lyrics cache directory to load, or
            None to skip the lyrics capture layer.
        :param wikidata_csv: The Wikidata artist snapshot CSV file
            to apply, or None to skip the artist capture layer.
        """
        self.__session: Session = session
        self.__lyrics_dir: Path | None = lyrics_dir
        self.__wikidata_csv: Path | None = wikidata_csv

    def run(self) -> None:
        """Apply the optional capture-layer inputs onto the store.

        When the method returns, the applied changes are queryable
        in the session.

        :return: None.
        :raises BuildError: When ``lyrics_dir`` does not exist, or
            a name in ``wikidata_csv`` matches no artist.
        :raises OSError: When a capture file cannot be read.
        """
        if self.__lyrics_dir is not None:
            if not self.__lyrics_dir.is_dir():
                raise BuildError(
                    f"{self.__lyrics_dir}: no such directory")
            self.__load_lyrics(self.__lyrics_dir)
        if self.__wikidata_csv is not None:
            self.__apply_artist_csv(self.__wikidata_csv)
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

        Artists match by exact name.

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
                for column, attribute in \
                        self.__ARTIST_FIELDS.items():
                    if row.get(column):
                        setattr(artist, attribute, row[column])


class PerformerGenderDeriver:
    """The performer-gender job: derives the song-level performer
    gender from the genders of the credited artists that are
    performing acts, a credited artist without an artist type
    taking no part."""

    __MIXED: ClassVar[str] = "mixed"
    """The performer gender of a song whose performing credited
    artists do not all share one gender."""

    def __init__(self, session: Session) -> None:
        """Initialize the deriver.

        :param session: The database session.
        """
        self.__session: Session = session

    def run(self) -> None:
        """Set the performer gender of every stored song.

        Reads the songs back from the database, including any songs
        pending in the same session, and sets
        ``Song.performer_gender`` from the genders of the artists
        credited on the song, primary and featured alike, that have
        an artist type (see `performer_gender`).  A credited artist
        without an artist type is not a performing act and takes no
        part.  When the method returns, the derived performer
        genders are queryable in the session.

        :return: None.
        """
        song: Song
        for song in self.__session.scalars(sa.select(Song)):
            song.performer_gender = self.performer_gender(
                [x.artist.gender for x in song.song_artists
                 if x.artist.type])
        self.__session.flush()

    @classmethod
    def performer_gender(
            cls, genders: Iterable[str | None]) -> str | None:
        """Combine the performing artists' genders into one value.

        A gender that is None or empty counts as unknown.  Two or
        more distinct known genders give the mixed gender, an
        unknown one notwithstanding, as an unknown cannot undo a
        disagreement.  A single known gender shared by every given
        artist gives that gender.  Anything else -- a single known
        gender alongside an unknown one, no known gender at all, or
        no gender given at all -- gives None.

        :param genders: The genders of the performing artists
            credited on one song, in any order.
        :return: The performer gender of the song, or None when it
            is undetermined.
        """
        values: list[str | None] = list(genders)
        known: set[str] = {x for x in values if x}
        if len(known) > 1:
            return cls.__MIXED
        if len(known) == 1 and all(x for x in values):
            return known.pop()
        return None


class ColumnCheckedImporter:
    """The shared skeleton of an optional, header-checked CSV
    importer: a None path leaves the layer unloaded; otherwise the
    header is validated and every row imports within one flush.
    A subclass supplies its required columns to the constructor and
    overrides `prepare` and `import_row` for its own row-handling.
    """

    def __init__(self, session: Session, path: Path | None,
                 columns: Sequence[str]) -> None:
        """Initialize the shared importer skeleton.

        :param session: The database session.
        :param path: The CSV file to import, or None to skip.
        :param columns: The required column names of the file.
        """
        self.__session: Session = session
        self.__path: Path | None = path
        self.__columns: Sequence[str] = columns

    @property
    def session(self) -> Session:
        """The database session."""
        return self.__session

    @property
    def path(self) -> Path | None:
        """The CSV file being imported, or None when skipped."""
        return self.__path

    def run(self) -> None:
        """Validate the header and import every row of the file.

        A None path leaves the layer unloaded.  Otherwise calls
        `prepare` once, then `import_row` for every data row, and
        flushes the session once every row is stored.

        :return: None.
        :raises BuildError: When the file lacks a required column,
            or a subclass raises importing a row.
        :raises OSError: When the file cannot be read.
        """
        if self.__path is None:
            return
        self.prepare()
        with open(self.__path, encoding="utf-8",
                  newline="") as file:
            reader: csv.DictReader[str] = csv.DictReader(file)
            self.__check_columns(reader.fieldnames)
            row: dict[str, str]
            for row in reader:
                self.import_row(row)
        self.__session.flush()

    def __check_columns(
            self, fieldnames: Sequence[str] | None) -> None:
        """Verify the CSV file has the required columns.

        :param fieldnames: The header row of the file, or None
            when the file is empty.
        :return: None.
        :raises BuildError: When a required column is absent.
        """
        header: Sequence[str] = fieldnames or ()
        missing: list[str] = [
            x for x in self.__columns if x not in header]
        if len(missing) > 0:
            raise BuildError(
                f"{self.__path}: missing column(s):"
                f" {', '.join(missing)}")

    def prepare(self) -> None:
        """Set up any state needed before the rows import.

        The default is a no-op; a subclass overrides this to load
        database lookups needed by `import_row`.

        :return: None.
        """
        return None

    def import_row(self, row: dict[str, str]) -> None:
        """Import one data row.

        A subclass overrides this to store the row.

        :param row: The CSV row.
        :return: None.
        """
        raise NotImplementedError


class GenderCorrectionImporter(ColumnCheckedImporter):
    """The gender-correction job: overrides the derived performer
    gender of the stored songs it names, matched by exact title and
    exact artist credit, with the performer gender column stored
    verbatim.  Run this after `PerformerGenderDeriver`, so a
    correction overrides the derived value.
    """

    __COLUMNS: ClassVar[tuple[str, ...]] = (
        "Title", "Artist Credit", "Performer Gender", "Note")
    """The required columns of the gender correction CSV file."""

    def __init__(self, session: Session, path: Path | None) -> None:
        """Initialize the importer.

        :param session: The database session.
        :param path: The gender correction table CSV file to
            apply, or None to skip the corrections.
        """
        super().__init__(session, path, self.__COLUMNS)
        self.__songs: dict[tuple[str, str], Song] = {}

    def prepare(self) -> None:
        """Load the stored songs, keyed by title and artist credit.

        :return: None.
        """
        self.__songs = {
            (x.title, x.artist_credit): x
            for x in self.session.scalars(sa.select(Song))}

    def import_row(self, row: dict[str, str]) -> None:
        """Apply one gender correction row.

        :param row: The gender correction CSV row.
        :return: None.
        :raises BuildError: When the row names a song that the
            store does not have.
        """
        key: tuple[str, str] = (
            row["Title"], row["Artist Credit"])
        song: Song | None = self.__songs.get(key)
        if song is None:
            raise BuildError(
                f"{self.path}: no song \"{row['Title']}\" by"
                f" \"{row['Artist Credit']}\"")
        song.performer_gender = row["Performer Gender"]


class CodingImporter(ColumnCheckedImporter):
    """The coding-import job: loads the settled coding table onto
    the stored songs, matched by exact title and exact artist
    credit, with the quote column stored verbatim; a quote carries
    the lyric line-break convention ``" / "`` where the lyric has a
    line break, and an empty quote column stores an empty string.
    """

    __COLUMNS: ClassVar[tuple[str, ...]] = (
        "Song", "Artist Credit", "Keyword", "Quote")
    """The required columns of the coding CSV file."""

    def __init__(self, session: Session, path: Path | None) -> None:
        """Initialize the importer.

        :param session: The database session.
        :param path: The settled coding table CSV file to import,
            or None to skip the coding.
        """
        super().__init__(session, path, self.__COLUMNS)
        self.__songs: dict[tuple[str, str], Song] = {}
        self.__seen: set[tuple[int, str]] = set()

    def prepare(self) -> None:
        """Load the stored songs, keyed by title and artist credit.

        :return: None.
        """
        self.__songs = {
            (x.title, x.artist_credit): x
            for x in self.session.scalars(sa.select(Song))}

    def import_row(self, row: dict[str, str]) -> None:
        """Store one coding row.

        :param row: The coding CSV row.
        :return: None.
        :raises BuildError: When the row names a song that the
            store does not have, or its song and keyword repeat an
            earlier row.
        """
        key: tuple[str, str] = (row["Song"], row["Artist Credit"])
        song: Song | None = self.__songs.get(key)
        if song is None:
            raise BuildError(
                f"{self.path}: no song \"{row['Song']}\" by"
                f" \"{row['Artist Credit']}\"")
        coding_key: tuple[int, str] = (song.id, row["Keyword"])
        if coding_key in self.__seen:
            raise BuildError(
                f"{self.path}: duplicated coding: \"{row['Song']}\""
                f" by \"{row['Artist Credit']}\", keyword"
                f" \"{row['Keyword']}\"")
        self.__seen.add(coding_key)
        self.session.add(Coding(
            song=song, keyword=row["Keyword"],
            quotes=row["Quote"]))


class GroupImporter(ColumnCheckedImporter):
    """The group-import job: loads the settled code group table
    into the working store, with the group name, the keyword, and
    the integer vote count stored verbatim."""

    __COLUMNS: ClassVar[tuple[str, ...]] = (
        "Group", "Keyword", "Votes")
    """The required columns of the group CSV file."""

    def __init__(self, session: Session, path: Path | None) -> None:
        """Initialize the importer.

        :param session: The database session.
        :param path: The settled code group table CSV file to
            import, or None to skip the groups.
        """
        super().__init__(session, path, self.__COLUMNS)
        self.__seen: set[tuple[str, str]] = set()

    def import_row(self, row: dict[str, str]) -> None:
        """Store one group member row.

        :param row: The group CSV row.
        :return: None.
        :raises BuildError: When the votes field is not an
            integer, or the group and keyword repeat an earlier
            row.
        """
        key: tuple[str, str] = (row["Group"], row["Keyword"])
        if key in self.__seen:
            raise BuildError(
                f"{self.path}: duplicated group member: group"
                f" \"{row['Group']}\", keyword"
                f" \"{row['Keyword']}\"")
        self.__seen.add(key)
        votes: int
        try:
            votes = int(row["Votes"])
        except ValueError as error:
            raise BuildError(
                f"{self.path}: group \"{row['Group']}\", keyword"
                f" \"{row['Keyword']}\": votes"
                f" \"{row['Votes']}\" is not an integer"
            ) from error
        self.session.add(CodeGroup(
            group=row["Group"], keyword=row["Keyword"],
            votes=votes))


class PatternImporter(ColumnCheckedImporter):
    """The pattern-import job: loads the pattern definition table
    into the working store, with the pattern ID, the group, the
    name, and the description stored verbatim."""

    __COLUMNS: ClassVar[tuple[str, ...]] = (
        "Pattern", "Group", "Name", "Description")
    """The required columns of the pattern CSV file."""

    def __init__(self, session: Session, path: Path | None) -> None:
        """Initialize the importer.

        :param session: The database session.
        :param path: The pattern definition table CSV file to
            import, or None to skip the patterns.
        """
        super().__init__(session, path, self.__COLUMNS)
        self.__seen: set[str] = set()

    def import_row(self, row: dict[str, str]) -> None:
        """Store one pattern row.

        :param row: The pattern CSV row.
        :return: None.
        :raises BuildError: When the pattern ID repeats an
            earlier row.
        """
        if row["Pattern"] in self.__seen:
            raise BuildError(
                f"{self.path}: duplicated pattern"
                f" \"{row['Pattern']}\"")
        self.__seen.add(row["Pattern"])
        self.session.add(Pattern(
            pattern=row["Pattern"], group=row["Group"],
            name=row["Name"], description=row["Description"]))


class AnnotationImporter(ColumnCheckedImporter):
    """The annotation-import job: loads the settled pattern
    annotation table onto the stored songs, linking the song named
    by its title and artist credit to the stored pattern named by
    its pattern ID, with the integer vote count stored verbatim.
    Import the pattern table first (see `PatternImporter`), so
    every named pattern is already stored.
    """

    __COLUMNS: ClassVar[tuple[str, ...]] = (
        "Song", "Artist Credit", "Pattern", "Votes")
    """The required columns of the annotation CSV file."""

    def __init__(self, session: Session, path: Path | None) -> None:
        """Initialize the importer.

        :param session: The database session.
        :param path: The settled pattern annotation table CSV
            file to import, or None to skip the annotations.
        """
        super().__init__(session, path, self.__COLUMNS)
        self.__songs: dict[tuple[str, str], Song] = {}
        self.__patterns: dict[str, Pattern] = {}
        self.__seen: set[tuple[int, str]] = set()

    def prepare(self) -> None:
        """Load the stored songs and patterns for the row lookups.

        :return: None.
        """
        self.__songs = {
            (x.title, x.artist_credit): x
            for x in self.session.scalars(sa.select(Song))}
        self.__patterns = {
            x.pattern: x
            for x in self.session.scalars(sa.select(Pattern))}

    def import_row(self, row: dict[str, str]) -> None:
        """Store one annotation row.

        :param row: The annotation CSV row.
        :return: None.
        :raises BuildError: When the row names a song that the
            store does not have, names a pattern that the store
            does not have, its votes field is not an integer, or
            its song and pattern repeat an earlier row.
        """
        key: tuple[str, str] = (row["Song"], row["Artist Credit"])
        song: Song | None = self.__songs.get(key)
        if song is None:
            raise BuildError(
                f"{self.path}: no song \"{row['Song']}\" by"
                f" \"{row['Artist Credit']}\"")
        pattern: Pattern | None = self.__patterns.get(row["Pattern"])
        if pattern is None:
            raise BuildError(
                f"{self.path}: no pattern \"{row['Pattern']}\"")
        annotation_key: tuple[int, str] = (
            song.id, pattern.pattern)
        if annotation_key in self.__seen:
            raise BuildError(
                f"{self.path}: duplicated annotation:"
                f" \"{row['Song']}\" by \"{row['Artist Credit']}\","
                f" pattern \"{row['Pattern']}\"")
        self.__seen.add(annotation_key)
        votes: int
        try:
            votes = int(row["Votes"])
        except ValueError as error:
            raise BuildError(
                f"{self.path}: \"{row['Song']}\" by"
                f" \"{row['Artist Credit']}\", pattern"
                f" \"{row['Pattern']}\": votes"
                f" \"{row['Votes']}\" is not an integer"
            ) from error
        self.session.add(Annotation(
            song=song, pattern=pattern, votes=votes))


@dataclass
class StoreCounts:
    """The row counts of the working store, for the build summary."""

    songs: int
    """The number of the songs."""
    artists: int
    """The number of the artists."""

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
            artists=count(
                sa.select(sa.func.count()).select_from(Artist)))


class CSVExporter:
    """Writes the review CSV files mirroring the working store,
    without a song or an artist ID, on a successful build."""

    __SONGS_HEADER: ClassVar[tuple[str, ...]] = (
        "Title", "Artists", "Positions", "Performer Gender")
    """The header row of ``songs.csv``, for human readers."""
    __ARTISTS_HEADER: ClassVar[tuple[str, ...]] = (
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
        """Format the chart positions of a song.

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
                self.__song_positions(song),
                song.performer_gender or ""]
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
            f"{song.title} ({cls.__song_positions(song)})"
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


class StoreBuilder:
    """The orchestrator of a full working store rebuild: resets the
    store, runs the importers and derivers in the pipeline order,
    and writes the review CSV files, all in one transaction
    committed only on success."""

    def __init__(
            self, chart_csv: Path, derived_dir: Path,
            lyrics_dir: Path | None, wikidata_csv: Path | None,
            codings: Path | None, groups: Path | None,
            gender_corrections: Path | None,
            patterns: Path | None,
            annotations: Path | None) -> None:
        """Set up the builder of the working store rebuild.

        :param chart_csv: The year-end chart CSV file.
        :param derived_dir: The output directory for the review
            CSV files.
        :param lyrics_dir: The lyrics cache directory to load, or
            None to skip it.
        :param wikidata_csv: The Wikidata artist snapshot CSV file
            to apply, or None to skip it.
        :param codings: The settled coding table CSV file to
            import, or None to skip it.
        :param groups: The settled code group table CSV file to
            import, or None to skip it.
        :param gender_corrections: The gender correction table CSV
            file to apply, or None to skip it.
        :param patterns: The pattern definition table CSV file to
            import, or None to skip it.
        :param annotations: The settled pattern annotation table
            CSV file to import, or None to skip it.
        """
        self.__chart_csv: Path = chart_csv
        self.__derived_dir: Path = derived_dir
        self.__lyrics_dir: Path | None = lyrics_dir
        self.__wikidata_csv: Path | None = wikidata_csv
        self.__codings: Path | None = codings
        self.__groups: Path | None = groups
        self.__gender_corrections: Path | None = gender_corrections
        self.__patterns: Path | None = patterns
        self.__annotations: Path | None = annotations

    def run(self) -> StoreCounts:
        """Rebuild the working store from the configured inputs.

        :return: The row counts of the rebuilt working store.
        :raises BuildError: When an input is malformed, as
            detailed on the importer and deriver classes.
        :raises OSError: When an input or output file cannot be
            read or written.
        """
        Base.metadata.create_all(ds.engine)
        session: Session = ds.get_db()
        counts: StoreCounts
        try:
            self.__reset_store(session)
            SongImporter(session, self.__chart_csv).run()
            ArtistImporter(session).run()
            CaptureImporter(
                session, self.__lyrics_dir,
                self.__wikidata_csv).run()
            PerformerGenderDeriver(session).run()
            GenderCorrectionImporter(
                session, self.__gender_corrections).run()
            CodingImporter(session, self.__codings).run()
            GroupImporter(session, self.__groups).run()
            PatternImporter(session, self.__patterns).run()
            AnnotationImporter(session, self.__annotations).run()
            counts = StoreCounts.get_instance(session)
            CSVExporter(session, self.__derived_dir).write()
            session.commit()
        except (OSError, BuildError):
            session.rollback()
            raise
        finally:
            session.close()
        return counts

    @staticmethod
    def __reset_store(session: Session) -> None:
        """Delete all the rows from every table of the store.

        :param session: The database session.
        :return: None.
        """
        model: type[Base]
        for model in (CodeGroup, Coding, Annotation, SongArtist,
                      ChartEntry, Song, Pattern, Artist):
            session.execute(sa.delete(model))


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
    parser.add_argument(
        "--codings", type=Path, default=None,
        help="the settled coding table CSV file to import")
    parser.add_argument(
        "--groups", type=Path, default=None,
        help="the settled code group table CSV file to import")
    parser.add_argument(
        "--gender-corrections", type=Path, default=None,
        help="the gender correction table CSV file to apply")
    parser.add_argument(
        "--patterns", type=Path, default=None,
        help="the pattern definition table CSV file to import")
    parser.add_argument(
        "--annotations", type=Path, default=None,
        help="the settled pattern annotation table CSV file to"
             " import")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Rebuild the SQLite working store from the inputs.

    :param argv: The command-line arguments, or None for
        ``sys.argv``.
    :return: The exit status: 0 on success, non-zero on failure.
    """
    started: float = time.monotonic()
    args: argparse.Namespace = parse_args(argv)
    try:
        counts: StoreCounts = StoreBuilder(
            args.chart_csv, args.derived_dir, args.lyrics_dir,
            args.wikidata_csv, args.codings, args.groups,
            args.gender_corrections, args.patterns,
            args.annotations).run()
    except (OSError, BuildError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    elapsed: str = format_duration(time.monotonic() - started)
    print(f"Done.  {counts.songs} songs/{counts.artists} artists."
          f"  {elapsed} elapsed.",
          file=sys.stderr)
    return 0
