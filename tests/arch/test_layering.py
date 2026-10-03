"""Architectural invariants - the layering the merge depends on.

Merging five packages into one removes their boundaries, so they have to be
re-asserted somewhere executable. These tests read the source with ``ast``
(no imports, so they hold even if the package is broken) and check that the
layering stays acyclic:

    protocol   pure codec        -> imports nothing from dykit
    source     the only network  -> imports nothing from dykit
    schema     the run file      -> imports nothing from dykit
    collect    live capture      -> protocol, source, schema
    stats      offline analysis  -> schema, source

A leaf importing from an application (or ``collect`` from ``stats``) is a
cycle waiting to happen - exactly what the old five-package split prevented.
"""

from __future__ import annotations

import ast
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "src" / "dykit"

#: Layers that are packages (directories) and layers that are single modules.
PACKAGES = ("protocol", "source", "collect", "stats")
MODULES = ("schema",)
LAYERS = frozenset(PACKAGES + MODULES)

#: Layer -> the dykit layers it is allowed to import.
ALLOWED: dict[str, set[str]] = {
    "protocol": set(),
    "source": set(),
    "schema": set(),
    "collect": {"protocol", "source", "schema"},
    "stats": {"source", "schema"},
}


def _modules_in(layer: str) -> list[Path]:
    if layer in PACKAGES:
        return sorted(PACKAGE_ROOT.joinpath(layer).rglob("*.py"))
    return [PACKAGE_ROOT / f"{layer}.py"]


def _add_layer(found: set[str], dotted: str) -> None:
    """Record the dykit layer an absolute module path refers to, if any."""
    parts = dotted.split(".")
    if len(parts) > 1 and parts[0] == "dykit" and parts[1] in LAYERS:
        found.add(parts[1])


def _dykit_imports(path: Path) -> set[str]:
    """Top-level dykit layers this module imports.

    A relative import is attributed to the layer that names it, so
    ``from ..schema import x`` inside ``collect`` reads as ``collect -> schema``.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level > 0:
                # `from .x` stays inside the layer; level >= 2 reaches out.
                if node.level >= 2:
                    head = module.split(".")[0]
                    if head in LAYERS:
                        found.add(head)
                continue
            _add_layer(found, module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                _add_layer(found, alias.name)

    return found


def test_layers_exist() -> None:
    """Guard against a layer being emptied out and silently dropping its tests."""
    for layer in PACKAGES:
        assert (PACKAGE_ROOT / layer).is_dir(), f"missing layer: {layer}"
        assert _modules_in(layer), f"layer has no modules: {layer}"
    for module in MODULES:
        assert (PACKAGE_ROOT / f"{module}.py").is_file(), f"missing module: {module}"


def test_every_module_belongs_to_a_layer() -> None:
    """No source file may sit at the package root outside the declared layers."""
    known = {"__init__.py"} | {f"{module}.py" for module in MODULES}
    loose = sorted(p.name for p in PACKAGE_ROOT.glob("*.py") if p.name not in known)
    assert loose == [], f"unexpected modules at the package root: {loose}"


def test_layering_is_respected() -> None:
    violations: list[str] = []
    for layer, allowed in ALLOWED.items():
        for path in _modules_in(layer):
            illegal = _dykit_imports(path) - allowed
            if illegal:
                violations.append(
                    f"{path.relative_to(PACKAGE_ROOT).as_posix()} imports {sorted(illegal)}"
                )
    assert violations == [], "layering violations:\n" + "\n".join(violations)
