import random

import pandas as plain
import pytest

import incpandas as pd
from fuzz_ops import OPS

HEADER = "k,a,b,n\n"


def rows(rng, n):
    out = []
    for _ in range(n):
        out.append((rng.choice("wxyz"), rng.randint(-5, 9), rng.choice([0, 0.25, 0.5, 1, 2, 4]),
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


@pytest.mark.filterwarnings("ignore::Warning")
@pytest.mark.parametrize("name", list(OPS))
def test_op_matches_pandas_across_appends(name):
    op, rng = OPS[name], random.Random(name)
    write(rows(rng, 6), header=True)
    for step in range(4):
        same(op(pd.read_csv("d.csv")), op(plain.read_csv("d.csv")))
        write(rows(rng, rng.randint(0, 4)))          # append (possibly nothing)
    write(rows(rng, 5), header=True)                  # file replaced -> full re-read
    same(op(pd.read_csv("d.csv")), op(plain.read_csv("d.csv")))
