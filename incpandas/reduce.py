from __future__ import annotations

import numpy as np
import pandas as pd

from .nodes import Node, StateMismatch, _h

FUNCS = ("sum", "mean", "min", "max", "count")
_NEED = {"sum": ("sum",), "count": ("count",), "mean": ("sum", "count"), "min": ("min",), "max": ("max",)}
_EXACT_FLOAT = 2 ** 53   # beyond this an int sum no longer converts to float64 exactly


class _Unsafe(Exception):
    """The incremental answer could differ from pandas; use the fallback path."""


def _eligible(dt):
    return isinstance(dt, np.dtype) and (dt.kind in "iu" or dt == np.float64)


def _empty(fn, dt, n):
    """What pandas returns when no non-null values were seen (keeps its exact result type)."""
    vals = np.full(min(n, 1), np.nan) if dt.kind == "f" else []
    return getattr(pd.Series(vals, dtype=dt), fn)()


class Reduce(Node):
    """series.sum/mean/min/max/count() kept as running totals instead of a full rescan.

    Output is a scalar, so stream() always returns reset=True. Falls back to real pandas
    over the full parent when the column dtype isn't a plain numpy int/float or changed.
    """
    kind = "Reduce"

    def __init__(self, parent, col, fn):
        self.parent, self.parents = parent, (parent,)
        self.col, self.fn = col, fn
        self.sig = _h("reduce", parent.sig, repr(col), fn)

    def label(self):
        return f"{self.col!r}.{self.fn}()"

    def stream(self, ctx):
        d, reset = ctx.stream(self.parent)
        s = d[self.col]
        if _eligible(s.dtype):
            st = None
            if not reset:
                st = ctx.old_state(self)
                if st is None:
                    raise StateMismatch(self.label())
            if st is None or st["dtype"] == s.dtype:
                try:
                    return self._incremental(ctx, s, st, reset), True
                except _Unsafe:
                    pass
        ctx.clear_state(self)
        ctx.changed = True
        full = ctx.full(self.parent)
        ctx.note(self, "fallback", len(full))
        return self.apply_pandas(full), True

    def apply_pandas(self, p):
        return getattr(p[self.col], self.fn)()

    def _incremental(self, ctx, s, old, reset):
        if old is not None and len(s) == 0:
            new = old
        else:
            part = self._partial(s)
            new = part if old is None else self._merge(old, part)
        out = self._result(new)
        ctx.set_state(self, new)
        if reset or len(s):
            ctx.changed = True
        ctx.note(self, "full" if reset else "incremental", len(s))
        return out

    def _partial(self, s):
        part = {"dtype": s.dtype, "n": len(s)}
        for stat in _NEED[self.fn]:
            v = getattr(s, stat)()
            part[stat] = None if stat in ("min", "max") and pd.isna(v) else v
        return part

    def _merge(self, a, b):
        out = {"dtype": a["dtype"], "n": a["n"] + b["n"]}
        for stat in _NEED[self.fn]:
            x, y = a[stat], b[stat]
            if stat in ("sum", "count"):
                with np.errstate(over="ignore"):   # int sums wrap, like pandas
                    out[stat] = x + y
            elif x is None or y is None:
                out[stat] = y if x is None else x
            else:
                out[stat] = min(x, y) if stat == "min" else max(x, y)
        return out

    def _result(self, st):
        fn, dt = self.fn, st["dtype"]
        if fn in ("sum", "count"):
            return st[fn]
        if fn in ("min", "max"):
            v = st[fn]
            return _empty(fn, dt, st["n"]) if v is None else v
        if st["count"] == 0:
            return _empty(fn, dt, st["n"])
        if dt.kind in "iu" and abs(int(st["sum"])) > _EXACT_FLOAT:
            raise _Unsafe
        return np.float64(st["sum"]) / st["count"]

    def replay(self, rep):
        return self.apply_pandas(rep(self.parent))
