"""Contract: every setting is exposed on the CLI, with the setting's default.

This is what makes ``CaptureSettings`` a single source of truth rather than
documentation: adding a field there fails this test until the CLI exposes it,
and the CLI default is checked to equal the dataclass default so the two
cannot drift.
"""

from __future__ import annotations

import inspect

from dykit.collect.cli import collect
from dykit.collect.settings import SETTINGS, CaptureSettings

_COMMANDS = [collect]


def _signature_params(command: object) -> dict[str, inspect.Parameter]:
    return dict(inspect.signature(command).parameters)  # type: ignore[arg-type]


def test_every_setting_is_a_cli_parameter() -> None:
    missing = [
        name
        for name in CaptureSettings.__dataclass_fields__
        if name not in _signature_params(collect)
    ]
    assert missing == [], f"settings not exposed on the CLI: {missing}"


def test_cli_defaults_match_the_settings_dataclass() -> None:
    drifted = [
        f"{name}: cli={param.default!r} settings={getattr(SETTINGS, name)!r}"
        for name, param in _signature_params(collect).items()
        if name in CaptureSettings.__dataclass_fields__
        and param.default is not inspect.Parameter.empty
        and param.default != getattr(SETTINGS, name)
    ]
    assert drifted == [], "CLI default drifted from CaptureSettings:\n" + "\n".join(drifted)


def test_room_stays_required() -> None:
    """A required setting must not be given a default that silently runs the wrong room."""
    assert _signature_params(collect)["room"].default is inspect.Parameter.empty


def test_rotate_after_default_is_one_million() -> None:
    """Sharding is on by default, at the agreed threshold."""
    assert SETTINGS.rotate_after == 1_000_000
    assert _signature_params(collect)["rotate_after"].default == 1_000_000


def test_flush_interval_default_bounds_crash_loss() -> None:
    """A killed process may only lose what is still in the memory buffer."""
    assert SETTINGS.flush_interval <= 0.5
