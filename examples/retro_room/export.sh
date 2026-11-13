#!/usr/bin/env bash
# Windows exe of the retro room: godot/build/RetroRoom.exe (PCK embedded). Rebuilds the art first (kiln build).
# Usage: export.sh [tag]   with a tag, also copies it to D:\cernbox\Documents\GMT\RetroRoom-<tag>-<shorthash>.exe
# SKIP_ART=1 skips the art build and exports whatever godot/assets/kiln holds.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
export PATH="$HOME/.local/bin:$PATH"
export DISPLAY=  # never a window: everything below runs headless
LOG="$(mktemp)"
trap 'rm -f "$LOG"' EXIT
hash="$(git -C "$REPO" rev-parse --short HEAD 2>/dev/null || echo unknown)"
[ -z "$(git -C "$REPO" status --porcelain -- examples/retro_room src 2>/dev/null)" ] || hash="$hash-dirty"
if [ -z "${SKIP_ART:-}" ]; then
	(cd "$HERE/art" && "$REPO/.venv/bin/kiln" build)
fi
GAME="$HERE/godot"
[ -s "$GAME/assets/kiln/manifest.json" ] || { echo "no assets/kiln/manifest.json: the art hasn't been built"; exit 1; }
godot --headless --path "$GAME" --import >"$LOG" 2>&1 || { cat "$LOG"; echo "import failed"; exit 1; }
OUT="$GAME/build/RetroRoom.exe"
mkdir -p "$(dirname "$OUT")"; rm -f "$OUT"
godot --headless --path "$GAME" --export-release Windows "$OUT" >"$LOG" 2>&1 || { cat "$LOG"; echo "export failed"; exit 1; }
if grep -E '^(ERROR|SCRIPT ERROR)' "$LOG"; then cat "$LOG"; echo "export reported errors"; exit 1; fi
[ -s "$OUT" ] || { cat "$LOG"; echo "no exe produced"; exit 1; }
echo "$OUT ($hash, $(du -h "$OUT" | cut -f1))"
if [ -n "${1:-}" ]; then
	DEST=/mnt/d/cernbox/Documents/GMT
	cp "$OUT" "$DEST/RetroRoom-$1-$hash.exe"
	echo "copied to $DEST/RetroRoom-$1-$hash.exe"
fi
