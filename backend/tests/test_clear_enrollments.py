"""등록 정리 스크립트 (촬영 조건이 바뀌어 기존 템플릿이 무효일 때)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from sqlalchemy import select

from app import models
from tests.conftest import post_json
from tests.payloads import enroll_same_body

BACKEND_DIR = Path(__file__).resolve().parent.parent


def _load_script():
    spec = importlib.util.spec_from_file_location(
        "clear_enrollments", BACKEND_DIR / "scripts" / "clear_enrollments.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_clears_everything_but_keeps_users_and_logs(client, db, settings):
    script = _load_script()
    client.post("/users", json={"id": "kim", "name": "김길동"})
    assert post_json(client, "/enroll", enroll_same_body("kim", "G3", 0)).status_code == 200
    from tests.payloads import verify_body
    post_json(client, "/verify", verify_body("kim", 0, gesture_id="G3"))

    with db.session() as s:
        assert s.query(models.Enrollment).count() == 3
        assert s.query(models.Template).count() == 2  # user + gesture
        logs_before = s.query(models.AuthLog).count()
    assert logs_before == 1

    result = script.clear(settings.database_url)
    assert result["enrollments"] == 3
    assert result["embeddings"] == 6   # dual-head
    assert result["templates"] == 2

    with db.session() as s:
        assert s.query(models.Enrollment).count() == 0
        assert s.query(models.Embedding).count() == 0
        assert s.query(models.Template).count() == 0
        # 사용자와 이력은 남는다.
        assert s.scalars(select(models.User.id)).all() == ["kim"]
        assert s.query(models.AuthLog).count() == logs_before

    # 지운 뒤 인증하면 템플릿이 없다고 나온다.
    data = post_json(client, "/verify", verify_body("kim", 0, gesture_id="G3")).json()
    assert data["reason"] == "no_template"


def test_dry_run_changes_nothing(client, db, settings):
    script = _load_script()
    client.post("/users", json={"id": "kim", "name": "김길동"})
    post_json(client, "/enroll", enroll_same_body("kim", "G3", 0))

    result = script.clear(settings.database_url, dry_run=True)
    assert result["dry_run"] is True
    assert result["enrollments"] == 3
    with db.session() as s:
        assert s.query(models.Enrollment).count() == 3


def test_filters_by_user_and_gesture(client, db, settings):
    script = _load_script()
    for uid in ("kim", "lee"):
        client.post("/users", json={"id": uid, "name": uid})
        post_json(client, "/enroll", enroll_same_body(uid, "G3", 0))
    post_json(client, "/enroll", enroll_same_body("kim", "G1", 5))

    script.clear(settings.database_url, user_id="kim", gesture_id="G1")
    with db.session() as s:
        remaining = sorted(
            {(e.user_id, e.gesture_id) for e in s.scalars(select(models.Enrollment))}
        )
    assert remaining == [("kim", "G3"), ("lee", "G3")]

    script.clear(settings.database_url, user_id="kim")
    with db.session() as s:
        remaining = sorted(
            {(e.user_id, e.gesture_id) for e in s.scalars(select(models.Enrollment))}
        )
    assert remaining == [("lee", "G3")]


def test_re_enroll_after_clear(client, db, settings):
    """지운 뒤 다시 등록하면 새 템플릿이 만들어진다."""
    from tests.payloads import verify_body

    script = _load_script()
    client.post("/users", json={"id": "kim", "name": "김길동"})
    post_json(client, "/enroll", enroll_same_body("kim", "G3", 0))
    script.clear(settings.database_url)

    assert post_json(client, "/enroll", enroll_same_body("kim", "G3", 1)).status_code == 200
    data = post_json(client, "/verify", verify_body("kim", 1, gesture_id="G3")).json()
    assert data["passed"] is True
