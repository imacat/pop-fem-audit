# Tools for A Feminist Audit of Pop Music.
# Copyright 2026 imacat.  All rights reserved.
# Authors:
#   imacat@mail.imacat.idv.tw (imacat), 2026/7/31
"""Unit tests for the artist metadata fetcher module."""
import csv
import io
import json
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stderr
from pathlib import Path
from typing import Any
from unittest import mock

from sqlalchemy.orm import Session

from pop_fem_audit_tools import config
from pop_fem_audit_tools.commands import fetch_artists
from pop_fem_audit_tools.database import Base, DataSource
from pop_fem_audit_tools.models import Artist, Role, Song, SongArtist


class TestFetchArtists(unittest.TestCase):
    """Test cases for the artist metadata fetcher."""

    HEADER: list[str] = [
        "name", "qid", "gender", "type", "genre",
        "country", "note"]
    """The expected header row of the snapshot CSV file."""

    def setUp(self) -> None:
        """Create a temporary capture directory with the store."""
        tmp: tempfile.TemporaryDirectory[str] \
            = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.__dir: Path = Path(tmp.name)
        self.__snapshot: Path = \
            self.__dir / "artists_wikidata.csv"
        config.set_settings(config.Settings(
            SQLALCHEMY_DATABASE_URL="sqlite://",
            ANTHROPIC_API_KEY="test-key"))
        self.__ds: DataSource = DataSource()
        self.addCleanup(self.__ds.engine.dispose)
        patchers: list[Any] = [
            mock.patch.object(fetch_artists, "ds", self.__ds),
            mock.patch.object(fetch_artists, "SLEEP_SECONDS",
                              0.0),
            mock.patch.object(fetch_artists, "RETRY_SECONDS",
                              0.0)]
        for patcher in patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

    def __seed(self, names: list[str]) -> dict[str, int]:
        """Create the schema and the fixture artists.

        :param names: The artist names.
        :return: The created artist IDs, keyed by the name.
        """
        Base.metadata.create_all(self.__ds.engine)
        session: Session = self.__ds.get_db()
        ids: dict[str, int] = {}
        try:
            name: str
            for name in names:
                artist: Artist = Artist(name=name)
                session.add(artist)
                session.flush()
                ids[name] = artist.id
            session.commit()
        finally:
            session.close()
        return ids

    def __seed_song(self, artist_id: int, title: str) -> None:
        """Add a charted song credited to an artist.

        :param artist_id: The artist ID.
        :param title: The song title.
        :return: None.
        """
        session: Session = self.__ds.get_db()
        try:
            song: Song = Song(title=title, artist_credit=title)
            session.add(song)
            session.flush()
            session.add(SongArtist(
                song_id=song.id, artist_id=artist_id,
                role=Role.PRIMARY.value, position=0))
            session.commit()
        finally:
            session.close()

    @staticmethod
    def __response(payload: dict[str, Any]) -> mock.MagicMock:
        """Build a fake HTTP response with a JSON body.

        :param payload: The JSON payload of the response body.
        :return: The fake response, usable as a context manager.
        """
        response: mock.MagicMock = mock.MagicMock()
        response.__enter__.return_value = response
        response.read.return_value \
            = json.dumps(payload).encode("utf-8")
        return response

    @staticmethod
    def __http_error(status: int) -> urllib.error.HTTPError:
        """Build an HTTP error.

        :param status: The HTTP status code.
        :return: The HTTP error.
        """
        return urllib.error.HTTPError(
            "https://example.com/", status, "Error", None, None)

    @staticmethod
    def __claim(qid: str) -> dict[str, Any]:
        """Build a claim statement with an item-ID target.

        :param qid: The item ID of the statement target.
        :return: The claim statement.
        """
        return {"mainsnak": {"snaktype": "value",
                             "datavalue": {"value": {"id": qid}}}}

    @staticmethod
    def __labels(labels: dict[str, str]) -> dict[str, Any]:
        """Build a label query response payload.

        :param labels: The English labels, keyed by the item ID.
        :return: The response payload.
        """
        return {"entities": {
            x: {"labels": {"en": {"value": y}}}
            for x, y in labels.items()}}

    @staticmethod
    def __claims(qid: str, claims: dict[str, Any],
                 description: str) -> dict[str, Any]:
        """Build a claims-and-description response payload.

        :param qid: The item ID.
        :param claims: The claim statements, keyed by the
            property.
        :param description: The English description.
        :return: The response payload.
        """
        return {"entities": {qid: {
            "claims": claims,
            "descriptions": {"en": {"value": description}}}}}

    @staticmethod
    def __sparql(rows: list[dict[str, dict[str, str]]]) \
            -> dict[str, Any]:
        """Build a SPARQL query response payload.

        :param rows: The result bindings.
        :return: The response payload.
        """
        return {"results": {"bindings": rows}}

    @staticmethod
    def __uri(qid: str) -> dict[str, str]:
        """Build a SPARQL URI binding cell for an item ID.

        :param qid: The item ID.
        :return: The binding cell.
        """
        return {"type": "uri",
                "value": f"http://www.wikidata.org/entity/{qid}"}

    @staticmethod
    def __literal(value: str) -> dict[str, str]:
        """Build a SPARQL literal binding cell.

        :param value: The literal value.
        :return: The binding cell.
        """
        return {"type": "literal", "value": value}

    def __run_fetch(self) -> tuple[int, str]:
        """Run the fetcher with the standard error captured.

        :return: A tuple of the exit status and the standard
            error.
        """
        stderr: io.StringIO = io.StringIO()
        with redirect_stderr(stderr):
            status: int = fetch_artists.main(
                [str(self.__snapshot)])
        return status, stderr.getvalue()

    @staticmethod
    def __read_rows(path: Path) -> list[list[str]]:
        """Read the rows of a CSV file.

        :param path: The CSV file.
        :return: The rows, the header included.
        """
        with open(path, encoding="utf-8", newline="") as file:
            return list(csv.reader(file))

    def __assert_summary(self, stderr: str, resolved: int,
                         attempted: int) -> None:
        """Assert the closing summary line has the expected shape.

        :param stderr: The captured standard error.
        :param resolved: The expected count of resolved artists.
        :param attempted: The expected count of attempted
            artists.
        :return: None.
        """
        self.assertRegex(
            stderr,
            rf"Done\.  Resolved {resolved}/{attempted} artists\."
            r"  \d{2}:\d{2} elapsed\.")

    def test_unique_candidate_selected(self) -> None:
        """Test a single candidate resolving the full metadata."""
        self.__seed(["Adele"])
        candidates: dict[str, Any] = self.__sparql(
            [{"item": self.__uri("Q1")}])
        claims: dict[str, Any] = self.__claims(
            "Q1", {
                "P21": [self.__claim("Q2")],
                "P31": [self.__claim("Q5")],
                "P136": [self.__claim("Q3"), self.__claim("Q4")],
                "P27": [self.__claim("Q6")]},
            "English singer")
        labels: dict[str, Any] = self.__labels({
            "Q2": "female", "Q5": "human", "Q3": "pop",
            "Q4": "soul music", "Q6": "United Kingdom"})
        urlopen: mock.Mock
        with mock.patch(
                "urllib.request.urlopen",
                side_effect=[self.__response(candidates),
                             self.__response(claims),
                             self.__response(labels)]) as urlopen:
            status: int
            stderr: str
            status, stderr = self.__run_fetch()
        self.assertEqual(status, 0)
        self.assertEqual(urlopen.call_count, 3)
        first: Any = urlopen.call_args_list[0][0][0]
        self.assertEqual(first.get_header("User-agent"),
                         fetch_artists.USER_AGENT)
        self.assertTrue(
            first.full_url.startswith(fetch_artists.SPARQL_URL))
        self.assertEqual(
            first.get_header("Accept"),
            "application/sparql-results+json")
        rows: list[list[str]] = self.__read_rows(
            self.__snapshot)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0], self.HEADER)
        self.assertEqual(rows[1], [
            "Adele", "Q1", "female", "solo", "pop; soul music",
            "United Kingdom", "English singer"])
        self.__assert_summary(stderr, 1, 1)

    def test_full_run_sorted_by_name(self) -> None:
        """Test that a full run writes rows sorted by artist
        name, not by the artist ID order."""
        self.__seed(["Zed", "Amy", "Mia"])
        empty: dict[str, Any] = self.__sparql([])
        urlopen: mock.Mock
        with mock.patch(
                "urllib.request.urlopen",
                side_effect=[self.__response(empty),
                             self.__response(empty),
                             self.__response(empty)]) as urlopen:
            status: int = self.__run_fetch()[0]
        self.assertEqual(status, 0)
        self.assertEqual(urlopen.call_count, 3)
        rows: list[list[str]] = self.__read_rows(
            self.__snapshot)
        self.assertEqual(
            [x[0] for x in rows[1:]], ["Amy", "Mia", "Zed"])

    def test_pinned_qid_skips_search(self) -> None:
        """Test that a pinned name short-circuits the search."""
        self.__seed(["Pinkfong"])
        qid: str = fetch_artists.PINNED_QIDS["Pinkfong"]
        claims: dict[str, Any] = self.__claims(
            qid, {}, "South Korean children's brand")
        urlopen: mock.Mock
        with mock.patch(
                "urllib.request.urlopen",
                side_effect=[self.__response(claims)]) as urlopen:
            status: int = self.__run_fetch()[0]
        self.assertEqual(status, 0)
        self.assertEqual(urlopen.call_count, 1)
        first: Any = urlopen.call_args_list[0][0][0]
        self.assertTrue(first.full_url.startswith(
            fetch_artists.API_URL))
        rows: list[list[str]] = self.__read_rows(
            self.__snapshot)
        self.assertEqual(rows[1], [
            "Pinkfong", qid, "", "", "",
            "", "South Korean children's brand"])

    def test_stage1_performer_intersection(self) -> None:
        """Test the multi-candidate resolution via a performer."""
        ids: dict[str, int] = self.__seed(["Boyz"])
        self.__seed_song(ids["Boyz"], "Song A")
        self.__seed_song(ids["Boyz"], "Song B")
        candidates: dict[str, Any] = self.__sparql([
            {"item": self.__uri("Q1")},
            {"item": self.__uri("Q2")}])
        stage1: dict[str, Any] = self.__sparql(
            [{"performer": self.__uri("Q2")}])
        claims: dict[str, Any] = self.__claims(
            "Q2", {}, "A boy band")
        urlopen: mock.Mock
        with mock.patch(
                "urllib.request.urlopen",
                side_effect=[self.__response(candidates),
                             self.__response(stage1),
                             self.__response(claims)]) as urlopen:
            status: int = self.__run_fetch()[0]
        self.assertEqual(status, 0)
        self.assertEqual(urlopen.call_count, 3)
        rows: list[list[str]] = self.__read_rows(
            self.__snapshot)
        self.assertEqual(rows[1], [
            "Boyz", "Q2", "", "", "", "", "A boy band"])

    def test_stage1_member_hop(self) -> None:
        """Test the multi-candidate resolution via a member."""
        ids: dict[str, int] = self.__seed(["Trio"])
        self.__seed_song(ids["Trio"], "Track")
        candidates: dict[str, Any] = self.__sparql([
            {"item": self.__uri("Q1")},
            {"item": self.__uri("Q2")}])
        stage1: dict[str, Any] = self.__sparql([{
            "performer": self.__uri("Q9"),
            "member": self.__uri("Q2")}])
        claims: dict[str, Any] = self.__claims(
            "Q2", {}, "A member of a group")
        urlopen: mock.Mock
        with mock.patch(
                "urllib.request.urlopen",
                side_effect=[self.__response(candidates),
                             self.__response(stage1),
                             self.__response(claims)]) as urlopen:
            status: int = self.__run_fetch()[0]
        self.assertEqual(status, 0)
        self.assertEqual(urlopen.call_count, 3)
        rows: list[list[str]] = self.__read_rows(
            self.__snapshot)
        self.assertEqual(rows[1], [
            "Trio", "Q2", "", "", "", "", "A member of a group"])

    def test_stage2_casefold_rescue(self) -> None:
        """Test the case-insensitive stage-2 rescue."""
        ids: dict[str, int] = self.__seed(["Case"])
        self.__seed_song(ids["Case"], "Song One")
        candidates: dict[str, Any] = self.__sparql([
            {"item": self.__uri("Q1")},
            {"item": self.__uri("Q2")}])
        stage1: dict[str, Any] = self.__sparql([])
        stage2: dict[str, Any] = self.__sparql([{
            "cand": self.__uri("Q2"),
            "label": self.__literal("song one")}])
        claims: dict[str, Any] = self.__claims(
            "Q2", {}, "Rescued by casefold")
        urlopen: mock.Mock
        with mock.patch(
                "urllib.request.urlopen",
                side_effect=[self.__response(candidates),
                             self.__response(stage1),
                             self.__response(stage2),
                             self.__response(claims)]) as urlopen:
            status: int = self.__run_fetch()[0]
        self.assertEqual(status, 0)
        self.assertEqual(urlopen.call_count, 4)
        rows: list[list[str]] = self.__read_rows(
            self.__snapshot)
        self.assertEqual(rows[1], [
            "Case", "Q2", "", "", "", "", "Rescued by casefold"])

    def test_unresolved_continues_to_next_artist(self) -> None:
        """Test that an unresolved artist does not stop the run."""
        self.__seed(["Ambiguous", "Nobody"])
        candidates_ambiguous: dict[str, Any] = self.__sparql([
            {"item": self.__uri("Q1")},
            {"item": self.__uri("Q2")}])
        stage2_empty: dict[str, Any] = self.__sparql([])
        candidates_nobody: dict[str, Any] = self.__sparql([])
        urlopen: mock.Mock
        with mock.patch(
                "urllib.request.urlopen",
                side_effect=[self.__response(candidates_ambiguous),
                             self.__response(stage2_empty),
                             self.__response(candidates_nobody)]
                ) as urlopen:
            status: int
            stderr: str
            status, stderr = self.__run_fetch()
        self.assertEqual(status, 0)
        self.assertEqual(urlopen.call_count, 3)
        rows: list[list[str]] = self.__read_rows(
            self.__snapshot)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[1], [
            "Ambiguous", "", "", "", "", "", "not found"])
        self.assertEqual(rows[2], [
            "Nobody", "", "", "", "", "", "not found"])
        self.__assert_summary(stderr, 0, 2)

    def test_retry_429_then_success(self) -> None:
        """Test a 429 retry followed by a successful request."""
        self.__seed(["Retry"])
        candidates: dict[str, Any] = self.__sparql([])
        urlopen: mock.Mock
        with mock.patch(
                "urllib.request.urlopen",
                side_effect=[self.__http_error(429),
                             self.__response(candidates)]
                ) as urlopen:
            status: int
            stderr: str
            status, stderr = self.__run_fetch()
        self.assertEqual(status, 0)
        self.assertEqual(urlopen.call_count, 2)
        rows: list[list[str]] = self.__read_rows(
            self.__snapshot)
        self.assertEqual(rows[1], [
            "Retry", "", "", "", "", "", "not found"])
        self.__assert_summary(stderr, 0, 1)

    def test_timeout_then_success(self) -> None:
        """Test a read timeout retried into a successful request."""
        self.__seed(["SlowQuery"])
        candidates: dict[str, Any] = self.__sparql([])
        urlopen: mock.Mock
        with mock.patch(
                "urllib.request.urlopen",
                side_effect=[TimeoutError("timed out"),
                             self.__response(candidates)]
                ) as urlopen:
            status: int
            stderr: str
            status, stderr = self.__run_fetch()
        self.assertEqual(status, 0)
        self.assertEqual(urlopen.call_count, 2)
        rows: list[list[str]] = self.__read_rows(
            self.__snapshot)
        self.assertEqual(rows[1], [
            "SlowQuery", "", "", "", "", "", "not found"])
        self.__assert_summary(stderr, 0, 1)

    def test_retry_exhausted_is_error(self) -> None:
        """Test that exhausted retries yield an error row."""
        self.__seed(["Exhausted"])
        urlopen: mock.Mock
        with mock.patch(
                "urllib.request.urlopen",
                side_effect=[self.__http_error(503)] * 5) as urlopen:
            status: int
            stderr: str
            status, stderr = self.__run_fetch()
        self.assertEqual(status, 0)
        self.assertEqual(urlopen.call_count, 5)
        rows: list[list[str]] = self.__read_rows(
            self.__snapshot)
        self.assertEqual(rows[1][:2], ["Exhausted", ""])
        self.assertTrue(rows[1][6].startswith(
            "error: retries exhausted"))
        self.__assert_summary(stderr, 0, 1)

    def test_non_retryable_error_continues(self) -> None:
        """Test that a non-retryable HTTP error is noted as an
        error and does not stop the run."""
        self.__seed(["Broken", "Nobody"])
        urlopen: mock.Mock
        with mock.patch(
                "urllib.request.urlopen",
                side_effect=[self.__http_error(404),
                             self.__response(self.__sparql([]))]
                ) as urlopen:
            status: int
            stderr: str
            status, stderr = self.__run_fetch()
        self.assertEqual(status, 0)
        self.assertEqual(urlopen.call_count, 2)
        rows: list[list[str]] = self.__read_rows(
            self.__snapshot)
        self.assertEqual(rows[1][:2], ["Broken", ""])
        self.assertTrue(rows[1][6].startswith("error: "))
        self.assertEqual(rows[2], [
            "Nobody", "", "", "", "", "", "not found"])
        self.__assert_summary(stderr, 0, 2)

    def test_rerun_skips_existing(self) -> None:
        """Test that the snapshot rows are skipped and preserved."""
        self.__seed(["Adele", "Nobody"])
        snapshot: Path = self.__snapshot
        old_row: list[str] = [
            "Adele", "Q1", "female", "solo", "pop",
            "United Kingdom", "English singer"]
        with open(snapshot, "w", encoding="utf-8",
                  newline="") as file:
            writer: Any = csv.writer(file)
            writer.writerow(self.HEADER)
            writer.writerow(old_row)
        urlopen: mock.Mock
        with mock.patch(
                "urllib.request.urlopen",
                side_effect=[self.__response(self.__sparql([]))]
                ) as urlopen:
            status: int
            stderr: str
            status, stderr = self.__run_fetch()
        self.assertEqual(status, 0)
        self.assertEqual(urlopen.call_count, 1)
        rows: list[list[str]] = self.__read_rows(snapshot)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0], self.HEADER)
        self.assertNotIn(self.HEADER, rows[1:])
        self.assertEqual(rows[1], old_row)
        self.assertEqual(rows[2], [
            "Nobody", "", "", "", "", "", "not found"])
        self.__assert_summary(stderr, 0, 1)

    def test_topup_inserts_sorted_position(self) -> None:
        """Test that a top-up inserts the new row in its sorted
        position, not appended at the end of the file."""
        self.__seed(["Amy", "Mia", "Zed"])
        snapshot: Path = self.__snapshot
        amy_row: list[str] = [
            "Amy", "Q1", "", "", "", "", "not found"]
        zed_row: list[str] = [
            "Zed", "Q2", "", "", "", "", "not found"]
        with open(snapshot, "w", encoding="utf-8",
                  newline="") as file:
            writer: Any = csv.writer(file)
            writer.writerow(self.HEADER)
            writer.writerow(amy_row)
            writer.writerow(zed_row)
        empty: dict[str, Any] = self.__sparql([])
        urlopen: mock.Mock
        with mock.patch(
                "urllib.request.urlopen",
                side_effect=[self.__response(empty)]) as urlopen:
            status: int = self.__run_fetch()[0]
        self.assertEqual(status, 0)
        self.assertEqual(urlopen.call_count, 1)
        rows: list[list[str]] = self.__read_rows(snapshot)
        self.assertEqual(
            [x[0] for x in rows[1:]], ["Amy", "Mia", "Zed"])
        self.assertEqual(rows[1], amy_row)
        self.assertEqual(rows[3], zed_row)

    def test_crash_mid_run_leaves_partial_rows(self) -> None:
        """Test that a crash mid-run leaves the already-fetched
        rows on disk for a later top-up run to resume from."""
        self.__seed(["Alpha", "Zulu"])
        empty: dict[str, Any] = self.__sparql([])
        urlopen: mock.Mock
        with (mock.patch(
                "urllib.request.urlopen",
                side_effect=[self.__response(empty)]) as urlopen,
              mock.patch.object(
                  fetch_artists, "read_artist_titles",
                  side_effect=[[], OSError("boom")])):
            status: int = self.__run_fetch()[0]
        self.assertNotEqual(status, 0)
        self.assertEqual(urlopen.call_count, 1)
        rows: list[list[str]] = self.__read_rows(
            self.__snapshot)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0], self.HEADER)
        self.assertEqual(rows[1], [
            "Alpha", "", "", "", "", "", "not found"])

    def test_no_store_fails(self) -> None:
        """Test that a missing working store fails the run."""
        urlopen: mock.Mock
        with mock.patch("urllib.request.urlopen") as urlopen:
            status: int
            stderr: str
            status, stderr = self.__run_fetch()
        self.assertNotEqual(status, 0)
        urlopen.assert_not_called()
        self.assertIn("error:", stderr)

    def test_summary_line_exact_shape(self) -> None:
        """Test the exact wording and timing of the summary
        line."""
        self.__seed(["Adele"])
        candidates: dict[str, Any] = self.__sparql([])
        with (mock.patch(
                "urllib.request.urlopen",
                side_effect=[self.__response(candidates)]),
              mock.patch(
                  "time.monotonic",
                  side_effect=[1000.0, 1125.0])):
            stderr: str = self.__run_fetch()[1]
        self.assertIn(
            "Done.  Resolved 0/1 artists.  02:05 elapsed.",
            stderr)
