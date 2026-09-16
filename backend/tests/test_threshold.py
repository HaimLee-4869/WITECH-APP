"""threshold 3종 DB 저장과 재시작 없는 전환 (명세 2장, 10장)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import models
from app.main import create_app
from tests.conftest import post_json
from tests.payloads import enroll_body, enroll_same_body, verify_body

GESTURE = "G3"
FAR1, EER, FAR5 = 0.6275163888931274, 0.4360462427139282, 0.27212807536125183
UNRELATED_SEED = 7  # seed 0 템플릿과의 유사도가 EER과 FAR1 사이에 오는 입력


def _enroll(client):
    client.post("/users", json={"id": "kim", "name": "김길동"})
    assert post_json(client, "/enroll", enroll_same_body(gesture_id=GESTURE, seed=0)).status_code == 200


def _verify(client, seed=UNRELATED_SEED):
    return post_json(client, "/verify", verify_body(seed=seed, gesture_id=GESTURE)).json()


def test_three_operating_points_in_db(client):
    rows = client.get("/admin/thresholds").json()
    assert [(r["basis"], r["value"], r["isActive"]) for r in rows] == [
        ("far1", FAR1, True),
        ("eer", EER, False),
        ("far5", FAR5, False),
    ]
    assert rows[0]["far"] == pytest.approx(0.0095, abs=1e-4)
    assert rows[0]["frr"] == pytest.approx(0.0429, abs=1e-4)


def test_switch_flips_decision_without_restart(client):
    _enroll(client)
    before = _verify(client)
    assert EER < before["score"] < FAR1, "테스트 입력이 두 운영점 사이에 있어야 판정이 뒤집힌다"
    assert before["passed"] is False and before["threshold"] == FAR1

    res = client.post("/admin/threshold", json={"basis": "eer"})
    assert res.status_code == 200
    assert res.json()["value"] == EER and res.json()["isActive"] is True

    after = _verify(client)
    assert after["score"] == before["score"]
    assert after["threshold"] == EER
    assert after["passed"] is True

    client.post("/admin/threshold", json={"basis": "far1"})
    assert _verify(client)["passed"] is False


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
        assert c.get("/health").json()["activeThreshold"] == FAR5


def test_logs_record_threshold_used(client):
    _enroll(client)
    _verify(client)
    client.post("/admin/threshold", json={"basis": "eer"})
    _verify(client)
    items = client.get("/logs").json()["items"]
    assert [(i["threshold"], i["passed"]) for i in reversed(items)] == [(FAR1, False), (EER, True)]


def test_patch_config_applies_immediately(client):
    res = client.patch("/admin/config", json={"enrollmentGestures": 5, "enrollmentTakes": 2})
    assert res.status_code == 200
    assert client.get("/config").json()["enrollmentGestures"] == 5
    client.post("/users", json={"id": "kim", "name": "김길동"})
    assert post_json(client, "/enroll", enroll_body(seeds=(0, 1))).json()["required"] == 2
