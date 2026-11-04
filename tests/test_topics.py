"""`kiln docs` and the token budgets that keep the skill cheap for agents."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from kiln import topics as docs
from kiln.cli import main


def run_json(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, dict[str, Any]]:
    code = main(["--json", *argv])
    return code, json.loads(capsys.readouterr().out)

SKILL = Path(__file__).parent.parent / "src" / "kiln" / "skill"

# Budgets in bytes (about 4 per token). The core is loaded whenever the skill triggers and stays in context for
# the whole session, so it is the expensive one; topics are read on demand.
SKILL_CORE_BYTES = 8_000
TOPIC_BYTES = 16_000
DESCRIPTION_CHARS = 420


def test_skill_core_budget() -> None:
    size = len((SKILL / "SKILL.md").read_bytes())
    assert size <= SKILL_CORE_BYTES, f"SKILL.md is {size} bytes: move detail into a topic"


def test_skill_description_budget() -> None:
    line = next(line for line in (SKILL / "SKILL.md").read_text().splitlines() if line.startswith("description: "))
    assert len(line) - len("description: ") <= DESCRIPTION_CHARS


@pytest.mark.parametrize("topic", [t.name for t in docs.topics()])
def test_topic_budget_and_shape(topic: str) -> None:
    found = docs.find(topic)
    assert found is not None and found.text.startswith("# ") and found.summary
    assert len(found.text.encode()) <= TOPIC_BYTES, f"{topic} is {len(found.text.encode())} bytes: split it"


def test_core_names_every_topic() -> None:
    core = (SKILL / "SKILL.md").read_text()
    assert all(f"`{t.name}`" in core for t in docs.topics())


def test_docs_list_print_search(capsys: pytest.CaptureFixture[str]) -> None:
    code, data = run_json(["docs"], capsys)
    assert code == 0 and {"parts", "rigs", "lint"} <= {t["name"] for t in data["topics"]}
    code, data = run_json(["docs", "parts"], capsys)
    assert code == 0 and data["topics"][0]["text"].startswith("# Parts")
    code, data = run_json(["docs", "--search", "blend", "radius"], capsys)
    assert code == 0 and 1 <= len(data["hits"]) <= 5
    assert all(len(h["text"]) < 2000 for h in data["hits"])  # paragraphs, not whole topics


def test_docs_unknown_topic_suggests(capsys: pytest.CaptureFixture[str]) -> None:
    code, data = run_json(["docs", "part"], capsys)
    assert code != 0 and "parts" in data["findings"][0]["message"]


def test_status_is_terse_by_default(capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(Path(__file__).parent.parent / "examples" / "demo")
    assert main(["status"]) == 0
    terse = capsys.readouterr().out
    assert main(["status", "-v"]) == 0
    verbose = capsys.readouterr().out
    assert len(terse) < len(verbose) / 2
    assert main(["--json", "status"]) == 0
    raw = capsys.readouterr().out
    assert raw.count("\n") == 1 and '"description"' not in raw  # compact JSON, descriptions only with -v
