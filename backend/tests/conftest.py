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


# 릴리스 thresholds.json의 default 운영점 (app/default_thresholds.json)
TU_DEFAULT, TG_DEFAULT = 0.824398994, 0.937420845
# 전환 테스트용 두 번째 운영점. v1.0.0 mobile 릴리스는 운영점을 하나만 주므로
# 전환 기능을 검증하려면 테스트가 직접 넣는다. 값 자체에는 의미가 없다.
RELAXED, TU_RELAXED, TG_RELAXED = "test_relaxed", 0.5, 0.9


def add_operating_point(db, basis: str = RELAXED, user: float = TU_RELAXED,
                        gesture: float = TG_RELAXED) -> None:
    """로드된 인코더 버전에 비활성 운영점(user/gesture 두 행)을 추가한다."""
    from ai import encoder

    with db.session() as s:
        for gate, value in (("user", user), ("gesture", gesture)):
            s.add(
                models.Threshold(
                    scheme="global", gate=gate, gesture_id=None,
                    model_version=encoder.MODEL_VERSION, value=value,
                    basis=basis, is_active=False,
                )
            )
        s.commit()
