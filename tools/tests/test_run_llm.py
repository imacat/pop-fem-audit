# Tools for A Feminist Audit of Pop Music.
# Copyright 2026 imacat.  All rights reserved.
# Authors:
#   imacat@mail.imacat.idv.tw (imacat), 2026/7/30
# AI assistance: Claude Code (Anthropic)
"""Unit tests for the run_llm batch executor module."""
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest import mock

from pop_fem_audit_tools import config
from pop_fem_audit_tools.commands import run_llm


class RunLLMTestCase(unittest.TestCase):
    """The common base test case with the shared helpers."""

    def _make_temp_dir(self) -> Path:
        """Create a temporary directory removed on test cleanup.

        :return: The path of the temporary directory.
        """
        tmp: tempfile.TemporaryDirectory[str] \
            = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Path(tmp.name)

    def _make_success_entry(self, custom_id: str,
                            text: str) -> mock.Mock:
        """Create a mock succeeded batch result entry.

        :param custom_id: The custom ID of the entry.
        :param text: The output text.
        :return: The mock result entry.
        """
        entry: mock.Mock = mock.Mock()
        entry.custom_id = custom_id
        entry.result = mock.Mock()
        entry.result.type = "succeeded"
        entry.result.message = self.__make_message(text)
        return entry

    @staticmethod
    def _make_error_entry(custom_id: str,
                          error_type: str) -> mock.Mock:
        """Create a mock errored batch result entry.

        The error object is shaped as the SDK envelope: the outer
        error carries the constant type ``error``, and the specific
        error code lives at ``error.error.type``.

        :param custom_id: The custom ID of the entry.
        :param error_type: The specific error code.
        :return: The mock result entry.
        """
        entry: mock.Mock = mock.Mock()
        entry.custom_id = custom_id
        entry.result = mock.Mock()
        entry.result.type = "errored"
        entry.result.error = mock.Mock()
        entry.result.error.type = "error"
        entry.result.error.error = mock.Mock()
        entry.result.error.error.type = error_type
        return entry

    @staticmethod
    def __make_message(text: str) -> mock.Mock:
        """Create a mock message with a single text block.

        :param text: The text of the text block.
        :return: The mock message.
        """
        block: mock.Mock = mock.Mock()
        block.type = "text"
        block.text = text
        usage: mock.Mock = mock.Mock()
        usage.model_dump.return_value = {
            "input_tokens": 10, "output_tokens": 5, "extra": None}
        message: mock.Mock = mock.Mock()
        message.content = [block]
        message.stop_reason = "end_turn"
        message.usage = usage
        return message


class TestLoadItems(RunLLMTestCase):
    """Test cases for the input JSONL validation."""

    def setUp(self) -> None:
        """Create a temporary directory for the input files."""
        self.__dir: Path = self._make_temp_dir()

    def __write_input(self, content: str) -> Path:
        """Write an input file with the given content.

        :param content: The file content.
        :return: The path of the input file.
        """
        path: Path = self.__dir / "items.jsonl"
        path.write_text(content, encoding="utf-8")
        return path

    def test_valid_items(self) -> None:
        """Test that valid items are loaded in file order."""
        path: Path = self.__write_input(
            '{"id": "a", "content": "one"}\n'
            '{"id": "b", "content": "two"}\n')
        items: list[run_llm.InputItem] = run_llm.load_items(path)
        self.assertEqual(items, [
            run_llm.InputItem(id="a", content="one"),
            run_llm.InputItem(id="b", content="two")])

    def test_malformed_json_names_line(self) -> None:
        """Test that malformed JSON reports the line number."""
        path: Path = self.__write_input(
            '{"id": "a", "content": "one"}\n'
            'not json\n')
        with self.assertRaises(run_llm.InputFormatError) as context:
            run_llm.load_items(path)
        self.assertIn("line 2", str(context.exception))

    def test_missing_key_names_line(self) -> None:
        """Test that a missing key reports the line number."""
        path: Path = self.__write_input('{"id": "a"}\n')
        with self.assertRaises(run_llm.InputFormatError) as context:
            run_llm.load_items(path)
        self.assertIn("line 1", str(context.exception))

    def test_extra_key_rejected(self) -> None:
        """Test that an extra key is rejected."""
        path: Path = self.__write_input(
            '{"id": "a", "content": "one", "extra": 1}\n')
        with self.assertRaises(run_llm.InputFormatError):
            run_llm.load_items(path)

    def test_non_string_content_rejected(self) -> None:
        """Test that a non-string content is rejected."""
        path: Path = self.__write_input('{"id": "a", "content": 3}\n')
        with self.assertRaises(run_llm.InputFormatError):
            run_llm.load_items(path)

    def test_duplicated_id_names_line(self) -> None:
        """Test that a duplicated ID reports the line number."""
        path: Path = self.__write_input(
            '{"id": "a", "content": "one"}\n'
            '{"id": "a", "content": "two"}\n')
        with self.assertRaises(run_llm.InputFormatError) as context:
            run_llm.load_items(path)
        self.assertIn("line 2", str(context.exception))
        self.assertIn("a", str(context.exception))

    def test_empty_file_rejected(self) -> None:
        """Test that an empty input file is rejected."""
        path: Path = self.__write_input("")
        with self.assertRaises(run_llm.InputFormatError):
            run_llm.load_items(path)


class TestRequestBuilding(RunLLMTestCase):
    """Test cases for the request construction."""

    def test_build_request(self) -> None:
        """Test the shape of a batch request."""
        request: dict[str, Any] = run_llm.build_request(
            run_llm.InputItem(id="song-1", content="the lyrics"),
            "the system prompt", 2048)
        self.assertEqual(request["custom_id"], "song-1")
        params: dict[str, Any] = request["params"]
        self.assertEqual(params["model"], "claude-sonnet-4-6")
        self.assertEqual(params["temperature"], 0.0)
        self.assertEqual(params["thinking"], {"type": "disabled"})
        self.assertEqual(params["max_tokens"], 2048)
        self.assertEqual(params["system"], "the system prompt")
        self.assertEqual(params["messages"],
                         [{"role": "user", "content": "the lyrics"}])


class TestCollectResults(RunLLMTestCase):
    """Test cases for the batch result collection."""

    def test_collect_success_and_error(self) -> None:
        """Test collecting succeeded and errored results."""
        client: mock.Mock = mock.Mock()
        client.messages.batches.results.return_value = iter([
            self._make_success_entry("a", "output a"),
            self._make_error_entry("b", "invalid_request_error")])
        results: run_llm.Results = run_llm.collect_results(
            client, "batch_x")
        self.assertEqual(results["a"].text, "output a")
        self.assertEqual(results["a"].stop_reason, "end_turn")
        self.assertEqual(results["a"].usage,
                         {"input_tokens": 10, "output_tokens": 5})
        self.assertEqual(results["b"], run_llm.BatchResult(
            id="b", error="invalid_request_error"))
        client.messages.batches.results.assert_called_once_with(
            "batch_x")

    def test_find_failures(self) -> None:
        """Test finding failed and missing items."""
        results: run_llm.Results = {
            "a": run_llm.BatchResult(id="a", text="fine"),
            "b": run_llm.BatchResult(id="b", error="errored")}
        self.assertEqual(
            run_llm.find_failures(["a", "b", "c"], results),
            ["b", "c"])

    def test_sum_usage(self) -> None:
        """Test summing the token usage across results."""
        results: run_llm.Results = {
            "a": run_llm.BatchResult(
                id="a", text="fine",
                usage={"input_tokens": 10, "output_tokens": 5}),
            "b": run_llm.BatchResult(
                id="b", text="fine",
                usage={"input_tokens": 3, "output_tokens": 2}),
            "c": run_llm.BatchResult(id="c", error="errored")}
        self.assertEqual(
            run_llm.sum_usage(results),
            {"input_tokens": 13, "output_tokens": 7})


class TestArchive(RunLLMTestCase):
    """Test cases for the archive directory handling."""

    def setUp(self) -> None:
        """Create a temporary directory as the runs root."""
        self.__dir: Path = self._make_temp_dir()

    def test_create_archive_dir(self) -> None:
        """Test the archive directory creation."""
        target: Path = self.__dir / "01-01-tag" / "run1"
        directory: Path = run_llm.create_archive_dir(target, False)
        self.assertTrue(directory.is_dir())
        self.assertEqual(directory, target)

    def test_existing_archive_dir_rejected_without_replace(
            self) -> None:
        """Test that an existing archive is rejected by default."""
        target: Path = self.__dir / "01-01-tag" / "run1"
        run_llm.create_archive_dir(target, False)
        with self.assertRaises(FileExistsError):
            run_llm.create_archive_dir(target, False)

    def test_existing_archive_dir_replaced(self) -> None:
        """Test that --replace replaces an existing archive."""
        target: Path = self.__dir / "01-01-tag" / "run1"
        first: Path = run_llm.create_archive_dir(target, False)
        (first / "stale.txt").write_text("stale", encoding="utf-8")
        second: Path = run_llm.create_archive_dir(target, True)
        self.assertEqual(first, second)
        self.assertFalse((second / "stale.txt").exists())

    def test_replace_leaves_sibling_dir_untouched(self) -> None:
        """Test that replacing run2 does not touch run1."""
        run1: Path = run_llm.create_archive_dir(
            self.__dir / "01-01-tag" / "run1", False)
        (run1 / "output.jsonl").write_text(
            "run1 data", encoding="utf-8")
        run2: Path = run_llm.create_archive_dir(
            self.__dir / "01-01-tag" / "run2", False)
        (run2 / "stale.jsonl").write_text("stale", encoding="utf-8")
        run_llm.create_archive_dir(
            self.__dir / "01-01-tag" / "run2", True)
        self.assertEqual(
            (run1 / "output.jsonl").read_text(encoding="utf-8"),
            "run1 data")

    def test_write_jsonl(self) -> None:
        """Test writing records as JSON Lines."""
        path: Path = self.__dir / "out.jsonl"
        run_llm.write_jsonl(path, [{"id": "a", "text": "中文"},
                                   {"id": "b", "text": "two"}])
        lines: list[str] = path.read_text(
            encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(json.loads(lines[0]),
                         {"id": "a", "text": "中文"})
        self.assertIn("中文", lines[0])


class TestMainFlow(RunLLMTestCase):
    """Test cases for the end-to-end main flow."""

    def setUp(self) -> None:
        """Create a temporary directory with the input files."""
        directory: Path = self._make_temp_dir()
        self.__runs: Path = directory / "runs"
        self.__archive_dir: Path = self.__runs / "task_v1" / "run1"
        self.__prompt: Path = directory / "task_v1.md"
        self.__prompt.write_text(
            "The task prompt.\n", encoding="utf-8")
        self.__input: Path = directory / "items.jsonl"
        self.__input.write_text(
            '{"id": "a", "content": "first item"}\n'
            '{"id": "b", "content": "second item"}\n',
            encoding="utf-8")
        self.__argv: list[str] = [
            str(self.__prompt), str(self.__input),
            str(self.__archive_dir)]
        self.__settings: config.Settings = config.Settings(
            SQLALCHEMY_DATABASE_URL="sqlite://",
            ANTHROPIC_API_KEY="test-key")
        config.set_settings(self.__settings)

    @staticmethod
    def __make_client(entries: list[Any]) -> mock.Mock:
        """Create a mock Anthropic client serving canned results.

        :param entries: The result entries of the single run batch.
        :return: The mock client.
        """
        client: mock.Mock = mock.Mock()
        client.messages.batches.create.return_value = mock.Mock(
            id="batch_run1")
        ended: mock.Mock = mock.Mock()
        ended.processing_status = "ended"
        ended.ended_at = datetime(2026, 7, 30, 20, 0)
        client.messages.batches.retrieve.return_value = ended
        client.messages.batches.results.return_value = iter(entries)
        return client

    @staticmethod
    def __run_main(argv: list[str],
                   client: mock.Mock | None = None) -> tuple[int, str]:
        """Run main() with a mocked client and captured output.

        :param argv: The command-line arguments.
        :param client: The mock client, or None for dry runs.
        :return: A tuple of the exit status and the standard output.
        """
        stdout: io.StringIO = io.StringIO()
        stderr: io.StringIO = io.StringIO()
        with mock.patch.object(run_llm.anthropic, "Anthropic",
                               return_value=client), \
                redirect_stdout(stdout), redirect_stderr(stderr):
            status: int = run_llm.main(argv)
        return status, stdout.getvalue()

    def test_dry_run(self) -> None:
        """Test the dry-run behavior."""
        status: int
        stdout: str
        status, stdout = self.__run_main(
            self.__argv + ["--dry-run"])
        self.assertEqual(status, 0)
        run_dir: Path = self.__archive_dir
        self.assertEqual((run_dir / "prompt.md").read_text(
            encoding="utf-8"), "The task prompt.\n")
        meta: dict[str, Any] = json.loads(
            (run_dir / "meta.json").read_text(encoding="utf-8"))
        self.assertTrue(meta["dry_run"])
        self.assertEqual(meta["item_count"], 2)
        self.assertEqual(meta["model"], "claude-sonnet-4-6")
        self.assertNotIn("run", meta)
        self.assertFalse((run_dir / "output.jsonl").exists())
        request: dict[str, Any] = json.loads(stdout)
        self.assertEqual(request["custom_id"], "a")
        self.assertEqual(request["params"]["system"],
                         "The task prompt.\n")

    def test_run_produces_output_file(self) -> None:
        """Test that a run submits one batch and writes output."""
        client: mock.Mock = self.__make_client(
            [self._make_success_entry("a", "answer a"),
             self._make_success_entry("b", "answer b")])
        status: int = self.__run_main(self.__argv, client)[0]
        self.assertEqual(status, 0)
        self.assertEqual(
            client.messages.batches.create.call_count, 1)
        run_dir: Path = self.__archive_dir
        self.assertTrue((run_dir / "output.jsonl").exists())
        output: list[dict[str, Any]] = [
            json.loads(x) for x in (run_dir / "output.jsonl")
            .read_text(encoding="utf-8").splitlines()]
        self.assertEqual(output[0]["text"], "answer a")
        meta: dict[str, Any] = json.loads(
            (run_dir / "meta.json").read_text(encoding="utf-8"))
        self.assertNotIn("run", meta)
        self.assertEqual(meta["batch"]["batch_id"], "batch_run1")
        self.assertEqual(meta["usage"],
                         {"input_tokens": 20, "output_tokens": 10})

    def test_existing_archive_rejected_without_replace(self) -> None:
        """Test that an existing archive without --replace fails."""
        run_dir: Path = self.__archive_dir
        run_dir.mkdir(parents=True)
        (run_dir / "stale.jsonl").write_text(
            "stale", encoding="utf-8")
        status: int = self.__run_main(
            self.__argv + ["--dry-run"])[0]
        self.assertEqual(status, 1)
        self.assertTrue((run_dir / "stale.jsonl").exists())

    def test_rerun_replaces_archive_with_flag(self) -> None:
        """Test that --replace replaces a pre-existing archive."""
        run_dir: Path = self.__archive_dir
        run_dir.mkdir(parents=True)
        (run_dir / "stale.jsonl").write_text(
            "stale", encoding="utf-8")
        client: mock.Mock = self.__make_client(
            [self._make_success_entry("a", "answer a"),
             self._make_success_entry("b", "answer b")])
        status: int = self.__run_main(
            self.__argv + ["--replace"], client)[0]
        self.assertEqual(status, 0)
        self.assertFalse((run_dir / "stale.jsonl").exists())
        self.assertTrue((run_dir / "output.jsonl").exists())

    def test_replace_leaves_sibling_dir_untouched(self) -> None:
        """Test that replacing run2 does not affect run1's archive."""
        run1_dir: Path = self.__archive_dir
        run1_dir.mkdir(parents=True)
        (run1_dir / "output.jsonl").write_text(
            "run1 data", encoding="utf-8")
        run2_dir: Path = self.__runs / "task_v1" / "run2"
        run2_dir.mkdir(parents=True)
        (run2_dir / "output.jsonl").write_text(
            "stale run2 data", encoding="utf-8")
        client: mock.Mock = self.__make_client(
            [self._make_success_entry("a", "answer a"),
             self._make_success_entry("b", "answer b")])
        argv: list[str] = [
            str(self.__prompt), str(self.__input),
            str(run2_dir), "--replace"]
        status: int = self.__run_main(argv, client)[0]
        self.assertEqual(status, 0)
        self.assertEqual(
            (run1_dir / "output.jsonl").read_text(encoding="utf-8"),
            "run1 data")
        self.assertNotEqual(
            (run2_dir / "output.jsonl").read_text(encoding="utf-8"),
            "stale run2 data")

    def test_run_failure_exits_non_zero(self) -> None:
        """Test that a failed item aborts with a non-zero status."""
        client: mock.Mock = self.__make_client(
            [self._make_success_entry("a", "answer a"),
             self._make_error_entry("b", "invalid_request_error")])
        status: int = self.__run_main(self.__argv, client)[0]
        self.assertEqual(status, 1)
        run_dir: Path = self.__archive_dir
        self.assertTrue((run_dir / "output.jsonl").exists())
        self.assertTrue((run_dir / "meta.json").exists())
        output_lines: list[str] = (run_dir / "output.jsonl") \
            .read_text(encoding="utf-8").splitlines()
        self.assertEqual(json.loads(output_lines[1]),
                         {"id": "b",
                          "error": "invalid_request_error"})

    def test_invalid_input_exits_non_zero(self) -> None:
        """Test that an invalid input file aborts before archiving."""
        self.__input.write_text('{"id": "a"}\n', encoding="utf-8")
        status: int = self.__run_main(
            self.__argv + ["--dry-run"])[0]
        self.assertEqual(status, 1)
        self.assertFalse(self.__runs.exists())
