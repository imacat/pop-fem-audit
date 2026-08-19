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
    """Test cases for the input JSONL validation, driven by a dry
    run since the validation happens before any API call."""

    def setUp(self) -> None:
        """Create the prompt and input paths for a dry run."""
        directory: Path = self._make_temp_dir()
        self.__prompt: Path = directory / "task.md"
        self.__prompt.write_text("The task.\n", encoding="utf-8")
        self.__input: Path = directory / "items.jsonl"
        self.__archive_dir: Path = directory / "runs" / "run1"

    def __run_dry(self, content: str) -> tuple[int, str]:
        """Write the input file and dry-run against it.

        :param content: The input file content.
        :return: The exit status and the standard error text.
        """
        self.__input.write_text(content, encoding="utf-8")
        stderr: io.StringIO = io.StringIO()
        status: int
        with redirect_stderr(stderr):
            status = run_llm.main([
                str(self.__prompt), str(self.__input),
                str(self.__archive_dir), "--dry-run"])
        return status, stderr.getvalue()

    def test_malformed_json_names_line(self) -> None:
        """Test that malformed JSON reports the line number."""
        status: int
        stderr: str
        status, stderr = self.__run_dry(
            '{"id": "a", "content": "one"}\n'
            'not json\n')
        self.assertEqual(status, 1)
        self.assertIn("line 2", stderr)

    def test_missing_key_names_line(self) -> None:
        """Test that a missing key reports the line number."""
        status: int
        stderr: str
        status, stderr = self.__run_dry('{"id": "a"}\n')
        self.assertEqual(status, 1)
        self.assertIn("line 1", stderr)

    def test_extra_key_rejected(self) -> None:
        """Test that an extra key is rejected."""
        status: int
        status, _ = self.__run_dry(
            '{"id": "a", "content": "one", "extra": 1}\n')
        self.assertEqual(status, 1)

    def test_non_string_content_rejected(self) -> None:
        """Test that a non-string content is rejected."""
        status: int
        status, _ = self.__run_dry('{"id": "a", "content": 3}\n')
        self.assertEqual(status, 1)

    def test_duplicated_id_names_line(self) -> None:
        """Test that a duplicated ID reports the line number."""
        status: int
        stderr: str
        status, stderr = self.__run_dry(
            '{"id": "a", "content": "one"}\n'
            '{"id": "a", "content": "two"}\n')
        self.assertEqual(status, 1)
        self.assertIn("line 2", stderr)
        self.assertIn("a", stderr)

    def test_empty_file_rejected(self) -> None:
        """Test that an empty input file is rejected."""
        status: int
        status, _ = self.__run_dry("")
        self.assertEqual(status, 1)
        self.assertFalse(self.__archive_dir.exists())


class TestRequestBuilding(RunLLMTestCase):
    """Test cases for the request preview, driven by a dry run."""

    def setUp(self) -> None:
        """Create the prompt and input files for a dry run."""
        directory: Path = self._make_temp_dir()
        self.__prompt: Path = directory / "task.md"
        self.__prompt.write_text(
            "the system prompt", encoding="utf-8")
        self.__input: Path = directory / "items.jsonl"
        self.__input.write_text(
            '{"id": "song-1", "content": "the lyrics"}\n',
            encoding="utf-8")
        self.__archive_dir: Path = directory / "runs" / "run1"

    def __preview(self, extra_argv: list[str]) -> dict[str, Any]:
        """Dry-run and parse the previewed request.

        :param extra_argv: The extra command-line arguments.
        :return: The parsed request.
        """
        stdout: io.StringIO = io.StringIO()
        with redirect_stdout(stdout):
            run_llm.main([
                str(self.__prompt), str(self.__input),
                str(self.__archive_dir), "--dry-run"] + extra_argv)
        return json.loads(stdout.getvalue())

    def test_default_model_request(self) -> None:
        """Test the request shape for the default model."""
        request: dict[str, Any] = self.__preview([])
        self.assertEqual(request["custom_id"], "song-1")
        params: dict[str, Any] = request["params"]
        self.assertEqual(params["model"], "claude-sonnet-4-6")
        self.assertEqual(params["temperature"], 0.0)
        self.assertEqual(params["thinking"], {"type": "disabled"})
        self.assertEqual(params["max_tokens"], 2048)
        self.assertEqual(params["system"], "the system prompt")
        self.assertEqual(
            params["messages"],
            [{"role": "user", "content": "the lyrics"}])

    def test_fable_5_request(self) -> None:
        """Test the request shape for the claude-fable-5 model."""
        request: dict[str, Any] = self.__preview(
            ["--model", "claude-fable-5", "--max-tokens", "8192"])
        params: dict[str, Any] = request["params"]
        self.assertEqual(params["model"], "claude-fable-5")
        self.assertNotIn("temperature", params)
        self.assertNotIn("thinking", params)
        self.assertEqual(params["max_tokens"], 8192)


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

    def __make_client(self, entries: list[Any]) -> mock.Mock:
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
    def __run_main(
            argv: list[str],
            client: mock.Mock | None = None) -> tuple[int, str, str]:
        """Run main() with a mocked client and captured output.

        :param argv: The command-line arguments.
        :param client: The mock client, or None for dry runs.
        :return: A tuple of the exit status, the standard output,
            and the standard error.
        """
        stdout: io.StringIO = io.StringIO()
        stderr: io.StringIO = io.StringIO()
        with mock.patch.object(run_llm.anthropic, "Anthropic",
                               return_value=client), \
                redirect_stdout(stdout), redirect_stderr(stderr):
            status: int = run_llm.main(argv)
        return status, stdout.getvalue(), stderr.getvalue()

    def test_dry_run(self) -> None:
        """Test the dry-run behavior."""
        status: int
        stdout: str
        stderr: str
        with mock.patch(
                "time.monotonic", side_effect=[1000.0, 1125.0]):
            status, stdout, stderr = self.__run_main(
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
        self.assertTrue(stderr.rstrip("\n").endswith(
            "Done.  2 jobs finished.  02:05 elapsed."))

    def test_run_produces_output_file(self) -> None:
        """Test that a run submits one batch and writes output,
        the item order preserved and the token usage summed, the
        output text written unescaped."""
        client: mock.Mock = self.__make_client(
            [self._make_success_entry("a", "answer 中文 a"),
             self._make_success_entry("b", "answer b")])
        status: int
        stderr: str
        with mock.patch(
                "time.monotonic", side_effect=[1000.0, 1125.0]):
            status, _, stderr = self.__run_main(self.__argv, client)
        self.assertEqual(status, 0)
        self.assertEqual(
            client.messages.batches.create.call_count, 1)
        run_dir: Path = self.__archive_dir
        self.assertTrue((run_dir / "output.jsonl").exists())
        output_text: str = (run_dir / "output.jsonl").read_text(
            encoding="utf-8")
        self.assertIn("中文", output_text)
        output: list[dict[str, Any]] = [
            json.loads(x) for x in output_text.splitlines()]
        self.assertEqual(output[0]["text"], "answer 中文 a")
        self.assertEqual(output[1]["text"], "answer b")
        meta: dict[str, Any] = json.loads(
            (run_dir / "meta.json").read_text(encoding="utf-8"))
        self.assertNotIn("run", meta)
        self.assertEqual(meta["batch"]["batch_id"], "batch_run1")
        self.assertEqual(meta["usage"],
                         {"input_tokens": 20, "output_tokens": 10})
        self.assertTrue(stderr.rstrip("\n").endswith(
            "Done.  2 jobs finished.  02:05 elapsed."))

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
        """Test that a failed item aborts with a non-zero status,
        the summed usage counting only the succeeded item."""
        client: mock.Mock = self.__make_client(
            [self._make_success_entry("a", "answer a"),
             self._make_error_entry("b", "invalid_request_error")])
        status: int
        stderr: str
        status, _, stderr = self.__run_main(self.__argv, client)
        self.assertEqual(status, 1)
        run_dir: Path = self.__archive_dir
        self.assertTrue((run_dir / "output.jsonl").exists())
        self.assertTrue((run_dir / "meta.json").exists())
        output_lines: list[str] = (run_dir / "output.jsonl") \
            .read_text(encoding="utf-8").splitlines()
        self.assertEqual(json.loads(output_lines[1]),
                         {"id": "b",
                          "error": "invalid_request_error"})
        meta: dict[str, Any] = json.loads(
            (run_dir / "meta.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["usage"],
                         {"input_tokens": 10, "output_tokens": 5})
        self.assertNotIn("Done.", stderr)

    def test_missing_result_item_is_a_failure(self) -> None:
        """Test that an item missing from the batch results is
        reported as a failed item."""
        client: mock.Mock = self.__make_client(
            [self._make_success_entry("a", "answer a")])
        status: int
        stderr: str
        status, _, stderr = self.__run_main(self.__argv, client)
        self.assertEqual(status, 1)
        self.assertIn("b", stderr)

    def test_invalid_input_exits_non_zero(self) -> None:
        """Test that an invalid input file aborts before archiving."""
        self.__input.write_text('{"id": "a"}\n', encoding="utf-8")
        status: int = self.__run_main(
            self.__argv + ["--dry-run"])[0]
        self.assertEqual(status, 1)
        self.assertFalse(self.__runs.exists())
