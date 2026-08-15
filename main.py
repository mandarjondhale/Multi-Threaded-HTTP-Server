"""
main.py — CLI entry point for the Multi-Threaded Web Server project.

Commands
--------
  python main.py server   [--host HOST] [--port PORT] [--workers N] [--queue N]
      Start the HTTP server (blocks until Ctrl-C).

  python main.py loadtest [--url URL] [--threads N] [--duration N] [--ramp-up N]
      Run a standalone closed-loop load test (server must already be running).

  python main.py report
      Print the most recent bottleneck report from reports/.
"""

import argparse
import os
import signal
import sys
import time


# ─────────────────────────────────────────────
#  Sub-commands
# ─────────────────────────────────────────────

def cmd_server(args: argparse.Namespace) -> None:
    from server.tcp_server import HTTPServer

    public_dir = os.path.join(os.path.dirname(__file__), "public")

    server = HTTPServer(
        host=args.host,
        port=args.port,
        workers=args.workers,
        max_queue=args.queue,
        public_dir=public_dir,
    )

    def _shutdown(sig, frame):
        print("\n[Main] Shutting down…")
        server.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT,  _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    server.start()   # blocks


def cmd_loadtest(args: argparse.Namespace) -> None:
    from load_tester.generator import load_tester

    print(f"\n[LoadTest] Starting closed-loop load test")
    print(f"  URL      : {args.url}")
    print(f"  Threads  : {args.threads}")
    print(f"  Duration : {args.duration}s")
    print(f"  Ramp-up  : {args.ramp_up}s\n")

    result = load_tester.start(
        url=args.url,
        threads=args.threads,
        duration=args.duration,
        ramp_up=args.ramp_up,
    )

    if result.get("status") == "error":
        print(f"[LoadTest] Error: {result['message']}")
        return

    # Poll and print live stats every 2 seconds
    try:
        while True:
            time.sleep(2)
            status = load_tester.status()
            m = status["metrics"]
            remaining = status["time_remaining_seconds"]
            print(
                f"  [{remaining:>5.1f}s left]  "
                f"RPS: {m['rps']:<8}  "
                f"p50: {m['p50']:<8} ms  "
                f"p99: {m['p99']:<8} ms  "
                f"Errors: {m['error_rate_pct']}%"
            )
            if not status["running"]:
                break
    except KeyboardInterrupt:
        load_tester.stop()

    # Final summary
    final = load_tester.status()["metrics"]
    print("\n--- Final Results -----------------------------------------------")
    for k, v in final.items():
        print(f"  {k:<25}: {v}")
    print("-------------------------------------------------")
    print("\n[LoadTest] Report saved in reports/ (run: python main.py report)\n")


def cmd_report(args: argparse.Namespace) -> None:
    reports_dir = os.path.join(os.path.dirname(__file__), "reports")
    if not os.path.isdir(reports_dir):
        print("[Report] No reports directory found. Run a load test first.")
        return

    reports = sorted(
        [f for f in os.listdir(reports_dir) if f.endswith(".txt")],
        reverse=True,
    )
    if not reports:
        print("[Report] No report files found. Run a load test first.")
        return

    latest = os.path.join(reports_dir, reports[0])
    print(f"[Report] Showing: {latest}\n")
    with open(latest, encoding="utf-8") as fh:
        print(fh.read())


# ─────────────────────────────────────────────
#  Argument Parsing
# ─────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="main.py",
        description="Multi-Threaded Web Server with Load Testing",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # server
    p_server = sub.add_parser("server", help="Start the HTTP server")
    p_server.add_argument("--host",    default="0.0.0.0",  help="Bind address (default: 0.0.0.0)")
    p_server.add_argument("--port",    type=int, default=8080, help="Listen port (default: 8080)")
    p_server.add_argument("--workers", type=int, default=16,   help="Thread pool size (default: 16)")
    p_server.add_argument("--queue",   type=int, default=1000, help="Max task queue depth (default: 1000)")

    # loadtest
    p_lt = sub.add_parser("loadtest", help="Run a closed-loop load test (server must be running)")
    p_lt.add_argument("--url",      default="http://127.0.0.1:8080/workload/cpu?intensity=500")
    p_lt.add_argument("--threads",  type=int, default=20,  help="Virtual client threads (default: 20)")
    p_lt.add_argument("--duration", type=int, default=15,  help="Test duration in seconds (default: 15)")
    p_lt.add_argument("--ramp-up",  type=int, default=0,   dest="ramp_up",
                      help="Ramp-up period in seconds — staggers thread launches (default: 0)")

    # report
    sub.add_parser("report", help="Print the most recent bottleneck report")

    return parser


if __name__ == "__main__":
    parser = build_parser()
    args   = parser.parse_args()

    dispatch = {
        "server":   cmd_server,
        "loadtest": cmd_loadtest,
        "report":   cmd_report,
    }
    dispatch[args.command](args)
