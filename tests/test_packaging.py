"""PyPI and MCP Registry metadata stay in step (#155): the registry checks server.json against the PyPI release."""

import json
import tomllib
from pathlib import Path

import kiln

ROOT = Path(__file__).resolve().parent.parent


def test_server_json_matches_pyproject_and_readme() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    server = json.loads((ROOT / "server.json").read_text())
    (package,) = server["packages"]
    assert server["version"] == package["version"] == project["version"]
    assert package["identifier"] == project["name"]
    assert project["name"] in project["scripts"]  # uvx runs the command named like the package
    assert f"<!-- mcp-name: {server['name']} -->" in (ROOT / "README.md").read_text()


def test_installed_version_is_the_project_version() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    assert kiln.__version__ == project["version"]


def test_install_hints_name_the_pypi_distribution() -> None:
    """Hints like `pip install "kiln[extra]"` would point at another project's name on PyPI."""
    stale = [f"{p.relative_to(ROOT)}:{n}" for p in (ROOT / "src" / "kiln").rglob("*") if p.is_file() and p.suffix in {".py", ".md", ".toml", ".gd"}
             for n, line in enumerate(p.read_text(errors="ignore").splitlines(), 1) if "kiln[" in line and "-gen[" not in line]
    assert not stale, stale
