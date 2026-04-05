"""Tests for the config module."""

import os
from unittest.mock import patch

from investment_researcher.config import PROJECT_ROOT


class TestConfig:
    def test_project_root_exists(self):
        assert PROJECT_ROOT.exists()

    def test_project_root_contains_pyproject(self):
        assert (PROJECT_ROOT / "pyproject.toml").exists()
