import random

import pandas as plain
import pytest

import incpandas as pd
from fuzz_ops import OPS

HEADER = "k,a,b,n\n"


def rows(rng, n):
    out = []
    for _ in range(n):
        out.append((rng.choice("wxyz" if rng.random() > 0.1 else [""]), rng.randint(-5, 9), rng.choice([0, 0.25, 0.5, 1, 2, 4]),
                    rng.choice(["", 0.5, 1, 2.5])))
    return out


def write(rs, header=False, mode="a"):
    with open("d.csv", "w" if header else mode) as f:
        if header:
            f.write(HEADER)
        for r in rs:
            f.write(",".join(map(str, r)) + "\n")


def same(got, want):
    if isinstance(want, (plain.DataFrame, plain.Series)):
        got = got.to_pandas() if hasattr(got, "to_pandas") else got
        (plain.testing.assert_frame_equal if isinstance(want, plain.DataFrame)
         else plain.testing.assert_series_equal)(got, want, check_exact=False, rtol=1e-7)
    else:
        assert type(got) is type(want), (got, want)
        assert got == want or (plain.isna(got) and plain.isna(want)), (got, want)


RIGHT_HEADER = "k,v,w\n"


def right_rows(rng, n):
    return [(rng.choice(["x", "y", "y", "z", "z", "q", "r"] + ([""] if rng.random() < 0.3 else [])),
             rng.randint(-5, 9), rng.choice(["aa", "bb", "cc", "dd"])) for _ in range(n)]


def write_right(rs, header=False):
    with open("r.csv", "w" if header else "a") as f:
        if header:
            f.write(RIGHT_HEADER)
        for r in rs:
            f.write(",".join(map(str, r)) + "\n")


def mutate_right(mode, rng):
    """0 unchanged, 1 appended, 2 edited in the middle, 3 replaced."""
    if mode == 1:
        write_right(right_rows(rng, rng.randint(1, 3)))
    elif mode == 2:
        lines = open("r.csv").read().splitlines()
        lines[rng.randint(1, len(lines) - 1)] = ",".join(map(str, right_rows(rng, 1)[0]))
        with open("r.csv", "w") as f:
            f.write("\n".join(lines) + "\n")
    elif mode == 3:
        write_right(right_rows(rng, rng.randint(2, 6)), header=True)


def attempt(fn):
    try:
        out = fn()
        return out.to_pandas() if hasattr(out, "to_pandas") else out, None
    except Exception as e:      # noqa: BLE001 - the exception type is what we compare
        return None, e


def compare(op, where):
    want, werr = attempt(lambda: op(plain.read_csv("d.csv")))
    got, gerr = attempt(lambda: op(pd.read_csv("d.csv")))
    if werr is not None or gerr is not None:
        assert type(werr) is type(gerr), (where, werr, gerr)
    else:
        try:
            same(got, want)
        except AssertionError as e:
            raise AssertionError(where) from e


@pytest.mark.filterwarnings("ignore::Warning")
@pytest.mark.parametrize("rmode", range(4))
@pytest.mark.parametrize("name", list(OPS))
def test_op_matches_pandas_across_appends(name, rmode):
    op, rng = OPS[name], random.Random(f"{name}/{rmode}")
    write(rows(rng, 6), header=True)
    write_right(right_rows(rng, 5), header=True)
    for step in range(4):
        compare(op, f"{name} rmode={rmode} step={step}")
        write(rows(rng, rng.randint(0, 4)))          # append (possibly nothing)
        if step == 1:
            mutate_right(rmode, rng)
    write(rows(rng, 5), header=True)                  # file replaced -> full re-read
    compare(op, f"{name} rmode={rmode} replaced")
