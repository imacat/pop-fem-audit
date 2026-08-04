# Tools for A Feminist Audit of Pop Music.
# Copyright 2026 imacat.  All rights reserved.
# Authors:
#   imacat@mail.imacat.idv.tw (imacat), 2026/8/4
"""Unit tests for the shared utilities module."""
import unittest

from pop_fem_audit_tools import utils


class TestUtils(unittest.TestCase):
    """Test cases for the shared utilities."""

    def test_format_duration_under_hour(self) -> None:
        """Test the mm:ss format for a duration under one hour."""
        self.assertEqual(utils.format_duration(205), "03:25")

    def test_format_duration_over_hour(self) -> None:
        """Test the h:mm:ss format once the duration reaches an
        hour."""
        self.assertEqual(utils.format_duration(6439), "1:47:19")
