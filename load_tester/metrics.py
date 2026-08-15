"""
metrics.py — Latency statistics and load-test result aggregation.

Calculates:
  - Requests per second (RPS)
  - Latency: min, max, average, p50, p99
  - Success/failure counts and error rate
  - Per-status-code breakdown
"""

import math
import threading
import time


class MetricsCollector:
    """
    Thread-safe collector for request-level timing data.

    Usage:
        collector = MetricsCollector()
        collector.start_timer()
        # ... run load test ...
        collector.stop_timer()
        summary = collector.summary()
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._latencies: list[float] = []    # ms
        self._status_counts: dict[int, int] = {}
        self._errors: int = 0
        self._successes: int = 0
        self._start_time: float = 0.0
        self._end_time: float = 0.0

    # ------------------------------------------------------------------ #
    #  Timer                                                               #
    # ------------------------------------------------------------------ #

    def start_timer(self) -> None:
        self._start_time = time.time()

    def stop_timer(self) -> None:
        self._end_time = time.time()

    def mark_end_now(self) -> None:
        """Update end time to current moment (for live snapshots)."""
        self._end_time = time.time()

    # ------------------------------------------------------------------ #
    #  Recording                                                           #
    # ------------------------------------------------------------------ #

    def record(self, latency_ms: float, status_code: int) -> None:
        success = 200 <= status_code < 400
        with self._lock:
            self._latencies.append(latency_ms)
            self._status_counts[status_code] = self._status_counts.get(status_code, 0) + 1
            if success:
                self._successes += 1
            else:
                self._errors += 1

    # ------------------------------------------------------------------ #
    #  Summary                                                             #
    # ------------------------------------------------------------------ #

    def summary(self) -> dict:
        with self._lock:
            lats = list(self._latencies)
            status_counts = dict(self._status_counts)
            successes = self._successes
            errors = self._errors

        total = len(lats)
        duration = max(0.001, self._end_time - self._start_time)
        rps = total / duration if total > 0 else 0.0

        if not lats:
            return {
                "total_requests":     0,
                "successful":         0,
                "errors":             0,
                "error_rate_pct":     0.0,
                "duration_seconds":   round(duration, 2),
                "rps":                0.0,
                "p50":                0.0,
                "p99":                0.0,
                "latency_min_ms":     0.0,
                "latency_max_ms":     0.0,
                "latency_avg_ms":     0.0,
                "status_codes":       {},
            }

        sorted_lats = sorted(lats)

        def percentile(p: float) -> float:
            k = (len(sorted_lats) - 1) * p
            lo, hi = math.floor(k), math.ceil(k)
            if lo == hi:
                return sorted_lats[lo]
            return sorted_lats[lo] * (hi - k) + sorted_lats[hi] * (k - lo)

        return {
            "total_requests":   total,
            "successful":       successes,
            "errors":           errors,
            "error_rate_pct":   round(errors / total * 100, 2) if total else 0.0,
            "duration_seconds": round(duration, 2),
            "rps":              round(rps, 2),
            "p50":              round(percentile(0.50), 2),
            "p99":              round(percentile(0.99), 2),
            "latency_min_ms":   round(sorted_lats[0], 2),
            "latency_max_ms":   round(sorted_lats[-1], 2),
            "latency_avg_ms":   round(sum(sorted_lats) / len(sorted_lats), 2),
            "status_codes":     status_counts,
        }
