"""Run costs: peak memory and wall time for `kiln build` / `kiln lint`, and progress lines on long model builds."""

from __future__ import annotations

import importlib.util
import os
import sys
import threading
import time
from collections.abc import Callable

PROGRESS_ENV = "KILN_PROGRESS"  # set by the CLI for human output (inherited by lint's worker processes)
QUIET_SECONDS = 10.0  # a model build says what it is doing only once it has run this long
LONG_SECONDS = 120.0  # a phase projected to take longer than this says so at once, with what would make it faster
MANY_PARTS = 100  # a model with this many parts prints its first phase line at once (its build is rarely short)


Progress = Callable[[str, int, int], None]  # (what, done, total): how far a long step is


def duration(seconds: float) -> str:
    """A rough duration for ETAs: 40 s, 3 min, 1.5 h."""
    if seconds < 90:
        return f"{seconds:.0f} s"
    if seconds < 5400:
        return f"{seconds / 60:.0f} min"
    return f"{seconds / 3600:.1f} h"


def peak_gb() -> float | None:
    """Peak resident memory of this process and of its finished children (lint workers), whichever is bigger."""
    try:
        import resource
    except ImportError:  # Windows
        return None
    scale = 1024**3 if sys.platform == "darwin" else 1024**2  # macOS reports bytes, Linux kilobytes
    peak = max(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss, resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss)
    return round(peak / scale, 2)


SLOW_SECONDS = 20.0  # past this, a run without kiln-gen[fast] says what the extra would save


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
        self.loud = False  # print every phase line at once (a big model: MANY_PARTS)
        self.phase_start = self.start  # when the current phase began (ETAs)
        self._warned: set[str] = set()  # phases that already said they'll be long
        self._eta: tuple[str, int, int, float] | None = None  # the last progress: (label, done, total, expected end)
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
                self._say(self._counted() or self.current)

    def _counted(self) -> str | None:
        """The last progress with its time left counted down to now (the heartbeat's line), if it's still current."""
        if self._eta is None or not self.current.startswith(self._eta[0]):
            return None
        label, done, total, end = self._eta
        left = end - time.monotonic()
        return f"{label} {done}/{total}, " + (f"about {duration(left)} left" if left > 0 else "past the estimate")

    def _say(self, what: str, now: bool = False) -> None:
        with self._lock:
            elapsed = time.monotonic() - self.start
            if (now or self.loud or elapsed >= QUIET_SECONDS) and not self._stop.is_set():
                self.last = elapsed
                print(f"kiln: {self.name}: {what} ({elapsed:.0f} s)", file=sys.stderr, flush=True)

    def __call__(self, what: str) -> None:
        self.current = what
        self.phase_start = time.monotonic()
        self._eta = None
        if self.on:
            self._say(what)

    def progress(self, label: str, done: int, total: int, hint: str = "") -> None:
        """How far a long phase is (done of total) and roughly how long it has left, at most every QUIET_SECONDS. When
        the projection passes LONG_SECONDS the phase says so at once (once), with `hint`: what would make it faster."""
        spent = time.monotonic() - self.phase_start
        left = spent / done * (total - done) if 0 < done < total and spent > 1.0 else None
        what = f"{label} {done}/{total}" + (f", about {duration(left)} left" if left is not None else "")
        self._eta = (label, done, total, time.monotonic() + left) if left is not None else None
        if self.on and left is not None and spent + left > LONG_SECONDS and label not in self._warned:
            self._warned.add(label)
            self.current = what
            self._say(f"{what}: a long build{'; ' + hint if hint else ''}", now=True)
            return
        self.within(what)

    def within(self, what: str) -> None:
        """Progress inside a long phase: a line at most every QUIET_SECONDS."""
        self.current = what
        if self.on and time.monotonic() - self.start - self.last >= QUIET_SECONDS:
            self._say(what)


__all__ = ["LONG_SECONDS", "MANY_PARTS", "PROGRESS_ENV", "Phases", "Progress", "cost_line", "duration", "peak_gb"]
