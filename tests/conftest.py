"""Общие фикстуры тестов."""

from __future__ import annotations

from pathlib import Path

import pytest

from nanotasks.config import Config
from nanotasks.db import Database, Repository

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


@pytest.fixture
def db(tmp_path):
    database = Database(str(tmp_path / "t.duckdb"))
    yield database
    database.close()


@pytest.fixture
def repo(db):
    return Repository(db.con)


@pytest.fixture
def config(tmp_path):
    return Config(
        database_path=str(tmp_path / "t.duckdb"),
        output_dir=str(tmp_path / "out"),
        max_retries=1,
    )


@pytest.fixture
def examples_dir():
    return EXAMPLES
