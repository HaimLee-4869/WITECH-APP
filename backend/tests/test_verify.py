"""6단계: POST /verify + threshold 비교 + 로깅.

기본 클라이언트(`client`)는 운영 설정 USE_GESTURE_CLASSIFIER=false다.
앱이 보낸 gestureId로 템플릿을 조회하고, 분류 결과는 기록만 한다.
`client_classifier`는 명세 7장의 true 모드다.

합성 랜드마크라 유사도의 절대값은 의미가 없다. 같은 입력이면 1.0, 무관한 입력이면
낮다는 성질만 이용한다.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import select

from ai import encoder
from app import models
from app.services import app_config_service as cfg
from tests.conftest import post_json
from tests.payloads import (
    enroll_body,
    enroll_same_body,
    other_gesture,
    predicted_gesture,
    verify_body,
)

GESTURE = "G3"          # 앱이 보내는 gestureId (개인 제스처 ID로 바뀌어도 구조는 동일)
UNRELATED_SEED = 1      # seed 0 등록분과 무관한 입력


def _logs(db):
    with db.session() as s:
        return s.scalars(select(models.AuthLog).order_by(models.AuthLog.id)).all()


@pytest.fixture
def enrolled(client, make_user):
    """kim이 seed 0 입력을 G3로 3회 등록한 상태 (3회 모두 같은 입력)."""
    make_user()
    res = post_json(client, "/enroll", enroll_same_body(gesture_id=GESTURE, seed=0))
    assert res.status_code == 200, res.text
    return GESTURE


# --- 운영 모드 (USE_GESTURE_CLASSIFIER=false) ---------------------------------------

def test_same_input_passes_with_score_near_one(client, enrolled):
    res = post_json(client, "/verify", verify_body(seed=0, gesture_id=GESTURE))
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["score"] == pytest.approx(1.0, abs=1e-5)
    assert data["passed"] is True
    assert data["reason"] is None
    assert data["threshold"] == 0.6275163888931274
    assert data["gestureId"] == GESTURE                    # 조회에 쓴 제스처 = 앱이 보낸 값
    assert data["predictedGesture"] in {"G1", "G2", "G3", "G4", "G5"}  # 기록만
    assert 0.0 <= data["gestureConfidence"] <= 1.0
    assert data["modelVersion"] == encoder.MODEL_VERSION
    assert isinstance(data["latencyMs"], int)


def test_unrelated_input_rejected(client, enrolled):
    data = post_json(client, "/verify", verify_body(seed=UNRELATED_SEED, gesture_id=GESTURE)).json()
    assert data["score"] < data["threshold"]
    assert data["passed"] is False
    assert data["reason"] == "below_threshold"


def test_prediction_is_recorded_but_not_used(client, db, enrolled):
    """분류 결과가 gestureId와 달라도 판정에 영향이 없어야 한다."""
    predicted = predicted_gesture(0)
    body = verify_body(seed=0, gesture_id=GESTURE)
    data = post_json(client, "/verify", body).json()
    log = _logs(db)[-1]
    assert (log.claimed_gesture_id, log.predicted_gesture_id) == (GESTURE, predicted)
    assert log.gesture_confidence is not None
    assert data["passed"] is True
    assert data["reason"] != "gesture_mismatch"


def test_gesture_id_required(client, enrolled):
    res = post_json(client, "/verify", verify_body(seed=0))
    assert res.status_code == 422
    assert res.json()["detail"]["reason"] == "gesture_id_required"


def test_no_template_for_other_gesture(client, enrolled):
    data = post_json(client, "/verify", verify_body(seed=0, gesture_id=other_gesture(GESTURE))).json()
    assert data["passed"] is False
    assert data["reason"] == "no_template"
    assert data["score"] is None


def test_second_gesture_uses_its_own_template(client, db, enrolled, make_user):
    """한 사용자가 제스처를 두 개 등록하면 gestureId로 갈라진다."""
    other = other_gesture(GESTURE)
    assert post_json(client, "/enroll", enroll_same_body(gesture_id=other, seed=5)).status_code == 200
    same = post_json(client, "/verify", verify_body(seed=5, gesture_id=other)).json()
    crossed = post_json(client, "/verify", verify_body(seed=5, gesture_id=GESTURE)).json()
    assert same["passed"] is True and same["score"] == pytest.approx(1.0, abs=1e-5)
    assert crossed["score"] < same["score"]


def test_unknown_user(client):
    res = post_json(client, "/verify", verify_body(user_id="nobody", gesture_id=GESTURE))
    assert res.status_code == 404
    assert res.json()["detail"]["reason"] == "user_not_found"


def test_threshold_read_from_db_each_request(client, db, enrolled):
    """threshold는 코드 상수가 아니라 DB 활성 행. 값을 바꾸면 재시작 없이 반영."""
    first = post_json(client, "/verify", verify_body(seed=UNRELATED_SEED, gesture_id=GESTURE)).json()
    assert first["passed"] is False
    with db.session() as s:
        row = s.scalar(select(models.Threshold).where(models.Threshold.is_active.is_(True)))
        row.value = first["score"] - 0.01
        s.commit()
    second = post_json(client, "/verify", verify_body(seed=UNRELATED_SEED, gesture_id=GESTURE)).json()
    assert second["score"] == first["score"]
    assert second["threshold"] != first["threshold"]
    assert second["passed"] is True


# --- auth_logs ------------------------------------------------------------------

def test_auth_log_records_everything(client, db, enrolled):
    body = verify_body(seed=0, gesture_id=GESTURE)
    raw = json.dumps(body)
    client.post("/verify", content=raw, headers={"Content-Type": "application/json"})
    log = _logs(db)[-1]
    assert log.user_id == "kim"
    assert log.passed is True and log.fail_reason is None
    assert log.score == pytest.approx(1.0, abs=1e-5)
    assert log.threshold == 0.6275163888931274
    assert log.claimed_gesture_id == GESTURE
    assert log.predicted_gesture_id is not None
    assert log.auth_model_version == encoder.MODEL_VERSION
    assert log.gesture_model_version == encoder.GESTURE_MODEL_VERSION
    assert log.landmarks_json == raw  # 앱이 보낸 바이트 그대로
    assert log.latency_ms is not None and log.latency_ms >= 0


def test_failures_are_logged_too(client, db, enrolled):
    post_json(client, "/verify", verify_body(seed=0, gesture_id=GESTURE))                      # 통과
    post_json(client, "/verify", verify_body(seed=UNRELATED_SEED, gesture_id=GESTURE))         # 점수 미달
    post_json(client, "/verify", verify_body(seed=0, gesture_id=other_gesture(GESTURE)))       # 템플릿 없음
    bad = verify_body(seed=0, gesture_id=GESTURE)
    bad["frames"] = bad["frames"][:3]
    assert post_json(client, "/verify", bad).status_code == 422                                # 입력 거절
    assert [(l.passed, l.fail_reason) for l in _logs(db)] == [
        (True, None), (False, "below_threshold"), (False, "no_template"), (False, "invalid_input"),
    ]
    assert all(l.landmarks_json for l in _logs(db))


# --- 명세 7장 모드 (USE_GESTURE_CLASSIFIER=true) --------------------------------------

@pytest.fixture
def enrolled_as_predicted(client_classifier):
    """true 모드에서 통과하려면 분류 모델이 예측하는 제스처로 등록해야 한다."""
    c = client_classifier
    c.post("/users", json={"id": "kim", "name": "김길동"})
    gesture = predicted_gesture(0)
    assert post_json(c, "/enroll", enroll_same_body(gesture_id=gesture, seed=0)).status_code == 200
    return gesture


def test_classifier_mode_uses_prediction(client_classifier, enrolled_as_predicted):
    data = post_json(client_classifier, "/verify", verify_body(seed=0)).json()
    assert data["passed"] is True
    assert data["gestureId"] == enrolled_as_predicted == data["predictedGesture"]


def test_classifier_mode_gesture_mismatch(client_classifier, enrolled_as_predicted):
    claimed = other_gesture(enrolled_as_predicted)
    data = post_json(client_classifier, "/verify", verify_body(seed=0, gesture_id=claimed)).json()
    assert data["passed"] is False
    assert data["reason"] == "gesture_mismatch"
    assert data["score"] is None


def test_classifier_mode_matching_gesture_id(client_classifier, enrolled_as_predicted):
    data = post_json(
        client_classifier, "/verify", verify_body(seed=0, gesture_id=enrolled_as_predicted)
    ).json()
    assert data["passed"] is True


def test_modes_differ_on_same_data(client, client_classifier, make_user):
    """분류 예측과 다른 제스처로 등록한 경우: false는 통과, true는 거부."""
    predicted = predicted_gesture(0)
    enrolled = other_gesture(predicted)
    for c in (client, client_classifier):
        c.post("/users", json={"id": "lee", "name": "이길동"})
        post_json(c, "/enroll", enroll_same_body("lee", enrolled, 0))

    false_mode = post_json(client, "/verify", verify_body("lee", 0, gesture_id=enrolled)).json()
    true_mode = post_json(client_classifier, "/verify", verify_body("lee", 0, gesture_id=enrolled)).json()
    assert false_mode["passed"] is True
    assert true_mode["passed"] is False and true_mode["reason"] == "gesture_mismatch"


def test_classifier_is_called_in_both_modes(client, client_classifier, monkeypatch, make_user):
    calls = []
    original = encoder.classify_gesture
    monkeypatch.setattr(encoder, "classify_gesture", lambda f: (calls.append(1), original(f))[1])

    make_user()
    post_json(client, "/enroll", enroll_same_body(gesture_id=GESTURE, seed=0))
    post_json(client, "/verify", verify_body(seed=0, gesture_id=GESTURE))
    assert len(calls) == 1  # 등록은 분류를 부르지 않는다

    client_classifier.post("/users", json={"id": "lee", "name": "이길동"})
    post_json(client_classifier, "/verify", verify_body("lee", 0, gesture_id=GESTURE))
    assert len(calls) == 2


# --- 모델 버전 불일치 -----------------------------------------------------------------

def test_active_version_mismatch_refuses_instead_of_silently_comparing(client, db, enrolled):
    with db.session() as s:
        cfg.set_value(s, cfg.ACTIVE_MODEL_VERSION, "old-model-v0")
        s.commit()
    res = post_json(client, "/verify", verify_body(seed=0, gesture_id=GESTURE))
    assert res.status_code == 503
    assert res.json()["detail"]["reason"] == "model_version_mismatch"
    assert _logs(db)[-1].fail_reason == "model_version_mismatch"


# --- 동시 요청 -------------------------------------------------------------------------

def test_concurrent_verify_is_consistent(client, db, enrolled, make_user):
    make_user("lee", "이길동")
    bodies = [
        verify_body(seed=0, gesture_id=GESTURE) if i % 2 == 0
        else verify_body(user_id="lee", seed=0, gesture_id=GESTURE)
        for i in range(24)
    ]

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda b: post_json(client, "/verify", b), bodies))

    assert all(r.status_code == 200 for r in results)
    kim = [r.json() for r, b in zip(results, bodies) if b["userId"] == "kim"]
    lee = [r.json() for r, b in zip(results, bodies) if b["userId"] == "lee"]
    assert {(d["passed"], round(d["score"], 6)) for d in kim} == {(True, 1.0)}
    assert {d["reason"] for d in lee} == {"no_template"}
    assert len(_logs(db)) == 24
