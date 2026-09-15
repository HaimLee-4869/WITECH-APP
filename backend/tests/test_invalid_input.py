"""입력 거절 6종 → 422 + 사유 코드 (명세 1장, 10장)."""

from __future__ import annotations

import pytest

from app.services.ai_gateway import REASON_MESSAGES, reason_of
from tests.conftest import post_json
from tests.payloads import enroll_body, make_frames


def _no_hand(frames, count):
    for f in frames[:count]:
        f["lm"] = None
    return frames


def _dup_timestamp(frames):
    frames[5]["tMs"] = frames[4]["tMs"]
    return frames


def _short_landmarks(frames):
    frames[3]["lm"] = frames[3]["lm"][:20]
    return frames


def _nan(frames):
    frames[3]["lm"][0][0] = float("nan")
    return frames


def _inf(frames):
    frames[3]["lm"][0][1] = float("inf")
    return frames


# (사유 코드, frames 변형, camera 변형)
CASES = [
    ("too_few_frames", lambda: make_frames(0, n=7), None),
    ("insufficient_valid_frames", lambda: _no_hand(make_frames(0, n=12), 5), None),
    ("duration_too_short", lambda: make_frames(0, n=20, span_ms=700), None),
    ("non_monotonic_timestamps", lambda: _dup_timestamp(make_frames(0)), None),
    ("missing_camera_size", lambda: make_frames(0), "drop"),
    ("missing_camera_size", lambda: make_frames(0), {"width": 720}),
    ("malformed_landmarks", lambda: _short_landmarks(make_frames(0)), None),
    ("malformed_landmarks", lambda: _nan(make_frames(0)), None),
    ("malformed_landmarks", lambda: _inf(make_frames(0)), None),
]
IDS = [f"{reason}-{i}" for i, (reason, _, _) in enumerate(CASES)]


def _apply_camera(body, cam):
    if cam == "drop":
        body.pop("camera")
    elif cam is not None:
        body["camera"] = cam


@pytest.mark.parametrize("reason,frames,cam", CASES, ids=IDS)
def test_enroll_rejections(client, make_user, reason, frames, cam):
    make_user()
    body = enroll_body()
    body["takes"][0]["frames"] = frames()
    _apply_camera(body, cam)
    res = post_json(client, "/enroll", body)
    assert res.status_code == 422, res.text
    detail = res.json()["detail"]
    assert detail["code"] == "invalid_sequence"
    assert detail["reason"] == reason
    assert detail["message"] == REASON_MESSAGES[reason]


def test_schema_error_uses_same_shape(client):
    res = post_json(client, "/enroll", {"userId": "kim"})
    assert res.status_code == 422
    detail = res.json()["detail"]
    assert detail["code"] == "invalid_request"
    assert detail["reason"] == "schema_validation"
    assert detail["errors"]


@pytest.mark.parametrize(
    "message,reason",
    [
        ("camera width/height is required", "missing_camera_size"),
        ("need at least 8 frames, got 5", "too_few_frames"),
        ("need at least 8 valid hand frames", "insufficient_valid_frames"),
        ("span 500ms is shorter than 750ms", "duration_too_short"),
        ("tMs must increase", "non_monotonic_timestamps"),
        ("landmark contains NaN", "malformed_landmarks"),
        ("something else", "invalid_sequence"),
    ],
)
def test_reason_fallback_from_message(message, reason):
    """실제 ai_release 예외에 reason 속성이 없을 때 메시지로 추정."""
    assert reason_of(ValueError(message)) == reason
