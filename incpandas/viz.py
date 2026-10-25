"""Plan graph: the same plan `explain()` prints as text, as a self-contained HTML page.

    from incpandas import viz

    df = pd.read_csv("sales.csv")
    df["revenue"] = df.qty * df.price
    out = df[df.revenue > 20].groupby("region")[["revenue"]].sum()
    out.to_pandas()                 # run it first, so the graph has a last run to show
    viz.graph(out, "plan.html")     # or out.graph("plan.html"), or viz.show(out)

Importing this module installs `LazyFrame.graph`, so nothing in `frame.py` has to change.

Node colour is what happened on the last run, falling back to what the plan can do if it has
not run yet:

    green   incremental -- only the appended rows went through this node
    blue    full        -- this node processed everything (a first run, or a rebuild)
    red     fallback    -- real pandas ran over the whole input here
    grey    not run yet

The page embeds its own CSS and SVG and loads nothing over the network, so it opens from a
file:// URL on a laptop with no internet.
"""
from __future__ import annotations

import html
import os
import tempfile
import webbrowser

from . import engine

NODE_W, NODE_H = 236, 82
X_GAP, Y_GAP = 26, 58
PAD = 26

# mode -> (css class, human label)
MODES = {"incremental": ("inc", "incremental"),
         "full": ("full", "full pass"),
         "fallback": ("fb", "pandas fallback")}


def _order(node):
    """Nodes in dependency order (parents before children), as `explain()` lists them."""
    out, seen = [], set()

    def visit(n):
        if n.sig in seen:
            return
        seen.add(n.sig)
        for d in n.deps():
            visit(d)
        out.append(n)
    visit(node)
    return out


def _layers(order):
    """Put every node directly above its earliest consumer.

    The obvious layering -- one past your deepest dependency -- puts a second `read_csv` on
    the top row even when it is only needed by a merge far below, and its edge then runs the
    whole height of the graph past unrelated nodes. Hanging each node from its first consumer
    instead keeps those edges short. `order` is topological, so walking it backwards means a
    node's consumers always have a depth already.
    """
    consumers = {}
    for n in order:
        for d in n.deps():
            consumers.setdefault(d.sig, []).append(n.sig)

    asap = {}
    for n in order:
        asap[n.sig] = 1 + max((asap[d.sig] for d in n.deps()), default=-1)

    depth = {order[-1].sig: max(asap.values())}          # the result sits on the bottom row
    for n in reversed(order[:-1]):
        depth[n.sig] = min(depth[c] for c in consumers[n.sig]) - 1

    # Pulling nodes down can empty a row, so renumber to consecutive rows.
    used = {d: i for i, d in enumerate(sorted(set(depth.values())))}
    depth = {sig: used[d] for sig, d in depth.items()}
    rows = {}
    for n in order:
        rows.setdefault(depth[n.sig], []).append(n)
    return depth, rows


def _status(n, ran):
    """(css class, status text, detail) for one node."""
    if n.sig in ran:
        mode, rows = ran[n.sig]
        cls, name = MODES.get(mode, ("full", mode))
        return cls, f"{name} · {rows:,} rows", (n.why if not n.fast else "")
    return ("none" if n.fast else "fb"), "not run yet", n.why


def _node_svg(n, x, y, idx, ran):
    cls, status, detail = _status(n, ran)
    label = n.label()
    tip = label if not detail else f"{label}\n{detail}"
    if n.columns:
        tip += "\ncolumns: " + ", ".join(map(str, n.columns))
    parts = [f'<g class="node {cls}">',
             f'<title>{html.escape(tip)}</title>',
             f'<rect x="{x}" y="{y}" width="{NODE_W}" height="{NODE_H}" rx="9"/>',
             f'<text class="kind" x="{x + 12}" y="{y + 21}">'
             f'<tspan class="idx">#{idx}</tspan> {html.escape(n.kind)}</text>',
             f'<text class="label" x="{x + 12}" y="{y + 39}">{html.escape(_clip(label, 30))}</text>',
             f'<text class="status" x="{x + 12}" y="{y + 56}">{html.escape(status)}</text>']
    if detail:
        # its own line: a right-anchored reason collides with the status text on a long one
        parts.append(f'<text class="why" x="{x + 12}" y="{y + 72}">'
                     f'{html.escape(_clip(detail, 32))}</text>')
    parts.append("</g>")
    return "".join(parts)


def _clip(text, n):
    text = str(text)
    return text if len(text) <= n else text[: n - 1] + "…"


def _edge_svg(x1, y1, x2, y2):
    """A dependency, curved so crossing edges stay readable."""
    mid = (y1 + y2) / 2
    return (f'<path class="edge" d="M {x1} {y1} C {x1} {mid}, {x2} {mid}, {x2} {y2}" '
            f'marker-end="url(#arrow)"/>')


def _svg(node, ran):
    order = _order(node)
    idx = {n.sig: i for i, n in enumerate(order)}
    depth, rows = _layers(order)
    widest = max(len(ns) for ns in rows.values())
    width = PAD * 2 + widest * NODE_W + (widest - 1) * X_GAP
    height = PAD * 2 + len(rows) * NODE_H + (len(rows) - 1) * Y_GAP

    at = {}
    for d in sorted(rows):
        layer = rows[d]
        span = len(layer) * NODE_W + (len(layer) - 1) * X_GAP
        x0 = (width - span) / 2
        for i, n in enumerate(layer):
            at[n.sig] = (x0 + i * (NODE_W + X_GAP), PAD + d * (NODE_H + Y_GAP))

    edges = []
    for n in order:
        cx, cy = at[n.sig]
        for dep in n.deps():
            px, py = at[dep.sig]
            edges.append(_edge_svg(px + NODE_W / 2, py + NODE_H, cx + NODE_W / 2, cy))

    nodes = [_node_svg(n, *at[n.sig], idx[n.sig], ran) for n in order]
    return (f'<svg viewBox="0 0 {width:.0f} {height:.0f}" width="{width:.0f}" '
            f'xmlns="http://www.w3.org/2000/svg" role="img">'
            '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" '
            'markerHeight="6" orient="auto-start-reverse">'
            '<path d="M 0 0 L 10 5 L 0 10 z"/></marker></defs>'
            + "".join(edges) + "".join(nodes) + "</svg>")


CSS = """
:root { color-scheme: light dark;
  --bg:#fff; --fg:#1b1f24; --muted:#6b7280; --line:#9aa4b2; --card:#f6f8fa;
  --inc:#1a7f37; --inc-bg:#e9f7ee; --full:#0a5cc4; --full-bg:#e8f1fd;
  --fb:#c0392b; --fb-bg:#fdecea; --none:#6b7280; --none-bg:#f1f3f5; }
@media (prefers-color-scheme: dark) { :root {
  --bg:#0d1117; --fg:#e6edf3; --muted:#9198a1; --line:#5b6472; --card:#161b22;
  --inc:#4ac26b; --inc-bg:#12261a; --full:#6cb0ff; --full-bg:#0f1f33;
  --fb:#ff8a80; --fb-bg:#2b1412; --none:#9198a1; --none-bg:#1b2027; } }
* { box-sizing:border-box }
body { margin:0; padding:24px; background:var(--bg); color:var(--fg);
  font:14px/1.5 ui-sans-serif,-apple-system,"Segoe UI",Roboto,sans-serif }
h1 { font-size:19px; margin:0 0 4px }
.sub { color:var(--muted); margin:0 0 18px }
.sub code { background:var(--card); padding:1px 5px; border-radius:4px }
.legend { display:flex; gap:18px; flex-wrap:wrap; margin:0 0 18px; padding:0; list-style:none }
.legend li { display:flex; align-items:center; gap:7px; color:var(--muted) }
.legend i { width:11px; height:11px; border-radius:3px; border:1.5px solid }
.wrap { overflow-x:auto; border:1px solid var(--card); border-radius:10px; background:var(--card) }
svg { display:block; max-width:100%; height:auto }
.edge { fill:none; stroke:var(--line); stroke-width:1.6 }
marker path { fill:var(--line) }
.node rect { stroke-width:1.6 }
.node text { font:12px/1 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace }
.node .kind { font-weight:600; font-size:12.5px }
.node .idx { fill:var(--muted); font-weight:400 }
.node .label { fill:var(--fg) }
.node .status, .node .why { font-size:11px }
.node.inc rect { fill:var(--inc-bg); stroke:var(--inc) }
.node.inc .kind, .node.inc .status { fill:var(--inc) }
.node.full rect { fill:var(--full-bg); stroke:var(--full) }
.node.full .kind, .node.full .status { fill:var(--full) }
.node.fb rect { fill:var(--fb-bg); stroke:var(--fb) }
.node.fb .kind, .node.fb .status, .node.fb .why { fill:var(--fb) }
.node.none rect { fill:var(--none-bg); stroke:var(--none); stroke-dasharray:4 3 }
.node.none .kind, .node.none .status { fill:var(--none) }
.node .why { fill:var(--muted) }
footer { color:var(--muted); margin-top:16px; font-size:12.5px }
"""


def _unwrap(obj):
    """The plan node behind a LazyFrame, a lazy Series/expression, or a node itself."""
    for attr in ("_node", "node"):
        if hasattr(obj, attr):
            return getattr(obj, attr)
    if hasattr(obj, "sig") and hasattr(obj, "deps"):
        return obj
    raise TypeError(f"{type(obj).__name__} has no incpandas plan to draw; pass a lazy frame")


def to_html(obj, title="incpandas plan"):
    """The plan behind `obj` as one self-contained HTML document."""
    node = _unwrap(obj)
    ran = engine.last_run()
    legend = "".join(
        f'<li><i style="background:var(--{c}-bg);border-color:var(--{c})"></i>{t}</li>'
        for c, t in [("inc", "incremental"), ("full", "full pass"),
                     ("fb", "pandas fallback"), ("none", "not run yet")])
    note = ("Colours are the last run." if ran else
            "This plan has not run yet — call <code>to_pandas()</code> first to see "
            "what each node did.")
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{html.escape(title)}</title><style>{CSS}</style></head><body>'
            f'<h1>{html.escape(title)}</h1><p class="sub">{note}</p>'
            f'<ul class="legend">{legend}</ul>'
            f'<div class="wrap">{_svg(node, ran)}</div>'
            f'<footer>Arrows point from a node to the nodes that depend on it. '
            f'Hover a node for its full label and columns.</footer></body></html>')


def graph(obj, path=None, title="incpandas plan"):
    """Render the plan. With `path`, write it there and return the path; else return the HTML."""
    doc = to_html(obj, title)
    if path is None:
        return doc
    path = os.fspath(path)
    with open(path, "w", encoding="utf-8") as f:
        f.write(doc)
    return path


def show(obj, title="incpandas plan"):
    """Write the plan to a temporary file and open it in a browser. Returns the path."""
    fd, path = tempfile.mkstemp(prefix="incpandas-plan-", suffix=".html")
    os.close(fd)
    graph(obj, path, title)
    webbrowser.open(f"file://{os.path.abspath(path)}")
    return path


def _install():
    """Attach `.graph()` to lazy frames, so `frame.py` needs no change for this."""
    from .frame import LazyFrame
    LazyFrame.graph = graph
    LazyFrame.show = show


_install()
