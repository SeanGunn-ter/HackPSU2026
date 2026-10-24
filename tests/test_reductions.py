import numpy as np
import pandas as plain
import pytest

import incpandas as pd
from incpandas import engine
from incpandas.reduce import FUNCS, Reduce

HEADER = "i,f,n,s\n"
# floats are multiples of 0.25 so chunked sums are exact and compare with ==
ROWS1 = [(1, 0.5, 1.5, "a"), (2, 1.25, "", "b"), (3, 2.0, 2.5, "c"), (4, 0.75, "", "d")]
ROWS2 = [(10, 3.5, 4.0, "e"), (-5, 0.25, "", "f"), (7, 1.0, 0.5, "g")]


def write(rows, header=True):
    with open("d.csv", "w" if header else "a") as f:
        if header:
            f.write(HEADER)
        for r in rows:
            f.write(",".join(map(str, r)) + "\n")


_notes = {}


def check(col, fn):
    """Compute through incpandas and compare value and type with plain pandas."""
    df = pd.read_csv("d.csv")
    got = getattr(df[col], fn)()
    run = engine.last_run()
    _notes[col, fn] = (run.get(Reduce(df[col].node, col, fn).sig), run)
    want = getattr(plain.read_csv("d.csv")[col], fn)()
    assert type(got) is type(want), (col, fn, got, want)
    assert (got == want) or (plain.isna(got) and plain.isna(want)), (col, fn, got, want)
    return got


def check_all(cols=("i", "f", "n")):
    for c in cols:
        for fn in FUNCS:
            check(c, fn)


def reduce_run(col, fn):
    """((mode, rows) of the Reduce node, whole last_run) as of the latest check(col, fn)."""
    return _notes[col, fn]


@pytest.mark.parametrize("col", ["i", "f", "n"])
@pytest.mark.parametrize("fn", FUNCS)
def test_function_on_each_column_kind(col, fn):
    write(ROWS1)
    check(col, fn)
    assert reduce_run(col, fn)[0] == ("full", 4)


@pytest.mark.parametrize("col", ["i", "f", "n"])
@pytest.mark.parametrize("fn", FUNCS)
def test_append_processes_only_the_delta(col, fn):
    write(ROWS1)
    check(col, fn)
    write(ROWS2, header=False)
    check(col, fn)
    (mode, rows), last = reduce_run(col, fn)
    assert (mode, rows) == ("incremental", 3)
    assert {m for m, _ in last.values()} == {"incremental"}
    assert sorted(r for _, r in last.values()) == [3, 3]


def test_many_appends_stay_correct():
    write(ROWS1)
    for k in range(5):
        check_all()
        write([(k, k * 0.25, k if k % 2 else "", "x")], header=False)
    check_all()


@pytest.mark.parametrize("fn", FUNCS)
def test_no_change(fn):
    write(ROWS1)
    a = check("n", fn)
    b = check("n", fn)
    assert type(a) is type(b) and (a == b or plain.isna(a))
    assert reduce_run("n", fn)[0] == ("incremental", 0)


def test_no_change_then_append_still_uses_state():
    write(ROWS1)
    check_all()
    check_all()
    write(ROWS2, header=False)
    check_all()
    assert reduce_run("i", "sum")[0] == ("incremental", 3)


def test_edited_file_is_reread_in_full():
    write(ROWS1)
    check_all()
    write([(100, 9.0, 9.0, "z")] + ROWS1[1:] + ROWS2)   # first row edited + appended
    check_all()
    assert reduce_run("i", "sum")[0] == ("full", 7)
    write(ROWS2, header=False)
    check_all()
    assert reduce_run("i", "sum")[0] == ("incremental", 3)


def test_truncated_file():
    write(ROWS1 + ROWS2)
    check_all()
    write(ROWS1)
    check_all()


def test_header_only_file():
    write([])
    check_all(("i", "f"))   # empty columns are object dtype -> fallback path
    assert reduce_run("i", "sum")[0][0] == "fallback"


def test_empty_and_all_nan_results():
    write([(1, 0.5, "", "a"), (2, 1.0, "", "b")])
    for fn in FUNCS:
        check("n", fn)           # all-NaN float column
    assert check("n", "sum") == 0 and check("n", "count") == 0
    assert np.isnan(check("n", "mean")) and np.isnan(check("n", "min")) and np.isnan(check("n", "max"))
    write([(3, 1.0, "", "c")], header=False)
    for fn in FUNCS:
        check("n", fn)           # still all-NaN after an incremental append
    assert reduce_run("n", "sum")[0] == ("incremental", 1)
    write([(4, 1.0, 8.5, "d")], header=False)
    for fn in FUNCS:
        check("n", fn)           # first real value arrives incrementally
    assert check("n", "min") == 8.5 and check("n", "count") == 1


def test_result_types():
    write(ROWS1)
    assert isinstance(check("i", "sum"), np.integer)
    assert isinstance(check("i", "mean"), float)
    assert isinstance(check("i", "count"), (int, np.integer))
    assert isinstance(check("i", "min"), np.integer)
    assert isinstance(check("f", "sum"), float)


def test_int32_and_uint_columns_keep_pandas_types():
    open("d.csv", "w").write("i,f,n,s\n1,1,1,a\n2,2,2,b\n")
    df = pd.read_csv("d.csv", dtype={"i": "int32", "f": "uint8"})
    p = plain.read_csv("d.csv", dtype={"i": "int32", "f": "uint8"})
    for c in ("i", "f"):
        for fn in FUNCS:
            g, w = getattr(df[c], fn)(), getattr(p[c], fn)()
            assert type(g) is type(w) and g == w


def test_non_numeric_column_falls_back():
    write(ROWS1)
    for fn in ("min", "max", "count"):
        check("s", fn)
    assert reduce_run("s", "count")[0][0] == "fallback"
    write(ROWS2, header=False)
    check("s", "max")
    check("s", "count")
    assert reduce_run("s", "count")[0][0] == "fallback"


def test_dtype_change_falls_back_then_recovers():
    write(ROWS1)
    check_all(("i",))
    open("d.csv", "a").write("5,1.0,1.0,x\n,2.0,1.0,y\n")   # int column i gets a NaN -> float64
    assert plain.read_csv("d.csv").i.dtype == np.float64
    check_all(("i",))
    open("d.csv", "a").write("9,1.0,1.0,z\n")
    check_all(("i",))
    open("d.csv", "a").write("oops,1.0,1.0,z\n")             # now object
    for fn in ("min", "max", "count"):
        check("i", fn)
    open("d.csv", "w").write(HEADER + "1,1,1,a\n")           # back to int
    check_all(("i",))


def test_state_persists_across_calls_with_other_function():
    write(ROWS1)
    check("i", "sum")
    check("i", "max")      # separate node and state per function
    write(ROWS2, header=False)
    check("i", "max")
    check("i", "sum")
    assert reduce_run("i", "sum")[0] == ("incremental", 3)


def test_arguments_and_unsupported_forms_use_pandas():
    write(ROWS1)
    df, p = pd.read_csv("d.csv"), plain.read_csv("d.csv")
    assert df.n.sum(skipna=False) is not None and np.isnan(df.n.sum(skipna=False))
    assert df.i.sum(min_count=1) == p.i.sum(min_count=1)
    assert (df.i * 2).sum() == (p.i * 2).sum()          # not a bare column
    assert df[df.i > 1].i.sum() == p[p.i > 1].i.sum()   # filtered frame, new Col
    assert engine.fallback_log


def test_filtered_and_derived_columns_are_incremental():
    write(ROWS1)

    def run():
        df = pd.read_csv("d.csv")
        df["c"] = df.i * df.f
        df = df[df.i > 1]
        return df.c.sum(), df.c.mean(), df.c.count()
    run()
    write(ROWS2, header=False)
    got = run()
    p = plain.read_csv("d.csv")
    p["c"] = p.i * p.f
    p = p[p.i > 1]
    assert got == (p.c.sum(), p.c.mean(), p.c.count())
    assert {m for m, _ in engine.last_run().values()} == {"incremental"}


def test_random_float_data_matches_within_tolerance():
    rng = np.random.default_rng(0)
    plain.DataFrame({"x": rng.normal(size=200)}).to_csv("d.csv", index=False)
    for _ in range(4):
        for fn in FUNCS:
            df = pd.read_csv("d.csv")
            got = getattr(df.x, fn)()
            assert got == pytest.approx(getattr(plain.read_csv("d.csv").x, fn)(), rel=1e-9)
            _notes["x", fn] = engine.last_run()[Reduce(df.x.node, "x", fn).sig], None
        plain.DataFrame({"x": rng.normal(size=50)}).to_csv("d.csv", mode="a", header=False, index=False)
    for fn in FUNCS:
        df = pd.read_csv("d.csv")
        getattr(df.x, fn)()
        assert engine.last_run()[Reduce(df.x.node, "x", fn).sig] == ("incremental", 50)


def test_rows_appended_to_header_only_file():
    write([])
    check_all(("i", "f"))
    write(ROWS1, header=False)
    check_all()
    write(ROWS2, header=False)
    check_all()
    assert reduce_run("i", "sum")[0] == ("incremental", 3)
