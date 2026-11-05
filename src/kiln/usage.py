"""Run costs: peak memory and wall time for `kiln build` / `kiln lint`, and progress lines on long model builds."""

from __future__ import annotations

import os
import sys
import time

PROGRESS_ENV = "KILN_PROGRESS"  # set by the CLI for human output (inherited by lint's worker processes)
QUIET_SECONDS = 10.0  # a model build says what it is doing only once it has run this long


def peak_gb() -> float | None:
    """Peak resident memory of this process and of its finished children (lint workers), whichever is bigger."""
    try:
        import resource
    except ImportError:  # Windows
        return None
    scale = 1024**3 if sys.platform == "darwin" else 1024**2  # macOS reports bytes, Linux kilobytes
    peak = max(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss, resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss)
    return round(peak / scale, 2)


def cost_line(seconds: float) -> str:
    peak = peak_gb()
    return f"{seconds:.0f} s" + (f", peak memory {peak:.1f} GB" if peak is not None else "")


class Phases:
    """Progress for one model build: a stderr line per phase, but only once the build has taken QUIET_SECONDS
    (short builds stay silent: agents pay for every line)."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.start = time.monotonic()
        self.on = os.environ.get(PROGRESS_ENV) == "1"

    def __call__(self, what: str) -> None:
        if not self.on:
            return
        elapsed = time.monotonic() - self.start
        if elapsed >= QUIET_SECONDS:
            print(f"kiln: {self.name}: {what} ({elapsed:.0f} s)", file=sys.stderr, flush=True)


__all__ = ["PROGRESS_ENV", "Phases", "cost_line", "peak_gb"]
