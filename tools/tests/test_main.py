# Tools for A Feminist Audit of Pop Music.
# Copyright 2026 imacat.  All rights reserved.
# Authors:
#   imacat@mail.imacat.idv.tw (imacat), 2026/7/31
# AI assistance: Claude Code (Anthropic)
"""Unit tests for the package-level CLI dispatcher."""
import argparse
import io
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from pop_fem_audit_tools import __main__, commands
from pop_fem_audit_tools.commands import run_llm


class TestDispatcher(unittest.TestCase):
    """Test cases for the package-level CLI dispatcher."""

    @staticmethod
    def __run_main(argv: list[str]) -> tuple[int, str, str]:
        """Run the dispatcher with captured output.

        :param argv: The command-line arguments.
        :return: A tuple of the exit status, the standard output,
            and the standard error.
        """
        stdout: io.StringIO = io.StringIO()
        stderr: io.StringIO = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            status: int = __main__.main(argv)
        return status, stdout.getvalue(), stderr.getvalue()

    def test_run_llm_registered(self) -> None:
        """Test that run-llm is bound to the run_llm wrapper."""
        self.assertIs(__main__.SUBCOMMANDS["run-llm"],
                      commands.run_llm_command)

    def test_every_subcommand_registered(self) -> None:
        """Test that every subcommand is bound to its wrapper."""
        for name, command in __main__.SUBCOMMANDS.items():
            with self.subTest(subcommand=name):
                wrapper: str = f"{name.replace('-', '_')}_command"
                self.assertIs(command, getattr(commands, wrapper))

    def test_run_llm_command_delegates(self) -> None:
        """Test that the run-llm wrapper calls the run_llm main."""
        tool: mock.Mock = mock.Mock(return_value=7)
        with mock.patch.object(run_llm, "main", tool):
            status: int = commands.run_llm_command(["--input", "x"])
        self.assertEqual(status, 7)
        tool.assert_called_once_with(["--input", "x"])

    def test_run_llm_command_defaults_to_none(self) -> None:
        """Test that the run-llm wrapper defaults the arguments."""
        tool: mock.Mock = mock.Mock(return_value=0)
        with mock.patch.object(run_llm, "main", tool):
            commands.run_llm_command()
        tool.assert_called_once_with(None)

    def test_run_llm_dispatch(self) -> None:
        """Test that run-llm forwards the arguments and the status."""
        tool: mock.Mock = mock.Mock(return_value=7)
        with mock.patch.dict(__main__.SUBCOMMANDS,
                             {"run-llm": tool}):
            status: int = self.__run_main(
                ["run-llm", "--input", "items.jsonl"])[0]
        self.assertEqual(status, 7)
        tool.assert_called_once_with(["--input", "items.jsonl"])

    def test_help_exits_zero_and_lists_subcommands(self) -> None:
        """Test that --help lists the subcommands and exits 0."""
        status: int
        stdout: str
        stderr: str
        status, stdout, stderr = self.__run_main(["--help"])
        self.assertEqual(status, 0)
        self.assertIn("run-llm", stdout)

    def test_no_arguments_exits_non_zero(self) -> None:
        """Test that no arguments yields the usage and non-zero."""
        status: int
        stdout: str
        stderr: str
        status, stdout, stderr = self.__run_main([])
        self.assertNotEqual(status, 0)
        self.assertIn("run-llm", stderr)

    def test_usage_prog_module_run(self) -> None:
        """Test the usage program name when run with python -m."""
        argv: list[str] = ["/x/pop_fem_audit_tools/__main__.py"]
        stdout: str
        with mock.patch.object(sys, "argv", argv):
            stdout = self.__run_main(["--help"])[1]
        self.assertIn(
            "usage: python -m pop_fem_audit_tools ", stdout)

    def test_usage_prog_console_script(self) -> None:
        """Test the usage program name when run as a script."""
        argv: list[str] = ["/x/bin/pop-fem-audit-tools"]
        stdout: str
        with mock.patch.object(sys, "argv", argv):
            stdout = self.__run_main(["--help"])[1]
        self.assertIn("usage: pop-fem-audit-tools ", stdout)

    def test_subcommand_prog_module_run(self) -> None:
        """Test the subcommand program name with python -m."""
        argv: list[str] = ["/x/pop_fem_audit_tools/__main__.py"]
        self.assertEqual(
            self.__dispatched_prog(argv),
            "python -m pop_fem_audit_tools run-llm")

    def test_subcommand_prog_console_script(self) -> None:
        """Test the subcommand program name as a script."""
        argv: list[str] = ["/x/bin/pop-fem-audit-tools"]
        self.assertEqual(
            self.__dispatched_prog(argv),
            "pop-fem-audit-tools run-llm")

    def __dispatched_prog(self, argv: list[str]) -> str:
        """Run a stub run-llm tool and return the prog it sees.

        :param argv: The value to patch ``sys.argv`` with.
        :return: The default argparse program name seen by the
            dispatched tool.
        """
        seen: list[str] = []

        def tool(tool_argv: list[str] | None) -> int:
            """Record the argparse program name and succeed.

            :param tool_argv: The tool command-line arguments.
            :return: Always 0.
            """
            parser: argparse.ArgumentParser = \
                argparse.ArgumentParser()
            seen.append(parser.prog)
            return 0

        with mock.patch.object(sys, "argv", argv), \
                mock.patch.dict(__main__.SUBCOMMANDS,
                                {"run-llm": tool}):
            self.__run_main(["run-llm"])
        return seen[0]

    def test_unknown_subcommand_exits_non_zero(self) -> None:
        """Test that an unknown subcommand errors to standard error."""
        status: int
        stdout: str
        stderr: str
        status, stdout, stderr = self.__run_main(["nonsense"])
        self.assertNotEqual(status, 0)
        self.assertIn("nonsense", stderr)
