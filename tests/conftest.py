"""Test isolation, plus the fast/comprehensive split.

Every test runs in its own empty directory with its own cache and INCPANDAS_VERIFY=1.

The two fuzz files are a cross product: every operation in `fuzz_ops.OPS` against every
right-table mutation mode (test_fuzz_ops) and every file mutation mode (test_fuzz_mutations).
All of it takes about seven minutes, which is too slow to run on every edit, so by default
each operation runs against ONE mode, picked round-robin so that every operation and every
mode still appears in the run. `--slow` restores the full cross product.

    python -m pytest -q              # fast: every op once per fuzz file, ~1.5 min
    python -m pytest -q --slow       # comprehensive: the full cross product, ~7 min
    python -m pytest -q --slow -n auto   # the same, in parallel, if pytest-xdist is installed

Tests marked `@pytest.mark.slow` also run only under `--slow`.
"""
import pytest

FUZZ_FILES = ("test_fuzz_ops.py", "test_fuzz_mutations.py")


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("INCPANDAS_CACHE", str(tmp_path / "cache"))
    monkeypatch.setenv("INCPANDAS_VERIFY", "1")   # every compute is checked against plain pandas


def pytest_addoption(parser):
    parser.addoption("--slow", action="store_true", default=False,
                     help="run the comprehensive suite: the full fuzz cross product and any "
                          "test marked slow (minutes, not seconds)")


def pytest_configure(config):
    config.addinivalue_line("markers", "slow: only runs under --slow (comprehensive suite)")


def _fuzz_key(item):
    """(file, test, op, mode) for a parametrized fuzz test, else None."""
    if item.path.name not in FUZZ_FILES:
        return None
    params = dict(getattr(item, "callspec", None).params) if hasattr(item, "callspec") else {}
    op = params.pop("name", None)
    if op is None or len(params) != 1:
        return None
    return item.path.name, item.originalname, op, next(iter(params.values()))


def pytest_collection_modifyitems(config, items):
    """Without --slow, thin the fuzz cross product to one mode per operation."""
    if config.getoption("--slow"):
        return

    # dict keys keep collection order (the parametrize order), so this is deterministic:
    # the nth operation of a fuzz test takes the nth mode, wrapping around. Every operation
    # runs and every mode is used, just not every pairing of the two.
    ops, modes = {}, {}
    for item in items:
        key = _fuzz_key(item)
        if key is not None:
            group, op, mode = key[:2], key[2], key[3]
            ops.setdefault(group, {})[op] = None
            modes.setdefault(group, {})[mode] = None

    chosen = {}
    for group, group_ops in ops.items():
        group_modes = list(modes[group])
        for i, op in enumerate(group_ops):
            chosen[(*group, op)] = group_modes[i % len(group_modes)]

    keep, dropped = [], []
    for item in items:
        if item.get_closest_marker("slow"):
            dropped.append(item)
            continue
        key = _fuzz_key(item)
        if key is None:
            keep.append(item)
        elif chosen[key[:3]] == key[3]:
            keep.append(item)
        else:
            dropped.append(item)

    if dropped:
        config.hook.pytest_deselected(items=dropped)
        items[:] = keep
        config._fast_deselected = len(dropped)


def pytest_report_collectionfinish(config, items):
    n = getattr(config, "_fast_deselected", 0)
    if n:
        return (f"fast suite: {len(items)} tests, {n} fuzz variants held back "
                f"(every operation still runs once per fuzz file) -- use --slow for all of them")
    return None
