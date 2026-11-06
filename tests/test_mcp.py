"""`kiln mcp`: tools return the CLI's JSON, previews come back as images, paths stay inside the project."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from conftest import SPHERE
from mcp.types import CallToolResult, ImageContent, TextContent

from kiln.mcp_server import create_server
from kiln.project import Project


def call(project: Project, tool: str, args: dict[str, Any] | None = None, allow_godot: bool = False) -> tuple[dict[str, Any], int]:
    """(the JSON result, how many images came with it)."""
    server = create_server(project.root, allow_godot)
    result = asyncio.run(server.call_tool(tool, args or {}))
    assert isinstance(result, CallToolResult)
    texts = [c.text for c in result.content if isinstance(c, TextContent)]
    images = len([c for c in result.content if isinstance(c, ImageContent)])
    data: dict[str, Any] = json.loads(texts[0])
    return data, images


def test_tools_are_listed(project: Project) -> None:
    tools = {t.name for t in asyncio.run(create_server(project.root).list_tools())}
    assert {"status", "write_model", "preview", "lint", "build", "lineup", "gallery", "style_write", "import_model", "pack_list", "pack_search",
            "pack_import"} <= tools
    assert "pack_add" not in tools  # downloading stays an explicit CLI command


def test_write_model_lints_and_returns_a_turntable(project: Project) -> None:
    result, images = call(project, "write_model", {"name": "ball", "text": SPHERE.format(name="ball")})
    assert result["lint"]["ok"] and images == 1
    status, _ = call(project, "status")
    assert [m["name"] for m in status["models"]] == ["ball"]


def test_bad_model_returns_findings_not_an_image(project: Project) -> None:
    result, images = call(project, "write_model", {"name": "bad", "text": "name: bad\nparts:\n  - sphere: { radius: -1 }\n"})
    assert not result["ok"] and images == 0 and any(f["rule"] == "E003" for f in result["findings"])


def test_preview_kinds_and_godot_gate(project: Project) -> None:
    call(project, "write_model", {"name": "ball", "text": SPHERE.format(name="ball"), "preview": False})
    result, images = call(project, "preview", {"model": "ball", "which": "closeup"})
    assert not result["ok"]  # closeup needs a part
    result, images = call(project, "preview", {"model": "ball", "which": "engine"})
    assert not result["ok"] and "allow-godot" in result["findings"][0]["message"]
    result, images = call(project, "preview", {"model": "ball"})
    assert result["ok"] and images == 1


def test_paths_stay_inside_the_project(project: Project) -> None:
    result, _ = call(project, "import_model", {"file": "../../etc/passwd", "licence": "CC0-1.0"})
    assert not result["ok"] and "outside" in result["findings"][0]["message"]
    result, _ = call(project, "read_model", {"name": "../x"})
    assert not result["ok"]


def test_docs_and_feedback(project: Project) -> None:
    call(project, "write_doc", {"doc": "BRIEF.md", "text": "# Art brief\n"})
    call(project, "log_feedback", {"note": "rounder hats"})
    docs, _ = call(project, "read_docs")
    assert "rounder hats" in docs["BRIEF.md"]


def test_tool_list_stays_small(project: Project) -> None:
    """#94: a client that loads every tool pays for the list on every request: no schema titles, no generic output
    schemas, only non-default hints, one-line descriptions (the docs tool has the detail)."""
    tools = asyncio.run(create_server(project.root).list_tools())
    wire = json.dumps([t.model_dump(by_alias=True, exclude_none=True) for t in tools])
    assert len(wire) < 10_500, len(wire)  # 15.1k before
    assert '"title"' not in json.dumps([t.input_schema for t in tools])
    assert all(t.output_schema is None for t in tools)
    status = next(t for t in tools if t.name == "status")
    assert status.annotations is not None and status.annotations.read_only_hint and status.annotations.destructive_hint is None
    write = next(t for t in tools if t.name == "write_model")
    assert write.annotations is not None and write.annotations.destructive_hint is None and write.annotations.idempotent_hint
    assert max(len(t.description or "") for t in tools) < 300
