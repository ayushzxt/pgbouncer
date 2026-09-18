#!/usr/bin/env python3
"""Tiny live dashboard for the PgBouncer PoC.

Queries the REAL running Postgres (and PgBouncer, if reachable) every request
and renders the numbers as HTML. No fabricated data: every figure on the page
comes from a live `psql` query executed at request time. Used only to produce
real, screenshot-able evidence of connection counts during the load tests.
"""
import http.server
import subprocess
import datetime
import os

PGPASSWORD = "root"

def run_sql(port, dbname, sql):
    env = dict(os.environ, PGPASSWORD=PGPASSWORD)
    try:
        out = subprocess.run(
            ["psql", "-h", "127.0.0.1", "-p", str(port), "-U", "postgres", "-d", dbname,
             "-tA", "-c", sql],
            capture_output=True, text=True, timeout=3, env=env,
        )
        if out.returncode != 0:
            return None, out.stderr.strip()
        return out.stdout.strip(), None
    except Exception as e:
        return None, str(e)

def run_sql_table(port, dbname, sql, expanded=False):
    env = dict(os.environ, PGPASSWORD=PGPASSWORD)
    args = ["psql", "-h", "127.0.0.1", "-p", str(port), "-U", "postgres", "-d", dbname]
    if expanded:
        args.append("-x")
    args += ["-c", sql]
    try:
        out = subprocess.run(
            args,
            capture_output=True, text=True, timeout=3, env=env,
        )
        if out.returncode != 0:
            return None, out.stderr.strip()
        return out.stdout, None
    except Exception as e:
        return None, str(e)


PAGE = """<!doctype html>
<html><head><meta charset="utf-8">
<title>PgBouncer PoC — live connection monitor</title>
<style>
body {{ background:#0d1117; color:#c9d1d9; font-family: 'DejaVu Sans Mono', monospace; padding:24px; }}
h1 {{ color:#58a6ff; font-size:20px; }}
h2 {{ color:#7ee787; font-size:15px; margin-top:28px; }}
pre {{ background:#161b22; border:1px solid #30363d; border-radius:6px; padding:14px; white-space:pre-wrap; font-size:13px; }}
.big {{ font-size:42px; font-weight:bold; }}
.ok {{ color:#3fb950; }}
.bad {{ color:#f85149; }}
.card {{ display:inline-block; background:#161b22; border:1px solid #30363d; border-radius:8px; padding:16px 28px; margin:8px 16px 8px 0; }}
.label {{ color:#8b949e; font-size:12px; text-transform:uppercase; letter-spacing:1px; }}
.ts {{ color:#8b949e; font-size:12px; }}
</style>
</head>
<body>
<h1>PgBouncer PoC &mdash; live connection monitor</h1>
<div class="ts">captured at {ts} (query executed live against the running Postgres/PgBouncer processes)</div>

<div class="card">
  <div class="label">Postgres max_connections</div>
  <div class="big">{max_conn}</div>
</div>
<div class="card">
  <div class="label">Real connections on Postgres :5432 right now</div>
  <div class="big {pg_class}">{pg_count}</div>
</div>

<h2>New direct connection attempt to Postgres (what a DBA / another service would experience right now)</h2>
<pre>{probe}</pre>

<h2>pg_stat_activity (real backend processes on Postgres :5432)</h2>
<pre>{activity}</pre>

<h2>PgBouncer SHOW POOLS (client-side demand vs. real server connections used)</h2>
<pre>{pools}</pre>
</body></html>
"""

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        max_conn, _ = run_sql(5432, "postgres", "SHOW max_connections;")
        pg_count, pg_err = run_sql(5432, "postgres", "SELECT count(*) FROM pg_stat_activity;")
        probe_out, probe_err = run_sql(5432, "postgres", "SELECT 'connection OK, backend pid ' || pg_backend_pid();")
        probe = probe_out if probe_out else ("ERROR: " + (probe_err or "unknown"))
        activity, act_err = run_sql_table(5432, "postgres",
            "SELECT pid, usename, datname, state, backend_start FROM pg_stat_activity WHERE datname IS NOT NULL ORDER BY pid;")
        activity = activity if activity else ("ERROR: " + (act_err or "unknown"))
        pools, pool_err = run_sql_table(6432, "pgbouncer", "SHOW POOLS;", expanded=True)
        pools = pools if pools else ("PgBouncer not reachable: " + (pool_err or "unknown"))

        pg_class = "ok"
        if pg_count and pg_count.isdigit() and max_conn and max_conn.isdigit():
            if int(pg_count) >= int(max_conn) - 2:
                pg_class = "bad"

        body = PAGE.format(
            ts=ts, max_conn=max_conn or "?", pg_count=pg_count or "ERR", pg_class=pg_class,
            probe=probe, activity=activity, pools=pools,
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

if __name__ == "__main__":
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 7000), Handler)
    print("monitor listening on http://127.0.0.1:7000")
    server.serve_forever()
