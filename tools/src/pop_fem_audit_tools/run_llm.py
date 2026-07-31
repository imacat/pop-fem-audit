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
``runs/<phase>/<YYYYMMDD-HHMM>-<prompt-stem>/``.
"""
import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import anthropic

type Item = dict[str, str]
"""An input item with "id" and "content"."""

type Result = dict[str, Any]
"""One batch result record."""

type Results = dict[str, Result]
"""The batch result records, keyed by item ID."""

MODEL: str = "claude-sonnet-4-6"
TEMPERATURE: float = 0.0
THINKING: dict[str, str] = {"type": "disabled"}
SCRIPT_VERSION: str = "run_llm.py 1.0.0"
POLL_INTERVAL_SECONDS: float = 60.0
ARBITRATION_TEMPLATE: str = (
    "<item>\n{content}\n</item>\n"
    "<run1>\n{run1}\n</run1>\n"
    "<run2>\n{run2}\n</run2>")


class InputFormatError(Exception):
    """An error in the JSONL input file."""


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Parse the command-line arguments.

    :param argv: The command-line arguments, or None for ``sys.argv``.
    :return: The parsed arguments.
    """
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description="Run one LLM step: 2 runs + 1 arbitration.")
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


def validate_item(data: Any, path: Path, number: int) -> Item:
    """Validate one parsed JSONL record as an input item.

    :param data: The parsed JSON value of the line.
    :param path: The path of the JSONL input file, for the messages.
    :param number: The line number, for the messages.
    :return: The validated item with "id" and "content".
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
    return {"id": data["id"], "content": data["content"]}


def load_items(path: Path) -> list[Item]:
    """Load and validate the JSONL input items.

    :param path: The path of the JSONL input file.
    :return: The items, each with "id" and "content", in file order.
    :raises InputFormatError: When a line is malformed, an ID is
        duplicated, or the file contains no item.
    :raises OSError: When the file cannot be read.
    """
    items: list[Item] = []
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
            item: Item = validate_item(data, path, number)
            if item["id"] in seen:
                raise InputFormatError(
                    f"{path}: line {number}: duplicated ID"
                    f" \"{item['id']}\"")
            seen.add(item["id"])
            items.append(item)
    if len(items) == 0:
        raise InputFormatError(f"{path}: no input items")
    return items


def parse_env_file(path: Path) -> dict[str, str]:
    """Parse a simple KEY=VALUE .env file.

    Blank lines and lines starting with "#" are ignored.

    :param path: The path of the .env file.
    :return: The key-value pairs; empty when the file is missing.
    """
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped: str = line.strip()
        if stripped == "" or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        values[key.strip()] = value.strip()
    return values


def resolve_api_key(env_path: Path) -> str:
    """Resolve the Anthropic API key.

    The ``ANTHROPIC_API_KEY`` environment variable takes precedence;
    the .env file is consulted as a fallback.

    :param env_path: The path of the .env file.
    :return: The API key.
    :raises RuntimeError: When no API key can be found.
    """
    key: str | None = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key
    key = parse_env_file(env_path).get("ANTHROPIC_API_KEY")
    if key:
        return key
    raise RuntimeError(
        "ANTHROPIC_API_KEY is not set in the environment and not"
        f" found in {env_path}")


def build_request(item: Item, system_prompt: str,
                  max_tokens: int) -> dict[str, Any]:
    """Build one Message Batches request for an input item.

    :param item: The input item with "id" and "content".
    :param system_prompt: The system prompt text.
    :param max_tokens: The maximum output tokens.
    :return: The batch request with "custom_id" and "params".
    """
    return {
        "custom_id": item["id"],
        "params": {
            "model": MODEL,
            "max_tokens": max_tokens,
            "temperature": TEMPERATURE,
            "thinking": THINKING,
            "system": system_prompt,
            "messages": [
                {"role": "user", "content": item["content"]},
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
    if hasattr(usage, "model_dump"):
        return {k: v for k, v in usage.model_dump().items()
                if v is not None}
    return dict(usage)


def collect_results(client: anthropic.Anthropic,
                    batch_id: str) -> Results:
    """Collect the results of an ended batch.

    A succeeded result carries "text", "stop_reason", and "usage";
    any other result carries "error" instead.

    :param client: The Anthropic client.
    :param batch_id: The batch ID.
    :return: The result records, keyed by custom ID.
    """
    results: Results = {}
    for entry in client.messages.batches.results(batch_id):
        result: Any = entry.result
        record: Result
        match result.type:
            case "succeeded":
                message: Any = result.message
                text: str = "".join(
                    x.text for x in message.content
                    if x.type == "text")
                record = {"id": entry.custom_id, "text": text,
                          "stop_reason": message.stop_reason,
                          "usage": usage_to_dict(message.usage)}
            case "errored":
                error_type: Any = getattr(
                    result.error, "type", "unknown")
                record = {"id": entry.custom_id,
                          "error": str(error_type)}
            case other:
                record = {"id": entry.custom_id,
                          "error": str(other)}
        results[entry.custom_id] = record
    return results


def find_failures(item_ids: list[str],
                  results: Results) -> list[str]:
    """Find the item IDs that failed in a result set.

    An item failed when it is missing from the results or when its
    record carries an "error" field.

    :param item_ids: The item IDs to check, in order.
    :param results: The result records, keyed by item ID.
    :return: The failed item IDs, in the given order.
    """
    return [x for x in item_ids
            if x not in results or "error" in results[x]]


def split_by_agreement(
        items: list[Item], run1: Results, run2: Results,
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
        item_id: str = item["id"]
        text1: str = run1[item_id]["text"].strip()
        text2: str = run2[item_id]["text"].strip()
        if text1 == text2:
            agreed.append(item_id)
        else:
            disagreed.append(item_id)
    return agreed, disagreed


def build_final_records(
        items: list[Item], run1: Results, arbitration: Results,
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
        item_id: str = item["id"]
        if item_id in arbitration:
            records.append({"id": item_id,
                            "text": arbitration[item_id]["text"],
                            "source": "arbitration"})
        else:
            records.append({"id": item_id,
                            "text": run1[item_id]["text"].strip(),
                            "source": "agreed"})
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
    stem: str = prompt_path.name
    if stem.endswith(".md"):
        stem = stem[:-len(".md")]
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
    """
    with open(path, "w", encoding="utf-8") as file:
        for record in records:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")


def write_json(path: Path, data: dict[str, Any]) -> None:
    """Write data to a file as pretty-printed JSON.

    :param path: The path of the file to write.
    :param data: The data to write.
    """
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")


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


def format_timestamp(value: Any) -> str:
    """Format a timestamp value from a batch object as a string.

    :param value: The timestamp: a datetime, a string, or None.
    :return: The timestamp as a string, or the current local time
        when the value is missing.
    """
    match value:
        case datetime():
            return value.isoformat()
        case str():
            return value
        case _:
            return now_iso()


def execute_runs(
        client: anthropic.Anthropic, items: list[Item],
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
    batch_ids: dict[str, str] = {}
    for run_name in ("run1", "run2"):
        batch_id: str = submit_batch(client, requests)
        batch_ids[run_name] = batch_id
        meta["batches"][run_name] = {
            "batch_id": batch_id, "submitted_at": now_iso(),
            "ended_at": None}
        print(f"{run_name}: submitted batch {batch_id}",
              file=sys.stderr)
    batches: dict[str, Any] = poll_batches(
        client, list(batch_ids.values()))
    for run_name, batch_id in batch_ids.items():
        meta["batches"][run_name]["ended_at"] = format_timestamp(
            getattr(batches[batch_id], "ended_at", None))
    return (collect_results(client, batch_ids["run1"]),
            collect_results(client, batch_ids["run2"]))


def execute_arbitration(
        client: anthropic.Anthropic, items: list[Item],
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
        x["id"]: x["content"] for x in items}
    requests: list[dict[str, Any]] = [
        build_request(
            {"id": x,
             "content": build_arbitration_content(
                 content_by_id[x], run1[x]["text"], run2[x]["text"])},
            system_prompt, max_tokens)
        for x in disagreed]
    batch_id: str = submit_batch(client, requests)
    meta["batches"]["arbitration"] = {
        "batch_id": batch_id, "submitted_at": now_iso(),
        "ended_at": None}
    print(f"arbitration: submitted batch {batch_id}", file=sys.stderr)
    batches: dict[str, Any] = poll_batches(client, [batch_id])
    meta["batches"]["arbitration"]["ended_at"] = format_timestamp(
        getattr(batches[batch_id], "ended_at", None))
    return collect_results(client, batch_id)


def main(argv: list[str] | None = None) -> int:
    """Run one LLM step end-to-end.

    :param argv: The command-line arguments, or None for ``sys.argv``.
    :return: The exit status: 0 on success, non-zero on failure.
    """
    args: argparse.Namespace = parse_args(argv)
    try:
        items: list[Item] = load_items(args.input)
        prompt_text: str = args.prompt.read_text(encoding="utf-8")
        arbitration_text: str = args.arbitration_prompt.read_text(
            encoding="utf-8")
    except (OSError, InputFormatError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    try:
        run_dir: Path = create_archive_dir(
            Path("runs"), args.phase, args.prompt, datetime.now())
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
        write_json(meta_path, meta)
        print(json.dumps(
            build_request(items[0], prompt_text, args.max_tokens),
            ensure_ascii=False, indent=2))
        print(f"dry run: archive created at {run_dir}",
              file=sys.stderr)
        return 0
    try:
        api_key: str = resolve_api_key(Path(".env"))
    except RuntimeError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    client: anthropic.Anthropic = anthropic.Anthropic(
        api_key=api_key)
    run1: Results
    run2: Results
    run1, run2 = execute_runs(
        client, items, prompt_text, args.max_tokens, meta)
    item_ids: list[str] = [x["id"] for x in items]
    write_jsonl(run_dir / "run1.jsonl",
                [run1[x] for x in item_ids if x in run1])
    write_jsonl(run_dir / "run2.jsonl",
                [run2[x] for x in item_ids if x in run2])
    failed: set[str] = (set(find_failures(item_ids, run1))
                        | set(find_failures(item_ids, run2)))
    if len(failed) > 0:
        write_json(meta_path, meta)
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
                [arbitration[x] for x in disagreed
                 if x in arbitration])
    arb_failed: list[str] = find_failures(disagreed, arbitration)
    if len(arb_failed) > 0:
        write_json(meta_path, meta)
        names = ", ".join(arb_failed)
        print(f"error: failed arbitration items: {names}",
              file=sys.stderr)
        return 1
    write_jsonl(run_dir / "final.jsonl",
                build_final_records(items, run1, arbitration))
    write_json(meta_path, meta)
    print(f"done: {len(items)} items, {len(agreed)} agreed,"
          f" {len(disagreed)} arbitrated; archived to {run_dir}",
          file=sys.stderr)
    return 0
