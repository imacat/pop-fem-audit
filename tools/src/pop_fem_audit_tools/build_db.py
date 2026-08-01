# Tools for A Feminist Audit of Pop Music.
# Copyright 2026 imacat.  All rights reserved.
# Authors:
#   imacat@mail.imacat.idv.tw (imacat), 2026/7/31
"""The builder of the SQLite working store.

Rebuilds the working store from scratch out of the committed
inputs: the year-end chart CSV, given as the positional
command-line argument, and the optional capture inputs, each
given as an option: the lyrics cache directory, the Wikidata
artist snapshot CSV, and the manual artist overrides CSV.  An
omitted option leaves its capture layer unloaded; a given
option whose path does not exist fails the build.  Missing
tables
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
"""
import argparse
import csv
import re
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Self

import sqlalchemy as sa
from sqlalchemy.orm import Session

from .database import Base, ds
from .models import (
    Artist,
    ChartEntry,
    Role,
    Song,
    SongArtist,
)

YEARS: Sequence[int] = range(2016, 2026)
"""The expected chart years."""
RANKS_PER_YEAR: int = 100
"""The expected number of ranks on the chart of each year."""
ARTIST_FIELDS: dict[str, str] = {
    "qid": "wikidata_qid",
    "gender": "gender",
    "type": "type",
    "genre": "genre",
    "country": "country",
}
"""The artist CSV columns mapped to the Artist attributes."""
FEATURING_PATTERN: re.Pattern[str] = re.compile(
    r" featuring | feat\. ", re.IGNORECASE)
"""The pattern splitting the primary and featured sides."""
DELIMITER_PATTERN: re.Pattern[str] = re.compile(
    r", | & | \+ |(?i: and | x | with )")
"""The pattern splitting the artist names within a side."""


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
        "--lyrics-dir", type=Path, default=None,
        help="the lyrics cache directory to load")
    parser.add_argument(
        "--wikidata-csv", type=Path, default=None,
        help="the Wikidata artist snapshot CSV file to apply")
    parser.add_argument(
        "--overrides-csv", type=Path, default=None,
        help="the manual artist override CSV file to apply")
    return parser.parse_args(argv)


def parse_artist_credit(credit: str) -> list[tuple[str, Role]]:
    """Parse a combined artist credit into artists and roles.

    The credit splits into a primary side and a featured side on
    the word "featuring" or "feat.", case-insensitively; without
    them, every artist is primary.  Each side splits into artist
    names on the delimiters ", ", " & ", " + " (literally) and
    " and ", " x ", " with " (case-insensitively).

    Known limitation: a compound act name that contains one of the
    delimiters is over-split; such cases are corrected later via
    the human override layer.

    :param credit: The combined artist credit string.
    :return: The (name, role) pairs in credit order, primary side
        first, with the role ``Role.PRIMARY`` or
        ``Role.FEATURED``.
    """
    sides: list[str] = FEATURING_PATTERN.split(credit, maxsplit=1)
    pairs: list[tuple[str, Role]] = []
    role: Role
    side: str
    for side, role in zip(sides, (Role.PRIMARY, Role.FEATURED)):
        token: str
        for token in DELIMITER_PATTERN.split(side):
            name: str = token.strip()
            if name != "":
                pairs.append((name, role))
    return pairs


def create_song(session: Session, song_id: int, title: str,
                credit: str, artists: dict[str, Artist]) -> Song:
    """Create a song with its parsed artist credits.

    The song takes the given ID.  A newly created artist takes
    the ID following the known artists, in credit order.  An
    artist duplicated within the credit is kept only at its
    first occurrence, with a warning to the standard error.

    :param session: The database session.
    :param song_id: The song ID to assign.
    :param title: The song title.
    :param credit: The combined artist credit string.
    :param artists: The known artists by name, updated with the
        newly created ones as an observable side effect.
    :return: The created song, added to the session.
    """
    song: Song = Song(id=song_id, title=title,
                      artist_credit=credit)
    session.add(song)
    seen: set[str] = set()
    position: int = 0
    name: str
    role: Role
    for name, role in parse_artist_credit(credit):
        if name in seen:
            print(f"warning: {credit}: duplicated artist"
                  f" \"{name}\"", file=sys.stderr)
            continue
        seen.add(name)
        if name not in artists:
            artists[name] = Artist(id=len(artists) + 1, name=name)
        session.add(SongArtist(song=song, artist=artists[name],
                               role=role, position=position))
        position += 1
    return song


def load_chart(session: Session, path: Path) -> None:
    """Load the chart CSV into songs, chart entries, and credits.

    A song repeated across the rows is stored once, keyed by its
    exact title and artist credit; every row yields one chart
    entry.  The songs and the artists take the IDs 1, 2, 3, ...
    in the first-occurrence row order.

    :param session: The database session.
    :param path: The chart CSV file with the columns year, rank,
        title, and artist.
    :return: None.
    :raises OSError: When the file cannot be read.
    """
    songs: dict[tuple[str, str], Song] = {}
    artists: dict[str, Artist] = {}
    with open(path, encoding="utf-8", newline="") as file:
        row: dict[str, str]
        for row in csv.DictReader(file):
            key: tuple[str, str] = (row["title"], row["artist"])
            if key not in songs:
                songs[key] = create_song(
                    session, len(songs) + 1, row["title"],
                    row["artist"], artists)
            session.add(ChartEntry(year=int(row["year"]),
                                   rank=int(row["rank"]),
                                   song=songs[key]))


def load_lyrics(session: Session, directory: Path) -> None:
    """Load the cached lyrics files into the matching songs.

    A file whose stem is not an existing song ID is skipped with
    a warning to the standard error.

    :param session: The database session, with the songs flushed.
    :param directory: The existing lyrics cache directory with
        one ``<song_id>.txt`` file per song.
    :return: None.
    :raises OSError: When a lyrics file cannot be read.
    """
    for path in sorted(directory.glob("*.txt")):
        song: Song | None = None
        if path.stem.isdigit():
            song = session.get(Song, int(path.stem))
        if song is None:
            print(f"warning: {path}: no song with ID"
                  f" \"{path.stem}\"", file=sys.stderr)
            continue
        song.lyrics = path.read_text(encoding="utf-8")


def apply_artist_csv(session: Session, path: Path) -> None:
    """Apply an artist attribute CSV onto the artist rows.

    Artists match by exact name.  Only the non-empty cells are
    applied, so a later CSV overrides an earlier one field by
    field.  The note column is ignored.

    :param session: The database session, with the artists
        flushed.
    :param path: The CSV file with the columns name, qid, gender,
        type, genre, country, and note.
    :return: None.
    :raises BuildError: When a name matches no artist.
    :raises OSError: When the file cannot be read.
    """
    with open(path, encoding="utf-8", newline="") as file:
        row: dict[str, str]
        for row in csv.DictReader(file):
            artist: Artist | None = session.scalar(
                sa.select(Artist)
                .where(Artist.name == row["name"]))
            if artist is None:
                raise BuildError(
                    f"{path}: no artist named \"{row['name']}\"")
            column: str
            attribute: str
            for column, attribute in ARTIST_FIELDS.items():
                if row.get(column):
                    setattr(artist, attribute, row[column])


def find_violations(session: Session, years: Iterable[int],
                    ranks_per_year: int) -> list[str]:
    """Find the invariant violations in the loaded data.

    The invariants: the chart entries cover each expected year
    and rank exactly once and nothing else, every song has at
    least one primary artist, and every artist name is non-empty.

    :param session: The database session with the loaded data
        flushed.
    :param years: The expected chart years.
    :param ranks_per_year: The expected number of ranks per year.
    :return: The violation messages, empty when the data is
        valid.
    """
    violations: list[str] = []
    expected: set[tuple[int, int]] = {
        (year, rank) for year in years
        for rank in range(1, ranks_per_year + 1)}
    actual: set[tuple[int, int]] = {
        (x.year, x.rank)
        for x in session.scalars(sa.select(ChartEntry))}
    year: int
    rank: int
    for year, rank in sorted(expected - actual):
        violations.append(
            f"missing chart entry: year {year} rank {rank}")
    for year, rank in sorted(actual - expected):
        violations.append(
            f"unexpected chart entry: year {year} rank {rank}")
    primary_ids: set[int] = set(session.scalars(
        sa.select(SongArtist.song_id)
        .where(SongArtist.role == Role.PRIMARY)))
    song: Song
    for song in session.scalars(sa.select(Song).order_by(Song.id)):
        if song.id not in primary_ids:
            violations.append(
                f"song {song.id} \"{song.title}\" has no primary"
                " artist")
    artist: Artist
    for artist in session.scalars(sa.select(Artist)):
        if artist.name.strip() == "":
            violations.append(
                f"artist {artist.id} has an empty name")
    return violations


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


def prepare_engine(engine: sa.Engine) -> None:
    """Prepare a SQLite engine for a build.

    For a file-based SQLite engine, the parent directory of the
    database file is created when missing.  A non-SQLite engine is
    left untouched.

    :param engine: The database engine.
    :return: None.
    """
    if engine.url.get_backend_name() != "sqlite":
        return
    database: str | None = engine.url.database
    if database is not None and database != ":memory:":
        Path(database).parent.mkdir(parents=True, exist_ok=True)


def reset_store(session: Session) -> None:
    """Delete all the rows from every table of the store.

    :param session: The database session.
    :return: None.
    """
    model: type[Base]
    for model in (SongArtist, ChartEntry, Song, Artist):
        session.execute(sa.delete(model))


def main(argv: list[str] | None = None) -> int:
    """Rebuild the SQLite working store from the inputs.

    :param argv: The command-line arguments, or None for
        ``sys.argv``.
    :return: The exit status: 0 on success, non-zero on failure.
    """
    args: argparse.Namespace = parse_args(argv)
    engine: sa.Engine = ds.engine
    prepare_engine(engine)
    Base.metadata.create_all(engine)
    session: Session = ds.get_db()
    counts: StoreCounts
    try:
        reset_store(session)
        load_chart(session, args.chart_csv)
        session.flush()
        if args.lyrics_dir is not None:
            if not args.lyrics_dir.is_dir():
                raise BuildError(
                    f"{args.lyrics_dir}: no such directory")
            load_lyrics(session, args.lyrics_dir)
        if args.wikidata_csv is not None:
            apply_artist_csv(session, args.wikidata_csv)
        if args.overrides_csv is not None:
            apply_artist_csv(session, args.overrides_csv)
        session.flush()
        violations: list[str] = find_violations(
            session, YEARS, RANKS_PER_YEAR)
        if len(violations) > 0:
            session.rollback()
            for violation in violations:
                print(f"error: {violation}", file=sys.stderr)
            return 1
        counts = StoreCounts.get_instance(session)
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
