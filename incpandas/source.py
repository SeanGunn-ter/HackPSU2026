from __future__ import annotations

import hashlib
import io
import os

import pandas as pd

from .nodes import Node, _h


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
