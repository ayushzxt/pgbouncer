#!/usr/bin/env python3
"""Runs the full pool-sizing benchmark matrix and writes raw results as JSON/CSV.

Matrix (see benchmark/README.md for the reasoning):
  S1  PostgreSQL direct, no connection pool at all
  S2  PostgreSQL + HikariCP, pool size <, = and > the database's usable ceiling,
      at 1 and 4 app instances
  S3  the same, routed through PgBouncer, plus PgBouncer pool-size variations

Every run is measured at several concurrency levels so the point where a setup
stops coping is visible rather than inferred.

Between runs PgBouncer is stopped and the harness waits for the app role's
backend connections to drain, so no run inherits connections from the previous one.
"""
import json
import os
import shutil
import subprocess
import sys
import threading
import time

import loadgen

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JAR = os.path.join(REPO, "target", "PoolKeeperBoot-1.0-SNAPSHOT.jar")
RESULTS_DIR = os.path.join(REPO, "benchmark", "results")
LOG_DIR = os.path.join(RESULTS_DIR, "logs")

# PostgreSQL is configured with max_connections=25 and superuser_reserved_connections=5,
# so the non-superuser app role can hold at most this many backends. Every "pool size
# vs postgres pool" comparison below is relative to this number.
PG_APP_CEILING = 20

WORK_MS = 50           # how long each request holds its database connection
CONCURRENCIES = [10, 25, 50, 100, 200]
DURATION = 12.0
WARMUP = 3.0
HIKARI_CONNECTION_TIMEOUT_MS = 5000
BASE_PORT = 9001

PG_PORT = 5432
PGB_PORT = 6432


def sh(cmd, check=False, capture=True):
    return subprocess.run(cmd, shell=True, check=check,
                          capture_output=capture, text=True, timeout=120)


def pg_app_connections():
    """Backends held by the app role, sampled as superuser via the reserved slots."""
    out = sh("sudo -u postgres psql -tAc \"SELECT count(*) FROM pg_stat_activity "
             "WHERE usename='appuser'\"")
    try:
        return int(out.stdout.strip())
    except ValueError:
        return -1


def pgbouncer_pools():
    out = sh("PGPASSWORD=apppass psql -h 127.0.0.1 -p 6432 -U appuser pgbouncer "
             "-tAF, -c 'SHOW POOLS'")
    for line in out.stdout.splitlines():
        parts = line.split(",")
        if len(parts) > 10 and parts[0] == "appdb":
            return {"cl_active": int(parts[2]), "cl_waiting": int(parts[3]),
                    "sv_active": int(parts[6]), "sv_idle": int(parts[9]),
                    "maxwait": int(parts[13])}
    return None


PGB_PIDFILE = "/var/run/postgresql/pgbouncer.pid"


def stop_pgbouncer():
    # Kill by pidfile rather than pkill -f: a pattern matching "pgbouncer" also matches
    # this harness's own shell command line, which would make it kill itself.
    try:
        with open(PGB_PIDFILE) as f:
            pid = int(f.read().strip())
        os.kill(pid, 15)
        for _ in range(20):
            time.sleep(0.25)
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
    except (FileNotFoundError, ValueError, ProcessLookupError):
        pass
    time.sleep(1)


def start_pgbouncer(pool_size):
    stop_pgbouncer()
    template = open(os.path.join(REPO, "benchmark", "pgbouncer.ini.template")).read()
    with open("/etc/pgbouncer/pgbouncer.ini", "w") as f:
        f.write(template.replace("__POOL_SIZE__", str(pool_size)))
    sh("chown postgres:postgres /etc/pgbouncer/pgbouncer.ini")
    sh("sudo -u postgres /usr/sbin/pgbouncer -d /etc/pgbouncer/pgbouncer.ini")
    for _ in range(30):
        time.sleep(0.5)
        if sh("PGPASSWORD=apppass psql -h 127.0.0.1 -p 6432 -U appuser appdb "
              "-tAc 'SELECT 1'").stdout.strip() == "1":
            return True
    raise RuntimeError("PgBouncer did not come up")


def wait_for_drain(timeout=60):
    """Wait until the app role holds no backends, so runs do not contaminate each other."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if pg_app_connections() == 0:
            return True
        time.sleep(1)
    return False


def start_instances(run, procs):
    ports = [BASE_PORT + i for i in range(run["instances"])]
    db_port = PGB_PORT if run["pgbouncer"] else PG_PORT
    os.makedirs(LOG_DIR, exist_ok=True)
    for port in ports:
        args = [
            "java", f"-Dbenchmark.run={run['id']}", "-jar", JAR,
            f"--server.port={port}",
            # keep the servlet container from becoming the bottleneck we are not measuring
            "--server.tomcat.threads.max=300",
            # benchmark-only: Boot hides exception messages by default, which would make
            # every failure an indistinguishable 500. The load generator classifies the
            # cause from this, so a pool timeout is not confused with a database refusal.
            "--server.error.include-message=always",
            f"--app.pooling={run['pooling']}",
            f"--app.datasources.appdb.jdbc-url=jdbc:postgresql://127.0.0.1:{db_port}/appdb",
            f"--app.datasources.appdb.connection-timeout={HIKARI_CONNECTION_TIMEOUT_MS}",
        ]
        if run["hikari"]:
            args += [f"--app.datasources.appdb.maximum-pool-size={run['hikari']}",
                     "--app.datasources.appdb.minimum-idle=2"]
        log = open(os.path.join(LOG_DIR, f"{run['id']}-{port}.log"), "w")
        procs.append(subprocess.Popen(args, cwd=REPO, stdout=log, stderr=subprocess.STDOUT))

    deadline = time.time() + 120
    pending = set(ports)
    while pending and time.time() < deadline:
        time.sleep(2)
        for port in list(pending):
            out = sh(f"curl -s -m 3 -o /dev/null -w '%{{http_code}}' "
                     f"http://localhost:{port}/actuator/health")
            if out.stdout.strip() == "200":
                pending.discard(port)
    if pending:
        raise RuntimeError(f"instances did not start: {sorted(pending)}")
    time.sleep(3)  # let startup connection churn settle
    return ports


def stop_instances(procs):
    for p in procs:
        p.terminate()
    for p in procs:
        try:
            p.wait(timeout=20)
        except subprocess.TimeoutExpired:
            p.kill()
    procs.clear()
    time.sleep(2)


class Sampler(threading.Thread):
    """Samples real database connection usage while a load level is running."""

    def __init__(self, with_pgbouncer):
        super().__init__(daemon=True)
        self.with_pgbouncer = with_pgbouncer
        self.stop_flag = threading.Event()
        self.pg_samples = []
        self.pgb_samples = []

    def run(self):
        while not self.stop_flag.is_set():
            self.pg_samples.append(pg_app_connections())
            if self.with_pgbouncer:
                p = pgbouncer_pools()
                if p:
                    self.pgb_samples.append(p)
            self.stop_flag.wait(0.5)

    def summary(self):
        valid = [s for s in self.pg_samples if s >= 0]
        out = {
            "pg_backends_max": max(valid) if valid else None,
            "pg_backends_avg": round(sum(valid) / len(valid), 1) if valid else None,
            "pg_sample_failures": len([s for s in self.pg_samples if s < 0]),
        }
        if self.pgb_samples:
            out["pgbouncer"] = {
                "cl_active_max": max(s["cl_active"] for s in self.pgb_samples),
                "cl_waiting_max": max(s["cl_waiting"] for s in self.pgb_samples),
                "sv_active_max": max(s["sv_active"] for s in self.pgb_samples),
                "sv_total_max": max(s["sv_active"] + s["sv_idle"] for s in self.pgb_samples),
                "maxwait_s": max(s["maxwait"] for s in self.pgb_samples),
            }
        return out


def run_one(run):
    print(f"\n=== {run['id']} :: {run['label']} ===", flush=True)
    if run["pgbouncer"]:
        start_pgbouncer(run["pgbouncer"])
    else:
        stop_pgbouncer()
    wait_for_drain()

    procs = []
    levels = []
    try:
        ports = start_instances(run, procs)
        urls = [f"http://localhost:{p}" for p in ports]
        for c in CONCURRENCIES:
            sampler = Sampler(bool(run["pgbouncer"]))
            sampler.start()
            result = loadgen.run(urls, c, DURATION, WARMUP,
                                 f"/api/appdb/employees?workMs={WORK_MS}")
            sampler.stop_flag.set()
            sampler.join(timeout=10)
            result.update(sampler.summary())
            levels.append(result)
            print(f"  c={c:>3}  rps={result['throughput_rps']:>7}  "
                  f"p95={result['latency_ms'].get('p95'):>8}ms  "
                  f"err={result['error_rate_pct']:>6}%  "
                  f"pg_backends_max={result.get('pg_backends_max')}", flush=True)
    finally:
        stop_instances(procs)

    return {**run, "levels": levels}


def build_matrix():
    runs = []

    runs.append({
        "id": "S1-direct-noPool-1inst", "scenario": "S1 direct (no pool)",
        "label": "PostgreSQL direct, no connection pool, 1 instance",
        "instances": 1, "pooling": "none", "hikari": None, "pgbouncer": None,
        "pool_vs_pg": "n/a",
    })

    for instances in (1, 4):
        for hikari, rel in ((10, "<"), (20, "="), (40, ">")):
            runs.append({
                "id": f"S2-hikari{hikari}-{instances}inst",
                "scenario": "S2 HikariCP",
                "label": (f"HikariCP pool {hikari} ({rel} postgres pool {PG_APP_CEILING}), "
                          f"{instances} instance(s), total demand {hikari * instances}"),
                "instances": instances, "pooling": "hikari", "hikari": hikari,
                "pgbouncer": None, "pool_vs_pg": rel,
            })

    for instances in (1, 4):
        for hikari, rel in ((10, "<"), (20, "="), (40, ">")):
            runs.append({
                "id": f"S3-hikari{hikari}-{instances}inst-pgb20",
                "scenario": "S3 HikariCP + PgBouncer",
                "label": (f"HikariCP pool {hikari} ({rel} postgres pool {PG_APP_CEILING}), "
                          f"{instances} instance(s), total demand {hikari * instances}, "
                          f"PgBouncer pool 20"),
                "instances": instances, "pooling": "hikari", "hikari": hikari,
                "pgbouncer": 20, "pool_vs_pg": rel,
            })

    # PgBouncer pool-size sweep: how much does the proxy's own pool matter?
    for instances, hikari in ((1, 20), (4, 40)):
        for pgb in (5, 10):
            runs.append({
                "id": f"S3-hikari{hikari}-{instances}inst-pgb{pgb}",
                "scenario": "S3 PgBouncer pool sweep",
                "label": (f"HikariCP pool {hikari}, {instances} instance(s), "
                          f"total demand {hikari * instances}, PgBouncer pool {pgb}"),
                "instances": instances, "pooling": "hikari", "hikari": hikari,
                "pgbouncer": pgb, "pool_vs_pg": "=" if hikari == PG_APP_CEILING else ">",
            })

    return runs


def main():
    if not os.path.exists(JAR):
        sys.exit(f"jar not found: {JAR} (run: mvn -DskipTests package)")
    os.makedirs(RESULTS_DIR, exist_ok=True)

    only = sys.argv[1] if len(sys.argv) > 1 else None
    runs = [r for r in build_matrix() if not only or only in r["id"]]

    meta = {
        "pg_max_connections": 25,
        "pg_superuser_reserved": 5,
        "pg_app_ceiling": PG_APP_CEILING,
        "work_ms": WORK_MS,
        "concurrencies": CONCURRENCIES,
        "duration_s": DURATION,
        "warmup_s": WARMUP,
        "hikari_connection_timeout_ms": HIKARI_CONNECTION_TIMEOUT_MS,
        "hikari_minimum_idle": 2,
        "started": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

    results = []
    for run in runs:
        try:
            results.append(run_one(run))
        except Exception as exc:
            print(f"  RUN FAILED: {exc}", flush=True)
            results.append({**run, "error": str(exc), "levels": []})
        with open(os.path.join(RESULTS_DIR, "matrix.json"), "w") as f:
            json.dump({"meta": meta, "runs": results}, f, indent=2)

    stop_pgbouncer()
    write_csv(results)
    print("\nDone. Results in benchmark/results/matrix.json", flush=True)


def write_csv(results):
    import csv
    path = os.path.join(RESULTS_DIR, "matrix.csv")
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["run_id", "scenario", "instances", "hikari_pool", "pool_vs_pg",
                    "total_client_demand", "pgbouncer_pool", "concurrency", "requests",
                    "throughput_rps", "success_rps", "error_rate_pct", "p50_ms", "p95_ms",
                    "p99_ms", "max_ms", "pg_backends_max", "pgb_sv_total_max",
                    "pgb_cl_waiting_max", "error_types"])
        for r in results:
            for lv in r.get("levels", []):
                pgb = lv.get("pgbouncer", {})
                w.writerow([
                    r["id"], r["scenario"], r["instances"], r["hikari"] or "", r["pool_vs_pg"],
                    (r["hikari"] or 0) * r["instances"] or "", r["pgbouncer"] or "",
                    lv["concurrency"], lv["requests"], lv["throughput_rps"], lv["success_rps"],
                    lv["error_rate_pct"], lv["latency_ms"].get("p50"), lv["latency_ms"].get("p95"),
                    lv["latency_ms"].get("p99"), lv["latency_ms"].get("max"),
                    lv.get("pg_backends_max"), pgb.get("sv_total_max", ""),
                    pgb.get("cl_waiting_max", ""),
                    ";".join(f"{k}={v}" for k, v in lv["error_types"].items()),
                ])


if __name__ == "__main__":
    main()
