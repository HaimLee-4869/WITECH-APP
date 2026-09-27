"""threshold 3종 DB 저장과 재시작 없는 전환 (명세 2장, 10장)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import models
from app.main import create_app
from tests.conftest import (
    RELAXED,
    TG_DEFAULT,
    TG_RELAXED,
    TU_DEFAULT,
    TU_RELAXED,
    add_operating_point,
    post_json,
)
from tests.payloads import enroll_body, enroll_same_body, verify_body

GESTURE = "G3"
TG = TG_DEFAULT


@pytest.fixture
def relaxed(db):
    """두 번째 운영점. 릴리스는 default 하나만 주므로 전환 테스트용으로 넣는다."""
    add_operating_point(db)
    return RELAXED


def _enroll(client):
    client.post("/users", json={"id": "kim", "name": "김길동"})
    assert post_json(client, "/enroll", enroll_same_body(gesture_id=GESTURE, seed=0)).status_code == 200


def _verify(client, seed=0):
    return post_json(client, "/verify", verify_body(seed=seed, gesture_id=GESTURE)).json()


def test_operating_points_in_db(client):
    """릴리스 운영점(default)이 user/gesture 두 행으로 들어간다."""
    rows = client.get("/admin/thresholds").json()
    got = {(r["basis"], r["gate"], r["value"], r["isActive"]) for r in rows}
    assert got == {
        ("default", "user", TU_DEFAULT, True),
        ("default", "gesture", TG, True),
    }


def test_switch_changes_active_pair_without_restart(client, relaxed):
    _enroll(client)
    before = _verify(client)
    assert before["threshold"] == TU_DEFAULT and before["gestureThreshold"] == TG

    res = client.post("/admin/threshold", json={"basis": relaxed})
    assert res.status_code == 200
    # 응답은 활성 두 행(관문마다 하나)
    assert {(r["gate"], r["value"]) for r in res.json()} == {
        ("user", TU_RELAXED),
        ("gesture", TG_RELAXED),
    }

    after = _verify(client)
    assert after["score"] == before["score"]
    assert after["threshold"] == TU_RELAXED
    assert after["gestureThreshold"] == TG_RELAXED

    client.post("/admin/threshold", json={"basis": "default"})
    assert _verify(client)["threshold"] == TU_DEFAULT


def test_only_one_basis_active_after_switches(client, db, relaxed):
    for basis in (relaxed, "default", relaxed):
        client.post("/admin/threshold", json={"basis": basis})
    with db.session() as s:
        rows = s.scalars(
            select(models.Threshold).where(models.Threshold.is_active.is_(True))
        ).all()
    # 활성은 한 운영점의 두 관문뿐
    assert {r.basis for r in rows} == {relaxed}
    assert {r.gate for r in rows} == {"user", "gesture"}
    assert client.get("/health").json()["activeThresholdBasis"] == relaxed


def test_unknown_basis_changes_nothing(client):
    res = client.post("/admin/threshold", json={"basis": "super_relaxed"})
    assert res.status_code == 404
    assert res.json()["detail"]["reason"] == "threshold_not_found"
    assert client.get("/health").json()["activeThresholdBasis"] == "default"


def test_switch_persists_across_restart(settings):
    with TestClient(create_app(settings)) as c:
        add_operating_point(c.app.state.db)
        c.post("/admin/threshold", json={"basis": RELAXED})
    with TestClient(create_app(settings)) as c:  # startup 시드가 덮어쓰지 않아야 한다
        assert c.get("/health").json()["activeThreshold"] == TU_RELAXED


def test_logs_record_thresholds_used(client, relaxed):
    _enroll(client)
    _verify(client)
    client.post("/admin/threshold", json={"basis": relaxed})
    _verify(client)
    items = client.get("/logs").json()["items"]
    used = [(i["threshold"], i["gestureThreshold"]) for i in reversed(items)]
    assert used == [(TU_DEFAULT, TG), (TU_RELAXED, TG_RELAXED)]


def test_capture_duration_change_warns_about_templates(client, caplog):
    """촬영 길이는 모델 입력 feature다. 조용히 바뀌면 원인 모를 인증 실패가 된다."""
    caplog.set_level("WARNING", logger="app.routers.admin")
    res = client.patch("/admin/config", json={"captureDurationMs": 2500})
    assert res.status_code == 200
    assert res.json()["captureDurationMs"] == 2500
    warnings = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert any("captureDurationMs 4000 → 2500" in w for w in warnings)
    assert any("clear_enrollments" in w for w in warnings)

    # 같은 값으로 다시 보내면 경고하지 않는다 (바뀐 게 없다).
    caplog.clear()
    client.patch("/admin/config", json={"captureDurationMs": 2500})
    assert not [r for r in caplog.records if "captureDurationMs" in r.getMessage()]


def test_patch_config_applies_immediately(client):
    res = client.patch("/admin/config", json={"enrollmentGestures": 5, "enrollmentTakes": 2})
    assert res.status_code == 200
    assert client.get("/config").json()["enrollmentGestures"] == 5
    client.post("/users", json={"id": "kim", "name": "김길동"})
    assert post_json(client, "/enroll", enroll_body(seeds=(0, 1))).json()["required"] == 2
