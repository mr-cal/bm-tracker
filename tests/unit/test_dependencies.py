"""Every third-party import must be a declared runtime dependency.

This exists because of a bug that only existed in the container.

`bm_tracker.notes.embeddings` imports `httpx`. It was not declared in
`pyproject.toml`. It worked in every local run, every test, and every
screenshot, because `uvicorn[standard]` happens to depend on httpx and so it
was in the development virtualenv. The container installs the *resolved* set,
and there httpx was absent — so the app imported fine until the first request
touched a route that reached that module, and the worker died on boot with a
ModuleNotFoundError. Three deploys, each a full restart of a shared box, to
find a missing line in a dependency list.

The dev environment hides this class of bug by construction, because it
contains every package anyone has ever installed. Only the image has the
resolved set. So the check has to be static, and it belongs here rather than
in whatever runs the build.

The mapping below is the awkward part: a distribution and the module it
provides are often not the same name. `argon2-cffi` provides `argon2`,
`jinja2` provides `markupsafe`, `fastapi` provides `starlette`. Listing them
explicitly is the honest way to say "this one is covered, and by that".
"""

from __future__ import annotations

import ast
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

#: Modules that a declared distribution provides under a different name.
PROVIDED_BY: dict[str, str] = {
    "argon2": "argon2_cffi",
    "markupsafe": "jinja2",
    "starlette": "fastapi",
}


def _distribution_name(requirement: str) -> str:
    """Return the bare distribution name from a requirement string.

    Args:
        requirement: A PEP 508 requirement, e.g. `uvicorn[standard]>=0.34`.

    Returns:
        The name lowercased with hyphens turned into underscores.

    """
    return (
        requirement.split("[", maxsplit=1)[0]
        .split(";", maxsplit=1)[0]
        .strip()
        .split(">", 1)[0]
        .split("<", 1)[0]
        .split("=", 1)[0]
        .split("~", 1)[0]
        .replace("-", "_")
        .lower()
    )


def _declared() -> set[str]:
    """Return every runtime dependency's bare name.

    Returns:
        The declared distribution names, underscored.

    """
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    return {_distribution_name(dep) for dep in project["dependencies"]}


def _imported_modules() -> dict[str, str]:
    """Return every third-party module the application imports.

    Returns:
        The module name mapped to one file that imports it.

    """
    found: dict[str, str] = {}
    for path in sorted((ROOT / "bm_tracker").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module.split(".")[0]]
            for name in names:
                if (
                    name not in sys.stdlib_module_names
                    and name != "bm_tracker"
                    and not name.startswith("_")
                ):
                    found.setdefault(name, path.relative_to(ROOT).as_posix())
    return found


@pytest.mark.parametrize("module", sorted(_imported_modules()))
def test_every_import_is_something_the_image_will_have(module: str) -> None:
    """A module with no declared provider is a module the container will not have.

    Args:
        module: The imported module name.

    """
    declared = _declared()
    provider = PROVIDED_BY.get(module, module)

    assert provider in declared, (
        f"{module} is imported by {_imported_modules()[module]} but nothing "
        f"declared in pyproject.toml provides it. It works locally only "
        f"because the development virtualenv contains it transitively; the "
        f"image installs the resolved set and the worker will die on boot."
    )
