from __future__ import annotations

from pathlib import Path
import importlib.util
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = REPO_ROOT / "tools" / "check_imports.py"


def _load_tool():
    spec = importlib.util.spec_from_file_location("check_imports_tool", TOOL_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


check_imports = _load_tool()


class RepositoryImportTests(unittest.TestCase):
    def test_every_intra_package_import_in_this_repository_resolves(self) -> None:
        self.assertEqual(check_imports.find_unresolved_imports(), [])


class SyntheticTreeTests(unittest.TestCase):
    """Pin the behaviours that make the check useful rather than noisy."""

    def _check(self, **files: str) -> list[tuple[str, str, str]]:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "custom_components"
            for relative, source in files.items():
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(source, encoding="utf-8")
            return check_imports.find_unresolved_imports(root)

    def test_missing_name_is_reported(self) -> None:
        problems = self._check(
            **{
                "pkg/__init__.py": "",
                "pkg/leaf.py": "VALUE = 1\n",
                # Imports a name `leaf` never defines.
                "pkg/user.py": "from .leaf import VALUE, MISSING\n",
            }
        )

        self.assertEqual(problems, [("pkg.user", "pkg.leaf", "MISSING")])

    def test_import_from_package_init_is_checked(self) -> None:
        """Regression guard: package __init__ imports once resolved to nothing.

        Treating ``pkg/__init__.py`` as living in a package named ``pkg.__init__``
        made every import inside it resolve to a non-existent
        ``pkg.__init__.leaf`` and be skipped, so the exact regression this tool
        exists to catch went unreported.
        """

        problems = self._check(
            **{
                "pkg/leaf.py": "VALUE = 1\n",
                "pkg/__init__.py": "from .leaf import VALUE, MISSING\n",
            }
        )

        self.assertEqual(problems, [("pkg.__init__", "pkg.leaf", "MISSING")])

    def test_type_checking_only_import_is_ignored(self) -> None:
        problems = self._check(
            **{
                "pkg/__init__.py": "",
                "pkg/leaf.py": "VALUE = 1\n",
                "pkg/user.py": (
                    "from typing import TYPE_CHECKING\n"
                    "if TYPE_CHECKING:\n"
                    "    from .leaf import OnlyForTypeCheckers\n"
                ),
            }
        )

        self.assertEqual(problems, [])

    def test_optional_import_guard_is_ignored(self) -> None:
        problems = self._check(
            **{
                "pkg/__init__.py": "",
                "pkg/leaf.py": "VALUE = 1\n",
                "pkg/user.py": (
                    "try:\n"
                    "    from .leaf import VALUE, MAYBE_MISSING\n"
                    "except ImportError:\n"
                    "    MAYBE_MISSING = None\n"
                ),
            }
        )

        self.assertEqual(problems, [])

    def test_lazy_module_getattr_satisfies_any_name(self) -> None:
        problems = self._check(
            **{
                "pkg/leaf.py": (
                    "def __getattr__(name):\n"
                    "    raise AttributeError(name)\n"
                ),
                "pkg/__init__.py": "from .leaf import Coerced\n",
            }
        )

        self.assertEqual(problems, [])

    def test_submodule_import_resolves_without_reexport(self) -> None:
        """`from package import submodule` works without an `__init__` re-export."""

        problems = self._check(
            **{
                "pkg/__init__.py": "",
                "pkg/sub.py": "VALUE = 1\n",
                "pkg/user.py": "from . import sub\n",
            }
        )

        self.assertEqual(problems, [])

    def test_reexported_import_satisfies_the_contract(self) -> None:
        problems = self._check(
            **{
                "pkg/__init__.py": "",
                "pkg/leaf.py": "VALUE = 1\n",
                "pkg/mid.py": "from .leaf import VALUE\n",
                "pkg/user.py": "from .mid import VALUE\n",
            }
        )

        self.assertEqual(problems, [])


if __name__ == "__main__":
    unittest.main()
