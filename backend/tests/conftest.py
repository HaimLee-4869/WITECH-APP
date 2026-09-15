from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def settings(tmp_path) -> Settings:
    """테스트마다 임시 SQLite 파일."""
    return Settings(
        database_url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
        _env_file=None,
    )


@pytest.fixture
def client(settings) -> Iterator[TestClient]:
    app = create_app(settings)
    with TestClient(app) as c:
        yield c
