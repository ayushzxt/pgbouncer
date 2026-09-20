#!/usr/bin/env python3
"""Turns benchmark/results/matrix.json into the charts and tables used by RESULTS.md.

Charts follow one categorical palette, validated for colour-vision deficiency
(scripts/validate_palette.js: all checks pass, contrast WARN relieved by the
direct labels here plus the full tables in RESULTS.md / matrix.csv).
"""
import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(HERE, "results")
CHARTS = os.path.join(RESULTS, "charts")

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
# categorical slots 1-4, in the palette's fixed order
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]
CRITICAL = "#d03b3b"

PG_CEILING = 20


def load():
    with open(os.path.join(RESULTS, "matrix.json")) as f:
        return json.load(f)


def by_id(data):
    return {r["id"]: r for r in data["runs"] if r.get("levels")}


def style(ax, title, subtitle, xlabel, ylabel):
    ax.set_facecolor(SURFACE)
    ax.figure.patch.set_facecolor(SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(AXIS)
        ax.spines[side].set_linewidth(0.8)
    ax.grid(axis="y", color=GRID, linewidth=0.8, linestyle="-")
    ax.set_axisbelow(True)
    ax.tick_params(colors=MUTED, labelsize=9, length=0)
    ax.set_xlabel(xlabel, color=INK_2, fontsize=10)
    ax.set_ylabel(ylabel, color=INK_2, fontsize=10)
    ax.set_title(title, color=INK, fontsize=13, fontweight="600", loc="left", pad=22)
    if subtitle:
        ax.text(0, 1.03, subtitle, transform=ax.transAxes, color=INK_2,
                fontsize=9.5, va="bottom")


def line_chart(path, series, title, subtitle, ylabel, metric, ceiling=None,
               ceiling_label=None, percent=False):
    """series: list of (label, run) - metric pulled per concurrency level."""
    fig, ax = plt.subplots(figsize=(8.6, 4.8), dpi=170)
    endpoints = []
    for i, (label, run) in enumerate(series):
        xs = [lv["concurrency"] for lv in run["levels"]]
        ys = [metric(lv) for lv in run["levels"]]
        color = SERIES[i % len(SERIES)]
        ax.plot(xs, ys, color=color, linewidth=2, marker="o", markersize=6,
                markeredgecolor=SURFACE, markeredgewidth=1.5, label=label, zorder=3)
        endpoints.append([ys[-1], label, color, xs[-1]])

    if ceiling is not None:
        ax.axhline(ceiling, color=MUTED, linewidth=1, zorder=1)
        ax.text(ax.get_xlim()[0], ceiling, f" {ceiling_label}", color=MUTED,
                fontsize=9, va="bottom", ha="left")

    # selective direct labels at the line ends, nudged apart so they never collide
    endpoints.sort()
    span = (max(e[0] for e in endpoints) - min(e[0] for e in endpoints)) or 1
    min_gap = span * 0.085
    for j in range(1, len(endpoints)):
        if endpoints[j][0] - endpoints[j - 1][0] < min_gap:
            endpoints[j][0] = endpoints[j - 1][0] + min_gap
    for y, label, color, x in endpoints:
        ax.text(x * 1.06, y, label, color=color, fontsize=9,
                va="center", ha="left", fontweight="600")

    ax.set_xscale("log")
    ticks = [lv["concurrency"] for lv in series[0][1]["levels"]]
    ax.set_xticks(ticks)
    ax.set_xticklabels([str(t) for t in ticks])
    ax.set_xlim(ticks[0] * 0.88, ticks[-1] * 1.95)
    ax.set_ylim(bottom=0)
    if percent:
        ax.set_ylim(top=105)
    style(ax, title, subtitle, "concurrent clients (log scale)", ylabel)
    leg = ax.legend(frameon=False, fontsize=9, loc="upper left",
                    bbox_to_anchor=(0, -0.16), ncol=len(series))
    for text in leg.get_texts():
        text.set_color(INK_2)
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight", facecolor=SURFACE)
    plt.close(fig)
    print("wrote", path)


def backends_chart(path, rows):
    """rows: list of (label, demand, actual_backends)"""
    fig, ax = plt.subplots(figsize=(9.6, 5.0), dpi=170)
    xs = range(len(rows))
    width = 0.38
    demand = [r[1] for r in rows]
    actual = [r[2] for r in rows]
    # 2px surface gap between adjacent bars, no borders around marks
    ax.bar([x - width / 2 - 0.01 for x in xs], demand, width, color=SERIES[1],
           label="connections the app wants at peak load", zorder=3)
    ax.bar([x + width / 2 + 0.01 for x in xs], actual, width, color=SERIES[0],
           label="real PostgreSQL backends used (max observed)", zorder=3)
    # The ceiling is named in the legend rather than annotated inline: at this bar
    # density every inline position collides with a bar.
    ceiling_line = ax.axhline(PG_CEILING, color=CRITICAL, linewidth=1.2, zorder=4,
                              label=f"PostgreSQL ceiling for the app role ({PG_CEILING})")

    for x, v in zip(xs, demand):
        ax.text(x - width / 2 - 0.01, v + 2, str(v), color=SERIES[1], fontsize=8.5,
                ha="center", fontweight="600")
    for x, v in zip(xs, actual):
        ax.text(x + width / 2 + 0.01, v + 2, str(v), color=SERIES[0], fontsize=8.5,
                ha="center", fontweight="600")

    ax.set_xticks(list(xs))
    ax.set_xticklabels([r[0] for r in rows], fontsize=8)
    style(ax, "PgBouncer decouples what the app asks for from what the database holds",
          "At 200 concurrent clients. Demand is instances × Hikari pool; with no pool it is one "
          "connection per in-flight request.",
          "", "connections")
    ax.set_ylim(0, max(demand) * 1.12)
    leg = ax.legend(frameon=False, fontsize=9, loc="upper left",
                    bbox_to_anchor=(0, -0.13), ncol=3)
    for text in leg.get_texts():
        text.set_color(INK_2)
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight", facecolor=SURFACE)
    plt.close(fig)
    print("wrote", path)


def main():
    os.makedirs(CHARTS, exist_ok=True)
    data = load()
    runs = by_id(data)

    def m_success(lv):
        return lv["success_rps"]

    def m_err(lv):
        return lv["error_rate_pct"]

    def m_p95(lv):
        return lv["latency_ms"].get("p95", 0)

    # --- 1: pool size sets throughput; no pool throws it away --------------
    single = [
        ("no pool", runs.get("S1-direct-noPool-1inst")),
        ("Hikari 10 (< 20)", runs.get("S2-hikari10-1inst")),
        ("Hikari 20 (= 20)", runs.get("S2-hikari20-1inst")),
        ("Hikari 40 (> 20)", runs.get("S2-hikari40-1inst")),
    ]
    single = [(l, r) for l, r in single if r]
    if single:
        line_chart(os.path.join(CHARTS, "01-throughput-single-instance.png"), single,
                   "Pool size sets throughput — up to the database's ceiling, not past it",
                   "One app instance. Successful requests only. Pools of 20 and 40 land on the "
                   "same line: PostgreSQL allows 20 either way.",
                   "successful requests / sec", m_success)

    # --- 2: the only configuration that failed at all ----------------------
    errs = [(l, r) for l, r in [
        ("no pool", runs.get("S1-direct-noPool-1inst")),
        ("HikariCP (all sizes)", runs.get("S2-hikari20-1inst")),
    ] if r]
    if errs:
        line_chart(os.path.join(CHARTS, "02-errors-single-instance.png"), errs,
                   "Only the unpooled setup ever failed a request",
                   "Every pooled run in the whole matrix — all pool sizes, 1 and 4 instances, "
                   "with and without PgBouncer — recorded 0 failures.",
                   "failed requests (%)", m_err, percent=True)

    # --- 3: the measured PgBouncer effect: tail latency --------------------
    # Hikari 20 ×4 and 40 ×4 direct differ by <0.1% (1885.0 vs 1886.6 ms at c=200),
    # so plotting both would draw one line on top of the other. One line, labelled
    # for both; the tables carry each separately.
    tail = [(l, r) for l, r in [
        ("Hikari 20 and 40 ×4, direct", runs.get("S2-hikari40-4inst")),
        ("Hikari 20 ×4, PgBouncer", runs.get("S3-hikari20-4inst-pgb20")),
        ("Hikari 40 ×4, PgBouncer", runs.get("S3-hikari40-4inst-pgb20")),
    ] if r]
    if tail:
        line_chart(os.path.join(CHARTS, "03-tail-latency-4instances.png"), tail,
                   "What PgBouncer actually bought: tail latency, not throughput",
                   "4 instances oversubscribing a 20-connection database. Same throughput, same "
                   "backend count — one shared queue instead of four competing ones.",
                   "p95 latency (ms)", m_p95)

    # --- 6: what the database actually holds -------------------------------
    rows = []
    for label, rid in [
        ("no pool\n1 inst", "S1-direct-noPool-1inst"),
        ("Hikari 10\n1 inst", "S2-hikari10-1inst"),
        ("Hikari 20\n1 inst", "S2-hikari20-1inst"),
        ("Hikari 40\n1 inst", "S2-hikari40-1inst"),
        ("Hikari 10\n4 inst", "S2-hikari10-4inst"),
        ("Hikari 20\n4 inst", "S2-hikari20-4inst"),
        ("Hikari 40\n4 inst", "S2-hikari40-4inst"),
        ("40 ×4 →\nPgB 20", "S3-hikari40-4inst-pgb20"),
        ("40 ×4 →\nPgB 10", "S3-hikari40-4inst-pgb10"),
        ("40 ×4 →\nPgB 5", "S3-hikari40-4inst-pgb5"),
    ]:
        r = runs.get(rid)
        if not r:
            continue
        last = r["levels"][-1]
        demand = (r["hikari"] or last["concurrency"]) * r["instances"]
        rows.append((label, demand, last.get("pg_backends_max") or 0))
    if rows:
        backends_chart(os.path.join(CHARTS, "04-backends-used.png"), rows)

    # --- 7: PgBouncer pool sweep -------------------------------------------
    sweep = [
        ("PgBouncer 5", runs.get("S3-hikari40-4inst-pgb5")),
        ("PgBouncer 10", runs.get("S3-hikari40-4inst-pgb10")),
        ("PgBouncer 20", runs.get("S3-hikari40-4inst-pgb20")),
    ]
    sweep = [(l, r) for l, r in sweep if r]
    if sweep:
        line_chart(os.path.join(CHARTS, "05-pgbouncer-pool-sweep.png"), sweep,
                   "Once PgBouncer is in the path, its pool size is the real throughput limit",
                   "4 instances × Hikari 40 (160 client connections). Hikari's own size stops "
                   "mattering — throughput tracks the PgBouncer pool exactly.",
                   "successful requests / sec", m_success)

    write_tables(data, runs)


def write_tables(data, runs):
    """Markdown tables — the table view that relieves the palette's contrast warning."""
    out = [f"<!-- generated by benchmark/make_report.py -->\n"]
    meta = data["meta"]
    out.append(f"PostgreSQL `max_connections={meta['pg_max_connections']}`, "
               f"`superuser_reserved_connections={meta['pg_superuser_reserved']}` "
               f"→ **{meta['pg_app_ceiling']} backends available to the app role**. "
               f"Each request holds its connection for {meta['work_ms']}ms.\n")
    for run in data["runs"]:
        if not run.get("levels"):
            continue
        out.append(f"\n### `{run['id']}`\n\n{run['label']}\n")
        out.append("| concurrency | success req/s | failed % | p50 ms | p95 ms | p99 ms | "
                   "PG backends (max) | PgBouncer server conns | failures seen |")
        out.append("|---:|---:|---:|---:|---:|---:|---:|---:|---|")
        for lv in run["levels"]:
            pgb = lv.get("pgbouncer", {})
            errs = ", ".join(f"`{k}` ×{v}" for k, v in lv["error_types"].items()) or "—"
            out.append(
                f"| {lv['concurrency']} | {lv['success_rps']} | {lv['error_rate_pct']} | "
                f"{lv['latency_ms'].get('p50')} | {lv['latency_ms'].get('p95')} | "
                f"{lv['latency_ms'].get('p99')} | {lv.get('pg_backends_max')} | "
                f"{pgb.get('sv_total_max', '—')} | {errs} |")
    path = os.path.join(RESULTS, "tables.md")
    with open(path, "w") as f:
        f.write("\n".join(out) + "\n")
    print("wrote", path)


if __name__ == "__main__":
    main()
