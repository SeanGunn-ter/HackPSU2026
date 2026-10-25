"""Print the benchmark tables as markdown, from the JSON files in this folder.

    python docs/benchmarks/make_tables.py > docs/benchmarks/tables.md
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
NAMES = {"reduction": "`df.qty.sum()`", "formula_reduction": "`(df.qty * df.price).sum()`",
         "groupby": "filter + groupby agg", "merge": "left merge + groupby",
         "rowwise": "row-wise filter (large output)"}
ORDER = ["reduction", "formula_reduction", "groupby", "merge", "rowwise"]


def load(name):
    p = os.path.join(HERE, name)
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else None


def idx(d):
    return {(c["pipeline"], c["rows"]): c for c in d["results"]}


def sec(x):
    return f"{x['median']:.3f} ({x['min']:.3f}-{x['max']:.3f})" if x["median"] >= 0.01 else \
        f"{x['median'] * 1e3:.1f} ms ({x['min'] * 1e3:.1f}-{x['max'] * 1e3:.1f})"


def table(scen, r1, r2):
    a, b = idx(r1), idx(r2)
    out = [f"| pipeline | rows | pandas, s (min-max) | incpandas (min-max) | speedup run 1 | speedup run 2 |",
           "|---|---|---|---|---|---|"]
    for rows in sorted({k[1] for k in a}):
        for p in ORDER:
            x, y = a[(p, rows)]["scenarios"][scen], b[(p, rows)]["scenarios"][scen]
            out.append(f"| {NAMES[p]} | {rows / 1e6:g}M | {sec(x['pandas'])} | {sec(x['incpandas'])} | "
                       f"{x['speedup']:.1f}x | {y['speedup']:.1f}x |")
    return "\n".join(out)


def exact_table(r1, ex):
    a, e = idx(r1), idx(ex)
    out = ["| pipeline | rows | scenario | default: incpandas | default speedup | exact: incpandas | exact speedup |",
           "|---|---|---|---|---|---|---|"]
    for rows in sorted({k[1] for k in e}):
        for p in ORDER:
            for scen in ("append", "no change"):
                x, y = a[(p, rows)]["scenarios"][scen], e[(p, rows)]["scenarios"][scen]
                out.append(f"| {NAMES[p]} | {rows / 1e6:g}M | {scen} | {sec(x['incpandas'])} | "
                           f"{x['speedup']:.1f}x | {sec(y['incpandas'])} | {y['speedup']:.1f}x |")
    return "\n".join(out)


def state_table(r1):
    out = ["| pipeline | rows | CSV size | saved state on disk | rerun after append | of which: read + hash file | load saved state |",
           "|---|---|---|---|---|---|---|"]
    for c in sorted(r1["results"], key=lambda c: (c["rows"], ORDER.index(c["pipeline"]))):
        k = c["components"]
        tot = c["scenarios"]["append"]["incpandas"]["median"]
        size = k["state_bytes"]
        shown = f"{size / 1e6:.1f} MB" if size >= 1e6 else f"{size / 1e3:.0f} KB"
        out.append(f"| {NAMES[c['pipeline']]} | {c['rows'] / 1e6:g}M | {c['file_bytes'] / 1e6:.0f} MB | "
                   f"{shown} | {tot * 1e3:.0f} ms | {k['read_and_hash'] * 1e3:.0f} ms "
                   f"({100 * k['read_and_hash'] / tot:.0f}%) | {k['load_saved_state'] * 1e3:.0f} ms "
                   f"({100 * k['load_saved_state'] / tot:.0f}%) |")
    return "\n".join(out)


if __name__ == "__main__":
    r1, r2, ex = load("results.json"), load("results_run2.json"), load("results_exact.json")
    print("## First run\n\n" + table("first run", r1, r2))
    print("\n## Rerun after appending 1,000 rows\n\n" + table("append", r1, r2))
    print("\n## Rerun, file unchanged\n\n" + table("no change", r1, r2))
    print("\n## Default change detection vs INCPANDAS_CHECK=exact (run 1 vs the exact run)\n\n" + exact_table(r1, ex))
    print("\n## Saved state and where an append rerun goes (run 1)\n\n" + state_table(r1))
