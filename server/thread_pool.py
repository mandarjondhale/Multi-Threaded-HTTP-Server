"""
thread_pool.py — Custom bounded thread pool with worker lifecycle management.

Provides:
  - Fixed-size pool of daemon worker threads
  - Bounded task queue (rejects work when full → 503)
  - Live stats: active workers, idle workers, queue depth, completed tasks
  - Graceful shutdown with optional join timeout
"""

import threading
import queue
import time
from typing import Callable, Any


class ThreadPool:
    """
    A fixed-size thread pool backed by a bounded FIFO task queue.

    Workers pull (callable, args, kwargs) tuples off the queue and execute them.
    If the queue is full, submit() returns False immediately (caller should 503).
    """

    def __init__(self, num_workers: int = 16, max_queue_size: int = 1000):
        self.num_workers = num_workers
        self._task_queue: queue.Queue = queue.Queue(maxsize=max_queue_size)
        self._workers: list[threading.Thread] = []
        self._running = False

        # Stats (protected by lock)
        self._lock = threading.Lock()
        self._active_workers = 0
        self._total_completed = 0
        self._total_submitted = 0
        self._total_rejected = 0

    # ------------------------------------------------------------------ #
    #  Lifecycle                                                           #
    # ------------------------------------------------------------------ #

    def start(self) -> None:
        """Spin up all worker threads."""
        self._running = True
        for i in range(self.num_workers):
            t = threading.Thread(
                target=self._worker_loop,
                name=f"PoolWorker-{i + 1}",
                daemon=True,
            )
            self._workers.append(t)
            t.start()

    def shutdown(self, wait: bool = True, timeout: float = 2.0) -> None:
        """
        Signal all workers to stop.

        Parameters
        ----------
        wait    : block until all threads exit (or timeout elapses).
        timeout : per-thread join timeout in seconds.
        """
        self._running = False
        if wait:
            for t in self._workers:
                t.join(timeout=timeout)

    # ------------------------------------------------------------------ #
    #  Task submission                                                     #
    # ------------------------------------------------------------------ #

    def submit(self, func: Callable, *args: Any, **kwargs: Any) -> bool:
        """
        Enqueue a task.

        Returns True on success, False if the queue is full (caller → 503).
        """
        if not self._running:
            return False
        try:
            self._task_queue.put_nowait((func, args, kwargs))
            with self._lock:
                self._total_submitted += 1
            return True
        except queue.Full:
            with self._lock:
                self._total_rejected += 1
            return False

    # ------------------------------------------------------------------ #
    #  Worker loop                                                         #
    # ------------------------------------------------------------------ #

    def _worker_loop(self) -> None:
        """Drain the task queue until shutdown is requested."""
        while self._running:
            try:
                func, args, kwargs = self._task_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            with self._lock:
                self._active_workers += 1
            try:
                func(*args, **kwargs)
            except Exception as exc:
                print(f"[ThreadPool] Unhandled exception in worker: {exc}")
            finally:
                with self._lock:
                    self._active_workers -= 1
                    self._total_completed += 1
                self._task_queue.task_done()

    # ------------------------------------------------------------------ #
    #  Introspection                                                       #
    # ------------------------------------------------------------------ #

    def get_stats(self) -> dict:
        """Return a snapshot of pool health metrics."""
        with self._lock:
            active = self._active_workers
            completed = self._total_completed
            submitted = self._total_submitted
            rejected = self._total_rejected

        return {
            "num_workers": self.num_workers,
            "active_workers": active,
            "idle_workers": self.num_workers - active,
            "queue_depth": self._task_queue.qsize(),
            "queue_capacity": self._task_queue.maxsize,
            "total_submitted": submitted,
            "total_completed": completed,
            "total_rejected": rejected,
        }
