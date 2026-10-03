"""Shared test fixtures: the CLI harness and the "never touch the network" rule."""

from __future__ import annotations

from pathlib import Path

import pytest

from .cli_test_runner import CliRunner


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _keep_room(room: str) -> str:
    """Room passthrough - keeps tests deterministic and offline."""
    return room


def _stub_runtime(room: str, data: str | None) -> tuple[str, Path]:
    """Room/data resolution without the path existence check.

    Most CLI tests mock the query itself, so the only thing ``_analyze``
    needs is a pair to hand over. Tests that care about the real behaviour
    (``test_rank_missing_data_path``) re-patch the real function.
    """
    return _keep_room(room), Path(data) if data else Path("dycap-data")


@pytest.fixture(autouse=True)
def no_network_room(monkeypatch: pytest.MonkeyPatch) -> None:
    """Neutralize the two things that would reach the network.

    Both CLIs resolve vanity room names over HTTP, and the stats CLI checks
    that --data exists before querying. Stubbing both keeps every test
    offline, fast and deterministic.
    """
    monkeypatch.setattr("dykit.collect.cli.resolve_room_id", _keep_room)
    monkeypatch.setattr("dykit.stats.runtime.resolve_room_id", _keep_room)
    monkeypatch.setattr("dykit.stats.cli.resolve_runtime", _stub_runtime)
