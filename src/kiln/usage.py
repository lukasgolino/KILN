"""Run costs: peak memory and wall time for `kiln build` / `kiln lint`, and progress lines on long model builds."""

from __future__ import annotations

import importlib.util
import os
import sys
import threading
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


SLOW_SECONDS = 20.0  # past this, a run without kiln[fast] says what the extra would save


def cost_line(seconds: float) -> str:
    peak = peak_gb()
    line = f"{seconds:.0f} s" + (f", peak memory {peak:.1f} GB" if peak is not None else "")
    if seconds >= SLOW_SECONDS and importlib.util.find_spec("numba") is None:  # #99 (not when KILN_JIT=0 pins numpy)
        line += "; meshing runs faster with pip install 'kiln-gen[fast]'"
    return line


class Phases:
    """Progress for one model build: a stderr line per phase, but only once the build has taken QUIET_SECONDS
    (short builds stay silent: agents pay for every line). As a context manager it also keeps a heartbeat: a phase
    that runs on says so again every QUIET_SECONDS, so a long build is never silent for longer than that (#99)."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.start = time.monotonic()
        self.on = os.environ.get(PROGRESS_ENV) == "1"
        self.last = 0.0  # when the last line was printed (seconds into the build)
        self.current = "meshing"
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._beat: threading.Thread | None = None

    def __enter__(self) -> Phases:
        if self.on:
            self._beat = threading.Thread(target=self._heartbeat, daemon=True)
            self._beat.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        if self._beat is not None:
            self._beat.join()

    def _heartbeat(self) -> None:
        while not self._stop.wait(min(1.0, QUIET_SECONDS / 4)):
            if time.monotonic() - self.start - self.last >= QUIET_SECONDS:
                self._say(self.current)

    def _say(self, what: str) -> None:
        with self._lock:
            elapsed = time.monotonic() - self.start
            if elapsed >= QUIET_SECONDS and not self._stop.is_set():
                self.last = elapsed
                print(f"kiln: {self.name}: {what} ({elapsed:.0f} s)", file=sys.stderr, flush=True)

    def __call__(self, what: str) -> None:
        self.current = what
        if self.on:
            self._say(what)

    def within(self, what: str) -> None:
        """Progress inside a long phase: a line at most every QUIET_SECONDS."""
        self.current = what
        if self.on and time.monotonic() - self.start - self.last >= QUIET_SECONDS:
            self._say(what)


__all__ = ["PROGRESS_ENV", "Phases", "cost_line", "peak_gb"]
