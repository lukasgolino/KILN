#!/usr/bin/env bash
# Runs a command that needs a rendering Godot (engine renders, colour checks) OFFSCREEN: a private virtual X display
# (Xvfb) with Mesa's CPU drivers (lavapipe for Vulkan, llvmpipe for OpenGL), so no window opens on the desktop and the
# GPU is never touched. A machine-wide lock keeps it to one such run at a time; LP_NUM_THREADS caps the CPU it takes.
# Usage: tools/godot_window.sh godot --path . -s script.gd -- ...
set -euo pipefail
LOCK="${KILN_WINDOW_LOCK:-/tmp/kiln-godot-window.lock}"
LVP="/usr/share/vulkan/icd.d/lvp_icd.json"
command -v xvfb-run >/dev/null || { echo "godot_window.sh: needs xvfb (sudo apt install -y xvfb); refusing to open a window" >&2; exit 1; }
[ -f "$LVP" ] || { echo "godot_window.sh: needs Mesa lavapipe ($LVP, package mesa-vulkan-drivers)" >&2; exit 1; }
export VK_ICD_FILENAMES="$LVP" VK_DRIVER_FILES="$LVP" LP_NUM_THREADS="${LP_NUM_THREADS:-2}" LIBGL_ALWAYS_SOFTWARE=1 GALLIUM_DRIVER=llvmpipe
exec flock "$LOCK" env -u WAYLAND_DISPLAY xvfb-run -a -s "-screen 0 1280x720x24" "$@"
