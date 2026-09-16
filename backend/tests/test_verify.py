"""POST /verify — dual-head 두 관문 (gesture >= Tg AND user >= Tu).

합성 랜드마크라 유사도의 절대값은 의미가 없다. 같은 입력이면 1.0, 무관한 입력이면
낮다는 성질만 이용한다.

**핵심 회귀 테스트**: 같은 사람이 등록과 다른 동작을 하면 통과하면 안 된다.
v1.0.0은 user 임베딩만 봐서 이걸 막지 못했다(실기기 실측 0.81~0.99 전부 통과).
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
from tests.payloads import enroll_same_body, other_gesture, verify_body

GESTURE = "G3"          # 앱이 보내는 gestureId
UNRELATED_SEED = 1      # seed 0 등록분과 무관한 입력
TU = 0.3423501253128052
TG = 0.9020317792892456


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


# --- 기본 흐름 ---------------------------------------------------------------------

def test_same_input_passes_both_gates(client, enrolled):
    res = post_json(client, "/verify", verify_body(seed=0, gesture_id=GESTURE))
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["passed"] is True
    assert data["reason"] is None
    assert data["score"] == pytest.approx(1.0, abs=1e-5)          # user 관문
    assert data["gestureScore"] == pytest.approx(1.0, abs=1e-5)   # gesture 관문
    assert data["threshold"] == TU
    assert data["gestureThreshold"] == TG
    assert data["gestureId"] == GESTURE
    assert data["modelVersion"] == encoder.MODEL_VERSION
    assert isinstance(data["latencyMs"], int)


def test_unrelated_input_rejected(client, enrolled):
    data = post_json(client, "/verify", verify_body(seed=UNRELATED_SEED, gesture_id=GESTURE)).json()
    assert data["passed"] is False
    assert data["reason"] in {"gesture_gate", "below_threshold"}
    assert data["score"] is not None and data["gestureScore"] is not None


def test_same_user_different_gesture_is_blocked(client, db, make_user):
    """**회귀 테스트.** 본인이 등록과 다른 동작을 하면 gesture 관문에서 막혀야 한다.

    v1.0.0에서는 user 점수만 봤기 때문에 통과했다. dual-head의 존재 이유다.
    """
    make_user()
    # 같은 사람이 두 동작을 등록한다. 서로 다른 입력이므로 gesture 임베딩이 갈린다.
    assert post_json(client, "/enroll", enroll_same_body(gesture_id="G1", seed=0)).status_code == 200
    assert post_json(client, "/enroll", enroll_same_body(gesture_id="G2", seed=7)).status_code == 200

    # G1을 등록한 사람이 G2 동작을 하면서 G1이라고 주장한다.
    data = post_json(client, "/verify", verify_body(seed=7, gesture_id="G1")).json()
    assert data["passed"] is False
    assert data["reason"] == "gesture_gate"
    assert data["gestureScore"] < data["gestureThreshold"]

    log = _logs(db)[-1]
    assert log.fail_reason == "gesture_gate"
    assert log.gesture_score is not None and log.gesture_threshold == TG


def test_gesture_id_required(client, enrolled):
    res = post_json(client, "/verify", verify_body(seed=0))
    assert res.status_code == 422
    assert res.json()["detail"]["reason"] == "gesture_id_required"


def test_no_template_for_other_gesture(client, enrolled):
    data = post_json(client, "/verify", verify_body(seed=0, gesture_id=other_gesture(GESTURE))).json()
    assert data["passed"] is False
    assert data["reason"] == "no_template"
    assert data["score"] is None and data["gestureScore"] is None


def test_unknown_user(client):
    res = post_json(client, "/verify", verify_body(user_id="nobody", gesture_id=GESTURE))
    assert res.status_code == 404
    assert res.json()["detail"]["reason"] == "user_not_found"


def test_user_gate_blocks_other_person(client, db, make_user):
    """다른 사람이 같은 동작을 해도 user 관문에서 막힌다."""
    make_user()
    make_user("lee", "이길동")
    post_json(client, "/enroll", enroll_same_body("kim", GESTURE, 0))
    # lee가 kim의 동작을 흉내 내지만 lee의 템플릿은 없다 → no_template
    assert post_json(client, "/verify", verify_body("lee", 0, gesture_id=GESTURE)).json()["reason"] == "no_template"

    # lee도 등록한 뒤, kim의 입력으로 lee를 인증하려 하면 두 관문 중 하나에서 막힌다.
    post_json(client, "/enroll", enroll_same_body("lee", GESTURE, 9))
    data = post_json(client, "/verify", verify_body("lee", 0, gesture_id=GESTURE)).json()
    assert data["passed"] is False


def test_thresholds_read_from_db_each_request(client, db, enrolled):
    """threshold는 코드 상수가 아니라 DB 활성 행. 값을 바꾸면 재시작 없이 반영."""
    first = post_json(client, "/verify", verify_body(seed=UNRELATED_SEED, gesture_id=GESTURE)).json()
    assert first["passed"] is False
    with db.session() as s:
        for row in s.scalars(select(models.Threshold).where(models.Threshold.is_active.is_(True))):
            row.value = -1.0  # 어떤 점수든 통과하도록 낮춘다
        s.commit()
    second = post_json(client, "/verify", verify_body(seed=UNRELATED_SEED, gesture_id=GESTURE)).json()
    assert second["score"] == first["score"]
    assert second["gestureScore"] == first["gestureScore"]
    assert second["passed"] is True


# --- auth_logs ------------------------------------------------------------------

def test_auth_log_records_both_gates(client, db, enrolled):
    body = verify_body(seed=0, gesture_id=GESTURE)
    raw = json.dumps(body)
    client.post("/verify", content=raw, headers={"Content-Type": "application/json"})
    log = _logs(db)[-1]
    assert log.user_id == "kim"
    assert log.passed is True and log.fail_reason is None
    assert log.score == pytest.approx(1.0, abs=1e-5)
    assert log.threshold == TU
    assert log.gesture_score == pytest.approx(1.0, abs=1e-5)
    assert log.gesture_threshold == TG
    assert log.claimed_gesture_id == GESTURE
    assert log.auth_model_version == encoder.MODEL_VERSION
    assert log.landmarks_json == raw  # 앱이 보낸 바이트 그대로
    assert log.latency_ms is not None and log.latency_ms >= 0


def test_failures_are_logged_too(client, db, enrolled):
    post_json(client, "/verify", verify_body(seed=0, gesture_id=GESTURE))                   # 통과
    post_json(client, "/verify", verify_body(seed=UNRELATED_SEED, gesture_id=GESTURE))      # 관문 미달
    post_json(client, "/verify", verify_body(seed=0, gesture_id=other_gesture(GESTURE)))    # 템플릿 없음
    bad = verify_body(seed=0, gesture_id=GESTURE)
    bad["frames"] = bad["frames"][:3]
    assert post_json(client, "/verify", bad).status_code == 422                             # 입력 거절

    rows = [(l.passed, l.fail_reason) for l in _logs(db)]
    assert rows[0] == (True, None)
    assert rows[1][0] is False and rows[1][1] in {"gesture_gate", "below_threshold"}
    assert rows[2] == (False, "no_template")
    assert rows[3] == (False, "invalid_input")
    assert all(l.landmarks_json for l in _logs(db))


def test_each_request_logs_one_summary_line(client, enrolled, caplog):
    caplog.set_level("INFO", logger="app.services.auth_service")
    ok = verify_body(seed=0, gesture_id=GESTURE)
    post_json(client, "/verify", ok)
    post_json(client, "/verify", verify_body(seed=UNRELATED_SEED, gesture_id=GESTURE))
    bad = verify_body(seed=0, gesture_id=GESTURE)
    bad["frames"] = bad["frames"][:3]
    post_json(client, "/verify", bad)

    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("verify ")]
    assert len(lines) == 3
    cam = f"camera={ok['camera']['width']}x{ok['camera']['height']}"
    assert all(f"user=kim gesture={GESTURE} {cam}" in l for l in lines)
    assert f"frames={len(ok['frames'])}" in lines[0]
    assert "status=200" in lines[0] and "passed=True" in lines[0] and "reason=-" in lines[0]
    assert "score=1.0000" in lines[0] and "threshold=0." in lines[0]
    # 두 관문 값이 모두 한 줄에 남는다.
    assert "gestureScore=1.0000" in lines[0] and "gestureThreshold=0.9020" in lines[0]
    assert "passed=False" in lines[1]
    assert "status=422" in lines[2] and "frames=3" in lines[2] and "score=-" in lines[2]
    assert not any("[" in l for l in lines)  # 좌표 본문은 찍지 않는다


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
    assert {(d["passed"], round(d["score"], 6), round(d["gestureScore"], 6)) for d in kim} == {
        (True, 1.0, 1.0)
    }
    assert {d["reason"] for d in lee} == {"no_template"}
    assert len(_logs(db)) == 24
