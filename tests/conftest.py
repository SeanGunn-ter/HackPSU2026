import pytest


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("INCPANDAS_CACHE", str(tmp_path / "cache"))
    monkeypatch.setenv("INCPANDAS_VERIFY", "1")   # every compute is checked against plain pandas
