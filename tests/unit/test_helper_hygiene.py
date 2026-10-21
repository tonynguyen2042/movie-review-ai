"""One name, one meaning: no helper is defined in two test files.

T161. There was no root `tests/conftest.py`, and 134 helper functions were
spread across the suite with **51 names duplicated between files** —
`_harness` in twelve, `_script` in ten, `_paragraph` in eight, `_scene` in
seven, `_events` in nine.

The duplicates were not all identical: several of them were near enough
the same that a change to one should have been a change to the other, and
a reader who saw `_paragraph` in two files had to work out which one was
in play.

The rule now is simple: a helper name is defined in exactly one place.
The builders that several files want live in `tests/helpers.py`; a helper
that belongs to one file stays in that file, under a name that says so.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _is_fixture(decorator: ast.expr) -> bool:
    """Whether a decorator marks a fixture, called or bare."""
    if isinstance(decorator, ast.Call):
        decorator = decorator.func
    return isinstance(decorator, ast.Attribute) and decorator.attr == "fixture"


def _test_files() -> list[Path]:
    return sorted((ROOT / "tests").rglob("test_*.py"))


def _helper_definitions() -> dict[str, list[str]]:
    """Every module-level helper, and the files that define it."""
    found: dict[str, list[str]] = {}
    for path in _test_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name.startswith("_"):
                found.setdefault(node.name, []).append(str(path.relative_to(ROOT)))
    return found


def test_no_helper_name_is_defined_in_two_files() -> None:
    """Fifty-one names were duplicated."""
    found = _helper_definitions()
    duplicated = {name: paths for name, paths in found.items() if len(paths) > 1}
    assert not duplicated, f"these helpers are defined more than once: {duplicated}"


def test_the_shared_builders_live_in_one_module() -> None:
    """The builders that several files want are shared, not copied."""
    module = ROOT / "tests" / "helpers.py"
    assert module.is_file(), "there is no shared helper module"

    tree = ast.parse(module.read_text(encoding="utf-8"))
    shared = {
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name.startswith("_")
    }
    assert shared, "the shared helper module is empty"

    # Every shared builder is used by at least one file: a shared helper
    # nobody uses is dead code in a shared place.
    used: dict[str, set[str]] = {}
    for path in _test_files():
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and node.module == "tests.helpers":
                for alias in node.names:
                    used.setdefault(alias.name, set()).add(str(path.relative_to(ROOT)))
    for name in shared:
        assert used.get(name), f"{name} is shared but no file uses it"


def test_the_shared_fixtures_live_in_the_root_conftest() -> None:
    """The fixtures that span the suite are in one place."""
    root_conftest = ROOT / "tests" / "conftest.py"
    assert root_conftest.is_file(), "there is no root conftest"

    tree = ast.parse(root_conftest.read_text(encoding="utf-8"))
    fixtures = {
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and any(_is_fixture(decorator) for decorator in node.decorator_list)
    }
    assert fixtures, "the root conftest defines no fixtures"

    # No sub-directory defines a fixture of the same name.
    for path in (ROOT / "tests").rglob("conftest.py"):
        if path == root_conftest:
            continue
        sub_tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in sub_tree.body:
            if not isinstance(node, ast.FunctionDef):
                continue
            if not any(_is_fixture(decorator) for decorator in node.decorator_list):
                continue
            assert node.name not in fixtures, (
                f"{path.relative_to(ROOT)} defines the fixture {node.name}, "
                "which the root conftest also defines"
            )
