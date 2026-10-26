import shutil
from pathlib import Path

import pytest

from gov_engine.spec import load_spec

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def spec():
    return load_spec(ROOT)


@pytest.fixture
def spec_copy(tmp_path):
    """A writable copy of governance/ for tests that break the spec on purpose."""
    shutil.copytree(ROOT / "governance", tmp_path / "governance")
    return tmp_path
