from __future__ import annotations

import pytest

from .cli_test_runner import CliRunner


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()
