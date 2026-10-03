"""In-process CLI harness: run a cyclopts App and capture what it printed."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from io import StringIO

from cyclopts import App


@dataclass(frozen=True)
class CliResult:
    exit_code: int
    output: str


class CliRunner:
    """Invoke a cyclopts ``App`` the way the console script would.

    The App object is passed directly (``app(tokens)``), so the tests exercise
    the same parsing path as the installed command.
    """

    def invoke(self, app: App, tokens: list[str]) -> CliResult:
        buffer = StringIO()
        exit_code = 0

        with redirect_stdout(buffer), redirect_stderr(buffer):
            try:
                app(tokens)
            except SystemExit as exc:
                code = exc.code
                if isinstance(code, int):
                    exit_code = code
                elif code is None:
                    exit_code = 0
                else:
                    exit_code = 1

        return CliResult(exit_code=exit_code, output=buffer.getvalue())
