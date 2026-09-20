#!/usr/bin/env python3
"""Closed-loop HTTP load generator for the pool-sizing benchmark.

Runs `concurrency` worker threads against one or more app instances (round-robin,
modelling a load balancer). Each worker keeps a persistent HTTP connection so the
measurement reflects server-side behaviour rather than TCP setup cost.

Reports throughput, latency percentiles and a breakdown of failures by cause,
which is what distinguishes "slow because the pool is queueing" from "broken
because the database refused the connection".

Note on interpretation: this is a closed-loop generator, so offered load is
bounded by concurrency/latency. Rising latency at a fixed concurrency therefore
shows up as falling throughput, not as an unbounded queue.
"""
import argparse
import http.client
import json
import statistics
import threading
import time
from collections import Counter
from urllib.parse import urlparse


class Worker(threading.Thread):
    def __init__(self, targets, path, stop_at, warmup_until):
        super().__init__(daemon=True)
        self.targets = targets
        self.path = path
        self.stop_at = stop_at
        self.warmup_until = warmup_until
        self.latencies = []
        self.success_latencies = []
        self.errors = Counter()
        self.success = 0
        self.failed = 0

    def _classify(self, status, body):
        if status is None:
            return "transport"
        text = body.decode("utf-8", "replace")[:400] if body else ""
        if "Connection is not available" in text:
            return f"{status}:hikari-pool-timeout"
        if "too many clients" in text:
            return f"{status}:postgres-too-many-clients"
        if "no more connections allowed" in text:
            return f"{status}:pgbouncer-max-client-conn"
        if "timeout" in text.lower():
            return f"{status}:timeout"
        if "FATAL" in text:
            return f"{status}:postgres-fatal"
        # Spring reports only the top-level exception message, so a database refusal
        # arrives as this rather than the underlying FATAL. The specific cause is in
        # the application log; see benchmark/results/evidence/.
        if "Failed to obtain JDBC Connection" in text:
            return f"{status}:could-not-get-connection"
        return f"{status}:other"

    def run(self):
        conns = [None] * len(self.targets)
        i = 0
        while time.monotonic() < self.stop_at:
            idx = i % len(self.targets)
            i += 1
            host, port = self.targets[idx]
            started = time.monotonic()
            status, body, err = None, None, None
            try:
                if conns[idx] is None:
                    conns[idx] = http.client.HTTPConnection(host, port, timeout=30)
                conns[idx].request("GET", self.path)
                resp = conns[idx].getresponse()
                status = resp.status
                body = resp.read()
            except Exception as exc:  # transport level: refused, reset, timeout
                err = type(exc).__name__
                try:
                    if conns[idx]:
                        conns[idx].close()
                except Exception:
                    pass
                conns[idx] = None
            elapsed_ms = (time.monotonic() - started) * 1000.0

            # Warmup requests are issued but not recorded.
            if time.monotonic() < self.warmup_until:
                continue

            self.latencies.append(elapsed_ms)
            if status and 200 <= status < 300:
                self.success += 1
                self.success_latencies.append(elapsed_ms)
            else:
                self.failed += 1
                self.errors[err if err else self._classify(status, body)] += 1


def percentiles(values):
    if not values:
        return {}
    ordered = sorted(values)

    def pct(p):
        if len(ordered) == 1:
            return round(ordered[0], 1)
        k = (len(ordered) - 1) * p / 100.0
        lo, hi = int(k), min(int(k) + 1, len(ordered) - 1)
        return round(ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo), 1)

    return {
        "mean": round(statistics.fmean(ordered), 1),
        "p50": pct(50),
        "p95": pct(95),
        "p99": pct(99),
        "max": round(ordered[-1], 1),
    }


def run(urls, concurrency, duration, warmup, path):
    targets = []
    for u in urls:
        parsed = urlparse(u)
        targets.append((parsed.hostname, parsed.port or 80))

    now = time.monotonic()
    warmup_until = now + warmup
    stop_at = warmup_until + duration

    workers = [Worker(targets, path, stop_at, warmup_until) for _ in range(concurrency)]
    for w in workers:
        w.start()
    for w in workers:
        w.join(timeout=duration + warmup + 60)

    latencies, success_latencies = [], []
    errors = Counter()
    success = failed = 0
    for w in workers:
        latencies.extend(w.latencies)
        success_latencies.extend(w.success_latencies)
        errors.update(w.errors)
        success += w.success
        failed += w.failed

    total = success + failed
    return {
        "concurrency": concurrency,
        "duration_s": duration,
        "requests": total,
        "success": success,
        "failed": failed,
        "error_rate_pct": round(100.0 * failed / total, 2) if total else 0.0,
        "throughput_rps": round(total / duration, 1) if duration else 0.0,
        "success_rps": round(success / duration, 1) if duration else 0.0,
        "latency_ms": percentiles(latencies),
        "success_latency_ms": percentiles(success_latencies),
        "error_types": dict(errors),
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", action="append", required=True, help="repeatable: one per app instance")
    ap.add_argument("--concurrency", type=int, required=True)
    ap.add_argument("--duration", type=float, default=15)
    ap.add_argument("--warmup", type=float, default=3)
    ap.add_argument("--path", default="/api/appdb/employees?workMs=50")
    args = ap.parse_args()
    print(json.dumps(run(args.url, args.concurrency, args.duration, args.warmup, args.path)))
