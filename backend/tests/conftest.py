import os
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest


_test_data = TemporaryDirectory(prefix="mmt-tests-")
os.environ["MMT_DB_PATH"] = str(Path(_test_data.name) / "app.db")


@pytest.fixture
def parent_credentials(monkeypatch):
    password = "test-console-password"
    monkeypatch.setenv("MMT_PARENT_PASSWORD", password)
    return "parent", password
