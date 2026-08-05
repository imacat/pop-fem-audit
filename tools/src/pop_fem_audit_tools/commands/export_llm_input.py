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
"""
import argparse
import json
import sys
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from ..database import ds
from ..models import Song


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


def load_extras(path: Path) -> dict[str, Any]:
    """Load the extras object from a JSON file.

    :param path: The extras JSON file.
    :return: The extras, in file order.
    :raises OSError: When the file cannot be read.
    :raises ValueError: When the file is not valid JSON, is not
        a JSON object, has duplicate keys, or has a "lyrics" key.
    """
    with open(path, encoding="utf-8") as file:
        text: str = file.read()
    try:
        data: Any = json.loads(
            text, object_pairs_hook=_no_duplicate_keys)
    except json.JSONDecodeError as error:
        raise ValueError(
            f"invalid JSON in extras file {path}: {error}") \
            from error
    if not isinstance(data, dict):
        raise ValueError(
            f"extras file {path} must contain a JSON object")
    if "lyrics" in data:
        raise ValueError(
            f"extras file {path} must not have a \"lyrics\" key")
    return data


def build_lines(
        session: Session,
        extras: dict[str, Any] | None = None) -> list[str]:
    """Build the JSONL lines of every song's lyrics.

    Without extras, each record's ``content`` is the bare lyrics
    string.  With extras, ``content`` is a JSON object serialized
    as a string, whose first key is ``"lyrics"`` holding the
    lyrics string, followed by the extras' keys in their given
    order.

    :param session: The database session.
    :param extras: The extra parameters merged into every
        record's content alongside the lyrics, in the order they
        are to appear, or None for the bare lyrics string.
    :return: The JSON lines, one per song, ordered by song ID.
    :raises ValueError: When a song has no lyrics.
    """
    lines: list[str] = []
    song: Song
    for song in session.scalars(sa.select(Song).order_by(Song.id)):
        if song.lyrics is None:
            raise ValueError(
                f"song {song.id} \"{song.title}\": no lyrics")
        content: str
        if extras is None:
            content = song.lyrics
        else:
            payload: dict[str, Any] = {"lyrics": song.lyrics}
            payload.update(extras)
            content = json.dumps(payload, ensure_ascii=False)
        record: dict[str, str] = {
            "id": f"song-{song.id}", "content": content}
        lines.append(json.dumps(record, ensure_ascii=False))
    return lines


def main(argv: list[str] | None = None) -> int:
    """Export the LLM input JSONL file from the working store.

    :param argv: The command-line arguments, or None for
        ``sys.argv``.
    :return: The exit status: 0 on success, non-zero on failure.
    """
    args: argparse.Namespace = parse_args(argv)
    session: Session = ds.get_db()
    lines: list[str]
    try:
        extras: dict[str, Any] | None = None
        if args.extras is not None:
            extras = load_extras(args.extras)
        lines = build_lines(session, extras)
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
    print(f"done: {len(lines)} songs exported", file=sys.stderr)
    return 0
