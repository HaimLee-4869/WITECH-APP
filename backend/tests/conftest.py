from __future__ import annotations

import json
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app import models
from app.config import Settings
from app.main import create_app


@pytest.fixture
def settings(tmp_path) -> Settings:
    """테스트마다 임시 SQLite 파일."""
    # 셸 환경변수와 무관하게 고정.
    return Settings(
        database_url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
        auto_migrate=True,
        _env_file=None,
    )


@pytest.fixture
def client(settings) -> Iterator[TestClient]:
    app = create_app(settings)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def db(client):
    """앱과 같은 DB를 보는 세션 팩토리."""
    return client.app.state.db


@pytest.fixture
def make_user(db):
    def _make(user_id: str = "kim", name: str = "김길동", department: str | None = "개발팀"):
        with db.session() as s:
            s.add(models.User(id=user_id, name=name, department=department))
            s.commit()
        return user_id

    return _make


def post_json(client: TestClient, url: str, body: dict):
    """NaN을 그대로 보내기 위해 직접 직렬화한다 (httpx json=은 NaN을 거부)."""
    return client.post(url, content=json.dumps(body), headers={"Content-Type": "application/json"})
