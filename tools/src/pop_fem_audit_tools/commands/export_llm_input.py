# Tools for A Feminist Audit of Pop Music.
# Copyright 2026 imacat.  All rights reserved.
# Authors:
#   imacat@mail.imacat.idv.tw (imacat), 2026/8/4
"""The exporter of the LLM input JSONL file.

Exports the songs from the SQLite working store into the JSONL
input file for the ``run-llm`` subcommand, given as the positional
command-line argument.  This is the enforcement point of the
project's lyrics-only firewall: the output carries only the
lyrics text of each song, identified by an opaque song key; no
title, artist, or chart data crosses into the LLM input.

With ``--extras`` and ``--extras-per-id``, a record's content may
carry extra parameters alongside the lyrics, so a step that needs
them can get them without this module knowing what they mean; see
the exporter's content-building step for how the two merge.
"""
import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, ClassVar

import sqlalchemy as sa
from sqlalchemy.orm import Session

from ..database import ds
from ..models import Song
from ..utils import format_duration


class LlmInputExporter:
    """The exporter of the LLM input JSONL file."""

    __LYRICS_KEY: ClassVar[str] = "lyrics"
    """The key holding the lyrics in a record's merged content,
    and the key forbidden in an extras file."""

    def __init__(
            self, output_jsonl: Path, extras: Path | None = None,
            extras_per_id: Path | None = None) -> None:
        """Set up the exporter of the LLM input JSONL file.

        :param output_jsonl: The JSONL output file.
        :param extras: The extras JSON file, or None for none.
        :param extras_per_id: The per-ID extras JSON file, or
            None for none.
        """
        self.__output_jsonl: Path = output_jsonl
        """The JSONL output file."""
        self.__extras_path: Path | None = extras
        """The extras JSON file, or None for none."""
        self.__extras_per_id_path: Path | None = extras_per_id
        """The per-ID extras JSON file, or None for none."""

    def run(self) -> int:
        """Export the songs' lyrics to the output JSONL file.

        :return: The number of songs exported.
        :raises OSError: When a file cannot be read or written.
        :raises sqlalchemy.exc.SQLAlchemyError: When the working
            store cannot be read.
        :raises ValueError: When an extras file is malformed, an
            exported song has no lyrics, or the per-ID extras
            name a song the working store does not have.
        """
        session: Session = ds.get_db()
        try:
            extras: dict[str, Any] | None = None
            if self.__extras_path is not None:
                extras = self.__load_extras(self.__extras_path)
            extras_per_id: dict[str, dict[str, Any]] | None = None
            if self.__extras_per_id_path is not None:
                extras_per_id = self.__load_extras_per_id(
                    self.__extras_per_id_path)
            lines: list[str] = self.__build_lines(
                session, extras, extras_per_id)
        finally:
            session.close()
        self.__write_output(lines)
        return len(lines)

    @staticmethod
    def __no_duplicate_keys(
            pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        """Build a dict from JSON object pairs, rejecting
        duplicates.

        :param pairs: The key-value pairs of a JSON object, in
            file order.
        :return: The pairs as a dict, in file order.
        :raises ValueError: When a key appears more than once.
        """
        result: dict[str, Any] = {}
        key: str
        value: Any
        for key, value in pairs:
            if key in result:
                raise ValueError(
                    f"duplicate key \"{key}\" in extras")
            result[key] = value
        return result

    @classmethod
    def __load_json_object(
            cls, path: Path, label: str) -> dict[str, Any]:
        """Load a single JSON object from a file, in file order.

        :param path: The JSON file.
        :param label: The kind of file, for the error messages.
        :return: The object, in file order.
        :raises OSError: When the file cannot be read.
        :raises ValueError: When the file is not valid JSON, is
            not a JSON object, or has duplicate keys.
        """
        with open(path, encoding="utf-8") as file:
            text: str = file.read()
        try:
            data: Any = json.loads(
                text, object_pairs_hook=cls.__no_duplicate_keys)
        except json.JSONDecodeError as error:
            raise ValueError(
                f"invalid JSON in {label} file {path}: {error}") \
                from error
        if not isinstance(data, dict):
            raise ValueError(
                f"{label} file {path} must contain a JSON object")
        return data

    @classmethod
    def __load_extras(cls, path: Path) -> dict[str, Any]:
        """Load the extras object from a JSON file.

        :param path: The extras JSON file.
        :return: The extras, in file order.
        :raises OSError: When the file cannot be read.
        :raises ValueError: When the file is not valid JSON, is
            not a JSON object, has duplicate keys, or has a
            "lyrics" key.
        """
        data: dict[str, Any] = cls.__load_json_object(
            path, "extras")
        if cls.__LYRICS_KEY in data:
            raise ValueError(
                f"extras file {path} must not have a"
                f" \"{cls.__LYRICS_KEY}\" key")
        return data

    @classmethod
    def __load_extras_per_id(
            cls, path: Path) -> dict[str, dict[str, Any]]:
        """Load the per-ID extras object from a JSON file.

        :param path: The per-ID extras JSON file, mapping a song
            ID, as ``song-<N>``, to the extras of that one song.
        :return: The extras of each song ID, in file order, every
            song's own extras in their file order too.
        :raises OSError: When the file cannot be read.
        :raises ValueError: When the file is not valid JSON, is
            not a JSON object, has duplicate keys, has a song
            whose value is not a JSON object, or has a song with
            a "lyrics" key.
        """
        data: dict[str, Any] = cls.__load_json_object(
            path, "per-ID extras")
        song_id: str
        extras: Any
        for song_id, extras in data.items():
            if not isinstance(extras, dict):
                raise ValueError(
                    f"per-ID extras file {path}: id {song_id}"
                    " must have a JSON object")
            if cls.__LYRICS_KEY in extras:
                raise ValueError(
                    f"per-ID extras file {path}: id {song_id}"
                    f" must not have a \"{cls.__LYRICS_KEY}\""
                    " key")
        return data

    def __build_lines(
            self, session: Session,
            extras: dict[str, Any] | None = None,
            extras_per_id: dict[str, dict[str, Any]] | None
            = None) -> list[str]:
        """Build the JSONL lines of the exported songs' lyrics.

        Every song is exported, unless per-ID extras are given,
        in which case only the songs they name are; see
        :meth:`__build_content` for how the extras merge into a
        record's content.

        :param session: The database session.
        :param extras: The extra parameters merged into every
            record's content alongside the lyrics, in the order
            they are to appear, or None for none.
        :param extras_per_id: The extra parameters merged into
            the content of one record alone, keyed by that
            record's song ID and in the order they are to appear,
            restricting the export to the song IDs they name, or
            None for no such extras and no such restriction.
        :return: The JSON lines, one per exported song, ordered by
            song ID.
        :raises ValueError: When an exported song has no lyrics,
            or the per-ID extras name a song the working store
            does not have.
        """
        lines: list[str] = []
        exported: set[str] = set()
        song: Song
        for song in session.scalars(
                sa.select(Song).order_by(Song.id)):
            song_id: str = f"song-{song.id}"
            if extras_per_id is not None \
                    and song_id not in extras_per_id:
                continue
            if song.lyrics is None:
                raise ValueError(
                    f"song {song.id} \"{song.title}\": no lyrics")
            song_extras: dict[str, Any] | None = None \
                if extras_per_id is None \
                else extras_per_id[song_id]
            content: str = self.__build_content(
                song.lyrics, extras, song_extras)
            record: dict[str, str] = {
                "id": song_id, "content": content}
            lines.append(json.dumps(record, ensure_ascii=False))
            exported.add(song_id)
        if extras_per_id is not None:
            missing: list[str] = sorted(
                set(extras_per_id) - exported)
            if len(missing) > 0:
                raise ValueError(
                    "the per-ID extras name songs the working"
                    f" store does not have: {', '.join(missing)}")
        return lines

    @classmethod
    def __build_content(
            cls, lyrics: str, extras: dict[str, Any] | None,
            song_extras: dict[str, Any] | None) -> str:
        """Build the content of one exported record.

        Without extras of either kind, a record's content is the
        bare lyrics string.  With ``--extras``, the content
        becomes a JSON object serialized as a string, its
        "lyrics" key holding the song's lyrics followed by the
        keys of the given extras file, in their file order.  With
        ``--extras-per-id``, the same merge happens per song: the
        song's own extra keys follow the lyrics instead.  When
        both are given, a record's keys are "lyrics", the shared
        extras' keys, then that song's own keys, each group in
        its file order.

        :param lyrics: The lyrics of the song.
        :param extras: The extra parameters shared by every
            record, in the order they are to appear, or None for
            none.
        :param song_extras: The extra parameters of this record
            alone, in the order they are to appear, or None for
            none.
        :return: The bare lyrics when there are no extras of
            either kind, or otherwise a JSON object serialized as
            a string, whose first key is "lyrics" holding the
            lyrics, followed by the shared extras' keys and then
            this record's own keys, each group in its given
            order.
        """
        if extras is None and song_extras is None:
            return lyrics
        payload: dict[str, Any] = {cls.__LYRICS_KEY: lyrics}
        if extras is not None:
            payload.update(extras)
        if song_extras is not None:
            payload.update(song_extras)
        return json.dumps(payload, ensure_ascii=False)

    def __write_output(self, lines: list[str]) -> None:
        """Write the exported lines to the output JSONL file.

        Creates the parent directory when it does not exist.

        :param lines: The JSONL lines, in the output order.
        :return: None.
        :raises OSError: When the file cannot be written.
        """
        self.__output_jsonl.parent.mkdir(
            parents=True, exist_ok=True)
        with open(
                self.__output_jsonl, "w",
                encoding="utf-8") as file:
            line: str
            for line in lines:
                file.write(line + "\n")


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Parse the command-line arguments.

    :param argv: The command-line arguments, or None for
        ``sys.argv``.
    :return: The parsed arguments.
    """
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description="Export the LLM input JSONL file (lyrics"
                    " only) from the SQLite working store.")
    parser.add_argument(
        "output_jsonl", type=Path,
        help="the JSONL output file")
    parser.add_argument(
        "--extras", type=Path, default=None,
        help="a JSON file holding a single JSON object of extra"
             " parameters merged into every record's content")
    parser.add_argument(
        "--extras-per-id", type=Path, default=None,
        help="a JSON file holding a single JSON object that maps a"
             " song ID, as \"song-<N>\", to a JSON object of extra"
             " parameters for that one song, restricting the"
             " export to the song IDs the file names")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Export the LLM input JSONL file from the working store.

    :param argv: The command-line arguments, or None for
        ``sys.argv``.
    :return: The exit status: 0 on success, non-zero on failure.
    """
    started: float = time.monotonic()
    args: argparse.Namespace = parse_args(argv)
    try:
        count: int = LlmInputExporter(
            args.output_jsonl, args.extras,
            args.extras_per_id).run()
    except (OSError, sa.exc.SQLAlchemyError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    elapsed: str = format_duration(time.monotonic() - started)
    print(f"Done.  {count} songs exported."
          f"  {elapsed} elapsed.", file=sys.stderr)
    return 0
