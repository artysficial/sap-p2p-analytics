import pytest

from p2p.analytics import Dataset, analyse

pytest_plugins = ["results_plugin"]


@pytest.fixture(scope="session")
def ds():
    return Dataset.from_dir()


@pytest.fixture(scope="session")
def analysis(ds):
    return analyse(ds)
