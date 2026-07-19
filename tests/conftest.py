"""pytest shared fixtures for SCCS OS tests."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from sccsos.core.database import Database
from sccsos.core.hermes_adapter import MockHermesAdapter


@pytest.fixture
def db_path():
    """Temporary SQLite database for each test."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    yield path
    Path(path).unlink(missing_ok=True)


@pytest.fixture
def db(db_path):
    """Initialized SQLite database."""
    db = Database(db_path)
    db.initialize()
    return db


@pytest.fixture
def adapter():
    """Mock Hermes adapter (no real CLI calls)."""
    return MockHermesAdapter()
