"""Reading a CSV, and deciding whether it only grew since the last run.

By default that decision is exact: the whole file is read and the bytes seen last time are
hashed again, so any edit, deletion or truncation anywhere is caught and the plan rebuilds
from scratch. On a 55 MB file that read and hash is about half of a rerun.

`INCPANDAS_QUICK_CHECK=1` trades some of that certainty for the time: the file is not read,
only `stat()`ed, and just the last 64 KiB of the previously seen bytes are hashed. Appending
is then independent of file size. What it cannot see is an edit to the old bytes *earlier*
than those last 64 KiB -- it is the documented reason the flag is off by default, and why
`verify()` and INCPANDAS_VERIFY=1 exist. A file that shrank, or that was rewritten without
changing size, still falls back to the exact check.
"""
from __future__ import annotations

import hashlib
import io
import os

import pandas as pd

from .nodes import Node, _h

CHUNK = 1 << 16          # how much of the previously seen tail the quick check hashes


def _quick():
    return os.environ.get("INCPANDAS_QUICK_CHECK", "") not in ("", "0")


def _tail_sha(data):
    """Hash of the last CHUNK bytes of `data` (all of it, when it is shorter)."""
    return hashlib.sha256(data[-CHUNK:] if len(data) > CHUNK else data).hexdigest()


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
        st = ctx.old_state(self)
        if st is not None:
            # The quick check never reads the file; if it declines, the exact one still can.
            res = self._quick_append(st, ctx) if _quick() else None
            if res is None:
                res = self._append(self._read()[0], st, ctx)
            if res is not None:
                return res

        raw, mtime = self._read()
        df = pd.read_csv(io.BytesIO(raw), **self.kwargs)
        nl = raw.find(b"\n")
        header = raw[: nl + 1] if nl >= 0 and b'"' not in raw[:nl] else None
        if len(df) == 0:   # dtypes of an empty read are all object; don't reuse them for appends
            header = None
        ctx.set_state(self, {"size": len(raw), "sha": hashlib.sha256(raw).hexdigest(),
                             "mtime_ns": mtime, "tail_sha": _tail_sha(raw),
                             "nrows": len(df), "dtypes": df.dtypes.to_dict(), "header": header})
        ctx.changed = True
        ctx.note(self, "full", len(df))
        return df, True

    def _read(self):
        """The file's bytes, with the mtime taken *before* the read.

        Before, so that a write landing while we read shows up as a different mtime next run
        rather than as an unchanged file that we hold a torn copy of.
        """
        mtime = os.stat(self.path).st_mtime_ns
        with open(self.path, "rb") as f:
            return f.read(), mtime

    def _parse(self, fresh, st):
        """Parse appended bytes as rows, or None if they don't line up with the last run."""
        kw = {k: v for k, v in self.kwargs.items() if k != "dtype"}
        try:
            delta = pd.read_csv(io.BytesIO(st["header"] + fresh), dtype=st["dtypes"], **kw)
        except Exception:
            return None
        # New rows must parse to exactly the dtypes a full read would give.
        if (list(delta.columns) != list(st["dtypes"])
                or list(delta.dtypes) != list(st["dtypes"].values())):
            return None
        n = st["nrows"]
        delta.index = pd.RangeIndex(n, n + len(delta))
        return delta

    def _append(self, raw, st, ctx):
        """Return (delta, False) if the file only grew by whole appended rows, else None."""
        old, header = st["size"], st["header"]
        if header is None or old == 0 or len(raw) < old or raw[old - 1:old] != b"\n":
            return None
        h = hashlib.sha256()
        h.update(memoryview(raw)[:old])
        if st.get("sha") is None or h.hexdigest() != st["sha"]:
            return None                      # changed, or the quick check left no full hash
        delta = self._parse(raw[old:], st)
        if delta is None:
            return None
        new = dict(st)
        if len(raw) > old:
            h.update(memoryview(raw)[old:])
            new.update(size=len(raw), sha=h.hexdigest(), nrows=st["nrows"] + len(delta),
                       tail_sha=_tail_sha(raw), mtime_ns=os.stat(self.path).st_mtime_ns)
            ctx.changed = True
        ctx.set_state(self, new)
        ctx.note(self, "incremental", len(delta))
        return delta, False

    def _quick_append(self, st, ctx):
        """Same answer as `_append` from stat() plus the tail hash -- or None to go look."""
        old = st["size"]
        if st["header"] is None or not old or st.get("tail_sha") is None:
            return None
        try:
            info = os.stat(self.path)
        except OSError:
            return None
        if info.st_size < old:
            return None                                  # shrank: nothing incremental about it
        if info.st_size == old:
            if info.st_mtime_ns != st.get("mtime_ns"):
                return None                              # rewritten in place: check it properly
            return self._unchanged(st, ctx)

        start = max(0, old - CHUNK)
        with open(self.path, "rb") as f:
            f.seek(start)
            window = f.read()                            # the seen tail, plus everything after it
        seen, fresh = window[: old - start], window[old - start:]
        if len(seen) != old - start or not seen.endswith(b"\n"):
            return None
        if hashlib.sha256(seen).hexdigest() != st["tail_sha"]:
            return None                                  # the bytes before the append moved

        delta = self._parse(fresh, st)
        if delta is None:
            return None
        # The full hash would need the bytes we deliberately did not read, so it is dropped;
        # turning the flag back off costs one full re-read to re-establish it.
        ctx.set_state(self, dict(st, size=info.st_size, mtime_ns=info.st_mtime_ns,
                                 sha=None, tail_sha=_tail_sha(window),
                                 nrows=st["nrows"] + len(delta)))
        ctx.changed = True
        ctx.note(self, "incremental", len(delta))
        return delta, False

    def _unchanged(self, st, ctx):
        """An empty delta, shaped exactly as parsing no appended rows would have been."""
        delta = pd.DataFrame({c: pd.Series(dtype=dt) for c, dt in st["dtypes"].items()})
        delta.index = pd.RangeIndex(st["nrows"], st["nrows"])
        ctx.set_state(self, dict(st))
        ctx.note(self, "incremental", 0)
        return delta, False

    def replay(self, rep):
        return pd.read_csv(self.path, **self.kwargs)
