from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from io import StringIO
from typing import Any


@dataclass(frozen=True)
class CliResult:
    exit_code: int
    output: str


class CliRunner:
    def invoke(self, command: Any, args: list[str]) -> CliResult:
        buffer = StringIO()
        exit_code = 0

        entry = getattr(command, "main", command)

        with redirect_stdout(buffer), redirect_stderr(buffer):
            try:
                entry(args=args)
            except SystemExit as exc:
                code = exc.code
                if isinstance(code, int):
                    exit_code = code
                elif code is None:
                    exit_code = 0
                else:
                    exit_code = 1

        return CliResult(exit_code=exit_code, output=buffer.getvalue())
