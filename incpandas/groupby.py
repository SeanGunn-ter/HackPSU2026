from __future__ import annotations

import numpy as np
import pandas as pd

from .nodes import Node, StateMismatch, _h


_SIMPLE = ("sum", "count", "mean", "min", "max")
_STATS = {"sum": ("sum",), "count": ("count",), "mean": ("sum", "count"), "min": ("min",), "max": ("max",)}
_MERGE = {"sum": "sum", "count": "sum", "min": "min", "max": "max"}


def _targets(columns, keys, sel):
    if sel is None:
        return [c for c in columns if c not in keys]
    cols = [sel] if isinstance(sel, str) else list(sel)
    ok = (all(isinstance(c, str) and c in columns and c not in keys for c in cols)
          and len(set(cols)) == len(cols))
    return cols if ok else None


def plan_agg(columns, keys, sel, method, args, kwargs, gkw):
    """Describe a groupby call we can maintain incrementally, or None."""
    if columns is None or not all(k in columns for k in keys):
        return None
    if set(gkw) - {"as_index", "sort", "dropna"} or gkw.get("dropna", True) is not True:
        return None
    as_index, series, outputs = gkw.get("as_index", True), False, None
    fn = None
    if method in _SIMPLE and not args and not kwargs:
        fn = method
    elif (method in ("agg", "aggregate") and len(args) == 1 and not kwargs
          and isinstance(args[0], str) and args[0] in _SIMPLE):
        fn = args[0]
    if fn is not None:
        targets = _targets(columns, keys, sel)
        if not targets:
            return None
        outputs, series = [(c, c, fn) for c in targets], isinstance(sel, str)
    elif method in ("agg", "aggregate") and sel is None:
        outputs = []
        if len(args) == 1 and not kwargs and isinstance(args[0], dict):
            items = [(c, c, f) for c, f in args[0].items()]
        elif not args and kwargs and all(isinstance(v, tuple) and len(v) == 2 for v in kwargs.values()):
            items = [(name, c, f) for name, (c, f) in kwargs.items()]
        else:
            return None
        for out, c, f in items:
            if not (isinstance(c, str) and c in columns and c not in keys
                    and isinstance(f, str) and f in _SIMPLE):
                return None
            outputs.append((out, c, f))
    else:
        return None
    if (series and not as_index) or len({o for o, _, _ in outputs}) != len(outputs):
        return None
    cols = list(dict.fromkeys(c for _, c, _ in outputs))
    need = sorted({s for _, _, f in outputs for s in _STATS[f]})
    return {"outputs": outputs, "cols": cols, "need": need, "series": series,
            "as_index": as_index, "sort": gkw.get("sort", True)}


class GroupAgg(Node):
    """groupby(...).sum/count/mean/min/max kept as per-group partial aggregates.

    Falls back to a real pandas groupby over the full parent whenever the call or the
    dtypes aren't covered (so results are never wrong, just not incremental).
    """
    kind = "GroupBy"

    def __init__(self, parent, by, sel, gkw, call):
        self.parent, self.parents = parent, (parent,)
        self.by, self.sel, self.gkw, self.call = by, sel, dict(gkw), call
        self.keys = [by] if isinstance(by, str) else list(by)
        self.spec = plan_agg(parent.columns, self.keys, sel, call[0], call[1], call[2], self.gkw)
        self.fast = self.spec is not None
        if not self.fast:
            self.why = "aggregation not supported incrementally"
            self.columns = None
        else:
            outs = [o for o, _, _ in self.spec["outputs"]]
            self.columns = None if self.spec["series"] else (outs if self.spec["as_index"] else self.keys + outs)
        self.sig = _h("groupby", parent.sig, repr(by), repr(sel), repr(sorted(self.gkw.items())), repr(call))

    def label(self):
        sel = "" if self.sel is None else f"[{self.sel!r}]"
        m, a, k = self.call
        return f"groupby({self.by!r}){sel}.{m}({', '.join(map(repr, a))}{', '.join(f'{x}={y!r}' for x, y in k.items())})"

    def apply_pandas(self, p):
        g = p.groupby(self.by, **self.gkw)
        if self.sel is not None:
            g = g[self.sel]
        m, a, k = self.call
        return getattr(g, m)(*a, **k)

    def stream(self, ctx):
        spec = self.spec
        if spec is not None:
            d, reset = ctx.stream(self.parent)
            if self._eligible(d, spec):
                out = self._incremental(ctx, d, reset)
                if len(out) == 0:   # no groups: let pandas produce its exact empty shape
                    out = self.apply_pandas(d.iloc[:0])
                ctx.note(self, "full" if reset else "incremental", len(d))
                return out, True
            ctx.clear_state(self)
        full = ctx.full(self.parent)
        ctx.note(self, "fallback", len(full))
        return self.apply_pandas(full), True

    def _eligible(self, d, spec):
        for c in spec["cols"]:
            dt = d[c].dtype
            # float32/float16 are left to pandas: it keeps their width, so a float64 partial
            # total would give a different dtype (mean) or different rounding (sum)
            if not (isinstance(dt, np.dtype) and (dt.kind in "iu" or dt == np.float64)):
                return False
        return not any(isinstance(d[k].dtype, pd.CategoricalDtype) for k in self.keys)

    def _incremental(self, ctx, d, reset):
        spec = self.spec
        dts = {c: d[c].dtype for c in spec["cols"]}
        old = None
        if not reset:
            st = ctx.old_state(self)
            if st is None or st["dtypes"] != dts:
                raise StateMismatch(self.label())
            old = st["tables"]
        if old is not None and len(d) == 0:
            tables = old
        else:
            g = d.groupby(self.keys, sort=False, dropna=True)[spec["cols"]]
            part = {s: getattr(g, s)() for s in spec["need"]}
            tables = part if old is None else {s: _merge(old[s], part[s], s) for s in part}
            if len(d):
                ctx.changed = True
        ctx.set_state(self, {"tables": tables, "dtypes": dts})
        return self._result(tables)

    def _result(self, tables):
        spec = self.spec
        if spec["sort"]:
            tables = {s: t.sort_index() for s, t in tables.items()}
        cols = {}
        for out, col, fn in spec["outputs"]:
            cols[out] = tables["sum"][col] / tables["count"][col] if fn == "mean" else tables[fn][col]
        if spec["series"]:
            (out,) = cols
            s = cols[out]
            s.name = out
            return s
        frame = pd.DataFrame(cols)
        return frame if spec["as_index"] else frame.reset_index()

    def replay(self, rep):
        return self.apply_pandas(rep(self.parent))


def _merge(a, b, stat):
    levels = list(range(a.index.nlevels))
    return pd.concat([a, b]).groupby(level=levels, sort=False).agg(_MERGE[stat])
