"""9단계: 시드 스크립트가 팀 사용자를 넣는지.

가짜 인증 이력은 만들지 않는다. 실제 테스트로 쌓인 이력과 섞이면 관리자 화면 숫자를
믿을 수 없기 때문이다.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from app import models
from app.main import create_app

BACKEND_DIR = Path(__file__).resolve().parent.parent

TEAM = [
    ("geonju", "김건주", "개발팀"),
    ("taerin", "김태린", "AI팀"),
    ("seungyeon", "승연", "AI팀"),
    ("hyemin", "황혜민", "개발팀"),
    ("eunjung", "이은정", "개발팀"),
]


def _load_script():
    spec = importlib.util.spec_from_file_location(
        "seed_demo_data", BACKEND_DIR / "scripts" / "seed_demo_data.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_seeds_team_users_without_logs(settings):
    script = _load_script()
    result = script.seed(settings.database_url)
    assert result["created"] == len(TEAM)
    assert result["present"] == sorted(u[0] for u in TEAM)

    with TestClient(create_app(settings)) as c:
        users = c.get("/users").json()
        assert {(u["id"], u["name"], u["department"]) for u in users} == set(TEAM)
        # 모두 아직 등록 전이라 템플릿이 없다.
        assert all(u["enrolledGestures"] == [] for u in users)

        # 가짜 이력을 만들지 않는다. 관리자 화면은 비어 있어야 정확하다.
        assert c.get("/logs").json()["total"] == 0
        assert all(m["total"] == 0 for m in c.get("/stats/monthly").json())

        # 등록·인증에 필요한 기본 데이터는 그대로 들어간다.
        assert c.get("/health").json()["status"] == "ok"
        assert c.get("/config").json()["enrollmentTakes"] == 3


def test_seed_is_idempotent(settings):
    script = _load_script()
    script.seed(settings.database_url)
    again = script.seed(settings.database_url)
    assert again["created"] == 0
    assert len(again["present"]) == len(TEAM)

    with TestClient(create_app(settings)) as c:
        assert len(c.get("/users").json()) == len(TEAM)


def test_reset_recreates_team_but_keeps_others(settings):
    script = _load_script()
    script.seed(settings.database_url)
    with TestClient(create_app(settings)) as c:
        c.post("/users", json={"id": "guest01", "name": "외부 방문자"})

    script.seed(settings.database_url, reset=True)
    with TestClient(create_app(settings)) as c:
        ids = [u["id"] for u in c.get("/users").json()]
    assert "guest01" in ids
    assert sorted(i for i in ids if i != "guest01") == sorted(u[0] for u in TEAM)


def test_reset_clears_team_enrollments(settings):
    """--reset은 팀 사용자의 등록분도 지운다 (다시 등록해야 한다)."""
    from tests.conftest import post_json
    from tests.payloads import enroll_same_body

    script = _load_script()
    script.seed(settings.database_url)
    with TestClient(create_app(settings)) as c:
        assert post_json(c, "/enroll", enroll_same_body("geonju", "G1", 0)).status_code == 200

    script.seed(settings.database_url, reset=True)
    db_app = create_app(settings)
    with TestClient(db_app) as c:
        with c.app.state.db.session() as s:
            assert s.query(models.Enrollment).count() == 0
            assert s.query(models.Template).count() == 0
            assert s.scalars(select(models.User.id)).all() != []


def test_script_runs_from_command_line(settings):
    out = subprocess.run(
        [sys.executable, "scripts/seed_demo_data.py", "--database-url", settings.database_url],
        cwd=BACKEND_DIR, capture_output=True, text=True, encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    assert out.returncode == 0, out.stderr
    assert "사용자 5명" in out.stdout
    assert "김건주" in out.stdout
