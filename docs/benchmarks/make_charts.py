"""Draw the benchmark charts from results.json (and results_run2.json when present).

    python docs/benchmarks/make_charts.py

Needs matplotlib (not a dependency of incpandas). Every number comes from the JSON files;
nothing is typed in here. Writes PNG and SVG next to this script.
"""
import json
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
SCENARIOS = ["first run", "append", "no change"]
PIPE_LABEL = {"reduction": "col.sum()", "formula_reduction": "(a*b).sum()", "groupby": "groupby agg",
              "merge": "merge + groupby", "rowwise": "row-wise filter\n(large output)"}
ORDER = ["reduction", "formula_reduction", "groupby", "merge", "rowwise"]
# Okabe-Ito: distinguishable with the common kinds of colour-blindness
SIZE_COLOURS = ["#0072B2", "#E69F00", "#CC79A7", "#009E73"]
PART_COLOURS = {"read_header": "#56B4E9", "read_and_hash": "#0072B2", "parse_appended_tail": "#E69F00",
                "load_saved_state": "#CC79A7", "everything else": "#999999"}
PART_LABEL = {"read_header": "read CSV header", "read_and_hash": "read + hash whole file",
              "parse_appended_tail": "parse appended rows", "load_saved_state": "load saved state",
              "everything else": "everything else (residual)"}


def load(name):
    path = os.path.join(HERE, name)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def index(data):
    return {(c["pipeline"], c["rows"], c["appended"]): c for c in data["results"]}


def caption(env):
    machine = load("machine.json") or {}
    cpu = machine.get("cpu_model", env["processor"])
    ram = f", {machine['ram_gb']} GB RAM" if "ram_gb" in machine else ""
    return (f"{env['platform'].split('-with')[0]}, {cpu}, {env['cpus']} cores{ram}; "
            f"python {env['python']}, pandas {env['pandas']}, numpy {env['numpy']}")


def speedup_chart(run1, run2, appended):
    cells, cells2 = index(run1), index(run2) if run2 else {}
    sizes = sorted({c["rows"] for c in run1["results"] if c["appended"] == appended})
    pipes = [p for p in ORDER if any(k[0] == p for k in cells)]
    fig, axes = plt.subplots(1, 3, figsize=(16, 5.4))
    width = 0.8 / len(sizes)
    for ax, scen in zip(axes, SCENARIOS):
        for j, rows in enumerate(sizes):
            xs = [i + (j - (len(sizes) - 1) / 2) * width for i in range(len(pipes))]
            ys = [cells[(p, rows, appended)]["scenarios"][scen]["speedup"] for p in pipes]
            ax.bar(xs, ys, width * 0.92, color=SIZE_COLOURS[j], label=f"{rows / 1e6:g}M rows")
            for x, y in zip(xs, ys):
                ax.text(x, y, f"{y:.1f}", ha="center", va="bottom", fontsize=7)
            if cells2:
                y2 = [cells2[(p, rows, appended)]["scenarios"][scen]["speedup"] for p in pipes]
                ax.plot(xs, y2, "o", color="black", ms=3.5, zorder=3,
                        label="second full run" if j == 0 else None)
        ax.axhline(1, color="black", lw=1, ls="--")
        ax.set_title({"first run": "First run (no saved state)", "append": f"Rerun after appending {appended:,} rows",
                      "no change": "Rerun, file unchanged"}[scen])
        ax.set_xticks(range(len(pipes)), [PIPE_LABEL[p] for p in pipes], fontsize=8)
        ax.set_ylim(bottom=0)
        ax.set_ylabel("speedup over plain pandas (x, higher is better)")
        ax.grid(axis="y", alpha=0.25)
        ax.set_axisbelow(True)
    axes[0].legend(loc="upper left", fontsize=8, frameon=False)
    fig.suptitle("incpandas speedup over plain pandas (median of repeats; dashed line = same speed as pandas)",
                 fontsize=12)
    fig.text(0.5, 0.005, caption(run1["environment"]) + (". Dots: an independent second run of the same matrix."
                                                          if run2 else ""), ha="center", fontsize=8, color="#444")
    fig.tight_layout(rect=(0, 0.03, 1, 0.95))
    save(fig, "speedups")


def breakdown_chart(run1, appended):
    cells = index(run1)
    sizes = sorted({c["rows"] for c in run1["results"] if c["appended"] == appended})[-2:]
    pipes = [p for p in ORDER if any(k[0] == p for k in cells)]
    fig, axes = plt.subplots(1, len(sizes), figsize=(7.5 * len(sizes), 4.6), sharex=False)
    axes = [axes] if len(sizes) == 1 else axes
    for ax, rows in zip(axes, sizes):
        left = [0.0] * len(pipes)
        for part in list(PART_COLOURS):
            vals = []
            for p in pipes:
                c = cells[(p, rows, appended)]
                total = c["scenarios"]["append"]["incpandas"]["median"] * 1e3
                if part == "everything else":
                    v = total - sum(c["components"][k] * 1e3 for k in PART_COLOURS if k != part)
                else:
                    v = c["components"][part] * 1e3
                vals.append(max(v, 0))
            ax.barh(range(len(pipes)), vals, left=left, color=PART_COLOURS[part], label=PART_LABEL[part])
            left = [a + b for a, b in zip(left, vals)]
        for i, p in enumerate(pipes):
            ax.text(left[i], i, f"  {cells[(p, rows, appended)]['scenarios']['append']['incpandas']['median'] * 1e3:.0f} ms",
                    va="center", fontsize=8)
        ax.set_yticks(range(len(pipes)), [PIPE_LABEL[p].replace("\n", " ") for p in pipes])
        ax.invert_yaxis()
        ax.set_xlim(left=0, right=max(left) * 1.18)
        ax.set_xlabel("milliseconds per rerun (median)")
        ax.set_title(f"{rows / 1e6:g}M rows, +{appended:,} appended")
        ax.grid(axis="x", alpha=0.25)
        ax.set_axisbelow(True)
    axes[0].legend(loc="lower right", fontsize=7.5, frameon=False)
    fig.suptitle("Where an incpandas rerun spends its time (each part timed on its own; the rest is the residual)",
                 fontsize=11.5)
    fig.text(0.5, 0.005, caption(run1["environment"]), ha="center", fontsize=8, color="#444")
    fig.tight_layout(rect=(0, 0.03, 1, 0.94))
    save(fig, "rerun_time_breakdown")


def absolute_chart(run1, appended):
    cells = index(run1)
    sizes = sorted({c["rows"] for c in run1["results"] if c["appended"] == appended})
    pipes = [p for p in ORDER if any(k[0] == p for k in cells)]
    fig, axes = plt.subplots(1, len(pipes), figsize=(3.4 * len(pipes), 4.2))
    for ax, p in zip(axes, pipes):
        for j, (lib, col) in enumerate([("pandas", "#999999"), ("incpandas", "#0072B2")]):
            ys = [cells[(p, r, appended)]["scenarios"]["append"][lib]["median"] for r in sizes]
            lo = [cells[(p, r, appended)]["scenarios"]["append"][lib]["min"] for r in sizes]
            hi = [cells[(p, r, appended)]["scenarios"]["append"][lib]["max"] for r in sizes]
            ax.errorbar([r / 1e6 for r in sizes], ys, yerr=[[y - l for y, l in zip(ys, lo)],
                                                          [h - y for y, h in zip(ys, hi)]],
                        marker="o", color=col, label=lib, capsize=3)
        ax.set_title(PIPE_LABEL[p].replace("\n", " "), fontsize=9)
        ax.set_xlabel("rows (millions)")
        ax.set_ylim(bottom=0)
        ax.grid(alpha=0.25)
    axes[0].set_ylabel("seconds for one rerun after an append")
    axes[0].legend(frameon=False, fontsize=8)
    fig.suptitle(f"Time for a rerun after appending {appended:,} rows (median, bars = min to max of repeats)",
                 fontsize=11.5)
    fig.text(0.5, 0.005, caption(run1["environment"]), ha="center", fontsize=8, color="#444")
    fig.tight_layout(rect=(0, 0.04, 1, 0.93))
    save(fig, "append_seconds_vs_rows")


def save(fig, name):
    for ext in ("png", "svg"):
        fig.savefig(os.path.join(HERE, f"{name}.{ext}"), dpi=140)
    plt.close(fig)
    print("wrote", name)


if __name__ == "__main__":
    run1, run2 = load("results.json"), load("results_run2.json")
    appended = sorted({c["appended"] for c in run1["results"]})[0]
    speedup_chart(run1, run2, appended)
    breakdown_chart(run1, appended)
    absolute_chart(run1, appended)
