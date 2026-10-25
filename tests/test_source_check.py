"""The size+mtime shortcut in Source.stream: an unchanged file is not read at all."""
import os

import pandas as plain
import pytest

import incpandas as pd
from incpandas import engine, source

ROWS = [("x", "p", 1, 2), ("y", "p", 3, 4), ("x", "q", 5, 6), ("z", "q", 7, 8)]


def write(path, rows, header=True):
    with open(path, "w" if header else "a", newline="\n") as f:
        if header:
            f.write("k,j,a,b\n")
        for r in rows:
            f.write(",".join(map(str, r)) + "\n")


def bump_mtime(path, secs=10):
    st = os.stat(path)
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + secs * 10**9))


@pytest.fixture
def reads(monkeypatch):
    """Bytes Source.stream reads from the CSV (plain pandas used by VERIFY is not counted)."""
    counter = {"bytes": 0}
    real_open = open

    class Counting:
        def __init__(self, f):
            self._f = f

        def read(self, *a):
            data = self._f.read(*a)
            counter["bytes"] += len(data)
            return data

        def __enter__(self):
            return self

        def __exit__(self, *a):
            self._f.close()

    monkeypatch.setattr(source, "open", lambda *a, **k: Counting(real_open(*a, **k)), raising=False)
    return counter


def run(path="d.csv"):
    df = pd.read_csv(path)
    out = df.groupby("k")[["a", "b"]].sum()
    got = out.to_pandas()
    want = plain.read_csv(path).groupby("k")[["a", "b"]].sum()
    plain.testing.assert_frame_equal(got, want)
    return got


def modes():
    return {m for m, _ in engine.last_run().values()}


def test_unchanged_file_reads_nothing(reads):
    write("d.csv", ROWS)
    run()
    assert reads["bytes"] > 0
    reads["bytes"] = 0
    run()
    assert reads["bytes"] == 0
    assert modes() == {"incremental"}


def test_touch_then_zero_reads(reads):
    write("d.csv", ROWS)
    run()
    bump_mtime("d.csv")
    reads["bytes"] = 0
    run()
    assert reads["bytes"] > 0          # mtime differs: exact logic
    reads["bytes"] = 0
    run()
    assert reads["bytes"] == 0         # saved mtime was refreshed


def test_same_size_edit_detected(reads):
    write("d.csv", ROWS)
    run()
    write("d.csv", [("x", "p", 9, 2)] + ROWS[1:])   # same byte length
    bump_mtime("d.csv")
    reads["bytes"] = 0
    run()
    assert reads["bytes"] > 0
    assert "full" in modes()


def test_append(reads):
    write("d.csv", ROWS)
    run()
    write("d.csv", [("w", "p", 2, 2)], header=False)
    run()
    assert modes() == {"incremental"}


def test_truncation(reads):
    write("d.csv", ROWS)
    run()
    write("d.csv", ROWS[:2])
    run()


def test_atomic_rename_replacement(reads):
    write("d.csv", ROWS)
    run()
    write("new.csv", [("q", "p", 5, 5)] + ROWS[1:])   # same size, different content
    os.replace("new.csv", "d.csv")
    bump_mtime("d.csv")
    run()
    write("new.csv", ROWS + ROWS)
    os.replace("new.csv", "d.csv")
    run()


def test_exact_mode_always_reads(reads, monkeypatch):
    write("d.csv", ROWS)
    run()
    monkeypatch.setenv("INCPANDAS_CHECK", "exact")
    reads["bytes"] = 0
    run()
    assert reads["bytes"] == os.path.getsize("d.csv")


def test_check_mode_not_in_sig(monkeypatch):
    write("d.csv", ROWS)
    a = pd.read_csv("d.csv")._node.sig
    monkeypatch.setenv("INCPANDAS_CHECK", "exact")
    assert pd.read_csv("d.csv")._node.sig == a


def test_old_state_without_mtime_does_not_crash(reads, monkeypatch):
    write("d.csv", ROWS)
    run()
    real = engine.Ctx.old_state

    def old_format(self, node):
        st = real(self, node)
        if st is not None:
            st = {k: v for k, v in st.items() if k != "mtime_ns"}
        return st

    monkeypatch.setattr(engine.Ctx, "old_state", old_format)
    reads["bytes"] = 0
    run()
    assert reads["bytes"] > 0
    write("d.csv", [("w", "p", 2, 2)], header=False)
    run()
