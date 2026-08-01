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

from pop_fem_audit_tools import config, fetch_artists
from pop_fem_audit_tools.database import Base, DataSource
from pop_fem_audit_tools.models import Artist


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
        url: str = f"sqlite:///{self.__dir}/store.sqlite3"
        config.set_settings(config.Settings(
            SQLALCHEMY_DATABASE_URL=url,
            ANTHROPIC_API_KEY="test-key"))
        self.__ds: DataSource = DataSource()
        patchers: list[Any] = [
            mock.patch.object(fetch_artists, "ds", self.__ds),
            mock.patch.object(fetch_artists, "SLEEP_SECONDS",
                              0.0)]
        for patcher in patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

    def __seed(self, names: list[str]) -> None:
        """Create the schema and the fixture artists.

        The artist IDs are assigned in list order starting from
        1.

        :param names: The artist names.
        :return: None.
        """
        Base.metadata.create_all(self.__ds.engine)
        session: Session = self.__ds.get_db()
        try:
            name: str
            for name in names:
                session.add(Artist(name=name))
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
    def __server_error() -> urllib.error.HTTPError:
        """Build an HTTP 500 error.

        :return: The HTTP 500 error.
        """
        return urllib.error.HTTPError(
            "https://example.com/", 500,
            "Internal Server Error", None, None)

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

    def test_human_artist(self) -> None:
        """Test a human artist resolving the full metadata."""
        self.__seed(["Adele"])
        search: dict[str, Any] = {"search": [
            {"id": "Q1", "description": "English singer"}]}
        claims: dict[str, Any] = {"entities": {"Q1": {"claims": {
            "P21": [self.__claim("Q2")],
            "P31": [self.__claim("Q5")],
            "P136": [self.__claim("Q3"), self.__claim("Q4")],
            "P27": [self.__claim("Q6")]}}}}
        labels: dict[str, Any] = self.__labels({
            "Q2": "female", "Q5": "human", "Q3": "pop",
            "Q4": "soul music", "Q6": "United Kingdom"})
        urlopen: mock.Mock
        with mock.patch(
                "urllib.request.urlopen",
                side_effect=[self.__response(search),
                             self.__response(claims),
                             self.__response(labels)]) as urlopen:
            status: int
            stderr: str
            status, stderr = self.__run_fetch()
        self.assertEqual(status, 0)
        self.assertEqual(urlopen.call_count, 3)
        request: Any = urlopen.call_args_list[0][0][0]
        self.assertEqual(request.get_header("User-agent"),
                         fetch_artists.USER_AGENT)
        urls: list[str] = [x[0][0].full_url
                           for x in urlopen.call_args_list]
        self.assertEqual(
            urls[0],
            "https://www.wikidata.org/w/api.php"
            "?action=wbsearchentities&search=Adele&language=en"
            "&type=item&format=json")
        self.assertEqual(
            urls[1],
            "https://www.wikidata.org/w/api.php"
            "?action=wbgetentities&ids=Q1&props=claims"
            "&format=json")
        self.assertEqual(
            urls[2],
            "https://www.wikidata.org/w/api.php"
            "?action=wbgetentities&ids=Q2%7CQ5%7CQ3%7CQ4%7CQ6"
            "&props=labels&languages=en&format=json")
        rows: list[list[str]] = self.__read_rows(
            self.__snapshot)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0], self.HEADER)
        self.assertEqual(rows[1], [
            "Adele", "Q1", "female", "solo", "pop; soul music",
            "United Kingdom", "English singer"])
        self.assertIn(
            "1 fetched, 0 not found, 0 errors, 0 skipped",
            stderr)

    def test_band(self) -> None:
        """Test a band resolving the group type and the origin."""
        self.__seed(["BTS"])
        search: dict[str, Any] = {"search": [
            {"id": "Q10",
             "description": "South Korean boy band"}]}
        claims: dict[str, Any] = {"entities": {"Q10": {"claims": {
            "P31": [self.__claim("Q11")],
            "P136": [self.__claim("Q12")],
            "P495": [self.__claim("Q13")]}}}}
        labels: dict[str, Any] = self.__labels({
            "Q11": "boy band", "Q12": "K-pop",
            "Q13": "South Korea"})
        with mock.patch(
                "urllib.request.urlopen",
                side_effect=[self.__response(search),
                             self.__response(claims),
                             self.__response(labels)]):
            status: int = self.__run_fetch()[0]
        self.assertEqual(status, 0)
        rows: list[list[str]] = self.__read_rows(
            self.__snapshot)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1], [
            "BTS", "Q10", "", "group", "K-pop", "South Korea",
            "South Korean boy band"])

    def test_not_found(self) -> None:
        """Test that a search miss writes a not-found row."""
        self.__seed(["Nobody"])
        urlopen: mock.Mock
        with mock.patch(
                "urllib.request.urlopen",
                side_effect=[self.__response({"search": []})]
                ) as urlopen:
            status: int
            stderr: str
            status, stderr = self.__run_fetch()
        self.assertEqual(status, 0)
        self.assertEqual(urlopen.call_count, 1)
        rows: list[list[str]] = self.__read_rows(
            self.__snapshot)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0], self.HEADER)
        self.assertEqual(rows[1], [
            "Nobody", "", "", "", "", "", "not found"])
        self.assertIn(
            "0 fetched, 1 not found, 0 errors, 0 skipped",
            stderr)

    def test_http_error_continues(self) -> None:
        """Test that an HTTP error is noted and the run goes on."""
        self.__seed(["Broken", "Nobody"])
        with mock.patch(
                "urllib.request.urlopen",
                side_effect=[self.__server_error(),
                             self.__response({"search": []})]):
            status: int
            stderr: str
            status, stderr = self.__run_fetch()
        self.assertEqual(status, 0)
        rows: list[list[str]] = self.__read_rows(
            self.__snapshot)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[1][:2], ["Broken", ""])
        self.assertTrue(rows[1][6].startswith("error: "))
        self.assertEqual(rows[2], [
            "Nobody", "", "", "", "", "", "not found"])
        self.assertIn(
            "0 fetched, 1 not found, 1 errors, 0 skipped",
            stderr)

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
                side_effect=[self.__response({"search": []})]
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
        self.assertIn(
            "0 fetched, 1 not found, 0 errors, 1 skipped",
            stderr)

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
