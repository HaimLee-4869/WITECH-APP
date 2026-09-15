"""9단계: 시드 데이터로 관리자 화면 API가 의미 있는 값을 돌려주는지."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from app.routers import logs as logs_router

BACKEND_DIR = Path(__file__).resolve().parent.parent
NOW = datetime(2026, 9, 16, 3, 0, tzinfo=timezone.utc)


def _load_script():
    spec = importlib.util.spec_from_file_location("seed_demo_data", BACKEND_DIR / "scripts" / "seed_demo_data.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_seeded_admin_api(settings, monkeypatch):
    script = _load_script()
    result = script.seed(settings.database_url, now_utc=NOW)
    assert result["users"] == 6 and result["logs"] > 150

    monkeypatch.setattr(logs_router, "_now_utc", lambda: NOW)
    with TestClient(create_app(settings)) as c:
        users = c.get("/users").json()
        assert [u["name"] for u in users] == ["홍길동", "김길동", "오박사", "둘리", "또치", "고길동"]
        assert {u["department"] for u in users} == {"개발팀", "인사팀", "영업팀"}

        page = c.get("/logs", params={"limit": 20}).json()
        assert page["total"] == result["logs"] and len(page["items"]) == 20
        assert all(i["userName"] for i in page["items"])
        assert {i["passed"] for i in page["items"]} == {True, False}

        stats = c.get("/stats/monthly").json()
        assert [s["month"] for s in stats] == ["2026-05", "2026-06", "2026-07", "2026-08", "2026-09"]
        assert all(s["total"] > 0 and s["passed"] > s["failed"] for s in stats)
        assert sum(s["total"] for s in stats) == result["logs"]

        health = c.get("/health").json()
        assert health["status"] == "ok" and health["activeThreshold"] == 0.627516


def test_seed_is_idempotent_and_reset(settings):
    script = _load_script()
    first = script.seed(settings.database_url, now_utc=NOW)
    assert script.seed(settings.database_url, now_utc=NOW)["skipped"] is True
    again = script.seed(settings.database_url, reset=True, now_utc=NOW)
    assert again["logs"] == first["logs"]  # 같은 seed → 같은 데이터

    with TestClient(create_app(settings)) as c:
        assert c.get("/logs").json()["total"] == first["logs"]
        assert len(c.get("/users").json()) == 6


def test_reset_keeps_non_demo_users(settings):
    script = _load_script()
    script.seed(settings.database_url, now_utc=NOW)
    with TestClient(create_app(settings)) as c:
        c.post("/users", json={"id": "real_user", "name": "실사용자"})
    script.seed(settings.database_url, reset=True, now_utc=NOW)
    with TestClient(create_app(settings)) as c:
        assert "real_user" in [u["id"] for u in c.get("/users").json()]


def test_seeded_logs_have_no_landmarks(settings):
    """가짜 이력이 AI팀 학습 데이터에 섞이지 않게 landmarks_json은 NULL."""
    from sqlalchemy import select

    from app import models
    from app.database import Database

    _load_script().seed(settings.database_url, now_utc=NOW)
    db = Database(settings.database_url)
    with db.session() as s:
        assert s.scalars(select(models.AuthLog.landmarks_json).where(
            models.AuthLog.landmarks_json.is_not(None))).all() == []
    db.dispose()


def test_script_runs_from_command_line(settings):
    out = subprocess.run(
        [sys.executable, "scripts/seed_demo_data.py", "--database-url", settings.database_url],
        cwd=BACKEND_DIR, capture_output=True, text=True, encoding="utf-8",
        env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"},
    )
    assert out.returncode == 0, out.stderr
    assert "사용자 6명" in out.stdout
