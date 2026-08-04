# Tools for A Feminist Audit of Pop Music.
# Copyright 2026 imacat.  All rights reserved.
# Authors:
#   imacat@mail.imacat.idv.tw (imacat), 2026/8/4
"""Unit tests for the LLM input exporter module."""
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from typing import Any
from unittest import mock

from sqlalchemy.orm import Session

from pop_fem_audit_tools import config
from pop_fem_audit_tools.commands import export_llm_input
from pop_fem_audit_tools.database import Base, DataSource
from pop_fem_audit_tools.models import (
    Artist,
    Role,
    Song,
    SongArtist,
)


class TestExportLlmInput(unittest.TestCase):
    """Test cases for the LLM input exporter."""

    def setUp(self) -> None:
        """Create a temporary working store for the tests."""
        tmp: tempfile.TemporaryDirectory[str] \
            = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.__dir: Path = Path(tmp.name)
        self.__output: Path = self.__dir / "llm-input.jsonl"
        url: str = f"sqlite:///{self.__dir}/store.sqlite3"
        config.set_settings(config.Settings(
            SQLALCHEMY_DATABASE_URL=url,
            ANTHROPIC_API_KEY="test-key"))
        self.__ds: DataSource = DataSource()
        patcher: Any = mock.patch.object(
            export_llm_input, "ds", self.__ds)
        patcher.start()
        self.addCleanup(patcher.stop)

    def __seed(
            self, songs: list[tuple[str, str, str | None]]) -> None:
        """Create the schema and the fixture songs.

        Each song gets a single primary artist at position 0,
        whose name equals the song's artist credit; the song IDs
        are assigned in list order starting from 1.

        :param songs: The (title, artist, lyrics) triples.
        :return: None.
        """
        Base.metadata.create_all(self.__ds.engine)
        session: Session = self.__ds.get_db()
        try:
            title: str
            artist: str
            lyrics: str | None
            for title, artist, lyrics in songs:
                artist_row: Artist = Artist(name=artist)
                song: Song = Song(
                    title=title, artist_credit=artist,
                    lyrics=lyrics)
                session.add(song)
                session.add(SongArtist(
                    song=song, artist=artist_row,
                    role=Role.PRIMARY, position=0))
            session.commit()
        finally:
            session.close()

    def __run_export(self) -> tuple[int, str]:
        """Run the exporter with the standard error captured.

        :return: A tuple of the exit status and the standard
            error.
        """
        stderr: io.StringIO = io.StringIO()
        with redirect_stderr(stderr):
            status: int = export_llm_input.main(
                [str(self.__output)])
        return status, stderr.getvalue()

    @staticmethod
    def __read_records(path: Path) -> list[dict[str, str]]:
        """Read the JSONL records of a file.

        :param path: The JSONL file.
        :return: The parsed records, in file order.
        """
        with open(path, encoding="utf-8") as file:
            return [json.loads(line) for line in file
                    if line.strip() != ""]

    def test_exports_songs_ordered_by_id(self) -> None:
        """Test that the songs export in ID order, one per line."""
        self.__seed([
            ("Hello", "Adele", "hello lyrics\n"),
            ("Umbrella", "Rihanna", "umbrella lyrics\n")])
        status: int
        stderr: str
        status, stderr = self.__run_export()
        self.assertEqual(status, 0)
        records: list[dict[str, str]] = self.__read_records(
            self.__output)
        self.assertEqual(records, [
            {"id": "song-1", "content": "hello lyrics\n"},
            {"id": "song-2", "content": "umbrella lyrics\n"}])
        self.assertIn("done: 2 songs exported", stderr)

    def test_preserves_non_ascii_lyrics(self) -> None:
        """Test that non-ASCII lyrics are written verbatim."""
        self.__seed([("Song", "Artist", "非英文歌詞\n")])
        self.assertEqual(self.__run_export()[0], 0)
        self.assertEqual(
            self.__output.read_text(encoding="utf-8"),
            json.dumps(
                {"id": "song-1", "content": "非英文歌詞\n"},
                ensure_ascii=False) + "\n")
        self.assertIn("非英文歌詞", self.__output.read_text(
            encoding="utf-8"))

    def test_no_artist_or_title_data_in_output(self) -> None:
        """Test the lyrics-only firewall: no title or artist
        leaks into the output."""
        self.__seed([(
            "Confidential Title", "Confidential Artist",
            "plain lyrics\n")])
        self.assertEqual(self.__run_export()[0], 0)
        content: str = self.__output.read_text(encoding="utf-8")
        self.assertNotIn("Confidential Title", content)
        self.assertNotIn("Confidential Artist", content)
        records: list[dict[str, str]] = self.__read_records(
            self.__output)
        self.assertEqual(records, [
            {"id": "song-1", "content": "plain lyrics\n"}])

    def test_missing_lyrics_fails(self) -> None:
        """Test that a song without lyrics fails without writing
        a partial file."""
        self.__seed([
            ("Hello", "Adele", "hello lyrics\n"),
            ("Silent", "Nobody", None)])
        status: int
        stderr: str
        status, stderr = self.__run_export()
        self.assertEqual(status, 1)
        self.assertIn(
            "error: song 2 \"Silent\": no lyrics", stderr)
        self.assertFalse(self.__output.exists())

    def test_creates_parent_directory(self) -> None:
        """Test that the output file's parent directory is
        created when missing."""
        self.__seed([("Hello", "Adele", "hello lyrics\n")])
        nested: Path = self.__dir / "nested" / "dir" / "out.jsonl"
        status: int = export_llm_input.main([str(nested)])
        self.assertEqual(status, 0)
        self.assertTrue(nested.exists())
        records: list[dict[str, str]] = self.__read_records(
            nested)
        self.assertEqual(records, [
            {"id": "song-1", "content": "hello lyrics\n"}])
