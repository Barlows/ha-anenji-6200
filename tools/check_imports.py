#!/usr/bin/env python3
"""Verify every intra-package relative import resolves to a real name.

Why this exists
---------------
Two real breakages shipped past ``compileall`` and past the unit suite's
import-time guards before this check existed:

* ``collector/transport/common.py`` lost three module-level private constants
  (``_WRITER_CLOSE_TIMEOUT`` and two AT-text timeouts) when their values were
  externalised to ``const.py`` -- the assignments were replaced by comments
  instead of being rebound -- while ``collector/transport/__init__.py`` still
  imported them. That broke ``import custom_components.eybond_local`` for the
  whole ``tests_ha`` lane.
* A dataclass moved into a new module was deleted from its old home without
  being carried over, leaving a dangling re-export.

Neither is caught by ``py_compile``/``compileall``, which never resolve
imports. This check resolves them statically, on any Python version, so it can
run in the stub-based quality gate where importing the package is not possible.

It honours the ways a name can legitimately exist without being a plain
module-level definition:

* ``if TYPE_CHECKING:`` imports, which never execute;
* ``try: ... except ImportError:`` optional-dependency guards;
* ``from package import submodule``, which resolves via the submodule even when
  the package ``__init__`` never re-exports it; and
* PEP 562 module ``__getattr__`` lazy re-exports, which resolve any name.

Exit codes: 0 when clean, 1 when any import cannot be resolved.
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CUSTOM_COMPONENTS = REPO_ROOT / "custom_components"

_TRY_NODES = tuple(
    node for node in (getattr(ast, "Try", None), getattr(ast, "TryStar", None)) if node
)


def _module_name(path: Path, root: Path) -> str:
    """Return the dotted module name for a file under ``custom_components``."""

    return ".".join(path.relative_to(root).with_suffix("").parts)


def _resolve(root: Path, dotted: str) -> Path | None:
    """Return the file implementing ``dotted``, or None if there is none."""

    base = root / Path(dotted.replace(".", "/"))
    candidate = base.with_suffix(".py")
    if candidate.exists():
        return candidate
    package = base / "__init__.py"
    if package.exists():
        return package
    return None


def _is_type_checking(test: ast.expr) -> bool:
    return "TYPE_CHECKING" in ast.unparse(test)


def _analyse(path: Path) -> tuple[set[str], bool]:
    """Return the module-level names a file defines, plus whether it is lazy.

    Names introduced by ``from x import Y`` count: a module that re-exports an
    import is a legitimate way to satisfy this contract, and that is exactly
    what ``collector/transport/__init__.py`` does.
    """

    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as exc:  # pragma: no cover - compileall reports these
        raise SystemExit(f"{path}: syntax error: {exc}") from exc

    names: set[str] = set()
    lazy = False

    def walk(body: list[ast.stmt]) -> None:
        nonlocal lazy
        for node in body:
            if isinstance(node, ast.If) and _is_type_checking(node.test):
                continue  # type-checker-only import
            if isinstance(node, _TRY_NODES):
                # Optional-import guards define a fallback, not a hard import.
                for handler in node.handlers:
                    walk(handler.body)
                continue
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                names.add(node.name)
                if node.name == "__getattr__":
                    lazy = True
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        names.add(target.id)
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                names.add(node.target.id)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    names.add(alias.asname or alias.name.split(".")[0])
            elif isinstance(node, (ast.If, ast.While, ast.For)):
                walk(node.body)
                walk(node.orelse)

    walk(tree.body)
    return names, lazy


def _relevant_imports(tree: ast.Module) -> list[ast.ImportFrom]:
    """Return the relative ``from ... import`` statements that run at import time.

    Two constructs make an import statement irrelevant to resolution and must be
    skipped here as well as in the target analysis:

    * ``if TYPE_CHECKING:`` blocks, which never execute; and
    * ``try: ... except ImportError:`` blocks, where a missing name is a
      deliberate optional dependency rather than a broken import.

    Imports nested in a function or class body are kept: a deferred import
    still has to resolve when it is reached.
    """

    found: list[ast.ImportFrom] = []

    def visit(body: list[ast.stmt]) -> None:
        for node in body:
            if isinstance(node, ast.If) and _is_type_checking(node.test):
                continue
            if isinstance(node, _TRY_NODES):
                continue
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                visit(node.body)
            elif isinstance(node, (ast.With, ast.AsyncWith)):
                visit(node.body)
            elif isinstance(node, (ast.If, ast.While, ast.For)):
                visit(node.body)
                visit(node.orelse)
            elif isinstance(node, ast.ImportFrom):
                found.append(node)

    visit(tree.body)
    return found


def find_unresolved_imports(root: Path | None = None) -> list[tuple[str, str, str]]:
    """Return every (importer, target module, name) that cannot be resolved.

    ``root`` defaults to this repository's ``custom_components`` directory; it
    is overridable so the check can be exercised against a synthetic tree.
    """

    root = CUSTOM_COMPONENTS if root is None else root
    cache: dict[str, tuple[set[str], bool]] = {}
    problems: list[tuple[str, str, str]] = []

    for path in sorted(root.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        me = _module_name(path, root)
        # An ``__init__.py`` *is* its package, so both cases drop the final
        # component: for ``pkg/__init__.py`` that is the literal ``__init__``,
        # and for ``pkg/mod.py`` it is the module name. Getting this wrong
        # makes every import inside a package ``__init__`` resolve to nothing
        # and get silently skipped -- which is precisely where the
        # ``_WRITER_CLOSE_TIMEOUT`` regression lived.
        package = me.split(".")[:-1]

        for node in _relevant_imports(tree):
            if not node.level:
                continue
            base = (
                package[: len(package) - (node.level - 1)]
                if node.level > 1
                else package
            )
            target_name = ".".join(base + ([node.module] if node.module else []))
            target = _resolve(root, target_name)
            if target is None:
                continue
            key = str(target)
            if key not in cache:
                cache[key] = _analyse(target)
            available, lazy = cache[key]
            for alias in node.names:
                if alias.name == "*" or alias.name in available or lazy:
                    continue
                # `from package import submodule` resolves even when the
                # package __init__ never re-exports it: the import system
                # falls back to importing the submodule itself.
                if target.name == "__init__.py" and (
                    _resolve(root, f"{target_name}.{alias.name}") is not None
                ):
                    continue
                problems.append((me, target_name, alias.name))

    return sorted(problems)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--list",
        action="store_true",
        help="print the unresolved imports instead of only reporting a verdict",
    )
    args = parser.parse_args()

    problems = find_unresolved_imports()
    if args.list:
        for importer, target, name in problems:
            print(f"{importer}: cannot import {name!r} from {target}")
    if problems:
        print(
            f"Unresolved intra-package imports: {len(problems)}",
            file=sys.stderr,
        )
        return 1
    print("Imports OK: every intra-package relative import resolves")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())