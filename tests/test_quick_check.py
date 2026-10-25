"""INCPANDAS_QUICK_CHECK=1: append detection from stat() plus a hash of the tail.

The whole suite already runs every operation against the exact check. These tests are about
the quick one: that it agrees with pandas on appends, no-ops, truncations and nearby edits,
and -- the last test -- exactly where it does not.
"""
import os

import pandas as plain
import pytest

import incpandas as pd
from incpandas import engine
from incpandas.source import CHUNK

HEADER = "k,a,b\n"


@pytest.fixture(autouse=True)
def _quick(monkeypatch):
    monkeypatch.setenv("INCPANDAS_QUICK_CHECK", "1")


def rows(n, start=0, val=1):
    return [(f"k{(start + i) % 4}", start + i, val) for i in range(n)]


def write(rs, header=False, name="d.csv"):
    with open(name, "w" if header else "a") as f:
        if header:
            f.write(HEADER)
        for r in rs:
            f.write(",".join(map(str, r)) + "\n")


def pipeline():
    return pd.read_csv("d.csv").groupby("k")[["a", "b"]].sum()


def want():
    return plain.read_csv("d.csv").groupby("k")[["a", "b"]].sum()


def check():
    """Run the pipeline, compare with pandas, and return what the nodes did on *that* run.

    verify() materialises a second time, which would otherwise overwrite last_run() with the
    notes of a rerun where nothing had changed.
    """
    out = pipeline()
    got = out.to_pandas()
    notes = list(engine.last_run().values())
    plain.testing.assert_frame_equal(got, want(), check_exact=False, rtol=1e-7)
    out.verify()
    return notes


def test_append_is_incremental_and_matches_pandas():
    write(rows(20), header=True)
    check()
    write(rows(5, start=20))
    assert ("incremental", 5) in check()


def test_no_change_processes_nothing():
    write(rows(20), header=True)
    check()
    assert ("incremental", 0) in check()


def test_truncation_falls_back_to_a_full_read():
    write(rows(20), header=True)
    check()
    write(rows(5), header=True)              # shorter file, rewritten
    assert any(mode == "full" for mode, _ in check())


def test_edit_without_changing_the_size_is_caught():
    """Same length, different bytes: the size matches, so mtime is what gives it away."""
    write(rows(20), header=True)
    check()
    text = open("d.csv").read().replace("k0,0,1", "k0,9,1", 1)
    assert len(text) == len(open("d.csv").read())
    with open("d.csv", "w") as f:
        f.write(text)
    assert any(mode == "full" for mode, _ in check())


def test_edit_near_the_end_then_append_is_caught():
    write(rows(20), header=True)
    check()
    lines = open("d.csv").read().splitlines()
    lines[-1] = "k3,999,1"                   # inside the hashed tail
    with open("d.csv", "w") as f:
        f.write("\n".join(lines) + "\n")
    write(rows(3, start=100))
    assert any(mode == "full" for mode, _ in check())


def test_rows_appended_in_one_byte_pieces_still_line_up():
    write(rows(10), header=True)
    check()
    for chunk in ("k1,", "77,", "1\n"):      # a partial line, then completed
        with open("d.csv", "a") as f:
            f.write(chunk)
    check()


def test_quick_state_survives_turning_the_flag_back_off(monkeypatch):
    write(rows(20), header=True)
    check()
    write(rows(5, start=20))
    check()                                   # state now carries no full hash
    monkeypatch.setenv("INCPANDAS_QUICK_CHECK", "0")
    write(rows(5, start=40))
    check()                                   # must still be right, by re-reading
    monkeypatch.setenv("INCPANDAS_QUICK_CHECK", "1")
    write(rows(5, start=60))
    check()


def test_an_edit_far_from_the_end_is_missed_by_the_quick_check():
    """The trade-off, pinned so it can't change unnoticed.

    The quick check hashes only the last CHUNK bytes before the append, so an edit further
    back than that goes unseen and the result is stale. It has to be a *same-length* edit:
    anything that changes the length shifts every later byte, which the tail hash does catch.
    This is the whole reason the flag is off by default; with it off, the same sequence is
    correct (asserted at the end).
    """
    big = rows(CHUNK // 8)                   # comfortably more than CHUNK bytes of file
    write(big, header=True)
    check()

    text = open("d.csv").read()
    edited = text.replace("k0,0,1\n", "k0,0,9\n", 1)        # first data row, far from the end
    assert len(text) == len(edited), "must not shift later bytes, or the tail hash sees it"
    with open("d.csv", "w") as f:
        f.write(edited)
    write(rows(3, start=10 ** 6))

    # INCPANDAS_VERIFY is on for the suite and would turn this into an exception, which is
    # the point: the number is wrong, and only a full replay notices.
    with pytest.raises(AssertionError):
        pipeline().to_pandas()

    # The exact check does see it.
    os.environ["INCPANDAS_QUICK_CHECK"] = "0"
    try:
        plain.testing.assert_frame_equal(pipeline().to_pandas(), want())
    finally:
        os.environ["INCPANDAS_QUICK_CHECK"] = "1"
