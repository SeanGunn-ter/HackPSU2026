"""Plan nodes. Each node knows how to (a) run incrementally and (b) replay in plain pandas.

`stream(ctx)` returns `(df, reset)`:
  * reset=False -> `df` holds only rows appended since the last run
  * reset=True  -> `df` is the complete output; downstream state must be rebuilt
"""
from __future__ import annotations

import hashlib
import io
import os
import uuid

import numpy as np
import pandas as pd

from .expr import Expr


def _h(*parts):
    return hashlib.sha1("\x00".join(map(str, parts)).encode()).hexdigest()


class StateMismatch(Exception):
    """Saved state doesn't line up with this run; caller recomputes from scratch."""


class Node:
    kind = "Node"
    fast = True          # statically known to run incrementally
    parents: tuple = ()
    columns = None       # known output columns, or None if unknown / not a frame
    sig = ""
    why = ""             # why a node is not incremental

    def deps(self):
        return self.parents

    def label(self):
        return self.kind


class Source(Node):
    kind = "Source"

    def __init__(self, path, kwargs, columns):
        self.path = os.path.abspath(path)
        self.kwargs = dict(kwargs)
        self.columns = list(columns)
        self.sig = _h("source", self.path, repr(sorted(self.kwargs.items(), key=lambda kv: kv[0])))

    def label(self):
        return f"read_csv({os.path.basename(self.path)})"

    def stream(self, ctx):
        with open(self.path, "rb") as f:
            raw = f.read()
        st = ctx.old_state(self)
        if st is not None:
            res = self._append(raw, st, ctx)
            if res is not None:
                return res
        df = pd.read_csv(io.BytesIO(raw), **self.kwargs)
        nl = raw.find(b"\n")
        header = raw[: nl + 1] if nl >= 0 and b'"' not in raw[:nl] else None
        ctx.set_state(self, {"size": len(raw), "sha": hashlib.sha256(raw).hexdigest(),
                             "nrows": len(df), "dtypes": df.dtypes.to_dict(), "header": header})
        ctx.changed = True
        ctx.note(self, "full", len(df))
        return df, True

    def _append(self, raw, st, ctx):
        """Return (delta, False) if the file only grew by whole appended rows, else None."""
        old, header = st["size"], st["header"]
        if header is None or old == 0 or len(raw) < old or raw[old - 1:old] != b"\n":
            return None
        h = hashlib.sha256()
        h.update(memoryview(raw)[:old])
        if h.hexdigest() != st["sha"]:
            return None
        kw = {k: v for k, v in self.kwargs.items() if k != "dtype"}
        try:
            delta = pd.read_csv(io.BytesIO(header + raw[old:]), dtype=st["dtypes"], **kw)
        except Exception:
            return None
        # New rows must parse to exactly the dtypes a full read would give.
        if list(delta.columns) != list(st["dtypes"]) or list(delta.dtypes) != list(st["dtypes"].values()):
            return None
        n = st["nrows"]
        delta.index = pd.RangeIndex(n, n + len(delta))
        new = dict(st)
        if len(raw) > old:
            h.update(memoryview(raw)[old:])
            new.update(size=len(raw), sha=h.hexdigest(), nrows=n + len(delta))
            ctx.changed = True
        ctx.set_state(self, new)
        ctx.note(self, "incremental", len(delta))
        return delta, False

    def replay(self, rep):
        return pd.read_csv(self.path, **self.kwargs)


class Mem(Node):
    """An in-memory frame produced by a pandas fallback (never incremental)."""
    kind = "Mem"
    fast = False
    why = "in-memory result of a pandas fallback"

    def __init__(self, df):
        self.df = df
        self.columns = list(df.columns)
        try:
            tag = int(pd.util.hash_pandas_object(df, index=True).sum())
        except Exception:
            tag = uuid.uuid4().hex
        self.sig = _h("mem", tag, tuple(map(str, df.dtypes)), tuple(map(str, df.columns)))

    def label(self):
        return f"in-memory frame {self.df.shape}"

    def stream(self, ctx):
        ctx.note(self, "fallback", len(self.df))
        return self.df, True

    def replay(self, rep):
        return self.df.copy()


class _ExprNode(Node):
    """Shared logic for nodes driven by one expression over one parent."""

    def _setup(self, parent, expr):
        self.parent, self.expr = parent, expr
        self.parents = (parent,)
        self.foreign = {n.sig: n for n in expr.nodes if n.sig != parent.sig}
        self.fast = not expr.opaque and not self.foreign
        if expr.opaque:
            self.why = "mixes in a concrete pandas/numpy value"
        elif self.foreign:
            self.why = "reads columns from another frame"

    def deps(self):
        return (self.parent, *self.foreign.values())

    def _resolver(self, ctx):
        full_parent = ctx.full(self.parent)
        return lambda n: full_parent if n.sig == self.parent.sig else ctx.full(n)


class Assign(_ExprNode):
    kind = "Assign"

    def __init__(self, parent, col, expr):
        self.col = col
        self._setup(parent, expr)
        cols = parent.columns
        self.columns = None if cols is None else cols + ([] if col in cols else [col])
        self.sig = _h("assign", parent.sig, col, expr.sig)

    def label(self):
        return f"{self.col} = {self.expr.text}"

    def stream(self, ctx):
        if self.fast:
            d, reset = ctx.stream(self.parent)
            val = self.expr.eval(lambda n: d)
            out = d.copy(deep=False)
            out[self.col] = val
            ctx.note(self, "full" if reset else "incremental", len(d))
            return out, reset
        full = ctx.full(self.parent)
        out = full.copy()
        out[self.col] = self.expr.eval(self._resolver(ctx))
        ctx.note(self, "fallback", len(out))
        return out, True

    def replay(self, rep):
        out = rep(self.parent).copy()
        out[self.col] = self.expr.eval(rep)
        return out


class Filter(_ExprNode):
    kind = "Filter"

    def __init__(self, parent, expr):
        self._setup(parent, expr)
        self.columns = parent.columns
        self.sig = _h("filter", parent.sig, expr.sig)

    def label(self):
        return self.expr.text

    def stream(self, ctx):
        if self.fast:
            d, reset = ctx.stream(self.parent)
            out = d[self.expr.eval(lambda n: d)]
            ctx.note(self, "full" if reset else "incremental", len(d))
            return out, reset
        full = ctx.full(self.parent)
        out = full[self.expr.eval(self._resolver(ctx))]
        ctx.note(self, "fallback", len(out))
        return out, True

    def replay(self, rep):
        return rep(self.parent)[self.expr.eval(rep)]


class Project(Node):
    kind = "Project"

    def __init__(self, parent, cols):
        self.parent, self.parents, self.cols = parent, (parent,), list(cols)
        self.columns = list(cols)
        self.sig = _h("project", parent.sig, repr(self.cols))

    def label(self):
        return repr(self.cols)

    def stream(self, ctx):
        d, reset = ctx.stream(self.parent)
        ctx.note(self, "full" if reset else "incremental", len(d))
        return d[self.cols], reset

    def replay(self, rep):
        return rep(self.parent)[self.cols]


# ---------------------------------------------------------------------------
# groupby

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
            if not (isinstance(dt, np.dtype) and dt.kind in "iuf"):
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
