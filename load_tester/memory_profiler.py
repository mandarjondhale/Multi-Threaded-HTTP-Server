"""
memory_profiler.py — tracemalloc-based memory leak assessor.

Runs a background thread that takes tracemalloc snapshots at configurable
intervals and computes the allocation delta between consecutive snapshots.
After a load test, call report() to get a ranked list of the top memory-
growing call-sites and an overall memory-growth trend (bytes/second).

Usage:
    profiler = MemoryProfiler(interval=2.0, top_n=10)
    profiler.start()
    # ... run load test ...
    profiler.stop()
    report = profiler.report()
"""

import tracemalloc
import threading
import time
from collections import defaultdict


class MemoryProfiler:
    """
    Periodic tracemalloc snapshotter with delta analysis.

    Parameters
    ----------
    interval  : seconds between snapshots (default 2.0)
    top_n     : top allocating call-sites to include in report (default 10)
    """

    def __init__(self, interval: float = 2.0, top_n: int = 10):
        self.interval = interval
        self.top_n = top_n

        self._snapshots: list[tuple[float, tracemalloc.Snapshot]] = []
        self._running = False
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------------ #
    #  Lifecycle                                                           #
    # ------------------------------------------------------------------ #

    def start(self) -> None:
        if not tracemalloc.is_tracing():
            tracemalloc.start(10)    # keep 10-frame tracebacks
        self._snapshots.clear()
        self._running = True
        self._thread = threading.Thread(
            target=self._loop,
            name="MemoryProfilerThread",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=self.interval + 1.0)
        # Take a final snapshot
        self._take_snapshot()

    def _loop(self) -> None:
        while self._running:
            self._take_snapshot()
            time.sleep(self.interval)

    def _take_snapshot(self) -> None:
        try:
            snap = tracemalloc.take_snapshot()
            self._snapshots.append((time.time(), snap))
        except Exception as exc:
            print(f"[MemoryProfiler] snapshot error: {exc}")

    # ------------------------------------------------------------------ #
    #  Analysis                                                            #
    # ------------------------------------------------------------------ #

    def report(self) -> dict:
        """
        Compute memory growth report from collected snapshots.

        Returns
        -------
        dict with keys:
          snapshot_count, total_duration_seconds, growth_bytes,
          growth_rate_bytes_per_sec, peak_kb, top_sites (list of dicts)
        """
        snaps = self._snapshots
        if len(snaps) < 2:
            return {
                "snapshot_count": len(snaps),
                "note": "Not enough snapshots for delta analysis (need ≥ 2).",
            }

        t_start, first = snaps[0]
        t_end,   last  = snaps[-1]
        duration = max(0.001, t_end - t_start)

        # Compare last vs. first snapshot
        stats = last.compare_to(first, "lineno")

        # Total size delta across all tracked allocations
        total_growth_bytes = sum(s.size_diff for s in stats)

        # Peak current memory usage (last snapshot)
        last_stats = last.statistics("lineno")
        peak_kb = sum(s.size for s in last_stats) / 1024

        # Top N growing call sites
        top_sites = []
        for stat in sorted(stats, key=lambda s: s.size_diff, reverse=True)[: self.top_n]:
            top_sites.append({
                "file":          str(stat.traceback[0].filename) if stat.traceback else "unknown",
                "line":          stat.traceback[0].lineno if stat.traceback else 0,
                "size_diff_kb":  round(stat.size_diff / 1024, 2),
                "count_diff":    stat.count_diff,
            })

        # Leak signal: classify growth rate
        growth_rate = total_growth_bytes / duration
        if growth_rate > 50_000:
            leak_signal = "HIGH — likely memory leak"
        elif growth_rate > 10_000:
            leak_signal = "MEDIUM — elevated allocation rate"
        else:
            leak_signal = "LOW — allocation rate normal"

        return {
            "snapshot_count":            len(snaps),
            "total_duration_seconds":    round(duration, 2),
            "growth_bytes":              total_growth_bytes,
            "growth_rate_bytes_per_sec": round(growth_rate, 1),
            "peak_kb":                   round(peak_kb, 1),
            "leak_signal":               leak_signal,
            "top_growing_sites":         top_sites,
        }
