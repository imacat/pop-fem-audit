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
"""
import argparse
import json
import sys
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.orm import Session

from .database import ds
from .models import Song


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
    return parser.parse_args(argv)


def build_lines(session: Session) -> list[str]:
    """Build the JSONL lines of every song's lyrics.

    :param session: The database session.
    :return: The JSON lines, one per song, ordered by song ID.
    :raises ValueError: When a song has no lyrics.
    """
    lines: list[str] = []
    song: Song
    for song in session.scalars(sa.select(Song).order_by(Song.id)):
        if song.lyrics is None:
            raise ValueError(
                f"song {song.id} \"{song.title}\": no lyrics")
        record: dict[str, str] = {
            "id": f"song-{song.id}", "content": song.lyrics}
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
        lines = build_lines(session)
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
