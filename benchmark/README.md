# Connection-pool sizing benchmark

Measures a Spring Boot app against PostgreSQL three ways — no pool, HikariCP, and
HikariCP behind PgBouncer — across pool sizes that sit below, at, and above the
database's own connection ceiling, at one and four app instances.

Everything here is produced by actually running the system. `benchmark/results/`
holds the raw output; nothing in the report is estimated or extrapolated.

## Why the numbers come out where they do

The workload is deliberately simple so the results are checkable by hand. Each
request holds one database connection for `workMs` (default 50ms) via
`pg_sleep` joined into the query, then returns. So a setup that can keep `N`
connections genuinely busy has a theoretical ceiling of:

```
max throughput (req/s) = N / 0.050
```

10 usable connections → ~200 req/s. 20 → ~400 req/s. When a measured number
lands near that line the setup is connection-bound; when it lands far below,
something else (connection setup cost, queueing, failures) is eating the budget.

## Topology

```
loadgen.py ──HTTP──> 1 or 4 Spring Boot instances ──JDBC──> [PgBouncer :6432] ──> PostgreSQL :5432
   (closed loop)        (HikariCP, or no pool)              (transaction mode)     max_connections=25
```

PostgreSQL runs with `max_connections = 25` and `superuser_reserved_connections = 5`.
The app connects as `appuser`, which is **not** a superuser, so it can hold at most
**20 backends** — that is the "postgres pool" every comparison is relative to.

Keeping 5 slots reserved for superusers is what lets the harness keep measuring
(`pg_stat_activity`, `SHOW POOLS`) even while the app has exhausted its own share.
It also mirrors how a real database stays reachable for operators during an incident.

## The matrix

| Scenario | What it varies |
|---|---|
| **S1** PostgreSQL direct, no pool | one instance, a new physical connection per request |
| **S2** PostgreSQL + HikariCP | pool 10 (`<` 20), 20 (`=` 20), 40 (`>` 20) × 1 and 4 instances |
| **S3** + PgBouncer (transaction mode) | the same six, through PgBouncer with pool 20 |
| **S3** PgBouncer pool sweep | PgBouncer pool 5 / 10 / 20 under the 1×20 and 4×40 client loads |

With 4 instances the client-side demand is `instances × hikari pool`, so the 4×40
case asks for 160 connections against a database that allows 20 — an 8× oversubscription.

Each run is measured at concurrency 10, 25, 50, 100 and 200 so the point where a
setup stops coping is observed rather than guessed.

## Method notes, including the limits

- **Closed-loop load.** `concurrency` worker threads each keep one persistent HTTP
  connection and issue requests back to back. Offered load is therefore bounded by
  `concurrency / latency`: when latency rises, throughput falls rather than a queue
  growing without bound. This models a fixed-size caller thread pool, not an
  open-loop arrival process, and it is why throughput flattens instead of collapsing.
- **Warmup.** 3s of unrecorded requests per level, so JIT and pool fill do not
  land in the percentiles.
- **Tomcat threads raised to 300** so the servlet container is not the bottleneck
  at concurrency 200 — the thing being measured is the database connection layer.
- **HikariCP `connection-timeout` is 5s** and `minimum-idle` is 2, so pools grow
  under load the way they would in production rather than being pre-filled.
- **Runs are isolated.** PgBouncer is stopped between runs and the harness waits
  for `appuser`'s backends to drain to zero, so no run inherits connections from
  the previous one. This matters: PgBouncer holds server connections idle for
  `server_idle_timeout` after clients disconnect.
- **Single host.** App, PgBouncer and PostgreSQL share one machine, so network
  latency is ~0. This *understates* PgBouncer's benefit (a real deployment pays
  round-trips PgBouncer can amortise) and *overstates* its relative overhead
  (its extra hop is pure cost here). Read the latency deltas with that in mind.

## Reproduce

```bash
# PostgreSQL: max_connections=25, superuser_reserved_connections=5, then
sudo -u postgres psql -c "CREATE ROLE appuser LOGIN PASSWORD 'apppass';" \
                     -c "CREATE DATABASE appdb OWNER appuser;"
PGPASSWORD=apppass psql -h 127.0.0.1 -U appuser -d appdb -f sql/hikaricp-setup.sql

# PgBouncer: userlist.txt needs appuser's SCRAM verifier from pg_authid;
# the harness generates pgbouncer.ini from pgbouncer.ini.template per run.

mvn -DskipTests package
python3 benchmark/run_matrix.py              # whole matrix, ~30 min
python3 benchmark/run_matrix.py S2-hikari10  # or a subset, by run id
```

Outputs: `benchmark/results/matrix.json` (full detail, including per-level error
breakdowns), `benchmark/results/matrix.csv` (flat, one row per run × concurrency),
`benchmark/results/logs/` (per-instance application logs).

## Running the app by hand

```bash
# pooled, straight to PostgreSQL
java -jar target/PoolKeeperBoot-1.0-SNAPSHOT.jar --app.datasources.appdb.maximum-pool-size=20

# no pool at all: a new physical connection per request
java -jar target/PoolKeeperBoot-1.0-SNAPSHOT.jar --app.pooling=none

# through PgBouncer
java -jar target/PoolKeeperBoot-1.0-SNAPSHOT.jar --spring.profiles.active=pgbouncer

curl 'http://localhost:8080/api/appdb/employees?workMs=50'
```
