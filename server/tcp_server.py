"""
tcp_server.py — TCP socket listener + multi-threaded connection acceptor.

Lifecycle:
  1. Bind a TCP socket to host:port
  2. Spin up the thread pool
  3. Accept loop runs in a dedicated thread (not the main thread)
  4. Each accepted socket is submitted to the thread pool as a task
  5. Workers parse HTTP requests, dispatch through the router, write response

ServerMetrics tracks uptime, request counts, byte totals, and active connections.
"""

import socket
import threading
import time
from server.thread_pool import ThreadPool
from server.http_handler import parse_request, build_response
from server.routes import Router


# ─────────────────────────────────────────────
#  Server metrics
# ─────────────────────────────────────────────

class ServerMetrics:
    """Thread-safe counters for server observability."""

    def __init__(self):
        self._lock = threading.Lock()
        self._start_time = time.time()
        self._total_requests = 0
        self._total_rx_bytes = 0
        self._total_tx_bytes = 0
        self._active_connections = 0

    def request_done(self, rx: int, tx: int) -> None:
        with self._lock:
            self._total_requests += 1
            self._total_rx_bytes += rx
            self._total_tx_bytes += tx

    def connection_opened(self) -> None:
        with self._lock:
            self._active_connections += 1

    def connection_closed(self) -> None:
        with self._lock:
            self._active_connections -= 1

    def snapshot(self) -> dict:
        with self._lock:
            uptime = time.time() - self._start_time
            rps = self._total_requests / uptime if uptime > 0 else 0.0
            return {
                "uptime_seconds":       round(uptime, 2),
                "total_requests":       self._total_requests,
                "active_connections":   self._active_connections,
                "avg_rps":              round(rps, 2),
                "total_rx_bytes":       self._total_rx_bytes,
                "total_tx_bytes":       self._total_tx_bytes,
            }


# ─────────────────────────────────────────────
#  HTTP Server
# ─────────────────────────────────────────────

class HTTPServer:
    """
    Multi-threaded HTTP/1.1 server over raw TCP sockets.

    Parameters
    ----------
    host        : bind address (default "0.0.0.0")
    port        : listen port  (default 8080)
    workers     : thread pool size (default 16)
    max_queue   : task queue capacity before 503 (default 1 000)
    public_dir  : directory from which to serve static files
    """

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8080,
        workers: int = 16,
        max_queue: int = 1000,
        public_dir: str = "public",
    ):
        self.host = host
        self.port = port
        self._running = False
        self._server_sock: socket.socket | None = None

        self.pool    = ThreadPool(num_workers=workers, max_queue_size=max_queue)
        self.metrics = ServerMetrics()
        self.router  = Router(public_dir=public_dir, thread_pool=self.pool, server_metrics=self.metrics)

    # ------------------------------------------------------------------ #
    #  Start / Stop                                                        #
    # ------------------------------------------------------------------ #

    def start(self) -> None:
        """Bind socket, start thread pool, launch acceptor thread, block."""
        self.pool.start()

        self._server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_sock.bind((self.host, self.port))
        self._server_sock.listen(512)
        self._server_sock.settimeout(1.0)  # allows clean shutdown checks

        self._running = True

        print(f"[Server] Listening on http://{self.host}:{self.port}  "
              f"(workers={self.pool.num_workers}, queue={self.pool._task_queue.maxsize})")

        acceptor = threading.Thread(
            target=self._accept_loop,
            name="AcceptorThread",
            daemon=True,
        )
        acceptor.start()
        acceptor.join()   # block main thread until stop() is called

    def stop(self) -> None:
        """Signal graceful shutdown."""
        self._running = False
        if self._server_sock:
            try:
                self._server_sock.close()
            except Exception:
                pass
        self.pool.shutdown(wait=True)
        print("[Server] Stopped.")

    # ------------------------------------------------------------------ #
    #  Accept Loop                                                         #
    # ------------------------------------------------------------------ #

    def _accept_loop(self) -> None:
        while self._running:
            try:
                client_sock, client_addr = self._server_sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break   # socket closed by stop()

            self.metrics.connection_opened()

            submitted = self.pool.submit(self._handle_connection, client_sock)
            if not submitted:
                # Thread pool queue is full → send 503 and close
                try:
                    busy = build_response(503, {"error": "Server busy — thread queue full"}, keep_alive=False)
                    client_sock.sendall(busy)
                except Exception:
                    pass
                finally:
                    client_sock.close()
                    self.metrics.connection_closed()

    # ------------------------------------------------------------------ #
    #  Connection Handler (executed by pool worker)                        #
    # ------------------------------------------------------------------ #

    def _handle_connection(self, client_sock: socket.socket) -> None:
        """
        Reads HTTP requests from the socket in a keep-alive loop,
        dispatches each through the router, and writes the response.
        """
        client_sock.settimeout(10.0)
        rx_total = 0
        tx_total = 0

        try:
            while self._running:
                # Read until we have the full header block
                raw = b""
                try:
                    while b"\r\n\r\n" not in raw:
                        chunk = client_sock.recv(4096)
                        if not chunk:
                            return  # client disconnected
                        raw += chunk
                        rx_total += len(chunk)
                except socket.timeout:
                    return

                request, keep_alive = parse_request(raw)

                if request is None:
                    resp = build_response(400, {"error": "Bad Request"}, keep_alive=False)
                    client_sock.sendall(resp)
                    tx_total += len(resp)
                    return

                resp = self.router.dispatch(request)
                client_sock.sendall(resp)
                tx_total += len(resp)
                self.metrics.request_done(len(raw), len(resp))

                if not keep_alive:
                    return

        except (ConnectionResetError, BrokenPipeError):
            pass
        except Exception as exc:
            print(f"[Server] Connection error: {exc}")
        finally:
            try:
                client_sock.close()
            except Exception:
                pass
            self.metrics.connection_closed()
            # Update aggregate byte counters (no double-count: only final totals here)
