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
        stat = os.stat(self.path)   # taken before the read: a racing write can only force an exact re-check
        st = ctx.old_state(self)
        if st is not None and os.environ.get("INCPANDAS_CHECK", "").lower() != "exact":
            res = self._unchanged(stat, st, ctx)
            if res is not None:
                return res
        with open(self.path, "rb") as f:
            raw = f.read()
        if st is not None:
            res = self._append(raw, st, stat, ctx)
            if res is not None:
                return res
        df = pd.read_csv(io.BytesIO(raw), **self.kwargs)
        nl = raw.find(b"\n")
        header = raw[: nl + 1] if nl >= 0 and b'"' not in raw[:nl] else None
        if len(df) == 0:   # dtypes of an empty read are all object; don't reuse them for appends
            header = None
        ctx.set_state(self, {"size": len(raw), "sha": hashlib.sha256(raw).hexdigest(),
                             "nrows": len(df), "dtypes": df.dtypes.to_dict(), "header": header,
                             "mtime_ns": self._mtime(stat, len(raw))})
        ctx.changed = True
        ctx.note(self, "full", len(df))
        return df, True

    @staticmethod
    def _mtime(stat, nbytes):
        # Only trust the mtime if the file had the size we hashed when it was stat'ed.
        return stat.st_mtime_ns if stat.st_size == nbytes else None

    def _delta(self, data, st):
        """Parse appended rows (with the saved header) to the saved dtypes, or None if they differ."""
        kw = {k: v for k, v in self.kwargs.items() if k != "dtype"}
        try:
            delta = pd.read_csv(io.BytesIO(data), dtype=st["dtypes"], **kw)
        except Exception:
            return None
        # New rows must parse to exactly the dtypes a full read would give.
        if list(delta.columns) != list(st["dtypes"]) or list(delta.dtypes) != list(st["dtypes"].values()):
            return None
        delta.index = pd.RangeIndex(st["nrows"], st["nrows"] + len(delta))
        return delta

    def _unchanged(self, stat, st, ctx):
        """Return (empty delta, False) if size and mtime match the previous run, else None."""
        mt = st.get("mtime_ns")
        if mt is None or st["header"] is None or stat.st_size != st["size"] or stat.st_mtime_ns != mt:
            return None
        delta = self._delta(st["header"], st)
        if delta is None:
            return None
        ctx.set_state(self, st)
        ctx.note(self, "incremental", 0)
        return delta, False

    def _append(self, raw, st, stat, ctx):
        """Return (delta, False) if the file only grew by whole appended rows, else None."""
        old, header = st["size"], st["header"]
        if header is None or old == 0 or len(raw) < old or raw[old - 1:old] != b"\n":
            return None
        h = hashlib.sha256()
        h.update(memoryview(raw)[:old])
        if h.hexdigest() != st["sha"]:
            return None
        delta = self._delta(header + raw[old:], st)
        if delta is None:
            return None
        n = st["nrows"]
        new = dict(st, mtime_ns=self._mtime(stat, len(raw)))   # also re-arms the shortcut after a touch
        if new["mtime_ns"] != st.get("mtime_ns"):
            ctx.changed = True   # unchanged content, but the state must be saved to keep the new mtime
        if len(raw) > old:
            h.update(memoryview(raw)[old:])
            new.update(size=len(raw), sha=h.hexdigest(), nrows=n + len(delta))
            ctx.changed = True
        ctx.set_state(self, new)
        ctx.note(self, "incremental", len(delta))
        return delta, False

    def replay(self, rep):
        return pd.read_csv(self.path, **self.kwargs)
