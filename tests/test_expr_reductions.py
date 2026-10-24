import numpy as np
import pandas as plain
import pytest

import incpandas as pd
from incpandas import engine
from incpandas.reduce import FUNCS, Reduce, reduction_input

HEADER = "a,b,n,name\n"
# floats are powers of two / multiples of 0.25 so chunked sums and quotients are exact
ROWS1 = [(1, 0.5, 1.5, "ab"), (2, 0, "", "cd"), (3, 2.0, 2.5, "ef"), (4, 0.25, "", "gh")]
ROWS2 = [(10, 4.0, 4.0, "ij"), (-5, 0, "", "kl"), (7, 1.0, 0.5, "mn"), (0, 0, 1.0, "op")]
EDIT = [(9, 2.0, 1.0, "zz"), (8, 0, "", "yy"), (6, 0.5, 3.5, "xx")]


def write(rows, header=True):
    with open("d.csv", "w" if header else "a") as f:
        if header:
            f.write(HEADER)
        for r in rows:
            f.write(",".join(map(str, r)) + "\n")


def assigned(df):
    df["c"] = df.a * 2
    return df


FORMULAS = {
    "mul": lambda df: df.a * df.b,
    "plus1": lambda df: df.a + 1,
    "neg": lambda df: -df.a,
    "div_inf": lambda df: df.a / df.b,
    "nan_formula": lambda df: df.n * 2,
    "filtered": lambda df: (lambda g: g.a * g.b)(df[df.a > 2]),
    "after_assign": lambda df: (lambda g: g.c + g.b)(assigned(df)),
    "bool_gt": lambda df: df.a > 3,
    "bool_filtered_empty": lambda df: (lambda g: g.a > 3)(df[df.a > 1000]),
    "filtered_empty": lambda df: (lambda g: g.a * 2)(df[df.a > 1000]),
}


def check(make, fn, path="d.csv"):
    """Run through incpandas; compare value and type to plain pandas. Returns Reduce's note."""
    lazy_df = pd.read_csv(path)
    expr = make(lazy_df)
    got = getattr(expr, fn)()
    src = reduction_input(expr)
    note = engine.last_run().get(Reduce(src[0], src[1], fn).sig)
    want = getattr(make(plain.read_csv(path)), fn)()
    assert type(got) is type(want), (got, want)
    assert got == want or (plain.isna(got) and plain.isna(want)), (got, want)
    return note


@pytest.mark.filterwarnings("ignore::RuntimeWarning")
@pytest.mark.parametrize("fn", FUNCS)
@pytest.mark.parametrize("name", list(FORMULAS))
def test_lifecycle(name, fn):
    if name.startswith("bool") and fn in ("min", "max"):
        pytest.skip("covered by test_bool_min_max_stay_on_fallback")
    make = FORMULAS[name]
    sizes = lambda df: len(make(df).index) if hasattr(make(df), "index") else 0
    write(ROWS1)
    note = check(make, fn)
    assert note == ("full", sizes(plain.read_csv("d.csv")))

    check(make, fn)                                   # nothing changed
    before = sizes(plain.read_csv("d.csv"))

    write(ROWS2, header=False)                        # append: only the delta is processed
    note = check(make, fn)
    assert note[0] == "incremental"
    assert note[1] == sizes(plain.read_csv("d.csv")) - before
    assert {m for m, _ in engine.last_run().values()} == {"incremental"}

    check(make, fn)                                   # no-change rerun after append
    assert check(make, fn)[0] == "incremental"

    write(EDIT)                                       # edit: full re-read
    note = check(make, fn)
    assert note[0] == "full"


def test_explain_labels_hidden_step():
    write(ROWS1)
    expr = pd.read_csv("d.csv").a * 2
    node = reduction_input(expr)[0]
    from incpandas.frame import LazyFrame
    expr.sum()
    text = LazyFrame(Reduce(node, reduction_input(expr)[1], "sum")).explain()
    assert "[for reduction]" in text and "Reduce" in text


def test_hidden_column_not_visible():
    write(ROWS1)
    df = pd.read_csv("d.csv")
    (df.a * 2).sum()
    assert list(df.to_pandas().columns) == ["a", "b", "n", "name"]
    assert df._node.columns == ["a", "b", "n", "name"]


@pytest.mark.parametrize("make,fn", [
    (lambda df: df.a > 3, "sum"),
    (lambda df: df.name.str.upper(), "count"),
    (lambda df: df.a * 2, "sum"),
])
def test_fallback_cases_match_pandas(make, fn):
    write(ROWS1)
    write(ROWS2, header=False)
    got = getattr(make(pd.read_csv("d.csv")), fn)()
    want = getattr(make(plain.read_csv("d.csv")), fn)()
    assert type(got) is type(want) and got == want


def test_two_frames_fall_back():
    write(ROWS1)
    x, y = pd.read_csv("d.csv"), pd.read_csv("d.csv")
    y2 = y[y.a > 1]
    expr = x.a + y2.a
    assert reduction_input(expr) is None
    px, py = plain.read_csv("d.csv"), plain.read_csv("d.csv")
    want = (px.a + py[py.a > 1].a).sum()
    got = expr.sum()
    assert type(got) is type(want) and got == want


def test_concrete_array_falls_back():
    write(ROWS1)
    arr = np.arange(4)
    expr = pd.read_csv("d.csv").a + arr
    assert reduction_input(expr) is None
    want = (plain.read_csv("d.csv").a + arr).sum()
    got = expr.sum()
    assert type(got) is type(want) and got == want


def test_call_with_arguments_falls_back():
    write([(1, 1, "", "a"), (2, 1, 1.0, "b")])
    for kw, fn in (({"skipna": False}, "sum"), ({"min_count": 5}, "sum")):
        got = getattr(pd.read_csv("d.csv").n * 2, fn)(**kw)
        want = getattr(plain.read_csv("d.csv").n * 2, fn)(**kw)
        assert (got == want) or (plain.isna(got) and plain.isna(want))
    got = (pd.read_csv("d.csv").a * 2).sum(skipna=False)
    assert got == (plain.read_csv("d.csv").a * 2).sum(skipna=False)


def test_temp_column_name_collision():
    write(ROWS1)
    expr = pd.read_csv("d.csv").a * 2
    node, col = reduction_input(expr)
    plain_df = plain.read_csv("d.csv")
    plain_df[col] = 100
    plain_df.to_csv("d.csv", index=False)
    df = pd.read_csv("d.csv")
    expr = df.a * 2
    node2, col2 = reduction_input(expr)
    assert col2 != col and col2 not in df._node.columns
    got = expr.sum()
    assert got == (plain.read_csv("d.csv").a * 2).sum()
    assert list(df.to_pandas().columns) == ["a", "b", "n", "name", col]


@pytest.mark.parametrize("fn", ["min", "max"])
@pytest.mark.parametrize("name", ["bool_gt", "bool_filtered_empty"])
def test_bool_min_max_stay_on_fallback(name, fn):
    write(ROWS1)
    write(ROWS2, header=False)
    make = FORMULAS[name]
    expr = make(pd.read_csv("d.csv"))
    got = getattr(expr, fn)()
    want = getattr(make(plain.read_csv("d.csv")), fn)()
    assert type(got) is type(want) and got == want
    src = reduction_input(expr)
    assert engine.last_run()[Reduce(src[0], src[1], fn).sig][0] == "fallback"
