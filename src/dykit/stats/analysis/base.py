"""The analysis plugin protocol.

An analysis is a named, parameterised query over the run-file corpus,
described by the SQL it needs plus, optionally, a single streaming pass over
the rows. The constraint that shapes everything here:

    **Work must be pushed into SQL whenever it can be.**

An analysis that only exposed ``rows -> result`` in Python would re-read the
whole corpus and degrade into a full scan plus a Python loop - exactly the
regression the storage layer exists to avoid. So the primary artefact is a
:class:`Query`; :meth:`Analysis.rows_to_result` is for the irreducible
remainder (incremental top-N, streaming similarity) and may only make one
pass.

Options are a per-analysis frozen dataclass so a plugin body stays fully
typed; the protocol boundary is deliberately loose and each implementation
narrows it with a single cast.

Register built-ins in ``dykit.stats.analysis.builtins``; third parties can
register through the ``dykit.analysis`` entry-point group.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Literal, Protocol, cast

ParamKind = Literal["str", "int", "float", "bool"]


@dataclass(frozen=True)
class Param:
    """One CLI-exposed option of an analysis."""

    name: str
    kind: ParamKind
    default: object
    help: str

    @property
    def flag(self) -> str:
        return "--" + self.name.replace("_", "-")


@dataclass(frozen=True)
class Query:
    """A SELECT against ``danmaku_all``, with qmark parameters."""

    sql: str
    params: tuple[object, ...] = ()
    columns: tuple[str, ...] = ()


class Analysis(Protocol):
    """A named, parameterised query over the run-file corpus."""

    @property
    def name(self) -> str:
        """Command-visible identifier, e.g. ``latest_unique``."""
        ...

    @property
    def summary(self) -> str:
        """One line shown in help."""
        ...

    @property
    def params(self) -> tuple[Param, ...]:
        """Declarative description of the options this analysis accepts."""
        ...

    def make_options(self, **overrides: object) -> object:
        """Validate and build this analysis typed options object."""
        ...

    def build_query(self, options: object) -> Query:
        """Translate options into SQL. All filtering belongs here."""
        ...

    def rows_to_result(self, rows: Iterator[sqlite3.Row], options: object) -> object:
        """Stream the query result into the shape a renderer expects."""
        ...


def run(analysis: Analysis, db: object, **overrides: object) -> object:
    """Build the query, execute it once, and stream the result."""
    options = analysis.make_options(**overrides)
    query = analysis.build_query(options)
    execute = cast("Any", db).query
    return analysis.rows_to_result(iter(execute(query.sql, query.params)), options)
