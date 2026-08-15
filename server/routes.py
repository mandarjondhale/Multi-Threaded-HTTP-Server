"""
routes.py — URL router and request handlers.

Registered endpoints:
  GET  /                       → serves public/index.html
  GET  /api/status             → server health + thread pool stats (JSON)
  GET  /workload/cpu           → CPU-intensive task (SHA-256 hashing loop)
  GET  /workload/io            → I/O-bound simulation (sleep)
  GET  <anything else>         → tries to serve from public/ directory
"""

import os
import time
import hashlib
from server.http_handler import (
    HTTPRequest,
    build_response,
    mime_for_extension,
)


class Router:
    def __init__(
        self,
        public_dir: str,
        thread_pool,       # ThreadPool instance (for stats)
        server_metrics,    # ServerMetrics instance (for stats)
    ):
        self.public_dir = os.path.abspath(public_dir)
        self.thread_pool = thread_pool
        self.server_metrics = server_metrics

        # Registered routes: method → {path → handler}
        self._routes: dict[str, dict[str, callable]] = {
            "GET": {},
            "POST": {},
        }
        self._register()

    def _register(self):
        self._routes["GET"]["/api/status"]    = self._status
        self._routes["GET"]["/workload/cpu"]  = self._workload_cpu
        self._routes["GET"]["/workload/io"]   = self._workload_io

    # ------------------------------------------------------------------ #
    #  Dispatch                                                            #
    # ------------------------------------------------------------------ #

    def dispatch(self, request: HTTPRequest) -> bytes:
        handler = self._routes.get(request.method, {}).get(request.path)
        if handler:
            return handler(request)

        # Fall through to static file serving
        if request.method == "GET":
            return self._static_file(request)

        return build_response(
            405, {"error": "Method Not Allowed"},
            keep_alive=request.keep_alive,
        )

    # ------------------------------------------------------------------ #
    #  API Handlers                                                        #
    # ------------------------------------------------------------------ #

    def _status(self, req: HTTPRequest) -> bytes:
        data = {
            "server":      self.server_metrics.snapshot(),
            "thread_pool": self.thread_pool.get_stats(),
            "timestamp":   time.time(),
        }
        return build_response(200, data, keep_alive=req.keep_alive)

    def _workload_cpu(self, req: HTTPRequest) -> bytes:
        """
        CPU-bound workload: repeated SHA-256 hashing.
        Query param: intensity (default 1 000, max 100 000).
        """
        intensity = int(req.query.get("intensity", 1000))
        intensity = max(10, min(intensity, 100_000))

        t0 = time.perf_counter()
        data = b"PyMTWebServer-CPU-Benchmark"
        for _ in range(intensity):
            data = hashlib.sha256(data).digest()
        elapsed_ms = (time.perf_counter() - t0) * 1_000

        return build_response(200, {
            "workload":          "cpu",
            "iterations":        intensity,
            "digest_prefix":     data.hex()[:16],
            "elapsed_ms":        round(elapsed_ms, 3),
        }, keep_alive=req.keep_alive)

    def _workload_io(self, req: HTTPRequest) -> bytes:
        """
        I/O-bound workload: sleep to simulate DB / disk latency.
        Query param: delay (ms, default 50, max 5 000).
        """
        delay_ms = float(req.query.get("delay", 50))
        delay_ms = max(1.0, min(delay_ms, 5_000.0))

        t0 = time.perf_counter()
        time.sleep(delay_ms / 1_000.0)
        elapsed_ms = (time.perf_counter() - t0) * 1_000

        return build_response(200, {
            "workload":        "io",
            "target_delay_ms": delay_ms,
            "actual_delay_ms": round(elapsed_ms, 3),
        }, keep_alive=req.keep_alive)

    # ------------------------------------------------------------------ #
    #  Static File Serving                                                 #
    # ------------------------------------------------------------------ #

    def _static_file(self, req: HTTPRequest) -> bytes:
        url_path = req.path if req.path != "/" else "/index.html"
        # Prevent path traversal
        safe = os.path.normpath(url_path).lstrip("/\\")
        full = os.path.join(self.public_dir, safe)

        if not os.path.abspath(full).startswith(self.public_dir):
            return build_response(403, "Forbidden", keep_alive=req.keep_alive)

        if not os.path.isfile(full):
            return build_response(404, f"Not found: {url_path}", keep_alive=req.keep_alive)

        ext = os.path.splitext(full)[1]
        ctype = mime_for_extension(ext)
        try:
            with open(full, "rb") as fh:
                content = fh.read()
            return build_response(200, content, content_type=ctype, keep_alive=req.keep_alive)
        except OSError as exc:
            return build_response(500, f"Read error: {exc}", keep_alive=req.keep_alive)
