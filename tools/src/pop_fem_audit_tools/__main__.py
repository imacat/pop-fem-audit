# Tools for A Feminist Audit of Pop Music.
# Copyright 2026 imacat.  All rights reserved.
# Authors:
#   imacat@mail.imacat.idv.tw (imacat), 2026/7/31
# AI assistance: Claude Code (Anthropic)
"""The package-level command-line entry point.

Dispatches ``python -m pop_fem_audit_tools <subcommand>`` or the
console script ``pop-fem-audit-tools <subcommand>`` to the main
function of the corresponding tool module.
"""
import os.path
import sys
from collections.abc import Callable
from importlib.machinery import ModuleSpec
from types import ModuleType

from .commands import (
    build_db_command,
    cluster_keywords_command,
    export_llm_input_command,
    fetch_artists_command,
    fetch_lyrics_command,
    run_llm_command,
    tally_annotations_command,
    tally_codings_command,
    tally_groups_command,
)

MODULE_PROG: str = "python -m pop_fem_audit_tools"
"""The program name when run with ``python -m``."""

SUBCOMMANDS: dict[str, Callable[[list[str] | None], int]] = {
    "build-db": build_db_command,
    "cluster-keywords": cluster_keywords_command,
    "export-llm-input": export_llm_input_command,
    "fetch-artists": fetch_artists_command,
    "fetch-lyrics": fetch_lyrics_command,
    "run-llm": run_llm_command,
    "tally-annotations": tally_annotations_command,
    "tally-codings": tally_codings_command,
    "tally-groups": tally_groups_command,
}
"""The dispatch table from the subcommand name to the tool main."""


def prog() -> str:
    """Return the program name shown in the usage messages.

    :return: ``python -m pop_fem_audit_tools`` when run with
        ``python -m``, or the basename of ``sys.argv[0]`` when run
        as a console script.
    """
    if sys.argv[0].endswith("__main__.py"):
        return MODULE_PROG
    return os.path.basename(sys.argv[0])


def usage() -> str:
    """Return the usage text listing the available subcommands.

    :return: The usage text.
    """
    lines: list[str] = [
        f"usage: {prog()} <subcommand> [<argument>...]",
        "",
        "subcommands:"]
    lines.extend(f"  {x}" for x in SUBCOMMANDS)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Dispatch a subcommand to its tool module.

    :param argv: The command-line arguments, or None for ``sys.argv``.
    :return: The exit status: the status of the subcommand, 0 for the
        usage help, or non-zero on a usage error.
    """
    args: list[str] = sys.argv[1:] if argv is None else argv
    if len(args) == 0:
        print("error: missing subcommand", file=sys.stderr)
        print(usage(), file=sys.stderr)
        return 2
    if args[0] in ("-h", "--help"):
        print(usage())
        return 0
    if args[0] not in SUBCOMMANDS:
        print(f"error: unknown subcommand \"{args[0]}\"",
              file=sys.stderr)
        print(usage(), file=sys.stderr)
        return 2
    prog_backup: str = sys.argv[0]
    main_module: ModuleType = sys.modules["__main__"]
    spec_backup: ModuleSpec | None = main_module.__spec__
    sys.argv[0] = f"{prog()} {args[0]}"
    main_module.__spec__ = None
    try:
        return SUBCOMMANDS[args[0]](args[1:])
    finally:
        sys.argv[0] = prog_backup
        main_module.__spec__ = spec_backup


if __name__ == "__main__":
    sys.exit(main())
