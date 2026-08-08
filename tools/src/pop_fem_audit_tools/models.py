# Tools for A Feminist Audit of Pop Music.
# Copyright 2026 imacat.  All rights reserved.
# Authors:
#   imacat@mail.imacat.idv.tw (imacat), 2026/7/31
"""The data models.

The schema covers the year-end chart data: songs with their
lyrics, their yearly chart entries, the individual artists, and
the song-artist credits with the role and order.  It also covers
the settled coding of the songs: the keywords assigned to each
song with the lyric quotes they are grounded in.

"""
import enum

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class Role(enum.StrEnum):
    """The role of an artist on a song credit."""

    PRIMARY = "primary"
    """The primary artist role."""
    FEATURED = "featured"
    """The featured artist role."""


class Song(Base):
    """A song, identified by its title and combined artist credit."""
    __tablename__ = "songs"
    """The table name."""

    id: Mapped[int] = mapped_column(primary_key=True)
    """The song ID."""
    title: Mapped[str] = mapped_column()
    """The song title."""
    artist_credit: Mapped[str] = mapped_column()
    """The combined artist credit string as printed on the chart."""
    lyrics: Mapped[str | None]
    """The lyrics text, when available."""
    performer_gender: Mapped[str | None]
    """The gender of the credited performers taken together:
    "mixed" when they disagree, their common gender when every
    credited artist's gender is known and they agree, and None
    otherwise."""
    chart_entries: Mapped[list[ChartEntry]] \
        = relationship(back_populates="song")
    """The chart entries of the song."""
    song_artists: Mapped[list[SongArtist]] \
        = relationship(back_populates="song")
    """The song-artist credits of the song."""
    codings: Mapped[list[Coding]] \
        = relationship(back_populates="song")
    """The settled codings of the song."""
    __table_args__ = (sa.UniqueConstraint(title, artist_credit),)
    """The table-level constraints."""


class ChartEntry(Base):
    """An entry of a song on the year-end chart."""
    __tablename__ = "chart_entries"
    """The table name."""

    year: Mapped[int] = mapped_column(primary_key=True)
    """The chart year."""
    rank: Mapped[int] = mapped_column(primary_key=True)
    """The rank of the song on the chart of the year."""
    song_id: Mapped[int] = mapped_column(sa.ForeignKey(Song.id))
    """The ID of the charted song."""
    song: Mapped[Song] = relationship(back_populates="chart_entries")
    """The charted song."""


class Artist(Base):
    """An individual artist."""
    __tablename__ = "artists"
    """The table name."""

    id: Mapped[int] = mapped_column(primary_key=True)
    """The artist ID."""
    name: Mapped[str] = mapped_column(unique=True)
    """The artist name."""
    wikidata_qid: Mapped[str | None]
    """The Wikidata QID of the artist."""
    gender: Mapped[str | None]
    """The gender of the artist."""
    type: Mapped[str | None]
    """The artist type: solo or group."""
    genre: Mapped[str | None]
    """The music genre of the artist."""
    country: Mapped[str | None]
    """The country of the artist."""
    song_artists: Mapped[list[SongArtist]] \
        = relationship(back_populates="artist")
    """The song-artist credits of the artist."""


class SongArtist(Base):
    """A credit of an artist on a song, with the role and order."""
    __tablename__ = "song_artists"
    """The table name."""

    song_id: Mapped[int] = mapped_column(sa.ForeignKey(Song.id),
                                         primary_key=True)
    """The ID of the credited song."""
    artist_id: Mapped[int] = mapped_column(
        sa.ForeignKey(Artist.id), primary_key=True)
    """The ID of the credited artist."""
    role: Mapped[str] = mapped_column()
    """The role of the artist, a ``Role`` value."""
    position: Mapped[int]
    """The 0-based position of the artist in the credit order."""
    song: Mapped[Song] = relationship(back_populates="song_artists")
    """The credited song."""
    artist: Mapped[Artist] \
        = relationship(back_populates="song_artists")
    """The credited artist."""
    __table_args__ = (
        sa.CheckConstraint(role.in_([x.value for x in Role]),
                           name="ck_song_artists_role"),)
    """The table-level constraints."""


class Coding(Base):
    """A settled coding keyword of a song, with its lyric quotes."""
    __tablename__ = "codings"
    """The table name."""

    song_id: Mapped[int] = mapped_column(sa.ForeignKey(Song.id),
                                         primary_key=True)
    """The ID of the coded song."""
    keyword: Mapped[str] = mapped_column(primary_key=True)
    """The coding keyword assigned to the song."""
    quotes: Mapped[str] = mapped_column()
    """The lyric quotes the keyword is grounded in, joined by a
    single "|", empty when the keyword carries no evidence."""
    song: Mapped[Song] = relationship(back_populates="codings")
    """The coded song."""
