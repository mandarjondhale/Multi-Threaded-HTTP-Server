import sys
print('Python:', sys.version)

sys.path.insert(0, r'C:\Users\manda\Desktop\workspace')
from server.thread_pool import ThreadPool
from server.http_handler import parse_request, build_response
from server.routes import Router
from server.tcp_server import HTTPServer, ServerMetrics
from load_tester.metrics import MetricsCollector
from load_tester.memory_profiler import MemoryProfiler
from load_tester.generator import LoadTester

print('All modules imported successfully.')

# ThreadPool test
import time
pool = ThreadPool(num_workers=4, max_queue_size=10)
pool.start()
results = []
for i in range(5):
    pool.submit(results.append, i)
time.sleep(0.3)
pool.shutdown()
assert len(results) == 5, 'Expected 5 tasks completed, got ' + str(len(results))
print('ThreadPool: OK (5/5 tasks executed)')

# HTTP parser test
raw = b'GET /workload/cpu?intensity=100 HTTP/1.1\r\nHost: localhost\r\nConnection: keep-alive\r\n\r\n'
req, keep_alive = parse_request(raw)
assert req is not None
assert req.method == 'GET'
assert req.path == '/workload/cpu'
assert req.query.get('intensity') == '100'
assert keep_alive is True
print('HTTP Parser: OK')

# Response builder test
resp = build_response(200, {'ok': True})
assert b'HTTP/1.1 200 OK' in resp
assert b'application/json' in resp
print('Response Builder: OK')

# MetricsCollector test
collector = MetricsCollector()
collector.start_timer()
for i in range(100):
    collector.record(float(i + 1), 200)
collector.stop_timer()
s = collector.summary()
assert s['total_requests'] == 100
assert s['successful'] == 100
assert s['p50'] > 0
print('MetricsCollector: OK  p50=' + str(s['p50']) + ' ms, p99=' + str(s['p99']) + ' ms, RPS=' + str(s['rps']))

print()
print('All checks passed.')
