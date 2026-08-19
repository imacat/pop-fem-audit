#!/usr/bin/env python3
# Tools for A Feminist Audit of Pop Music.
# Copyright 2026 imacat.  All rights reserved.
# Authors:
#   imacat@mail.imacat.idv.tw (imacat), 2026/7/30
# AI assistance: Claude Code (Anthropic)
"""The generic batch executor for one LLM analysis step.

One invocation is one definition file plus one input, sent to the
Anthropic Messages Batch API exactly once, archived self-contained
under the destination directory given by the three positional
command-line arguments: prompt, input, archive_dir.  The tool
knows nothing about run counts or protocols: run identity --
run1, run2, run3 -- lives entirely in the caller's command list,
per the research plan.  A rerun of an already existing
destination requires ``--replace``; any other directory is never
touched.

Counting the runs' votes into the final table is the
responsibility of a separate subcommand, not this one.
"""
import argparse
import hashlib
import json
import shutil
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar, Self

import anthropic

from ..config import get_settings
from ..utils import format_duration


class InputFormatError(Exception):
    """An error in the JSONL input file."""


@dataclass(frozen=True)
class InputItem:
    """An input item of the LLM step."""

    id: str
    """The item ID."""
    content: str
    """The item content."""

    @classmethod
    def get_instance(cls, data: Any, path: Path,
                     number: int) -> Self:
        """Validate one parsed JSONL record as an input item.

        :param data: The parsed JSON value of the line.
        :param path: The path of the JSONL input file, for the
            messages.
        :param number: The line number, for the messages.
        :return: The validated input item.
        :raises InputFormatError: When the record is malformed.
        """
        if not isinstance(data, dict):
            raise InputFormatError(
                f"{path}: line {number}: not a JSON object")
        if set(data.keys()) != {"id", "content"}:
            raise InputFormatError(
                f"{path}: line {number}: keys must be exactly"
                " \"id\" and \"content\"")
        if not isinstance(data["id"], str) or data["id"] == "":
            raise InputFormatError(
                f"{path}: line {number}: \"id\" must be a"
                " non-empty string")
        if not isinstance(data["content"], str):
            raise InputFormatError(
                f"{path}: line {number}: \"content\" must be a"
                " string")
        return cls(id=data["id"], content=data["content"])


@dataclass
class BatchResult:
    """One batch result record."""

    id: str
    """The item ID."""
    text: str | None = None
    """The output text of a succeeded result."""
    stop_reason: str | None = None
    """The stop reason of a succeeded result."""
    usage: dict[str, Any] | None = None
    """The token usage of a succeeded result."""
    error: str | None = None
    """The error code of a failed result."""

    @property
    def is_failure(self) -> bool:
        """Whether this result is a failure.

        :return: True when the result carries an error, or False
            when it succeeded.
        """
        return self.error is not None

    @classmethod
    def get_instance(cls, entry: Any) -> Self:
        """Create the result record of a batch result entry.

        A succeeded entry yields the text, the stop reason, and
        the usage; any other entry yields the error code.

        :param entry: The batch result entry.
        :return: The result record.
        """
        result: Any = entry.result
        match result.type:
            case "succeeded":
                message: Any = result.message
                text: str = "".join(
                    x.text for x in message.content
                    if x.type == "text")
                return cls(id=entry.custom_id, text=text,
                           stop_reason=message.stop_reason,
                           usage=cls.__usage_to_dict(message.usage))
            case "errored":
                return cls(id=entry.custom_id,
                           error=result.error.error.type)
            case other:
                return cls(id=entry.custom_id, error=str(other))

    @staticmethod
    def __usage_to_dict(usage: Any) -> dict[str, Any]:
        """Convert a usage object to a plain dictionary.

        :param usage: The usage object of a message.
        :return: The usage as a dictionary, without null entries.
        """
        return {k: v for k, v in usage.model_dump().items()
                if v is not None}

    def to_record(self) -> dict[str, Any]:
        """Return this result as an archive JSONL record.

        :return: The record, with the None fields omitted.
        """
        return {k: v for k, v in asdict(self).items()
                if v is not None}


type Results = dict[str, BatchResult]
"""The batch result records, keyed by item ID."""


@dataclass
class BatchInfo:
    """The bookkeeping of one submitted message batch."""

    batch_id: str
    """The batch ID."""
    submitted_at: str
    """The submission time, in ISO 8601 format."""
    ended_at: str | None = None
    """The end time, in ISO 8601 format, or None while the batch
    is still processing."""


@dataclass(frozen=True)
class ExecutionOutcome:
    """The outcome of submitting and awaiting one batch."""

    batch: BatchInfo
    """The submitted batch's bookkeeping."""
    results: Results
    """The batch's results, keyed by item ID."""


@dataclass(frozen=True)
class RunOutcome:
    """The outcome of one LLM definition file run."""

    item_count: int
    """The number of loaded input items."""
    dry_run: bool
    """Whether this was a dry run."""
    dry_run_request: dict[str, Any] | None
    """The first item's preview request, for a dry run; None for
    an actual run."""
    failed: list[str]
    """The failed item IDs, in item order; always empty for a dry
    run."""


class LLMRunner:
    """The orchestrator of one LLM definition file run."""

    # claude-fable-5 accepts neither "temperature" nor "thinking";
    # a model's entry holds exactly the extra request parameters
    # it accepts.
    MODELS: ClassVar[dict[str, dict[str, Any]]] = {
        "claude-sonnet-4-6": {
            "temperature": 0.0,
            "thinking": {"type": "disabled"},
        },
        "claude-fable-5": {},
    }
    """The supported model IDs and their extra request
    parameters."""
    DEFAULT_MODEL: ClassVar[str] = "claude-sonnet-4-6"
    """The default model ID."""
    __SCRIPT_VERSION: ClassVar[str] = "run_llm.py 3.1.0"
    """The script version recorded into the archive metadata."""
    __POLL_INTERVAL_SECONDS: ClassVar[float] = 60.0
    """The interval between batch status polls."""

    def __init__(self, prompt: Path, input_path: Path,
                 archive_dir: Path, model: str, max_tokens: int,
                 dry_run: bool, replace: bool) -> None:
        """Set up the run of one LLM definition file.

        :param prompt: The prompt definition file, used as the
            system prompt.
        :param input_path: The JSONL input file with "id" and
            "content".
        :param archive_dir: The destination archive directory.
        :param model: The model ID, a key of :attr:`MODELS`.
        :param max_tokens: The maximum output tokens per request.
        :param dry_run: Whether to validate and archive without
            calling the API.
        :param replace: Whether to replace an already existing
            archive directory.
        """
        self.__prompt: Path = prompt
        """The prompt definition file."""
        self.__input: Path = input_path
        """The JSONL input file."""
        self.__archive_dir: Path = archive_dir
        """The destination archive directory."""
        self.__model: str = model
        """The model ID."""
        self.__max_tokens: int = max_tokens
        """The maximum output tokens per request."""
        self.__dry_run: bool = dry_run
        """Whether to validate and archive without calling the
        API."""
        self.__replace: bool = replace
        """Whether to replace an already existing archive
        directory."""

    def run(self) -> RunOutcome:
        """Load the input, archive the prompt, and run the batch.

        Always writes ``prompt.md`` and ``meta.json`` into the
        archive directory.  A dry run stops there, previewing the
        first item's request; an actual run also submits the
        batch, awaits it, and writes ``output.jsonl``.

        :return: The outcome of the run.
        :raises InputFormatError: When the input file is
            malformed.
        :raises OSError: When the input or prompt file cannot be
            read, the archive directory already exists without
            ``replace``, or an output file cannot be written.
        """
        items: list[InputItem] = self.__load_items()
        prompt_text: str = self.__prompt.read_text(encoding="utf-8")
        archive_dir: Path = self.__create_archive_dir()
        (archive_dir / "prompt.md").write_bytes(
            self.__prompt.read_bytes())
        meta: dict[str, Any] = self.__build_meta(items)
        meta_path: Path = archive_dir / "meta.json"
        if self.__dry_run:
            self.__write_json(meta_path, meta)
            request: dict[str, Any] = self.__build_request(
                items[0], prompt_text)
            return RunOutcome(
                item_count=len(items), dry_run=True,
                dry_run_request=request, failed=[])
        client: anthropic.Anthropic = anthropic.Anthropic(
            api_key=get_settings().ANTHROPIC_API_KEY)
        outcome: ExecutionOutcome = self.__execute_run(
            client, items, prompt_text)
        item_ids: list[str] = [x.id for x in items]
        self.__write_jsonl(
            archive_dir / "output.jsonl",
            [outcome.results[x].to_record() for x in item_ids
             if x in outcome.results])
        meta["batch"] = outcome.batch
        meta["usage"] = self.__sum_usage(outcome.results)
        self.__write_meta(meta_path, meta)
        failed: list[str] = self.__find_failures(
            item_ids, outcome.results)
        return RunOutcome(
            item_count=len(items), dry_run=False,
            dry_run_request=None, failed=failed)

    def __load_items(self) -> list[InputItem]:
        """Load and validate the JSONL input items.

        :return: The input items, in file order.
        :raises InputFormatError: When a line is malformed, an ID
            is duplicated, or the file contains no item.
        :raises OSError: When the file cannot be read.
        """
        items: list[InputItem] = []
        seen: set[str] = set()
        with open(self.__input, encoding="utf-8") as file:
            for number, line in enumerate(file, start=1):
                if line.strip() == "":
                    continue
                data: Any
                try:
                    data = json.loads(line)
                except json.JSONDecodeError as error:
                    raise InputFormatError(
                        f"{self.__input}: line {number}: malformed"
                        f" JSON: {error}")
                item: InputItem = InputItem.get_instance(
                    data, self.__input, number)
                if item.id in seen:
                    raise InputFormatError(
                        f"{self.__input}: line {number}:"
                        f" duplicated ID \"{item.id}\"")
                seen.add(item.id)
                items.append(item)
        if len(items) == 0:
            raise InputFormatError(f"{self.__input}: no input items")
        return items

    def __create_archive_dir(self) -> Path:
        """Create the archive directory.

        Only this directory is ever created or removed; no other
        directory is ever touched.

        :return: The created archive directory.
        :raises FileExistsError: When the archive directory
            already exists and ``replace`` is False.
        """
        if self.__archive_dir.exists():
            if not self.__replace:
                raise FileExistsError(
                    f"{self.__archive_dir} already exists; pass"
                    " --replace to replace it")
            shutil.rmtree(self.__archive_dir)
        self.__archive_dir.mkdir(parents=True)
        return self.__archive_dir

    def __build_meta(self, items: list[InputItem]) -> dict[str, Any]:
        """Build the initial archive metadata.

        :param items: The loaded input items.
        :return: The metadata, "batch" and "usage" not yet filled
            in for an actual run.
        """
        return {
            "script_version": self.__SCRIPT_VERSION,
            "model": self.__model,
            "temperature": self.MODELS[self.__model].get(
                "temperature"),
            "thinking": self.MODELS[self.__model].get("thinking"),
            "max_tokens": self.__max_tokens,
            "prompt_path": str(self.__prompt),
            "prompt_sha256": self.__sha256_of(self.__prompt),
            "input_path": str(self.__input),
            "input_sha256": self.__sha256_of(self.__input),
            "item_count": len(items),
            "dry_run": self.__dry_run,
            "started_at": self.__now_iso(),
            "batch": None,
            "usage": {},
        }

    def __build_request(self, item: InputItem, system_prompt: str) \
            -> dict[str, Any]:
        """Build one Message Batches request for an input item.

        :param item: The input item.
        :param system_prompt: The system prompt text.
        :return: The batch request with "custom_id" and "params".
        """
        return {
            "custom_id": item.id,
            "params": {
                "model": self.__model,
                "max_tokens": self.__max_tokens,
                **self.MODELS[self.__model],
                "system": system_prompt,
                "messages": [
                    {"role": "user", "content": item.content},
                ],
            },
        }

    def __execute_run(
            self, client: anthropic.Anthropic,
            items: list[InputItem], system_prompt: str) \
            -> ExecutionOutcome:
        """Submit the batch of this run and await its results.

        :param client: The Anthropic client.
        :param items: The input items.
        :param system_prompt: The system prompt text.
        :return: The submitted batch's bookkeeping and its
            results.
        """
        requests: list[dict[str, Any]] = [
            self.__build_request(x, system_prompt) for x in items]
        info: BatchInfo = BatchInfo(
            batch_id=self.__submit_batch(client, requests),
            submitted_at=self.__now_iso())
        print(f"submitted batch {info.batch_id}", file=sys.stderr)
        batches: dict[str, Any] = self.__poll_batches(
            client, [info.batch_id])
        info.ended_at = batches[info.batch_id].ended_at.isoformat()
        results: Results = self.__collect_results(
            client, info.batch_id)
        return ExecutionOutcome(batch=info, results=results)

    @staticmethod
    def __submit_batch(client: anthropic.Anthropic,
                       requests: list[dict[str, Any]]) -> str:
        """Submit one message batch.

        :param client: The Anthropic client.
        :param requests: The batch requests.
        :return: The batch ID.
        """
        return client.messages.batches.create(requests=requests).id

    @classmethod
    def __poll_batches(cls, client: anthropic.Anthropic,
                       batch_ids: list[str]) -> dict[str, Any]:
        """Poll the batches until every one of them has ended.

        Progress is printed to the standard error every poll.

        :param client: The Anthropic client.
        :param batch_ids: The batch IDs to poll.
        :return: The final batch object of each batch, keyed by
            batch ID.
        """
        while True:
            batches: dict[str, Any] = {
                x: client.messages.batches.retrieve(x)
                for x in batch_ids}
            pending: list[str] = [
                x for x in batch_ids
                if batches[x].processing_status != "ended"]
            for batch_id in batch_ids:
                status: str = batches[batch_id].processing_status
                print(f"batch {batch_id}: {status}", file=sys.stderr)
            if len(pending) == 0:
                return batches
            time.sleep(cls.__POLL_INTERVAL_SECONDS)

    @staticmethod
    def __collect_results(client: anthropic.Anthropic,
                          batch_id: str) -> Results:
        """Collect the results of an ended batch.

        :param client: The Anthropic client.
        :param batch_id: The batch ID.
        :return: The result records, keyed by custom ID.
        """
        results: Results = {}
        for entry in client.messages.batches.results(batch_id):
            results[entry.custom_id] = BatchResult.get_instance(
                entry)
        return results

    @staticmethod
    def __find_failures(item_ids: list[str],
                        results: Results) -> list[str]:
        """Find the item IDs that failed in a result set.

        An item failed when it is missing from the results or when
        its record is a failure.

        :param item_ids: The item IDs to check, in order.
        :param results: The result records, keyed by item ID.
        :return: The failed item IDs, in the given order.
        """
        return [x for x in item_ids
                if x not in results or results[x].is_failure]

    @staticmethod
    def __sum_usage(results: Results) -> dict[str, int]:
        """Sum the token usage of every succeeded result.

        :param results: The result records, keyed by item ID.
        :return: The summed integer usage fields.
        """
        totals: dict[str, int] = {}
        for result in results.values():
            if result.usage is None:
                continue
            for key, value in result.usage.items():
                if isinstance(value, int):
                    totals[key] = totals.get(key, 0) + value
        return totals

    @staticmethod
    def __write_jsonl(path: Path,
                      records: list[dict[str, Any]]) -> None:
        """Write records to a file as JSON Lines.

        :param path: The path of the file to write.
        :param records: The records, one per line.
        :return: None.
        :raises OSError: When the file cannot be written.
        """
        with open(path, "w", encoding="utf-8") as file:
            for record in records:
                file.write(
                    json.dumps(record, ensure_ascii=False) + "\n")

    @staticmethod
    def __write_json(path: Path, data: dict[str, Any]) -> None:
        """Write data to a file as pretty-printed JSON.

        :param path: The path of the file to write.
        :param data: The data to write.
        :return: None.
        :raises OSError: When the file cannot be written.
        """
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")

    @classmethod
    def __write_meta(cls, path: Path, meta: dict[str, Any]) -> None:
        """Write the metadata to the ``meta.json`` file.

        The ``BatchInfo`` value under "batch" is written as a
        plain JSON object.

        :param path: The path of the ``meta.json`` file.
        :param meta: The metadata to write.
        :return: None.
        :raises OSError: When the file cannot be written.
        """
        cls.__write_json(
            path, {**meta, "batch": asdict(meta["batch"])})

    @staticmethod
    def __sha256_of(path: Path) -> str:
        """Calculate the SHA-256 digest of a file.

        :param path: The path of the file.
        :return: The hexadecimal SHA-256 digest.
        """
        with open(path, "rb") as file:
            return hashlib.file_digest(file, "sha256").hexdigest()

    @staticmethod
    def __now_iso() -> str:
        """Return the current local time in ISO 8601 format.

        :return: The current local time with the timezone offset.
        """
        return datetime.now().astimezone().isoformat(
            timespec="seconds")


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Parse the command-line arguments.

    :param argv: The command-line arguments, or None for
        ``sys.argv``.
    :return: The parsed arguments.
    """
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description="Run one LLM definition file against one input"
                    " and archive the result.")
    parser.add_argument(
        "prompt", type=Path,
        help="the prompt definition file, used as the system"
             " prompt")
    parser.add_argument(
        "input", type=Path,
        help="the JSONL input file with \"id\" and \"content\"")
    parser.add_argument(
        "archive_dir", type=Path,
        help="the destination archive directory")
    parser.add_argument(
        "--model", choices=sorted(LLMRunner.MODELS),
        default=LLMRunner.DEFAULT_MODEL,
        help=f"the model ID (default {LLMRunner.DEFAULT_MODEL})")
    parser.add_argument(
        "--max-tokens", type=int, default=2048,
        help="the maximum output tokens per request (default"
             " 2048)")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="validate and archive without calling the API")
    parser.add_argument(
        "--replace", action="store_true",
        help="replace an already existing archive directory")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run one LLM definition file against one input and archive it.

    :param argv: The command-line arguments, or None for
        ``sys.argv``.
    :return: The exit status: 0 on success, non-zero on failure.
    """
    started: float = time.monotonic()
    args: argparse.Namespace = parse_args(argv)
    try:
        outcome: RunOutcome = LLMRunner(
            args.prompt, args.input, args.archive_dir, args.model,
            args.max_tokens, args.dry_run, args.replace).run()
    except (InputFormatError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    if not outcome.dry_run and len(outcome.failed) > 0:
        print(f"error: failed items: {', '.join(outcome.failed)}",
              file=sys.stderr)
        return 1
    if outcome.dry_run:
        print(json.dumps(
            outcome.dry_run_request, ensure_ascii=False, indent=2))
    elapsed: str = format_duration(time.monotonic() - started)
    print(f"Done.  {outcome.item_count} jobs finished."
          f"  {elapsed} elapsed.", file=sys.stderr)
    return 0
