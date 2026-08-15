"""
generator.py — Closed-loop multi-threaded HTTP load generator.

"Closed-loop" means each virtual client thread:
  1. Sends a request
  2. Waits for the full response
  3. Immediately sends the next request
  …until the test duration elapses.

This accurately models think-time-zero workloads and prevents unbounded
request queuing that occurs with open-loop generators.

After the test finishes a bottleneck report is written to reports/.

API
---
    load_tester.start(url, threads, duration, ramp_up)
    load_tester.stop()
    load_tester.status()          → live metrics snapshot (dict)
"""

import os
import time
import threading
import urllib.request
import urllib.error
from load_tester.metrics import MetricsCollector


REPORTS_DIR = os.path.join(os.path.dirname(__file__), "..", "reports")


class LoadTester:
    """Singleton-style closed-loop load generator."""

    def __init__(self):
        self._lock = threading.Lock()
        self._running = False
        self._url = ""
        self._threads = 0
        self._duration = 0
        self._end_time = 0.0
        self._start_ts = 0.0
        self._collector = MetricsCollector()
        self._worker_threads: list[threading.Thread] = []

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    def start(
        self,
        url: str = "http://127.0.0.1:8080/workload/cpu?intensity=500",
        threads: int = 20,
        duration: int = 15,
        ramp_up: int = 0,
    ) -> dict:
        with self._lock:
            if self._running:
                return {"status": "error", "message": "A load test is already running"}

            self._url = url
            self._threads = max(1, min(threads, 500))
            self._duration = max(1, min(duration, 600))
            self._collector = MetricsCollector()
            self._collector.start_timer()
            self._start_ts = time.time()
            self._end_time = self._start_ts + self._duration
            self._running = True
            self._worker_threads = []

            for i in range(self._threads):
                # Optional linear ramp-up: stagger thread launches
                if ramp_up > 0:
                    time.sleep(ramp_up / self._threads)
                t = threading.Thread(
                    target=self._worker,
                    name=f"LTWorker-{i + 1}",
                    daemon=True,
                )
                self._worker_threads.append(t)
                t.start()

            # Monitor thread — stops everything when time is up
            monitor = threading.Thread(
                target=self._monitor,
                name="LTMonitor",
                daemon=True,
            )
            monitor.start()

            return {
                "status":   "started",
                "url":      self._url,
                "threads":  self._threads,
                "duration": self._duration,
                "ramp_up":  ramp_up,
            }

    def stop(self) -> dict:
        with self._lock:
            if not self._running:
                return {"status": "idle", "message": "No test is running"}
            self._running = False
        self._finalize()
        return {"status": "stopped"}

    def status(self) -> dict:
        with self._lock:
            running = self._running
            remaining = max(0.0, round(self._end_time - time.time(), 1)) if running else 0.0

        self._collector.mark_end_now()
        return {
            "running":                  running,
            "url":                      self._url,
            "threads":                  self._threads,
            "time_remaining_seconds":   remaining,
            "metrics":                  self._collector.summary(),
        }

    # ------------------------------------------------------------------ #
    #  Internal                                                            #
    # ------------------------------------------------------------------ #

    def _worker(self) -> None:
        """Closed-loop: send → wait → send → … until end_time."""
        while self._running and time.time() < self._end_time:
            t0 = time.perf_counter()
            status_code = 0
            try:
                req = urllib.request.Request(
                    self._url,
                    headers={"User-Agent": "PyMTWebServer-LoadTester/1.0"},
                )
                with urllib.request.urlopen(req, timeout=10.0) as resp:
                    status_code = resp.getcode()
                    resp.read()
            except urllib.error.HTTPError as e:
                status_code = e.code
            except Exception:
                status_code = 500

            latency_ms = (time.perf_counter() - t0) * 1_000
            self._collector.record(latency_ms, status_code)

    def _monitor(self) -> None:
        """Wait until test duration elapses, then finalize."""
        while self._running and time.time() < self._end_time:
            time.sleep(0.2)

        with self._lock:
            was_running = self._running
            self._running = False

        if was_running:
            self._finalize()

    def _finalize(self) -> None:
        """Collect metrics and write bottleneck report."""
        self._collector.stop_timer()
        self._write_report()

    def _write_report(self) -> None:
        """Write human-readable bottleneck report to reports/."""
        os.makedirs(REPORTS_DIR, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        path = os.path.join(REPORTS_DIR, f"report_{ts}.txt")

        metrics = self._collector.summary()

        lines = [
            "=" * 60,
            "  LOAD TEST BOTTLENECK REPORT",
            f"  Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}",
            "=" * 60,
            "",
            f"  Target URL  : {self._url}",
            f"  Threads     : {self._threads}",
            f"  Duration    : {self._duration}s",
            "",
            "── Performance ─────────────────────────────────────────────",
            f"  Total Requests   : {metrics['total_requests']}",
            f"  Successful       : {metrics['successful']}",
            f"  Errors           : {metrics['errors']}",
            f"  Error Rate       : {metrics['error_rate_pct']}%",
            f"  Throughput (RPS) : {metrics['rps']}",
            "",
            "── Latency (ms) ─────────────────────────────────────────────",
            f"  Min  : {metrics['latency_min_ms']}",
            f"  Avg  : {metrics['latency_avg_ms']}",
            f"  p50  : {metrics['p50']}",
            f"  p99  : {metrics['p99']}",
            f"  Max  : {metrics['latency_max_ms']}",
            "",
            "── Status Codes ─────────────────────────────────────────────",
        ]
        for code, count in metrics.get("status_codes", {}).items():
            lines.append(f"  HTTP {code} : {count}")

        # Bottleneck identification
        lines += ["", "── Bottleneck Analysis ──────────────────────────────────────"]
        rps = metrics["rps"]
        p99 = metrics["p99"]
        err = metrics["error_rate_pct"]

        if err > 5.0:
            lines.append("  ⚠  HIGH ERROR RATE — likely CPU or queue saturation")
            lines.append("     Reduce thread count or add more CPU cores")
        elif p99 > 2000:
            lines.append("  ⚠  HIGH p99 LATENCY — I/O or network bottleneck detected")
            lines.append("     Check disk I/O, external service latency, or NIC bandwidth")
        elif rps < 10:
            lines.append("  ⚠  LOW THROUGHPUT — single-thread bottleneck or blocked workers")
            lines.append("     Profile CPU usage; consider increasing thread pool size")
        else:
            lines.append("  ✓  No critical bottleneck detected at this load level")
            lines.append(f"     Throughput: {rps} RPS  |  p99 latency: {p99} ms")

        lines += ["", "=" * 60]

        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines))

        print(f"[LoadTester] Report saved -> {path}")


# Singleton used by the CLI
load_tester = LoadTester()
