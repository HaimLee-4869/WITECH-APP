"""7단계: /config, /users, /logs, /stats/monthly, /health."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from ai import encoder
from app import models
from app.routers import logs as logs_router
from app.services import app_config_service as cfg
from tests.conftest import post_json
from tests.payloads import enroll_same_body, stub_prediction, verify_body


# --- /config --------------------------------------------------------------------

def test_config_defaults(client):
    assert client.get("/config").json() == {
        "enrollmentTakes": 3,
        "enrollmentGestures": 1,
        "captureDurationMs": 2000,
        "handRequired": "right",
        "modelVersion": encoder.MODEL_VERSION,
    }


def test_config_reads_app_config_table(client, db):
    with db.session() as s:
        cfg.set_value(s, cfg.ENROLLMENT_GESTURES, 5)
        s.commit()
    assert client.get("/config").json()["enrollmentGestures"] == 5


# --- /users ---------------------------------------------------------------------

def test_create_and_list_users(client):
    res = client.post("/users", json={"id": "kim", "name": "김길동", "department": "개발팀"})
    assert res.status_code == 201
    assert res.json()["id"] == "kim"
    generated = client.post("/users", json={"name": "오박사"}).json()
    assert generated["id"].startswith("u_")
    users = client.get("/users").json()
    assert [u["name"] for u in users] == ["김길동", "오박사"]
    assert users[0]["enrolledGestures"] == []
    assert users[0]["createdAt"].endswith("+00:00")


def test_create_user_conflict_and_validation(client):
    client.post("/users", json={"id": "kim", "name": "김길동"})
    res = client.post("/users", json={"id": "kim", "name": "다른 김"})
    assert res.status_code == 409
    assert res.json()["detail"]["reason"] == "user_exists"
    assert client.post("/users", json={"id": "kim", "name": ""}).status_code == 422


def test_users_show_enrolled_gestures(client):
    client.post("/users", json={"id": "kim", "name": "김길동"})
    gesture = stub_prediction(0)
    post_json(client, "/enroll", enroll_same_body(gesture_id=gesture))
    assert client.get("/users").json()[0]["enrolledGestures"] == [gesture]


def test_delete_user_removes_everything(client, db):
    client.post("/users", json={"id": "kim", "name": "김길동"})
    client.post("/users", json={"id": "lee", "name": "이길동"})
    for uid in ("kim", "lee"):
        post_json(client, "/enroll", enroll_same_body(user_id=uid, gesture_id=stub_prediction(0)))
        post_json(client, "/verify", verify_body(user_id=uid))

    assert client.delete("/users/kim").status_code == 204
    with db.session() as s:
        for model in (models.Enrollment, models.Template, models.AuthLog):
            assert set(s.scalars(select(model.user_id)).all()) == {"lee"}
        assert s.query(models.Embedding).count() == 3  # lee 것만
        assert s.get(models.User, "kim") is None
    assert client.delete("/users/kim").status_code == 404


# --- /logs ----------------------------------------------------------------------

@pytest.fixture
def some_logs(client):
    client.post("/users", json={"id": "kim", "name": "김길동", "department": "개발팀"})
    client.post("/users", json={"id": "lee", "name": "이길동", "department": "인사팀"})
    post_json(client, "/enroll", enroll_same_body(gesture_id=stub_prediction(0)))
    for _ in range(3):
        post_json(client, "/verify", verify_body("kim", 0))   # 통과
    for seed in (1, 2):
        post_json(client, "/verify", verify_body("lee", seed))  # no_template


def test_logs_page(client, some_logs):
    page = client.get("/logs").json()
    assert page["total"] == 5 and page["limit"] == 50 and page["offset"] == 0
    first = page["items"][0]
    assert first["userName"] == "이길동" and first["department"] == "인사팀"
    assert {"score", "threshold", "passed", "failReason", "predictedGestureId", "claimedGestureId",
            "authModelVersion", "gestureModelVersion", "latencyMs", "createdAt"} <= set(first)
    assert "landmarksJson" not in first  # 목록 응답에는 원본을 싣지 않는다
    ids = [i["id"] for i in page["items"]]
    assert ids == sorted(ids, reverse=True)  # 최신순


def test_logs_filters_and_paging(client, some_logs):
    assert client.get("/logs", params={"userId": "kim"}).json()["total"] == 3
    assert client.get("/logs", params={"passed": "false"}).json()["total"] == 2
    assert client.get("/logs", params={"passed": "true", "userId": "lee"}).json()["total"] == 0
    page = client.get("/logs", params={"limit": 2, "offset": 4}).json()
    assert page["total"] == 5 and len(page["items"]) == 1
    assert client.get("/logs", params={"limit": 0}).status_code == 422


# --- /stats/monthly -------------------------------------------------------------

def _log_at(s, when_utc: datetime, passed: bool):
    s.add(models.AuthLog(user_id="kim", passed=passed, created_at=when_utc))


def test_monthly_stats_kst_buckets(client, db, monkeypatch):
    monkeypatch.setattr(
        logs_router, "_now_utc", lambda: datetime(2026, 9, 16, 3, 0, tzinfo=timezone.utc)
    )
    client.post("/users", json={"id": "kim", "name": "김길동"})
    with db.session() as s:
        _log_at(s, datetime(2026, 9, 10), True)
        _log_at(s, datetime(2026, 9, 11), False)
        _log_at(s, datetime(2026, 7, 31, 16, 0), True)   # KST 8/1 01:00 → 8월
        _log_at(s, datetime(2026, 7, 31, 14, 0), True)   # KST 7/31 23:00 → 7월
        _log_at(s, datetime(2026, 5, 1), False)
        _log_at(s, datetime(2026, 4, 30, 14, 59), True)  # KST 4/30 23:59 → 범위 밖
        s.commit()

    stats = client.get("/stats/monthly", params={"months": 5}).json()
    assert stats == [
        {"month": "2026-05", "total": 1, "passed": 0, "failed": 1},
        {"month": "2026-06", "total": 0, "passed": 0, "failed": 0},
        {"month": "2026-07", "total": 1, "passed": 1, "failed": 0},
        {"month": "2026-08", "total": 1, "passed": 1, "failed": 0},
        {"month": "2026-09", "total": 2, "passed": 1, "failed": 1},
    ]


def test_monthly_stats_year_boundary(client, monkeypatch):
    monkeypatch.setattr(
        logs_router, "_now_utc", lambda: datetime(2027, 2, 1, 0, 0, tzinfo=timezone.utc)
    )
    months = [m["month"] for m in client.get("/stats/monthly", params={"months": 4}).json()]
    assert months == ["2026-11", "2026-12", "2027-01", "2027-02"]


# --- /health --------------------------------------------------------------------

def test_health(client):
    data = client.get("/health").json()
    assert data == {
        "status": "ok",
        "modelVersion": encoder.MODEL_VERSION,
        "loadedModelVersion": encoder.MODEL_VERSION,
        "gestureModelVersion": encoder.GESTURE_MODEL_VERSION,
        "activeThreshold": 0.627516,
        "activeThresholdBasis": "far1",
        "useGestureClassifier": True,
        "dbOk": True,
    }


def test_health_degraded_on_version_mismatch(client, db):
    with db.session() as s:
        cfg.set_value(s, cfg.ACTIVE_MODEL_VERSION, "old-v0")
        s.commit()
    data = client.get("/health").json()
    assert data["status"] == "degraded"
    assert data["modelVersion"] == "old-v0"
    assert data["activeThreshold"] is None  # old-v0용 threshold 없음
