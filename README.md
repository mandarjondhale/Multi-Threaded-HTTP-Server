# Optimized Multi-Threaded HTTP Server and Load Testing Suite

A high-performance, lightweight **Multi-Threaded HTTP Web Server** and **Closed-Loop Load Testing Suite** built entirely using the Python standard library.

## 🚀 Key Features

- **Custom TCP & HTTP Protocol Handler**: Implements HTTP/1.1 request parsing, response building, keep-alive connections, and CORS support without external web framework dependencies.
- **Worker Thread Pool Architecture**: Thread-pooled execution queue (`ThreadPool`) for handling incoming client socket requests concurrently.
- **Integrated Load Testing Engine**: Standalone closed-loop virtual client generator with configurable thread counts, test durations, and ramp-up scheduling.
- **Real-Time Metrics & Profiling**: Tracks Requests Per Second (RPS), error rates, memory footprint, and response latency percentiles ($p_{50}$, $p_{95}$, $p_{99}$).
- **Built-in Workload Simulations**: Pre-configured routes for CPU-heavy benchmarking (repetitive SHA-256 hashing) and I/O-bound latency simulation (`time.sleep`).

---

## 📁 Repository Structure

```
.
├── main.py                  # CLI entry point (server, loadtest, report)
├── verify.py                # Comprehensive component verification & test suite
├── requirements.txt         # Project requirements (Python 3.10+ standard library)
├── server/                  # HTTP Server package
│   ├── tcp_server.py        # Socket server & connection listener
│   ├── thread_pool.py       # Custom task queue & worker thread management
│   ├── http_handler.py      # HTTP request parser & response builder
│   └── routes.py            # API routes & static file handlers
└── load_tester/             # Load Testing & Profiling package
    ├── generator.py         # Multi-threaded virtual client load generator
    ├── metrics.py           # Metrics collector & percentile calculation
    └── memory_profiler.py   # Memory tracking & snapshot utility
```

---

## 🛠️ Getting Started

### Prerequisites

- Python 3.10 or higher (no external third-party dependencies required).

### 1. Verify Components

Run the verification test suite to ensure all server modules, thread pools, and metrics collectors pass health checks:

```bash
python verify.py
```

### 2. Start the HTTP Server

Start the multi-threaded HTTP server with configurable worker pool and queue depth:

```bash
python main.py server --host 0.0.0.0 --port 8080 --workers 16 --queue 1000
```

Available endpoints:
- `GET /api/status` — Server health metrics & active thread pool stats
- `GET /workload/cpu?intensity=1000` — SHA-256 CPU workload benchmark
- `GET /workload/io?delay=50` — I/O latency workload benchmark
- `POST /api/loadtest/start` — Trigger load test remotely
- `GET /api/loadtest/status` — Fetch real-time load test status

### 3. Run a Load Test

In a separate terminal (while the server is running), execute a closed-loop load test:

```bash
python main.py loadtest --url http://127.0.0.1:8080/workload/cpu?intensity=500 --threads 20 --duration 15
```

### 4. View Performance Reports

Inspect the latest bottleneck and performance report saved in `reports/`:

```bash
python main.py report
```

---

## 📄 License

MIT License.
