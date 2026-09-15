"""6단계: POST /verify + threshold 비교 + 로깅."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from ai import encoder
from app import models
from app.main import create_app
from app.services import app_config_service as cfg
from tests.conftest import post_json
from tests.payloads import (
    enroll_body,
    enroll_same_body,
    other_gesture,
    stub_prediction,
    verify_body,
)


def _logs(db):
    with db.session() as s:
        return s.scalars(select(models.AuthLog).order_by(models.AuthLog.id)).all()


@pytest.fixture
def enrolled(client, make_user):
    """kim이 seed 0 입력을 (스텁이 예측하는 제스처로) 3회 등록한 상태."""
    make_user()
    gesture = stub_prediction(0)
    res = post_json(client, "/enroll", enroll_same_body(gesture_id=gesture, seed=0))
    assert res.status_code == 200, res.text
    return gesture


# --- 기본 흐름 (USE_GESTURE_CLASSIFIER=true, 기본값) ---------------------------------

def test_same_input_passes_with_score_near_one(client, enrolled):
    res = post_json(client, "/verify", verify_body(seed=0))
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["score"] == pytest.approx(1.0, abs=1e-5)
    assert data["passed"] is True
    assert data["reason"] is None
    assert data["threshold"] == 0.627516
    assert data["predictedGesture"] == enrolled
    assert data["gestureId"] == enrolled
    assert data["gestureConfidence"] == 0.90
    assert data["modelVersion"] == encoder.MODEL_VERSION
    assert isinstance(data["latencyMs"], int)


def test_different_input_rejected(client, make_user):
    make_user()
    # seed 1 입력을 그 입력의 예측 제스처로 등록하고, 같은 제스처로 예측되는 다른 입력으로 인증
    gesture = stub_prediction(1)
    other_seed = next(s for s in range(2, 200) if stub_prediction(s) == gesture)
    post_json(client, "/enroll", enroll_same_body(gesture_id=gesture, seed=1))
    data = post_json(client, "/verify", verify_body(seed=other_seed)).json()
    assert data["predictedGesture"] == gesture
    assert data["score"] < data["threshold"]
    assert data["passed"] is False
    assert data["reason"] == "below_threshold"


def test_different_takes_centroid_score(client, make_user):
    """3회가 서로 다르면 take 1 입력의 점수는 1.0이 아니다 (스텁: 약 1/sqrt(3))."""
    make_user()
    gesture = stub_prediction(0)
    post_json(client, "/enroll", enroll_body(gesture_id=gesture, seeds=(0, 101, 102)))
    data = post_json(client, "/verify", verify_body(seed=0)).json()
    assert 0.4 < data["score"] < 0.75


def test_matching_gesture_id_passes(client, enrolled):
    data = post_json(client, "/verify", verify_body(seed=0, gesture_id=enrolled)).json()
    assert data["passed"] is True


def test_gesture_mismatch_rejected(client, db, enrolled):
    claimed = other_gesture(enrolled)
    data = post_json(client, "/verify", verify_body(seed=0, gesture_id=claimed)).json()
    assert data["passed"] is False
    assert data["reason"] == "gesture_mismatch"
    assert data["score"] is None
    assert data["predictedGesture"] == enrolled
    log = _logs(db)[-1]
    assert (log.claimed_gesture_id, log.predicted_gesture_id, log.fail_reason) == (
        claimed, enrolled, "gesture_mismatch"
    )


def test_no_template(client, make_user):
    make_user()
    data = post_json(client, "/verify", verify_body(seed=0)).json()
    assert data["passed"] is False
    assert data["reason"] == "no_template"
    assert data["score"] is None
    assert data["threshold"] == 0.627516


def test_unknown_user(client):
    res = post_json(client, "/verify", verify_body(user_id="nobody"))
    assert res.status_code == 404
    assert res.json()["detail"]["reason"] == "user_not_found"


def test_threshold_read_from_db_each_request(client, db, make_user):
    """threshold는 코드 상수가 아니라 DB 활성 행. 값을 바꾸면 재시작 없이 반영."""
    make_user()
    gesture = stub_prediction(0)
    post_json(client, "/enroll", enroll_body(gesture_id=gesture, seeds=(0, 101, 102)))
    first = post_json(client, "/verify", verify_body(seed=0)).json()
    assert first["passed"] is False  # 약 0.58 < 0.627516
    with db.session() as s:
        row = s.scalar(select(models.Threshold).where(models.Threshold.is_active.is_(True)))
        row.value = 0.3
        s.commit()
    second = post_json(client, "/verify", verify_body(seed=0)).json()
    assert second["threshold"] == 0.3
    assert second["passed"] is True
    assert second["score"] == first["score"]


# --- auth_logs ------------------------------------------------------------------

def test_auth_log_records_everything(client, db, enrolled):
    body = verify_body(seed=0, gesture_id=enrolled)
    raw = json.dumps(body)
    client.post("/verify", content=raw, headers={"Content-Type": "application/json"})
    log = _logs(db)[-1]
    assert log.user_id == "kim"
    assert log.passed is True and log.fail_reason is None
    assert log.score == pytest.approx(1.0, abs=1e-5)
    assert log.threshold == 0.627516
    assert log.claimed_gesture_id == enrolled
    assert log.predicted_gesture_id == enrolled
    assert log.gesture_confidence == 0.90
    assert log.auth_model_version == encoder.MODEL_VERSION
    assert log.gesture_model_version == encoder.GESTURE_MODEL_VERSION
    assert log.landmarks_json == raw  # 앱이 보낸 바이트 그대로
    assert log.latency_ms is not None and log.latency_ms >= 0


def test_failures_are_logged_too(client, db, enrolled):
    post_json(client, "/verify", verify_body(seed=0))                                       # 통과
    post_json(client, "/verify", verify_body(seed=0, gesture_id=other_gesture(enrolled)))    # mismatch
    bad = verify_body(seed=0)
    bad["frames"] = bad["frames"][:3]
    assert post_json(client, "/verify", bad).status_code == 422                              # invalid
    reasons = [(l.passed, l.fail_reason) for l in _logs(db)]
    assert reasons == [(True, None), (False, "gesture_mismatch"), (False, "invalid_input")]
    assert all(l.landmarks_json for l in _logs(db))


# --- USE_GESTURE_CLASSIFIER=false ----------------------------------------------------

@pytest.fixture
def client_no_classifier(settings):
    app = create_app(settings.model_copy(update={"use_gesture_classifier": False}))
    with TestClient(app) as c:
        yield c


def _setup_other_gesture(client):
    """seed 0 입력을 스텁 예측과 **다른** 제스처로 등록."""
    with client.app.state.db.session() as s:
        s.add(models.User(id="kim", name="김길동"))
        s.commit()
    predicted = stub_prediction(0)
    enrolled = other_gesture(predicted)
    assert post_json(client, "/enroll", enroll_same_body(gesture_id=enrolled, seed=0)).status_code == 200
    return predicted, enrolled


def test_flag_false_uses_app_gesture_id(client_no_classifier):
    c = client_no_classifier
    predicted, enrolled = _setup_other_gesture(c)
    data = post_json(c, "/verify", verify_body(seed=0, gesture_id=enrolled)).json()
    assert data["passed"] is True
    assert data["score"] == pytest.approx(1.0, abs=1e-5)
    assert data["gestureId"] == enrolled
    assert data["predictedGesture"] == predicted  # 예측은 응답·로그에 남지만 판정에 안 쓰임

    with c.app.state.db.session() as s:
        log = s.scalars(select(models.AuthLog)).all()[-1]
    assert log.claimed_gesture_id == enrolled
    assert log.predicted_gesture_id == predicted
    assert log.passed is True and log.fail_reason is None


def test_flag_false_still_calls_classifier(client_no_classifier, monkeypatch):
    c = client_no_classifier
    _, enrolled = _setup_other_gesture(c)
    calls = []
    original = encoder.classify_gesture

    def spy(frames):
        calls.append(1)
        return original(frames)

    monkeypatch.setattr(encoder, "classify_gesture", spy)
    post_json(c, "/verify", verify_body(seed=0, gesture_id=enrolled))
    assert calls == [1]


def test_flag_false_requires_gesture_id(client_no_classifier):
    c = client_no_classifier
    _setup_other_gesture(c)
    res = post_json(c, "/verify", verify_body(seed=0))
    assert res.status_code == 422
    assert res.json()["detail"]["reason"] == "gesture_id_required"


def test_flag_false_no_template_for_claimed_gesture(client_no_classifier):
    c = client_no_classifier
    predicted, _ = _setup_other_gesture(c)
    data = post_json(c, "/verify", verify_body(seed=0, gesture_id=predicted)).json()
    assert data["reason"] == "no_template"


def test_flag_true_same_setup_is_gesture_mismatch(client):
    """같은 데이터를 true 모드로 보내면 예측과 달라서 거부된다 (모드 차이 확인)."""
    _, enrolled = _setup_other_gesture(client)
    data = post_json(client, "/verify", verify_body(seed=0, gesture_id=enrolled)).json()
    assert data["passed"] is False
    assert data["reason"] == "gesture_mismatch"


# --- 모델 버전 불일치 -----------------------------------------------------------------

def test_active_version_mismatch_refuses_instead_of_silently_comparing(client, db, enrolled):
    with db.session() as s:
        cfg.set_value(s, cfg.ACTIVE_MODEL_VERSION, "old-model-v0")
        s.commit()
    res = post_json(client, "/verify", verify_body(seed=0))
    assert res.status_code == 503
    assert res.json()["detail"]["reason"] == "model_version_mismatch"
    assert _logs(db)[-1].fail_reason == "model_version_mismatch"


# --- 동시 요청 -------------------------------------------------------------------------

def test_concurrent_verify_is_consistent(client, db, enrolled, make_user):
    make_user("lee", "이길동")
    bodies = [verify_body(seed=0) if i % 2 == 0 else verify_body(user_id="lee", seed=0) for i in range(24)]

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda b: post_json(client, "/verify", b), bodies))

    assert all(r.status_code == 200 for r in results)
    kim = [r.json() for r, b in zip(results, bodies) if b["userId"] == "kim"]
    lee = [r.json() for r, b in zip(results, bodies) if b["userId"] == "lee"]
    assert {(d["passed"], round(d["score"], 6)) for d in kim} == {(True, 1.0)}
    assert {d["reason"] for d in lee} == {"no_template"}
    assert len(_logs(db)) == 24
