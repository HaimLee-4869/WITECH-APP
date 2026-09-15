"""threshold 3종 DB 저장과 재시작 없는 전환 (명세 2장, 10장)."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from app import models
from app.main import create_app
from tests.conftest import post_json
from tests.payloads import enroll_body, stub_prediction, verify_body


def _enroll_mixed(client):
    """take 3개가 서로 다름 → take 1 입력의 점수는 약 0.6 (far1과 eer 사이)."""
    client.post("/users", json={"id": "kim", "name": "김길동"})
    gesture = stub_prediction(0)
    assert post_json(client, "/enroll", enroll_body(gesture_id=gesture, seeds=(0, 101, 102))).status_code == 200


def test_three_operating_points_in_db(client):
    rows = client.get("/admin/thresholds").json()
    assert [(r["basis"], r["value"], r["isActive"]) for r in rows] == [
        ("far1", 0.627516, True),
        ("eer", 0.436046, False),
        ("far5", 0.272128, False),
    ]
    assert rows[0]["far"] == 0.0095 and rows[0]["frr"] == 0.0429


def test_switch_flips_decision_without_restart(client):
    _enroll_mixed(client)
    before = post_json(client, "/verify", verify_body(seed=0)).json()
    assert 0.436046 < before["score"] < 0.627516
    assert before["passed"] is False and before["threshold"] == 0.627516

    res = client.post("/admin/threshold", json={"basis": "eer"})
    assert res.status_code == 200
    assert res.json()["value"] == 0.436046 and res.json()["isActive"] is True

    after = post_json(client, "/verify", verify_body(seed=0)).json()
    assert after["score"] == before["score"]
    assert after["threshold"] == 0.436046
    assert after["passed"] is True

    client.post("/admin/threshold", json={"basis": "far1"})
    again = post_json(client, "/verify", verify_body(seed=0)).json()
    assert again["passed"] is False


def test_only_one_active_after_switches(client, db):
    for basis in ("eer", "far5", "eer"):
        client.post("/admin/threshold", json={"basis": basis})
    with db.session() as s:
        active = s.scalars(select(models.Threshold.basis).where(models.Threshold.is_active.is_(True))).all()
    assert active == ["eer"]
    assert client.get("/health").json()["activeThresholdBasis"] == "eer"


def test_unknown_basis_changes_nothing(client):
    res = client.post("/admin/threshold", json={"basis": "far0.1"})
    assert res.status_code == 404
    assert res.json()["detail"]["reason"] == "threshold_not_found"
    assert client.get("/health").json()["activeThresholdBasis"] == "far1"


def test_switch_persists_across_restart(settings):
    with TestClient(create_app(settings)) as c:
        c.post("/admin/threshold", json={"basis": "far5"})
    with TestClient(create_app(settings)) as c:  # startup 시드가 덮어쓰지 않아야 한다
        assert c.get("/health").json()["activeThreshold"] == 0.272128


def test_logs_record_threshold_used(client):
    _enroll_mixed(client)
    post_json(client, "/verify", verify_body(seed=0))
    client.post("/admin/threshold", json={"basis": "eer"})
    post_json(client, "/verify", verify_body(seed=0))
    items = client.get("/logs").json()["items"]
    assert [(i["threshold"], i["passed"]) for i in reversed(items)] == [(0.627516, False), (0.436046, True)]


def test_patch_config_applies_immediately(client):
    res = client.patch("/admin/config", json={"enrollmentGestures": 5, "enrollmentTakes": 2})
    assert res.status_code == 200
    assert client.get("/config").json()["enrollmentGestures"] == 5
    client.post("/users", json={"id": "kim", "name": "김길동"})
    assert post_json(client, "/enroll", enroll_body(seeds=(0, 1))).json()["required"] == 2
