#!/usr/bin/env python3
# Tools for A Feminist Audit of Pop Music.
# Copyright 2026 imacat.  All rights reserved.
# Authors:
#   imacat@mail.imacat.idv.tw (imacat), 2026/7/30
# AI assistance: Claude Code (Anthropic)
"""The generic batch runner for one LLM analysis step.

Sends every input item to the Anthropic Messages Batch API twice with
the same system prompt, reconciles the disagreeing items with a third
arbitration batch, and archives every artifact self-contained under
``<runs_dir>/<phase>/<YYYYMMDD-HHMM>-<prompt-stem>/``, where the
base directory of the run archives is given as the positional
command-line argument.
"""
import argparse
import enum
import hashlib
import json
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Self

import anthropic

from .config import get_settings

MODEL: str = "claude-sonnet-4-6"
TEMPERATURE: float = 0.0
THINKING: dict[str, str] = {"type": "disabled"}
SCRIPT_VERSION: str = "run_llm.py 1.0.0"
POLL_INTERVAL_SECONDS: float = 60.0
ARBITRATION_TEMPLATE: str = (
    "<item>\n{content}\n</item>\n"
    "<run1>\n{run1}\n</run1>\n"
    "<run2>\n{run2}\n</run2>")


class Source(enum.StrEnum):
    """The source of a final record."""

    AGREED = "agreed"
    """The record takes the run text the two runs agreed on."""
    ARBITRATION = "arbitration"
    """The record takes the arbitration output."""


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
                           usage=usage_to_dict(message.usage))
            case "errored":
                return cls(id=entry.custom_id,
                           error=result.error.error.type)
            case other:
                return cls(id=entry.custom_id, error=str(other))

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


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Parse the command-line arguments.

    :param argv: The command-line arguments, or None for ``sys.argv``.
    :return: The parsed arguments.
    """
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description="Run one LLM step: 2 runs + 1 arbitration.")
    parser.add_argument(
        "runs_dir", type=Path,
        help="the base directory of the run archives")
    parser.add_argument(
        "--prompt", required=True, type=Path,
        help="the prompt definition file, used as the system prompt")
    parser.add_argument(
        "--arbitration-prompt", required=True, type=Path,
        help="the arbitration prompt definition file")
    parser.add_argument(
        "--input", required=True, type=Path,
        help="the JSONL input file with \"id\" and \"content\"")
    parser.add_argument(
        "--phase", required=True,
        help="the phase name for the archive directory")
    parser.add_argument(
        "--max-tokens", type=int, default=2048,
        help="the maximum output tokens per request (default 2048)")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="validate and archive without calling the API")
    return parser.parse_args(argv)


def load_items(path: Path) -> list[InputItem]:
    """Load and validate the JSONL input items.

    :param path: The path of the JSONL input file.
    :return: The input items, in file order.
    :raises InputFormatError: When a line is malformed, an ID is
        duplicated, or the file contains no item.
    :raises OSError: When the file cannot be read.
    """
    items: list[InputItem] = []
    seen: set[str] = set()
    with open(path, encoding="utf-8") as file:
        for number, line in enumerate(file, start=1):
            if line.strip() == "":
                continue
            try:
                data: Any = json.loads(line)
            except json.JSONDecodeError as error:
                raise InputFormatError(
                    f"{path}: line {number}: malformed JSON: {error}")
            item: InputItem = InputItem.get_instance(
                data, path, number)
            if item.id in seen:
                raise InputFormatError(
                    f"{path}: line {number}: duplicated ID"
                    f" \"{item.id}\"")
            seen.add(item.id)
            items.append(item)
    if len(items) == 0:
        raise InputFormatError(f"{path}: no input items")
    return items


def build_request(item: InputItem, system_prompt: str,
                  max_tokens: int) -> dict[str, Any]:
    """Build one Message Batches request for an input item.

    :param item: The input item.
    :param system_prompt: The system prompt text.
    :param max_tokens: The maximum output tokens.
    :return: The batch request with "custom_id" and "params".
    """
    return {
        "custom_id": item.id,
        "params": {
            "model": MODEL,
            "max_tokens": max_tokens,
            "temperature": TEMPERATURE,
            "thinking": THINKING,
            "system": system_prompt,
            "messages": [
                {"role": "user", "content": item.content},
            ],
        },
    }


def build_arbitration_content(content: str, run1_text: str,
                              run2_text: str) -> str:
    """Build the arbitration user message for one item.

    :param content: The original item content.
    :param run1_text: The run-1 output text.
    :param run2_text: The run-2 output text.
    :return: The user message text.
    """
    return ARBITRATION_TEMPLATE.format(
        content=content, run1=run1_text, run2=run2_text)


def submit_batch(client: anthropic.Anthropic,
                 requests: list[dict[str, Any]]) -> str:
    """Submit one message batch.

    :param client: The Anthropic client.
    :param requests: The batch requests.
    :return: The batch ID.
    """
    return client.messages.batches.create(requests=requests).id


def poll_batches(client: anthropic.Anthropic,
                 batch_ids: list[str]) -> dict[str, Any]:
    """Poll the batches until every one of them has ended.

    Progress is printed to the standard error every poll.

    :param client: The Anthropic client.
    :param batch_ids: The batch IDs to poll.
    :return: The final batch object of each batch, keyed by batch ID.
    """
    while True:
        batches: dict[str, Any] = {
            x: client.messages.batches.retrieve(x) for x in batch_ids}
        pending: list[str] = [
            x for x in batch_ids
            if batches[x].processing_status != "ended"]
        for batch_id in batch_ids:
            status: str = batches[batch_id].processing_status
            print(f"batch {batch_id}: {status}", file=sys.stderr)
        if len(pending) == 0:
            return batches
        time.sleep(POLL_INTERVAL_SECONDS)


def usage_to_dict(usage: Any) -> dict[str, Any]:
    """Convert a usage object to a plain dictionary.

    :param usage: The usage object of a message.
    :return: The usage as a dictionary, without null entries.
    """
    return {k: v for k, v in usage.model_dump().items()
            if v is not None}


def collect_results(client: anthropic.Anthropic,
                    batch_id: str) -> Results:
    """Collect the results of an ended batch.

    :param client: The Anthropic client.
    :param batch_id: The batch ID.
    :return: The result records, keyed by custom ID.
    """
    results: Results = {}
    for entry in client.messages.batches.results(batch_id):
        results[entry.custom_id] = BatchResult.get_instance(entry)
    return results


def find_failures(item_ids: list[str],
                  results: Results) -> list[str]:
    """Find the item IDs that failed in a result set.

    An item failed when it is missing from the results or when its
    record is a failure.

    :param item_ids: The item IDs to check, in order.
    :param results: The result records, keyed by item ID.
    :return: The failed item IDs, in the given order.
    """
    return [x for x in item_ids
            if x not in results or results[x].is_failure]


def split_by_agreement(
        items: list[InputItem], run1: Results, run2: Results,
) -> tuple[list[str], list[str]]:
    """Split the item IDs into agreed and disagreeing ones.

    Two outputs agree when their texts are identical after strip().

    :param items: The input items.
    :param run1: The run-1 results, keyed by item ID.
    :param run2: The run-2 results, keyed by item ID.
    :return: A tuple of the agreed item IDs and the disagreeing item
        IDs, both in input order.
    """
    agreed: list[str] = []
    disagreed: list[str] = []
    for item in items:
        text1: str | None = run1[item.id].text
        text2: str | None = run2[item.id].text
        assert text1 is not None and text2 is not None
        if text1.strip() == text2.strip():
            agreed.append(item.id)
        else:
            disagreed.append(item.id)
    return agreed, disagreed


def build_final_records(
        items: list[InputItem], run1: Results, arbitration: Results,
) -> list[dict[str, str]]:
    """Assemble the final records, one per item, in input order.

    An arbitrated item takes the arbitration output; an agreed item
    takes the agreed (stripped) run text.

    :param items: The input items.
    :param run1: The run-1 results, keyed by item ID.
    :param arbitration: The arbitration results, keyed by item ID.
    :return: The final records with "id", "text", and "source".
    """
    records: list[dict[str, str]] = []
    for item in items:
        text: str | None
        if item.id in arbitration:
            text = arbitration[item.id].text
            assert text is not None
            records.append({"id": item.id, "text": text,
                            "source": Source.ARBITRATION})
        else:
            text = run1[item.id].text
            assert text is not None
            records.append({"id": item.id, "text": text.strip(),
                            "source": Source.AGREED})
    return records


def create_archive_dir(runs_root: Path, phase: str, prompt_path: Path,
                       now: datetime) -> Path:
    """Create the archive directory for this execution.

    :param runs_root: The root directory of the run archives.
    :param phase: The phase name.
    :param prompt_path: The path of the prompt definition file.
    :param now: The local timestamp of this execution.
    :return: The created archive directory.
    :raises FileExistsError: When the directory already exists.
    """
    stem: str = prompt_path.stem
    name: str = f"{now.strftime('%Y%m%d-%H%M')}-{stem}"
    directory: Path = runs_root / phase / name
    if directory.exists():
        raise FileExistsError(
            f"archive directory {directory} already exists")
    directory.mkdir(parents=True)
    return directory


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    """Write records to a file as JSON Lines.

    :param path: The path of the file to write.
    :param records: The records, one per line.
    :return: None.
    """
    with open(path, "w", encoding="utf-8") as file:
        for record in records:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")


def write_json(path: Path, data: dict[str, Any]) -> None:
    """Write data to a file as pretty-printed JSON.

    :param path: The path of the file to write.
    :param data: The data to write.
    :return: None.
    """
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")


def write_meta(path: Path, meta: dict[str, Any]) -> None:
    """Write the metadata to the ``meta.json`` file.

    The ``BatchInfo`` values under ``batches`` are written as
    plain JSON objects.

    :param path: The path of the ``meta.json`` file.
    :param meta: The metadata to write.
    :return: None.
    """
    write_json(path, {
        **meta,
        "batches": {k: asdict(v)
                    for k, v in meta["batches"].items()}})


def sha256_of(path: Path) -> str:
    """Calculate the SHA-256 digest of a file.

    :param path: The path of the file.
    :return: The hexadecimal SHA-256 digest.
    """
    with open(path, "rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def now_iso() -> str:
    """Return the current local time in ISO 8601 format.

    :return: The current local time with the timezone offset.
    """
    return datetime.now().astimezone().isoformat(timespec="seconds")


def execute_runs(
        client: anthropic.Anthropic, items: list[InputItem],
        system_prompt: str, max_tokens: int, meta: dict[str, Any],
) -> tuple[Results, Results]:
    """Submit the two identical runs and await their results.

    The batch IDs and timestamps are recorded into the metadata as an
    observable side effect.

    :param client: The Anthropic client.
    :param items: The input items.
    :param system_prompt: The system prompt text.
    :param max_tokens: The maximum output tokens per request.
    :param meta: The metadata to record the batch bookkeeping into.
    :return: The results of run 1 and run 2, keyed by item ID.
    """
    requests: list[dict[str, Any]] = [
        build_request(x, system_prompt, max_tokens) for x in items]
    infos: dict[str, BatchInfo] = {}
    for run_name in ("run1", "run2"):
        info: BatchInfo = BatchInfo(
            batch_id=submit_batch(client, requests),
            submitted_at=now_iso())
        infos[run_name] = info
        meta["batches"][run_name] = info
        print(f"{run_name}: submitted batch {info.batch_id}",
              file=sys.stderr)
    batches: dict[str, Any] = poll_batches(
        client, [x.batch_id for x in infos.values()])
    for info in infos.values():
        info.ended_at = batches[info.batch_id].ended_at.isoformat()
    return (collect_results(client, infos["run1"].batch_id),
            collect_results(client, infos["run2"].batch_id))


def execute_arbitration(
        client: anthropic.Anthropic, items: list[InputItem],
        disagreed: list[str], run1: Results, run2: Results,
        system_prompt: str, max_tokens: int, meta: dict[str, Any],
) -> Results:
    """Submit the arbitration batch and await its results.

    The batch ID and timestamps are recorded into the metadata as an
    observable side effect.

    :param client: The Anthropic client.
    :param items: The input items.
    :param disagreed: The disagreeing item IDs.
    :param run1: The run-1 results, keyed by item ID.
    :param run2: The run-2 results, keyed by item ID.
    :param system_prompt: The arbitration system prompt text.
    :param max_tokens: The maximum output tokens per request.
    :param meta: The metadata to record the batch bookkeeping into.
    :return: The arbitration results, keyed by item ID.
    """
    content_by_id: dict[str, str] = {
        x.id: x.content for x in items}
    requests: list[dict[str, Any]] = []
    for item_id in disagreed:
        text1: str | None = run1[item_id].text
        text2: str | None = run2[item_id].text
        assert text1 is not None and text2 is not None
        requests.append(build_request(
            InputItem(id=item_id,
                      content=build_arbitration_content(
                          content_by_id[item_id], text1, text2)),
            system_prompt, max_tokens))
    info: BatchInfo = BatchInfo(
        batch_id=submit_batch(client, requests),
        submitted_at=now_iso())
    meta["batches"]["arbitration"] = info
    print(f"arbitration: submitted batch {info.batch_id}",
          file=sys.stderr)
    batches: dict[str, Any] = poll_batches(client, [info.batch_id])
    info.ended_at = batches[info.batch_id].ended_at.isoformat()
    return collect_results(client, info.batch_id)


def main(argv: list[str] | None = None) -> int:
    """Run one LLM step end-to-end.

    :param argv: The command-line arguments, or None for ``sys.argv``.
    :return: The exit status: 0 on success, non-zero on failure.
    """
    args: argparse.Namespace = parse_args(argv)
    try:
        items: list[InputItem] = load_items(args.input)
        prompt_text: str = args.prompt.read_text(encoding="utf-8")
        arbitration_text: str = args.arbitration_prompt.read_text(
            encoding="utf-8")
    except (OSError, InputFormatError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    try:
        run_dir: Path = create_archive_dir(
            args.runs_dir, args.phase, args.prompt,
            datetime.now())
    except FileExistsError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    meta_path: Path = run_dir / "meta.json"
    (run_dir / "prompt.md").write_bytes(args.prompt.read_bytes())
    (run_dir / "arbitration_prompt.md").write_bytes(
        args.arbitration_prompt.read_bytes())
    meta: dict[str, Any] = {
        "model": MODEL,
        "temperature": TEMPERATURE,
        "max_tokens": args.max_tokens,
        "thinking": THINKING,
        "prompt_path": str(args.prompt),
        "prompt_sha256": sha256_of(args.prompt),
        "arbitration_prompt_path": str(args.arbitration_prompt),
        "arbitration_prompt_sha256": sha256_of(
            args.arbitration_prompt),
        "batches": {},
        "item_count": len(items),
        "agreed_count": None,
        "agreement_rate": None,
        "dry_run": args.dry_run,
        "script_version": SCRIPT_VERSION,
    }
    if args.dry_run:
        write_meta(meta_path, meta)
        print(json.dumps(
            build_request(items[0], prompt_text, args.max_tokens),
            ensure_ascii=False, indent=2))
        print(f"dry run: archive created at {run_dir}",
              file=sys.stderr)
        return 0
    client: anthropic.Anthropic = anthropic.Anthropic(
        api_key=get_settings().ANTHROPIC_API_KEY)
    run1: Results
    run2: Results
    run1, run2 = execute_runs(
        client, items, prompt_text, args.max_tokens, meta)
    item_ids: list[str] = [x.id for x in items]
    write_jsonl(run_dir / "run1.jsonl",
                [run1[x].to_record() for x in item_ids if x in run1])
    write_jsonl(run_dir / "run2.jsonl",
                [run2[x].to_record() for x in item_ids if x in run2])
    failed: set[str] = (set(find_failures(item_ids, run1))
                        | set(find_failures(item_ids, run2)))
    if len(failed) > 0:
        write_meta(meta_path, meta)
        names: str = ", ".join(x for x in item_ids if x in failed)
        print(f"error: failed items: {names}", file=sys.stderr)
        return 1
    agreed: list[str]
    disagreed: list[str]
    agreed, disagreed = split_by_agreement(items, run1, run2)
    meta["agreed_count"] = len(agreed)
    meta["agreement_rate"] = len(agreed) / len(items)
    arbitration: Results = {}
    if len(disagreed) > 0:
        arbitration = execute_arbitration(
            client, items, disagreed, run1, run2, arbitration_text,
            args.max_tokens, meta)
    write_jsonl(run_dir / "arbitration.jsonl",
                [arbitration[x].to_record() for x in disagreed
                 if x in arbitration])
    arb_failed: list[str] = find_failures(disagreed, arbitration)
    if len(arb_failed) > 0:
        write_meta(meta_path, meta)
        names = ", ".join(arb_failed)
        print(f"error: failed arbitration items: {names}",
              file=sys.stderr)
        return 1
    write_jsonl(run_dir / "final.jsonl",
                build_final_records(items, run1, arbitration))
    write_meta(meta_path, meta)
    print(f"done: {len(items)} items, {len(agreed)} agreed,"
          f" {len(disagreed)} arbitrated; archived to {run_dir}",
          file=sys.stderr)
    return 0
