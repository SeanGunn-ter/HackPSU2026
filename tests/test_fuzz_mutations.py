"""Stronger fuzz: every op in fuzz_ops.OPS under hostile file mutations.

Mutation mode is seed % 5, applied at step 2 of a six-step trajectory:
  0 plain random appends   1 appended rows leave int column `a` empty (it becomes float)
  2 appended rows put text in `a`   3 edit a row in the middle, then append
  4 truncate to header + one row
At every step incpandas must agree with plain pandas: same result (value and type), or both
raise the same exception type (a pandas error must also be an incpandas error).
"""
import os
import random

import pandas as plain
import pytest

import incpandas as pd
from fuzz_ops import OPS
from test_fuzz_ops import HEADER, same

SEEDS = int(os.environ.get("FUZZ_SEEDS", "5"))
STEPS = 6


def rows(rng, n, a_values=None):
    out = []
    for _ in range(n):
        a = rng.randint(-5, 9) if a_values is None else rng.choice(a_values)
        k = rng.choice(["w", "x", "y", "z", ""] if rng.random() < 0.15 else "wxyz")
        b = "" if rng.random() < 0.1 else rng.choice([0, 0.25, 0.5, 1, 2, 4])
        out.append((k, a, b, rng.choice(["", 0.5, 1, 2.5])))
    return out


def write(rs, header=False):
    with open("d.csv", "w" if header else "a") as f:
        if header:
            f.write(HEADER)
        for r in rs:
            f.write(",".join(map(str, r)) + "\n")


def mutate(mode, rng):
    if mode == 0:
        write(rows(rng, rng.randint(1, 4)))
    elif mode == 1:
        write(rows(rng, rng.randint(1, 4), a_values=[""]))
    elif mode == 2:
        write(rows(rng, rng.randint(1, 4), a_values=["x", "1.5", "  7"]))
    elif mode == 3:
        lines = open("d.csv").read().splitlines()
        i = rng.randint(1, max(1, len(lines) - 2))
        lines[i] = ",".join(map(str, rows(rng, 1, a_values=[99])[0]))
        with open("d.csv", "w") as f:
            f.write("\n".join(lines) + "\n")
        write(rows(rng, rng.randint(1, 3)))
    else:
        lines = open("d.csv").read().splitlines()
        with open("d.csv", "w") as f:
            f.write("\n".join(lines[:2]) + "\n")


def attempt(fn):
    try:
        out = fn()
        return out.to_pandas() if hasattr(out, "to_pandas") else out, None
    except Exception as e:      # noqa: BLE001 - the exception type is what we compare
        return None, e


@pytest.mark.filterwarnings("ignore::Warning")
@pytest.mark.parametrize("seed", range(SEEDS))
@pytest.mark.parametrize("name", list(OPS))
def test_op_survives_mutations(name, seed):
    op, rng = OPS[name], random.Random(f"{name}/{seed}")
    write(rows(rng, 6), header=True)
    for step in range(STEPS):
        if step == 2:
            mutate(seed % 5, rng)
        elif step:
            write(rows(rng, rng.randint(0, 3)))
        want, werr = attempt(lambda: op(plain.read_csv("d.csv")))
        got, gerr = attempt(lambda: op(pd.read_csv("d.csv")))
        where = f"{name} seed={seed} step={step}"
        if werr is not None or gerr is not None:
            assert type(werr) is type(gerr), (where, werr, gerr)
        else:
            try:
                same(got, want)
            except AssertionError as e:
                raise AssertionError(where) from e
