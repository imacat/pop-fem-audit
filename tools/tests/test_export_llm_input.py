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
        config.set_settings(config.Settings(
            SQLALCHEMY_DATABASE_URL="sqlite://",
            ANTHROPIC_API_KEY="test-key"))
        self.__ds: DataSource = DataSource()
        self.addCleanup(self.__ds.engine.dispose)
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

    def __run_export(
            self, extras: Path | None = None,
            extras_per_id: Path | None = None) -> tuple[int, str]:
        """Run the exporter with the standard error captured.

        :param extras: The extras JSON file, or None for none.
        :param extras_per_id: The per-ID extras JSON file, or None
            for none.
        :return: A tuple of the exit status and the standard
            error.
        """
        argv: list[str] = [str(self.__output)]
        if extras is not None:
            argv += ["--extras", str(extras)]
        if extras_per_id is not None:
            argv += ["--extras-per-id", str(extras_per_id)]
        stderr: io.StringIO = io.StringIO()
        with redirect_stderr(stderr):
            status: int = export_llm_input.main(argv)
        return status, stderr.getvalue()

    def __write_extras(self, text: str) -> Path:
        """Write an extras file with the given raw text.

        :param text: The raw file content.
        :return: The path of the written extras file.
        """
        path: Path = self.__dir / "extras.json"
        path.write_text(text, encoding="utf-8")
        return path

    def __write_extras_per_id(self, text: str) -> Path:
        """Write a per-ID extras file with the given raw text.

        :param text: The raw file content.
        :return: The path of the written per-ID extras file.
        """
        path: Path = self.__dir / "extras-per-id.json"
        path.write_text(text, encoding="utf-8")
        return path

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
        self.assertIn("Done.  2 songs exported.", stderr)

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
        stderr: io.StringIO = io.StringIO()
        with redirect_stderr(stderr):
            status: int = export_llm_input.main([str(nested)])
        self.assertEqual(status, 0)
        self.assertTrue(nested.exists())
        records: list[dict[str, str]] = self.__read_records(
            nested)
        self.assertEqual(records, [
            {"id": "song-1", "content": "hello lyrics\n"}])

    def test_extras_merges_lyrics_first_in_file_order(
            self) -> None:
        """Test that with extras, content is a JSON object whose
        first key is lyrics, followed by the extras' keys in
        their file order."""
        self.__seed([("Hello", "Adele", "hello lyrics\n")])
        extras: Path = self.__write_extras(
            '{"b": 2, "a": 1}')
        status: int
        stderr: str
        status, stderr = self.__run_export(extras)
        self.assertEqual(status, 0)
        records: list[dict[str, str]] = self.__read_records(
            self.__output)
        self.assertEqual(len(records), 1)
        content: dict[str, Any] = json.loads(
            records[0]["content"])
        self.assertEqual(
            list(content.keys()), ["lyrics", "b", "a"])
        self.assertEqual(content["lyrics"], "hello lyrics\n")
        self.assertEqual(content["b"], 2)
        self.assertEqual(content["a"], 1)

    def test_extras_non_object_fails(self) -> None:
        """Test that a non-object extras file is rejected."""
        self.__seed([("Hello", "Adele", "hello lyrics\n")])
        extras: Path = self.__write_extras('[1, 2]')
        status: int
        stderr: str
        status, stderr = self.__run_export(extras)
        self.assertEqual(status, 1)
        self.assertIn("error:", stderr)
        self.assertFalse(self.__output.exists())

    def test_extras_with_lyrics_key_fails(self) -> None:
        """Test that an extras file carrying a "lyrics" key is
        rejected."""
        self.__seed([("Hello", "Adele", "hello lyrics\n")])
        extras: Path = self.__write_extras(
            '{"lyrics": "not allowed"}')
        status: int
        stderr: str
        status, stderr = self.__run_export(extras)
        self.assertEqual(status, 1)
        self.assertIn("error:", stderr)
        self.assertFalse(self.__output.exists())

    def test_extras_per_id_merges_each_song_its_own(self) -> None:
        """Test that with per-ID extras, each record's content is
        a JSON object of the lyrics followed by that song's own
        keys in their file order."""
        self.__seed([
            ("Hello", "Adele", "hello lyrics\n"),
            ("Umbrella", "Rihanna", "umbrella lyrics\n")])
        per_id: Path = self.__write_extras_per_id(
            '{"song-1": {"b": 2, "a": 1},'
            ' "song-2": {"disagreements": {"k": ["q"]}}}')
        status: int
        stderr: str
        status, stderr = self.__run_export(None, per_id)
        self.assertEqual(status, 0)
        records: list[dict[str, str]] = self.__read_records(
            self.__output)
        self.assertEqual(len(records), 2)
        first: dict[str, Any] = json.loads(records[0]["content"])
        self.assertEqual(
            list(first.keys()), ["lyrics", "b", "a"])
        self.assertEqual(first["lyrics"], "hello lyrics\n")
        self.assertEqual(first["b"], 2)
        self.assertEqual(first["a"], 1)
        second: dict[str, Any] = json.loads(records[1]["content"])
        self.assertEqual(
            list(second.keys()), ["lyrics", "disagreements"])
        self.assertEqual(second["lyrics"], "umbrella lyrics\n")
        self.assertEqual(
            second["disagreements"], {"k": ["q"]})

    def test_extras_per_id_restricts_the_export(self) -> None:
        """Test that the songs the per-ID extras do not name are
        not exported."""
        self.__seed([
            ("Hello", "Adele", "hello lyrics\n"),
            ("Umbrella", "Rihanna", "umbrella lyrics\n"),
            ("Halo", "Beyonce", "halo lyrics\n")])
        per_id: Path = self.__write_extras_per_id(
            '{"song-3": {"a": 1}, "song-1": {"a": 2}}')
        status: int
        stderr: str
        status, stderr = self.__run_export(None, per_id)
        self.assertEqual(status, 0)
        records: list[dict[str, str]] = self.__read_records(
            self.__output)
        self.assertEqual(
            [x["id"] for x in records], ["song-1", "song-3"])
        self.assertIn("Done.  2 songs exported.", stderr)

    def test_extras_per_id_unknown_id_fails(self) -> None:
        """Test that a per-ID extras file naming a song the
        working store does not have is rejected."""
        self.__seed([("Hello", "Adele", "hello lyrics\n")])
        per_id: Path = self.__write_extras_per_id(
            '{"song-1": {"a": 1}, "song-9": {"a": 2}}')
        status: int
        stderr: str
        status, stderr = self.__run_export(None, per_id)
        self.assertEqual(status, 1)
        self.assertIn("song-9", stderr)
        self.assertFalse(self.__output.exists())

    def test_extras_per_id_after_the_shared_extras(self) -> None:
        """Test that with both extras options, a record's keys are
        the lyrics, the shared extras, then that song's own."""
        self.__seed([
            ("Hello", "Adele", "hello lyrics\n"),
            ("Umbrella", "Rihanna", "umbrella lyrics\n")])
        extras: Path = self.__write_extras('{"shared": "s"}')
        per_id: Path = self.__write_extras_per_id(
            '{"song-2": {"own": "o"}}')
        status: int
        stderr: str
        status, stderr = self.__run_export(extras, per_id)
        self.assertEqual(status, 0)
        records: list[dict[str, str]] = self.__read_records(
            self.__output)
        self.assertEqual([x["id"] for x in records], ["song-2"])
        content: dict[str, Any] = json.loads(
            records[0]["content"])
        self.assertEqual(
            list(content.keys()), ["lyrics", "shared", "own"])
        self.assertEqual(content["lyrics"], "umbrella lyrics\n")
        self.assertEqual(content["shared"], "s")
        self.assertEqual(content["own"], "o")

    def test_extras_per_id_non_object_value_fails(self) -> None:
        """Test that a per-ID extras file whose song does not have
        a JSON object is rejected."""
        self.__seed([("Hello", "Adele", "hello lyrics\n")])
        per_id: Path = self.__write_extras_per_id(
            '{"song-1": [1, 2]}')
        status: int
        stderr: str
        status, stderr = self.__run_export(None, per_id)
        self.assertEqual(status, 1)
        self.assertIn("error:", stderr)
        self.assertFalse(self.__output.exists())

    def test_extras_per_id_with_lyrics_key_fails(self) -> None:
        """Test that a per-ID extras file whose song carries a
        "lyrics" key is rejected."""
        self.__seed([("Hello", "Adele", "hello lyrics\n")])
        per_id: Path = self.__write_extras_per_id(
            '{"song-1": {"lyrics": "not allowed"}}')
        status: int
        stderr: str
        status, stderr = self.__run_export(None, per_id)
        self.assertEqual(status, 1)
        self.assertIn("error:", stderr)
        self.assertFalse(self.__output.exists())
