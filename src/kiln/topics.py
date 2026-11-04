"""`kiln docs`: the skill's topic files (`skill/topics/*.md`), listed, printed one at a time or searched by
paragraph, so an agent reads only the part of the documentation its task needs.
The same code as PAGAN's `topics.py` and SEGAN's `docs.py`: port fixes between them on purpose."""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from importlib.resources import files

CHARS_PER_TOKEN = 4  # rough, for the sizes `kiln docs` lists


@dataclass(frozen=True)
class Topic:
    name: str
    summary: str  # the topic file's first paragraph after its title
    text: str

    @property
    def tokens(self) -> int:
        return len(self.text) // CHARS_PER_TOKEN


@dataclass(frozen=True)
class Hit:
    topic: str
    heading: str
    text: str
    score: float


def topics() -> list[Topic]:
    folder = files("kiln").joinpath("skill", "topics")
    out = []
    for entry in sorted(folder.iterdir(), key=lambda e: e.name):
        if not entry.name.endswith(".md"):
            continue
        text = entry.read_text(encoding="utf-8")
        paragraphs = [p for p in text.split("\n\n") if p.strip()]
        summary = paragraphs[1].strip() if len(paragraphs) > 1 and not paragraphs[1].startswith("#") else ""
        out.append(Topic(entry.name.removesuffix(".md"), summary, text))
    return out


def find(name: str) -> Topic | None:
    return next((t for t in topics() if t.name == name.lower().strip()), None)


def close_matches(name: str) -> list[str]:
    return difflib.get_close_matches(name.lower(), [t.name for t in topics()], n=3, cutoff=0.5)


def _blocks(topic: Topic) -> list[tuple[str, str]]:
    """(nearest heading, block) for each blank-line-separated block; a fenced code block stays whole."""
    out: list[tuple[str, str]] = []
    heading = topic.name
    current: list[str] = []
    in_code = False

    def flush() -> None:
        if current and "".join(current).strip():
            out.append((heading, "\n".join(current).strip()))
        current.clear()

    for line in topic.text.split("\n"):
        if line.startswith("```"):
            in_code = not in_code
        if not in_code and line.startswith("#"):
            flush()
            heading = line.lstrip("#").strip()
            continue
        if not in_code and not line.strip():
            flush()
            continue
        if not in_code and re.match(r"^\s*(?:- |\d+\. |\| )", line) and current and not current[-1].lstrip().startswith("|"):
            flush()  # each list item (and a table) is its own block
        current.append(line)
    flush()
    return out


LONG_BLOCK = 700  # characters; a longer block is cut down to its matching sentences


def _trim(block: str, patterns: list[re.Pattern[str]]) -> str:
    if len(block) <= LONG_BLOCK:
        return block
    if block.startswith("|"):  # a long table: its header and the matching rows
        rows = block.split("\n")
        return "\n".join(rows[:2] + [r for r in rows[2:] if any(p.search(r) for p in patterns)])
    if block.startswith("```"):  # a long example: the matching lines with one line around them, gaps marked
        lines = block.split("\n")
        keep = {0, len(lines) - 1}
        for i, line in enumerate(lines):
            if any(p.search(line) for p in patterns):
                keep |= {i - 1, i, i + 1}
        out: list[str] = []
        previous = -1
        for i in sorted(k for k in keep if 0 <= k < len(lines)):
            if previous >= 0 and i > previous + 1:
                out.append("...")
            out.append(lines[i])
            previous = i
        return "\n".join(out)
    sentences = re.split(r"(?<=[.;!?])\s+(?=[A-Z`*(])|,\s+(?=[WE]\d{3}\b)", re.sub(r"\s*\n\s*", " ", block))
    kept = [s for s in sentences if any(p.search(s) for p in patterns)]
    return " ... ".join(kept) if kept else block[:LONG_BLOCK] + " ..."


def search(query: str, limit: int = 5) -> list[Hit]:
    """Blocks that contain the most of the query's words (whole words, case-insensitive), best first. Words
    found in the heading count half."""
    words = [w for w in re.findall(r"[\w./-]+", query.lower()) if len(w) > 1]
    if not words:
        return []
    patterns = [re.compile(rf"(?<![\w]){re.escape(w)}(?![\w])", re.IGNORECASE) for w in words]
    hits: list[Hit] = []
    for topic in topics():
        for heading, block in _blocks(topic):
            score = 0.0
            for pattern in patterns:
                if pattern.search(block):
                    score += 1
                elif pattern.search(heading):
                    score += 0.5
            if score >= max(1.0, len(words) / 2):
                hits.append(Hit(topic.name, heading, _trim(block, patterns), score - len(block) / 100000))
    hits.sort(key=lambda h: -h.score)
    return hits[:limit]
