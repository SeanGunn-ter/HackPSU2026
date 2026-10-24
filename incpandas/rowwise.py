"""Row-wise nodes: rename / drop / astype / dropna / fillna.

Each one maps every input row to at most one output row without looking at other rows,
so running the real pandas operation on just the appended rows gives the same rows (and
index labels) as running it on the whole frame. Whether a call qualifies is decided in
frame.py; these nodes assume validated parameters.
"""
from __future__ import annotations

from .nodes import Node, _h


class _RowWise(Node):
    """One parent, one real pandas call applied to whatever rows arrive."""
    kind = "RowWise"

    def __init__(self, parent, params):
        self.parent, self.parents, self.params = parent, (parent,), params
        self.columns = self._columns(parent.columns)
        self.sig = _h(self.kind.lower(), parent.sig, repr(params))

    def _columns(self, cols):
        return list(cols)

    def _apply(self, d):
        raise NotImplementedError

    def label(self):
        return ", ".join(f"{k}={v!r}" for k, v in self.params.items())

    def stream(self, ctx):
        d, reset = ctx.stream(self.parent)
        out = self._apply(d)
        ctx.note(self, "full" if reset else "incremental", len(d))
        return out, reset

    def replay(self, rep):
        return self._apply(rep(self.parent))


class Rename(_RowWise):
    kind = "Rename"

    def _columns(self, cols):
        m = self.params["columns"]
        return [m.get(c, c) for c in cols]

    def _apply(self, d):
        return d.rename(columns=self.params["columns"])

    def label(self):
        return ", ".join(f"{a}->{b}" for a, b in self.params["columns"].items())


class Drop(_RowWise):
    kind = "Drop"

    def _columns(self, cols):
        gone = set(self.params["columns"])
        return [c for c in cols if c not in gone]

    def _apply(self, d):
        return d.drop(columns=self.params["columns"])

    def label(self):
        return repr(self.params["columns"])


class AsType(_RowWise):
    kind = "AsType"

    def _apply(self, d):
        return d.astype(self.params["dtype"])

    def label(self):
        return repr(self.params["dtype"])


class DropNa(_RowWise):
    kind = "DropNa"

    def _apply(self, d):
        return d.dropna(**self.params)


class FillNa(_RowWise):
    kind = "FillNa"

    def _apply(self, d):
        return d.fillna(self.params["value"])

    def label(self):
        return repr(self.params["value"])

    def stream(self, ctx):
        d, reset = ctx.stream(self.parent)
        out = self._apply(d)
        dtypes = list(out.dtypes)
        if not reset and len(d):
            # Filling with a value the column can't hold (e.g. 0 into strings) changes the
            # dtype only in batches that contain NaN; a whole-frame run decides once.
            # Trust a delta only if it lands on the dtypes of the previous output.
            old = ctx.old_state(self)
            if old is None or old["dtypes"] != dtypes:
                out = self._apply(ctx.full(self.parent))
                ctx.set_state(self, {"dtypes": list(out.dtypes)})
                ctx.changed = True
                ctx.note(self, "fallback", len(out))
                return out, True
        if reset or ctx.old_state(self) is None:
            ctx.set_state(self, {"dtypes": dtypes})
            ctx.changed = ctx.changed or reset
        else:
            ctx.set_state(self, {"dtypes": ctx.old_state(self)["dtypes"]})
        ctx.note(self, "full" if reset else "incremental", len(d))
        return out, reset
