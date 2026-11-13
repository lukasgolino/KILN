"""#254: the committed demo output says the version it was built with: the package's (a release PR that forgets to
rebuild the demo fails here)."""

from __future__ import annotations

import json
import re
from pathlib import Path

from kiln.vendor.gltf import read_glb

ROOT = Path(__file__).parent.parent
DEMO = ROOT / "examples" / "godot" / "assets" / "kiln"


def test_demo_generator_strings_match_the_package_version() -> None:
    version = re.search(r'^version = "([^"]+)"', (ROOT / "pyproject.toml").read_text(), re.M)
    assert version is not None
    want = f"kiln {version.group(1)}"
    manifest = json.loads((DEMO / "manifest.json").read_text())
    assert manifest["generator"] == want, f"manifest says {manifest['generator']}: rebuild the demo (cd examples/demo && kiln build)"
    stale = []
    for glb in sorted((DEMO / "models").glob("*.glb")):
        doc, _ = read_glb(glb.read_bytes())
        if doc["asset"].get("generator") != want:
            stale.append(f"{glb.name}: {doc['asset'].get('generator')}")
    assert not stale, f"rebuild the demo (cd examples/demo && kiln build): {stale[:5]}"
