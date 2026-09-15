"""4단계: 요청/응답 스키마."""

from __future__ import annotations

import json
import math
from datetime import datetime

import pytest
from pydantic import ValidationError

from app import schemas
from tests.payloads import enroll_body, verify_body


def test_verify_request_parses_app_payload():
    req = schemas.VerifyRequest.model_validate(verify_body(gesture_id="G3"))
    assert req.user_id == "kim"
    assert req.gesture_id == "G3"
    assert req.camera.width == 720 and req.camera.height == 1280
    assert len(req.frames) == 40
    assert len(req.frames[0].lm) == 21
    assert req.frames[0].handedness == "Right"
    assert req.captured_at.utcoffset().total_seconds() == 9 * 3600


def test_verify_request_gesture_optional():
    assert schemas.VerifyRequest.model_validate(verify_body()).gesture_id is None


def test_content_checks_are_left_to_ai_module():
    """21x3 위반, 카메라 누락, 손 없음은 스키마가 통과시킨다 → AI 모듈이 사유 코드로 거절."""
    body = verify_body()
    del body["camera"]
    body["frames"][0]["lm"] = [[0.1, 0.2]]
    body["frames"][1]["lm"] = None
    body["frames"][2]["lm"] = []
    req = schemas.VerifyRequest.model_validate(body)
    assert req.camera is None


def test_nan_in_landmarks_passes_schema():
    body = verify_body()
    body["frames"][0]["lm"][0][0] = float("nan")
    req = schemas.VerifyRequest.model_validate(body)
    assert math.isnan(req.frames[0].lm[0][0])


def test_verify_request_type_errors():
    with pytest.raises(ValidationError):
        schemas.VerifyRequest.model_validate({"frames": []})  # userId 없음
    body = verify_body()
    body["frames"][0]["lm"] = "abc"
    with pytest.raises(ValidationError):
        schemas.VerifyRequest.model_validate(body)


def test_enroll_request():
    req = schemas.EnrollRequest.model_validate(enroll_body())
    assert [t.take_no for t in req.takes] == [1, 2, 3]
    with pytest.raises(ValidationError):
        schemas.EnrollRequest.model_validate({**enroll_body(), "takes": []})
    with pytest.raises(ValidationError):
        body = enroll_body()
        body["takes"][0]["takeNo"] = 0
        schemas.EnrollRequest.model_validate(body)


def test_response_uses_camel_case_and_utc_offset():
    out = schemas.UserOut(
        id="kim", name="김길동", department=None,
        created_at=datetime(2026, 9, 16, 1, 0, 0), enrolled_gestures=["G1"],
    )
    data = json.loads(out.model_dump_json(by_alias=True))
    assert data == {
        "id": "kim", "name": "김길동", "department": None,
        "createdAt": "2026-09-16T01:00:00+00:00", "enrolledGestures": ["G1"],
    }


def test_verify_response_fields():
    out = schemas.VerifyResponse(
        score=0.71, threshold=0.627516, passed=True, predicted_gesture="G3",
        gesture_confidence=0.93, gesture_id="G3", model_version="v", latency_ms=42,
    )
    keys = set(json.loads(out.model_dump_json(by_alias=True)))
    assert {"score", "threshold", "passed", "predictedGesture", "gestureConfidence",
            "modelVersion", "latencyMs", "reason"} <= keys


def test_user_create_id_pattern():
    schemas.UserCreate(id="kim_01", name="김")
    with pytest.raises(ValidationError):
        schemas.UserCreate(id="김 길동", name="김")


def test_config_patch_bounds():
    assert schemas.ConfigPatch.model_validate({"enrollmentGestures": 5}).enrollment_gestures == 5
    with pytest.raises(ValidationError):
        schemas.ConfigPatch.model_validate({"enrollmentGestures": 6})
