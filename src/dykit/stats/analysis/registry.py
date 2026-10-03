"""Analysis registry.

Built-ins register on import; third parties arrive through the
``dykit.analysis`` entry-point group, so an analysis can live outside this
package without any registration code in dykit itself.
"""

from __future__ import annotations

import logging
from importlib.metadata import entry_points

from .base import Analysis

logger: logging.Logger = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "dykit.analysis"

_REGISTRY: dict[str, Analysis] = {}


def register(analysis: Analysis, *, replace: bool = False) -> None:
    """Make an analysis available by name."""
    if analysis.name in _REGISTRY and not replace:
        raise ValueError(f"analysis {analysis.name!r} is already registered")
    _REGISTRY[analysis.name] = analysis


def get(name: str) -> Analysis:
    """Look up an analysis by name, loading entry points on first miss."""
    if name not in _REGISTRY:
        load_entry_points()
    try:
        return _REGISTRY[name]
    except KeyError:
        known = ", ".join(sorted(_REGISTRY)) or "none"
        raise KeyError(f"unknown analysis {name!r}; available: {known}") from None


def available() -> tuple[str, ...]:
    """Every registered analysis name, sorted."""
    load_entry_points()
    return tuple(sorted(_REGISTRY))


_loaded = False


def reset() -> None:
    """Forget that entry points were already scanned (tests, long-lived hosts)."""
    global _loaded
    _loaded = False


def load_entry_points() -> None:
    """Register every plugin advertised in the ``dykit.analysis`` group."""
    global _loaded
    if _loaded:
        return
    _loaded = True
    try:
        found = entry_points(group=ENTRY_POINT_GROUP)
    except Exception:
        logger.debug("could not enumerate %s entry points", ENTRY_POINT_GROUP, exc_info=True)
        return
    for entry in found:
        try:
            candidate = entry.load()
            register(candidate(), replace=True)
        except Exception:
            logger.warning("could not load analysis plugin %s", entry.name, exc_info=True)
