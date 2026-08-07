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

With ``--extras``, each record's ``content`` becomes a JSON
object serialized as a string, its ``lyrics`` key holding the
song's lyrics followed by the keys of the given extras file in
their file order, so a step that needs parameters alongside the
lyrics can carry them without this module knowing what they mean.

With ``--extras-per-id``, the same merge happens per song: the
given file maps a song ID to the extra keys of that one song, and
the export is restricted to the song IDs the file names, so a step
that revisits only some of the songs, each with its own parameters,
gets exactly those records.  The two options may be given together,
in which case a record's keys are ``lyrics``, the shared extras'
keys, then that song's own keys, each group in its file order.
"""
import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from ..database import ds
from ..models import Song
from ..utils import format_duration


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
             " parameters; when given, each record's \"content\""
             " becomes a JSON object string with a \"lyrics\" key"
             " followed by the extras' keys, instead of the bare"
             " lyrics string")
    parser.add_argument(
        "--extras-per-id", type=Path, default=None,
        help="a JSON file holding a single JSON object that maps a"
             " song ID, as \"song-<N>\", to a JSON object of extra"
             " parameters for that one song; the song's object is"
             " merged into its \"content\" the same way as with"
             " --extras, and the export is restricted to the song"
             " IDs the file names")
    return parser.parse_args(argv)


def _no_duplicate_keys(
        pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Build a dict from JSON object pairs, rejecting duplicates.

    :param pairs: The key-value pairs of a JSON object, in file
        order.
    :return: The pairs as a dict, in file order.
    :raises ValueError: When a key appears more than once.
    """
    result: dict[str, Any] = {}
    key: str
    value: Any
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate key \"{key}\" in extras")
        result[key] = value
    return result


def _load_json_object(path: Path, label: str) -> dict[str, Any]:
    """Load a single JSON object from a file, in file order.

    :param path: The JSON file.
    :param label: The kind of file, for the error messages.
    :return: The object, in file order.
    :raises OSError: When the file cannot be read.
    :raises ValueError: When the file is not valid JSON, is not
        a JSON object, or has duplicate keys.
    """
    with open(path, encoding="utf-8") as file:
        text: str = file.read()
    try:
        data: Any = json.loads(
            text, object_pairs_hook=_no_duplicate_keys)
    except json.JSONDecodeError as error:
        raise ValueError(
            f"invalid JSON in {label} file {path}: {error}") \
            from error
    if not isinstance(data, dict):
        raise ValueError(
            f"{label} file {path} must contain a JSON object")
    return data


def load_extras(path: Path) -> dict[str, Any]:
    """Load the extras object from a JSON file.

    :param path: The extras JSON file.
    :return: The extras, in file order.
    :raises OSError: When the file cannot be read.
    :raises ValueError: When the file is not valid JSON, is not
        a JSON object, has duplicate keys, or has a "lyrics" key.
    """
    data: dict[str, Any] = _load_json_object(path, "extras")
    if "lyrics" in data:
        raise ValueError(
            f"extras file {path} must not have a \"lyrics\" key")
    return data


def load_extras_per_id(path: Path) -> dict[str, dict[str, Any]]:
    """Load the per-ID extras object from a JSON file.

    :param path: The per-ID extras JSON file, mapping a song ID,
        as ``song-<N>``, to the extras of that one song.
    :return: The extras of each song ID, in file order, every
        song's own extras in their file order too.
    :raises OSError: When the file cannot be read.
    :raises ValueError: When the file is not valid JSON, is not
        a JSON object, has duplicate keys, has a song whose value
        is not a JSON object, or has a song with a "lyrics" key.
    """
    data: dict[str, Any] = _load_json_object(path, "per-ID extras")
    song_id: str
    extras: Any
    for song_id, extras in data.items():
        if not isinstance(extras, dict):
            raise ValueError(
                f"per-ID extras file {path}: id {song_id} must"
                " have a JSON object")
        if "lyrics" in extras:
            raise ValueError(
                f"per-ID extras file {path}: id {song_id} must not"
                " have a \"lyrics\" key")
    return data


def _build_content(
        lyrics: str,
        extras: dict[str, Any] | None,
        song_extras: dict[str, Any] | None) -> str:
    """Build the content of one exported record.

    :param lyrics: The lyrics of the song.
    :param extras: The extra parameters shared by every record,
        in the order they are to appear, or None for none.
    :param song_extras: The extra parameters of this record
        alone, in the order they are to appear, or None for none.
    :return: The bare lyrics when there are no extras of either
        kind, or otherwise a JSON object serialized as a string,
        whose first key is ``"lyrics"`` holding the lyrics,
        followed by the shared extras' keys and then this
        record's own keys, each group in its given order.
    """
    if extras is None and song_extras is None:
        return lyrics
    payload: dict[str, Any] = {"lyrics": lyrics}
    if extras is not None:
        payload.update(extras)
    if song_extras is not None:
        payload.update(song_extras)
    return json.dumps(payload, ensure_ascii=False)


def build_lines(
        session: Session,
        extras: dict[str, Any] | None = None,
        extras_per_id: dict[str, dict[str, Any]] | None = None) \
        -> list[str]:
    """Build the JSONL lines of the exported songs' lyrics.

    Without extras of either kind, each record's ``content`` is
    the bare lyrics string.  With extras, ``content`` is a JSON
    object serialized as a string, whose first key is ``"lyrics"``
    holding the lyrics string, followed by the shared extras' keys
    and then the song's own per-ID extras' keys, each group in its
    given order.

    Every song is exported, unless per-ID extras are given, in
    which case only the songs they name are.

    :param session: The database session.
    :param extras: The extra parameters merged into every
        record's content alongside the lyrics, in the order they
        are to appear, or None for none.
    :param extras_per_id: The extra parameters merged into the
        content of one record alone, keyed by that record's song
        ID and in the order they are to appear, restricting the
        export to the song IDs they name, or None for no such
        extras and no such restriction.
    :return: The JSON lines, one per exported song, ordered by
        song ID.
    :raises ValueError: When an exported song has no lyrics, or
        the per-ID extras name a song the working store does not
        have.
    """
    lines: list[str] = []
    exported: set[str] = set()
    song: Song
    for song in session.scalars(sa.select(Song).order_by(Song.id)):
        song_id: str = f"song-{song.id}"
        if extras_per_id is not None and song_id not in extras_per_id:
            continue
        if song.lyrics is None:
            raise ValueError(
                f"song {song.id} \"{song.title}\": no lyrics")
        song_extras: dict[str, Any] | None = None \
            if extras_per_id is None else extras_per_id[song_id]
        content: str = _build_content(
            song.lyrics, extras, song_extras)
        record: dict[str, str] = {
            "id": song_id, "content": content}
        lines.append(json.dumps(record, ensure_ascii=False))
        exported.add(song_id)
    if extras_per_id is not None:
        missing: list[str] = sorted(set(extras_per_id) - exported)
        if len(missing) > 0:
            raise ValueError(
                "the per-ID extras name songs the working store"
                f" does not have: {', '.join(missing)}")
    return lines


def main(argv: list[str] | None = None) -> int:
    """Export the LLM input JSONL file from the working store.

    Every song is exported, unless ``--extras-per-id`` is given,
    in which case only the songs its file names are.

    :param argv: The command-line arguments, or None for
        ``sys.argv``.
    :return: The exit status: 0 on success, non-zero on failure.
    """
    started: float = time.monotonic()
    args: argparse.Namespace = parse_args(argv)
    session: Session = ds.get_db()
    lines: list[str]
    try:
        extras: dict[str, Any] | None = None
        if args.extras is not None:
            extras = load_extras(args.extras)
        extras_per_id: dict[str, dict[str, Any]] | None = None
        if args.extras_per_id is not None:
            extras_per_id = load_extras_per_id(args.extras_per_id)
        lines = build_lines(session, extras, extras_per_id)
    except (OSError, sa.exc.SQLAlchemyError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    finally:
        session.close()
    args.output_jsonl.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output_jsonl, "w", encoding="utf-8") as file:
        line: str
        for line in lines:
            file.write(line + "\n")
    elapsed: str = format_duration(time.monotonic() - started)
    print(f"Done.  {len(lines)} songs exported."
          f"  {elapsed} elapsed.", file=sys.stderr)
    return 0
