"""Every tunable knob of ``dykit-capture``, in one place.

This dataclass is the single source of truth for defaults. The CLI signature
re-declares types and help text, but reads its defaults from here, so a setting
can only exist in one place.

The contract "every field is exposed as a CLI option" is enforced by
``tests/collect/test_settings_cli.py`` - add a field here and the test fails
until the CLI exposes it.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any, Literal


@dataclass(frozen=True)
class CaptureSettings:
    """Capture-side settings. All of them are CLI-overridable."""

    # --- target -----------------------------------------------------------
    room: str = ""
    ws_url: str | None = None

    # --- sink -------------------------------------------------------------
    storage: Literal["sqlite", "csv", "console"] = "sqlite"
    output: str | None = None

    # --- message filters --------------------------------------------------
    msg_types_include: str | None = None
    msg_types_exclude: str | None = None

    # --- write path --------------------------------------------------------
    #: Roll over to a new run file after this many messages. The socket, the
    #: heartbeat and the in-flight buffer are untouched - the swap is a single
    #: pointer assignment, so a rollover loses nothing and duplicates nothing.
    #: 0 disables rollover.
    rotate_after: int = 1_000_000
    #: Messages buffered before an automatic commit.
    batch_size: int = 100
    #: Max seconds between automatic commits. This is also the upper bound on
    #: how much a killed process can lose, so it is deliberately small.
    flush_interval: float = 0.2

    # --- diagnostics ------------------------------------------------------
    verbose: bool = False
    debug_discovery: bool = False
    #: Stop cleanly after this many seconds. 0 runs until a signal. Useful for
    #: scripted captures, smoke tests, and rehearsing a restart by hand.
    stop_after: float = 0.0


SETTINGS = CaptureSettings()


def defaults() -> dict[str, Any]:
    """Field name -> default value, for reuse by CLI signatures and tests."""
    return {field.name: getattr(SETTINGS, field.name) for field in fields(CaptureSettings)}


def names() -> tuple[str, ...]:
    """Every setting name, in declaration order."""
    return tuple(field.name for field in fields(CaptureSettings))
