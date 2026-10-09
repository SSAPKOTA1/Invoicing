"""Shared fixtures."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from supplier_app.bootstrap import Storage, open_memory_storage, open_storage  # noqa: E402
from supplier_app.settings.paths import AppPaths  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture()
def storage() -> Iterator[Storage]:
    st = open_memory_storage()
    yield st
    st.close()


@pytest.fixture()
def repos(storage: Storage):
    return storage.repos


@pytest.fixture()
def file_storage(tmp_path: Path) -> Iterator[Storage]:
    st = open_storage(AppPaths(tmp_path / "data"))
    yield st
    st.close()
