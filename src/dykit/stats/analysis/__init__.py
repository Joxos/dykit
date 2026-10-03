"""Analysis plugins.

An analysis is a named, parameterised SQL query over the run-file corpus. The
built-ins live in :mod:`dykit.stats.analysis.builtins`; third parties register
through the ``dykit.analysis`` entry-point group.

The design rule that matters: push the work into SQL. ``build_query`` does the
filtering and aggregation; ``rows_to_result`` may only make a single streaming
pass over whatever the query returned.
"""

from __future__ import annotations

from .base import Analysis, Param, Query, run
from .builtins import BUILTINS
from .registry import available, get, load_entry_points, register, reset

for _builtin in BUILTINS:
    register(_builtin, replace=True)

__all__ = [
    "Analysis",
    "Param",
    "Query",
    "available",
    "get",
    "load_entry_points",
    "register",
    "reset",
    "run",
]
