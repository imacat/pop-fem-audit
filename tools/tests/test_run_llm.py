# Tools for A Feminist Audit of Pop Music.
# Copyright 2026 imacat.  All rights reserved.
# Authors:
#   imacat@mail.imacat.idv.tw (imacat), 2026/7/30
# AI assistance: Claude Code (Anthropic)
"""Unit tests for the run_llm batch runner module."""
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest import mock

from pop_fem_audit_tools import run_llm


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

        :param custom_id: The custom ID of the entry.
        :param error_type: The error type.
        :return: The mock result entry.
        """
        entry: mock.Mock = mock.Mock()
        entry.custom_id = custom_id
        entry.result = mock.Mock()
        entry.result.type = "errored"
        entry.result.error = mock.Mock()
        entry.result.error.type = error_type
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
        items: list[run_llm.Item] = run_llm.load_items(path)
        self.assertEqual(items, [{"id": "a", "content": "one"},
                                 {"id": "b", "content": "two"}])

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


class TestEnvParsing(RunLLMTestCase):
    """Test cases for the .env parsing and API key resolution."""

    def setUp(self) -> None:
        """Create a temporary directory for the .env files."""
        self.__dir: Path = self._make_temp_dir()

    def test_parse_env_file(self) -> None:
        """Test parsing a .env file with comments and blanks."""
        path: Path = self.__dir / ".env"
        path.write_text(
            "# a comment\n"
            "\n"
            "ANTHROPIC_API_KEY=sk-test-123\n"
            "OTHER = value \n"
            "garbage line\n",
            encoding="utf-8")
        values: dict[str, str] = run_llm.parse_env_file(path)
        self.assertEqual(values,
                         {"ANTHROPIC_API_KEY": "sk-test-123",
                          "OTHER": "value"})

    def test_parse_missing_env_file(self) -> None:
        """Test that a missing .env file yields no values."""
        values: dict[str, str] = run_llm.parse_env_file(
            self.__dir / ".env")
        self.assertEqual(values, {})

    def test_resolve_from_environment(self) -> None:
        """Test that the environment variable takes precedence."""
        path: Path = self.__dir / ".env"
        path.write_text("ANTHROPIC_API_KEY=sk-file\n",
                        encoding="utf-8")
        with mock.patch.dict(os.environ,
                             {"ANTHROPIC_API_KEY": "sk-env"}):
            self.assertEqual(run_llm.resolve_api_key(path), "sk-env")

    def test_resolve_from_env_file(self) -> None:
        """Test that the .env file is used as a fallback."""
        path: Path = self.__dir / ".env"
        path.write_text("ANTHROPIC_API_KEY=sk-file\n",
                        encoding="utf-8")
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(run_llm.resolve_api_key(path), "sk-file")

    def test_resolve_missing_key(self) -> None:
        """Test that a missing API key raises an error."""
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError):
                run_llm.resolve_api_key(self.__dir / ".env")


class TestRequestBuilding(RunLLMTestCase):
    """Test cases for the request construction."""

    def test_build_request(self) -> None:
        """Test the shape of a batch request."""
        request: dict[str, Any] = run_llm.build_request(
            {"id": "song-1", "content": "the lyrics"},
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

    def test_arbitration_content(self) -> None:
        """Test the arbitration user message format."""
        content: str = run_llm.build_arbitration_content(
            "the item", "output one", "output two")
        self.assertEqual(content,
                         "<item>\nthe item\n</item>\n"
                         "<run1>\noutput one\n</run1>\n"
                         "<run2>\noutput two\n</run2>")


class TestAgreement(RunLLMTestCase):
    """Test cases for the agreement computation."""

    def test_split_by_agreement(self) -> None:
        """Test splitting items into agreed and disagreeing ones."""
        items: list[run_llm.Item] = [
            {"id": "a", "content": "one"},
            {"id": "b", "content": "two"},
            {"id": "c", "content": "three"}]
        run1: run_llm.Results = {
            "a": {"id": "a", "text": "same\n"},
            "b": {"id": "b", "text": "left"},
            "c": {"id": "c", "text": " padded "}}
        run2: run_llm.Results = {
            "a": {"id": "a", "text": "same"},
            "b": {"id": "b", "text": "right"},
            "c": {"id": "c", "text": "padded"}}
        agreed: list[str]
        disagreed: list[str]
        agreed, disagreed = run_llm.split_by_agreement(
            items, run1, run2)
        self.assertEqual(agreed, ["a", "c"])
        self.assertEqual(disagreed, ["b"])


class TestFinalRecords(RunLLMTestCase):
    """Test cases for the final record assembly."""

    def test_build_final_records(self) -> None:
        """Test assembling final records from runs and arbitration."""
        items: list[run_llm.Item] = [
            {"id": "a", "content": "one"},
            {"id": "b", "content": "two"}]
        run1: run_llm.Results = {
            "a": {"id": "a", "text": "agreed text\n"},
            "b": {"id": "b", "text": "left"}}
        arbitration: run_llm.Results = {
            "b": {"id": "b", "text": "arbitrated text"}}
        records: list[dict[str, str]] = run_llm.build_final_records(
            items, run1, arbitration)
        self.assertEqual(records, [
            {"id": "a", "text": "agreed text", "source": "agreed"},
            {"id": "b", "text": "arbitrated text",
             "source": "arbitration"}])


class TestCollectResults(RunLLMTestCase):
    """Test cases for the batch result collection."""

    def test_collect_success_and_error(self) -> None:
        """Test collecting succeeded and errored results."""
        client: mock.Mock = mock.Mock()
        client.messages.batches.results.return_value = iter([
            self._make_success_entry("a", "output a"),
            self._make_error_entry("b", "invalid_request")])
        results: run_llm.Results = run_llm.collect_results(
            client, "batch_x")
        self.assertEqual(results["a"]["text"], "output a")
        self.assertEqual(results["a"]["stop_reason"], "end_turn")
        self.assertEqual(results["a"]["usage"],
                         {"input_tokens": 10, "output_tokens": 5})
        self.assertEqual(results["b"],
                         {"id": "b", "error": "invalid_request"})
        client.messages.batches.results.assert_called_once_with(
            "batch_x")

    def test_find_failures(self) -> None:
        """Test finding failed and missing items."""
        results: run_llm.Results = {
            "a": {"id": "a", "text": "fine"},
            "b": {"id": "b", "error": "errored"}}
        self.assertEqual(
            run_llm.find_failures(["a", "b", "c"], results),
            ["b", "c"])


class TestArchive(RunLLMTestCase):
    """Test cases for the archive directory handling."""

    def setUp(self) -> None:
        """Create a temporary directory as the runs root."""
        self.__dir: Path = self._make_temp_dir()

    def test_create_archive_dir(self) -> None:
        """Test the archive directory naming and creation."""
        now: datetime = datetime(2026, 7, 30, 20, 5)
        directory: Path = run_llm.create_archive_dir(
            self.__dir, "coding", Path("prompts/gender_v3.md"), now)
        self.assertTrue(directory.is_dir())
        self.assertEqual(
            directory,
            self.__dir / "coding" / "20260730-2005-gender_v3")

    def test_existing_archive_dir_rejected(self) -> None:
        """Test that an existing archive directory is rejected."""
        now: datetime = datetime(2026, 7, 30, 20, 5)
        run_llm.create_archive_dir(
            self.__dir, "coding", Path("gender_v3.md"), now)
        with self.assertRaises(FileExistsError):
            run_llm.create_archive_dir(
                self.__dir, "coding", Path("gender_v3.md"), now)

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
        """Create a temporary working directory with input files."""
        directory: Path = self._make_temp_dir()
        old_cwd: str = os.getcwd()
        self.addCleanup(os.chdir, old_cwd)
        os.chdir(directory)
        Path("prompts").mkdir()
        Path("prompts/task_v1.md").write_text(
            "The task prompt.\n", encoding="utf-8")
        Path("prompts/task_arbitration_v1.md").write_text(
            "The arbitration prompt.\n", encoding="utf-8")
        Path("items.jsonl").write_text(
            '{"id": "a", "content": "first item"}\n'
            '{"id": "b", "content": "second item"}\n',
            encoding="utf-8")
        self.__argv: list[str] = [
            "--prompt", "prompts/task_v1.md",
            "--arbitration-prompt", "prompts/task_arbitration_v1.md",
            "--input", "items.jsonl",
            "--phase", "coding"]

    @staticmethod
    def __make_client(run1: list[Any], run2: list[Any],
                      arbitration: list[Any] | None = None) \
            -> mock.Mock:
        """Create a mock Anthropic client serving canned batch results.

        :param run1: The result entries of the run-1 batch.
        :param run2: The result entries of the run-2 batch.
        :param arbitration: The result entries of the arbitration
            batch.
        :return: The mock client.
        """
        client: mock.Mock = mock.Mock()
        batch_ids: list[str] = ["batch_run1", "batch_run2",
                                "batch_arb"]
        client.messages.batches.create.side_effect = [
            mock.Mock(id=x) for x in batch_ids]
        ended: mock.Mock = mock.Mock()
        ended.processing_status = "ended"
        ended.ended_at = "2026-07-30T20:00:00+08:00"
        client.messages.batches.retrieve.return_value = ended
        results: dict[str, list[Any]] = {
            "batch_run1": run1, "batch_run2": run2,
            "batch_arb": arbitration if arbitration is not None
            else []}
        client.messages.batches.results.side_effect = (
            lambda batch_id: iter(results[batch_id]))
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
        environ: dict[str, str] = {"ANTHROPIC_API_KEY": "sk-test"}
        with mock.patch.dict(os.environ, environ), \
                mock.patch.object(run_llm.anthropic, "Anthropic",
                                  return_value=client), \
                redirect_stdout(stdout), redirect_stderr(stderr):
            status: int = run_llm.main(argv)
        return status, stdout.getvalue()

    def __archive_dir(self) -> Path:
        """Locate the single archive directory of the run.

        :return: The archive directory.
        """
        directories: list[Path] = list(Path("runs/coding").iterdir())
        self.assertEqual(len(directories), 1)
        return directories[0]

    def test_dry_run(self) -> None:
        """Test the dry-run behavior."""
        status: int
        stdout: str
        status, stdout = self.__run_main(
            self.__argv + ["--dry-run"])
        self.assertEqual(status, 0)
        run_dir: Path = self.__archive_dir()
        self.assertEqual((run_dir / "prompt.md").read_text(
            encoding="utf-8"), "The task prompt.\n")
        self.assertEqual(
            (run_dir / "arbitration_prompt.md").read_text(
                encoding="utf-8"), "The arbitration prompt.\n")
        meta: dict[str, Any] = json.loads(
            (run_dir / "meta.json").read_text(encoding="utf-8"))
        self.assertTrue(meta["dry_run"])
        self.assertEqual(meta["item_count"], 2)
        self.assertEqual(meta["model"], "claude-sonnet-4-6")
        self.assertFalse((run_dir / "run1.jsonl").exists())
        request: dict[str, Any] = json.loads(stdout)
        self.assertEqual(request["custom_id"], "a")
        self.assertEqual(request["params"]["system"],
                         "The task prompt.\n")

    def test_all_agreed_skips_arbitration(self) -> None:
        """Test that full agreement skips the arbitration batch."""
        client: mock.Mock = self.__make_client(
            run1=[self._make_success_entry("a", "answer a"),
                  self._make_success_entry("b", "answer b")],
            run2=[self._make_success_entry("a", "answer a\n"),
                  self._make_success_entry("b", "answer b")])
        status: int = self.__run_main(self.__argv, client)[0]
        self.assertEqual(status, 0)
        self.assertEqual(
            client.messages.batches.create.call_count, 2)
        run_dir: Path = self.__archive_dir()
        self.assertEqual(
            (run_dir / "arbitration.jsonl").read_text(
                encoding="utf-8"), "")
        final: list[dict[str, Any]] = [
            json.loads(x) for x in (run_dir / "final.jsonl")
            .read_text(encoding="utf-8").splitlines()]
        self.assertEqual(final, [
            {"id": "a", "text": "answer a", "source": "agreed"},
            {"id": "b", "text": "answer b", "source": "agreed"}])
        meta: dict[str, Any] = json.loads(
            (run_dir / "meta.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["agreed_count"], 2)
        self.assertEqual(meta["agreement_rate"], 1.0)
        self.assertNotIn("arbitration", meta["batches"])

    def test_disagreement_triggers_arbitration(self) -> None:
        """Test that disagreeing items go through arbitration."""
        client: mock.Mock = self.__make_client(
            run1=[self._make_success_entry("a", "answer a"),
                  self._make_success_entry("b", "answer b1")],
            run2=[self._make_success_entry("a", "answer a"),
                  self._make_success_entry("b", "answer b2")],
            arbitration=[
                self._make_success_entry("b", "answer b final")])
        status: int = self.__run_main(self.__argv, client)[0]
        self.assertEqual(status, 0)
        self.assertEqual(
            client.messages.batches.create.call_count, 3)
        arb_call: mock.call = \
            client.messages.batches.create.call_args_list[2]
        arb_requests: list[dict[str, Any]] = \
            arb_call.kwargs["requests"]
        self.assertEqual(len(arb_requests), 1)
        self.assertEqual(arb_requests[0]["custom_id"], "b")
        self.assertEqual(arb_requests[0]["params"]["system"],
                         "The arbitration prompt.\n")
        self.assertEqual(
            arb_requests[0]["params"]["messages"][0]["content"],
            "<item>\nsecond item\n</item>\n"
            "<run1>\nanswer b1\n</run1>\n"
            "<run2>\nanswer b2\n</run2>")
        run_dir: Path = self.__archive_dir()
        arb_lines: list[str] = (run_dir / "arbitration.jsonl") \
            .read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(arb_lines), 1)
        self.assertEqual(json.loads(arb_lines[0])["text"],
                         "answer b final")
        final: list[dict[str, Any]] = [
            json.loads(x) for x in (run_dir / "final.jsonl")
            .read_text(encoding="utf-8").splitlines()]
        self.assertEqual(final, [
            {"id": "a", "text": "answer a", "source": "agreed"},
            {"id": "b", "text": "answer b final",
             "source": "arbitration"}])
        meta: dict[str, Any] = json.loads(
            (run_dir / "meta.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["agreed_count"], 1)
        self.assertEqual(meta["agreement_rate"], 0.5)
        self.assertEqual(meta["batches"]["arbitration"]["batch_id"],
                         "batch_arb")

    def test_run_failure_exits_non_zero(self) -> None:
        """Test that a failed item aborts with a non-zero status."""
        client: mock.Mock = self.__make_client(
            run1=[self._make_success_entry("a", "answer a"),
                  self._make_error_entry("b", "invalid_request")],
            run2=[self._make_success_entry("a", "answer a"),
                  self._make_success_entry("b", "answer b")])
        status: int = self.__run_main(self.__argv, client)[0]
        self.assertEqual(status, 1)
        run_dir: Path = self.__archive_dir()
        self.assertTrue((run_dir / "run1.jsonl").exists())
        self.assertTrue((run_dir / "run2.jsonl").exists())
        self.assertTrue((run_dir / "meta.json").exists())
        self.assertFalse((run_dir / "final.jsonl").exists())
        run1_lines: list[str] = (run_dir / "run1.jsonl") \
            .read_text(encoding="utf-8").splitlines()
        self.assertEqual(json.loads(run1_lines[1]),
                         {"id": "b", "error": "invalid_request"})

    def test_invalid_input_exits_non_zero(self) -> None:
        """Test that an invalid input file aborts before archiving."""
        Path("items.jsonl").write_text(
            '{"id": "a"}\n', encoding="utf-8")
        status: int = self.__run_main(
            self.__argv + ["--dry-run"])[0]
        self.assertEqual(status, 1)
        self.assertFalse(Path("runs").exists())
