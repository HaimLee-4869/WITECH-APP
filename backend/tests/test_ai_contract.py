"""AI 모듈 계약 테스트 (witeck-mobile-shared-dual-head-g1g24-v1.0.0 + 명세 1장).

ai_release를 교체해도 이 파일은 그대로 통과해야 한다.
입력은 백엔드와 같은 경로(ai_gateway.to_ai_input)로 만든다.
"""

from __future__ import annotations

import copy
import inspect
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from ai import encoder, features
from app import schemas
from app.services.ai_gateway import (
    InvalidSequenceError,
    embed_both,
    embed_both_batch,
    reason_of,
    to_ai_input,
)
from tests.payloads import ai_input, camera, left_hand, make_frames

BACKEND_DIR = Path(__file__).resolve().parent.parent


def _input(frames, *, nominal_fps=None, duration_ms=None):
    return to_ai_input(
        schemas.Camera.model_validate(camera()),
        [schemas.Frame.model_validate(f) for f in copy.deepcopy(frames)],
        nominal_fps=nominal_fps,
        duration_ms=duration_ms,
    )


def test_public_signature():
    assert isinstance(encoder.MODEL_VERSION, str)
    assert encoder.EMBEDDING_DIM == 128
    assert issubclass(InvalidSequenceError, ValueError)
    assert list(inspect.signature(encoder.load_model).parameters) == ["device"]
    assert inspect.signature(encoder.load_model).parameters["device"].default == "cpu"
    for fn in (encoder.embed, encoder.embed_batch):
        assert len(inspect.signature(fn).parameters) == 1


def test_gateway_returns_user_then_gesture():
    """모듈은 (gesture, user), gateway는 (user, gesture). 뒤바뀌면 두 관문 점수가 뒤바뀐다."""
    payload = ai_input(make_frames(0))
    gesture, user = encoder.embed(payload)
    got_user, got_gesture = embed_both(payload)
    assert np.array_equal(got_user, user)
    assert np.array_equal(got_gesture, gesture)

    gestures, users = encoder.embed_batch([payload])
    batch_user, batch_gesture = embed_both_batch([payload])
    assert np.array_equal(batch_user, users)
    assert np.array_equal(batch_gesture, gestures)


def test_two_heads_have_different_spaces():
    """user와 gesture 임베딩은 서로 다른 벡터다. 같으면 관문 하나가 무의미해진다."""
    user, gesture = embed_both(ai_input(make_frames(0)))
    assert user.shape == gesture.shape == (128, )
    assert user.dtype == gesture.dtype == np.float32
    assert not np.allclose(user, gesture)


@pytest.mark.parametrize("kind", ["user", "gesture"])
def test_embedding_is_l2_normalized(kind):
    user, gesture = embed_both(ai_input(make_frames(0)))
    vector = user if kind == "user" else gesture
    assert np.linalg.norm(vector) == pytest.approx(1.0, abs=1e-5)


def test_embed_is_deterministic():
    payload = ai_input(make_frames(0))
    first = embed_both(payload)
    second = embed_both(payload)
    assert np.array_equal(first[0], second[0])
    assert np.array_equal(first[1], second[1])


def test_embed_deterministic_across_processes():
    """프로세스를 새로 띄워도 같은 벡터여야 한다 (eval 모드, 난수 의존 없음)."""
    code = (
        "from ai import encoder; from tests.payloads import ai_input, make_frames;"
        "encoder.load_model('cpu');"
        "print(encoder.embed(ai_input(make_frames(0)))[1][:4].tolist())"
    )
    outputs = set()
    for hashseed in ("1", "2"):
        env = {**os.environ, "PYTHONHASHSEED": hashseed, "PYTHONDONTWRITEBYTECODE": "1"}
        out = subprocess.run(
            [sys.executable, "-c", code], cwd=BACKEND_DIR, env=env,
            capture_output=True, text=True, check=True,
        )
        outputs.add(out.stdout.strip())
    assert len(outputs) == 1


def test_unrelated_inputs_are_not_identical():
    """서로 다른 입력이 같은 벡터가 되면 안 된다.

    합성 좌표라 유사도의 절대값 자체는 의미가 없다 (실제 사람 동작이 아니다).
    """
    a_user, a_gesture = embed_both(ai_input(make_frames(0)))
    b_user, b_gesture = embed_both(ai_input(make_frames(1)))
    assert not np.allclose(a_user, b_user, atol=1e-3)
    assert not np.allclose(a_gesture, b_gesture, atol=1e-3)


def test_batch():
    payloads = [ai_input(make_frames(s)) for s in range(3)]
    users, gestures = embed_both_batch(payloads)
    assert users.shape == gestures.shape == (3, 128)
    assert np.allclose(np.linalg.norm(users, axis=1), 1.0, atol=1e-5)
    assert np.allclose(np.linalg.norm(gestures, axis=1), 1.0, atol=1e-5)
    single_user, single_gesture = embed_both(payloads[1])
    assert np.allclose(users[1], single_user, atol=1e-5)
    assert np.allclose(gestures[1], single_gesture, atol=1e-5)


def test_seed_thresholds_match_release():
    """app/default_thresholds.json이 ai/thresholds.json과 같은 값이어야 한다."""
    release = json.loads((BACKEND_DIR / "ai" / "thresholds.json").read_text(encoding="utf-8"))
    seed = json.loads((BACKEND_DIR / "app" / "default_thresholds.json").read_text(encoding="utf-8"))
    assert seed["modelVersion"] == encoder.MODEL_VERSION
    default = next(p for p in seed["operatingPoints"] if p["basis"] == seed["defaultBasis"])
    assert default["userThreshold"] == release["user_threshold"]
    assert default["gestureThreshold"] == release["gesture_threshold"]


def test_load_model_accepts_device():
    assert encoder.load_model(device="cpu")["model_version"] == encoder.MODEL_VERSION


def test_build_features_shape():
    feats, duration = features.build_hand_features(ai_input(make_frames(0)))
    assert feats.shape == (features.T_OUT, features.FEATURE_DIM) == (32, 127)
    assert feats.dtype == np.float32
    assert duration > 0


def test_eight_frames_accepted_without_padding():
    """8~31프레임은 AI 모듈이 보간한다. 최소 조건(8프레임, 750ms)은 통과해야 한다."""
    embed_both(ai_input(make_frames(0, n=8, span_ms=750)))


# --- duration (totalFrames / fps) --------------------------------------------------

def test_duration_follows_capture_length_not_frame_count():
    """실기기 fps가 명목값(30)보다 낮아도 모듈이 보는 촬영 길이는 durationMs여야 한다.

    fps·totalFrames를 안 넘기면 모듈이 '검출 프레임 수 / 30'으로 채워서, 14fps 기기의
    4초 촬영이 약 1.9초로 들어간다. 에러 없이 user 점수만 떨어진다.
    """
    slow = make_frames(0, n=56, span_ms=3930)  # 4초 동안 14fps
    payload = _input(slow, nominal_fps=30.0, duration_ms=4000)
    assert payload["fps"] == 30.0 and payload["totalFrames"] == 120
    _, duration = features.build_hand_features(payload)
    assert duration == pytest.approx(4.0)


def test_duration_same_for_fast_and_slow_devices():
    fast = make_frames(0, n=120, span_ms=3967)
    slow = fast[::2]
    for frames in (fast, slow):
        _, duration = features.build_hand_features(_input(frames, nominal_fps=30.0, duration_ms=4000))
        assert duration == pytest.approx(4.0)


def test_duration_falls_back_to_tms_span():
    """durationMs가 없으면 tMs 간격 + 한 칸. 검출 프레임 수보다 실제 길이에 가깝다."""
    slow = make_frames(0, n=56, span_ms=3930)
    _, duration = features.build_hand_features(_input(slow))
    assert duration == pytest.approx(3.93 + 1 / 30, abs=1 / 30)


def test_frame_index_follows_tms():
    frames = make_frames(0, n=10, span_ms=900)
    payload = _input(frames, nominal_fps=30.0, duration_ms=1000)
    assert [f["frameIndex"] for f in payload["frames"]] == [0, 3, 6, 9, 12, 15, 18, 21, 24, 27]
    assert payload["totalFrames"] == 30


def test_declared_duration_never_cuts_frames():
    """durationMs가 실제 프레임 범위보다 짧게 와도 프레임을 잘라내지 않는다."""
    payload = _input(make_frames(0, n=40, span_ms=2000), nominal_fps=30.0, duration_ms=1000)
    assert payload["totalFrames"] == 61


# --- 거절 조건 (명세 1장) ------------------------------------------------------------

def _no_hand(frames, count):
    for f in frames[:count]:
        f["lm"] = None
    return frames


def _bad_timestamps(frames):
    frames[5]["tMs"] = frames[4]["tMs"]
    return frames


def _shuffled_timestamps(frames):
    """모듈은 tMs를 정렬해 받아버린다. 백엔드가 막아야 한다."""
    frames[5], frames[6] = frames[6], frames[5]
    return frames


def _bad_shape(frames):
    frames[3]["lm"] = frames[3]["lm"][:20]
    return frames


def _nan(frames):
    frames[3]["lm"][0][0] = float("nan")
    return frames


REJECTIONS = [
    ("too_few_frames", lambda: ai_input(make_frames(0, n=7))),
    ("insufficient_valid_frames", lambda: ai_input(_no_hand(make_frames(0, n=12), 5))),
    ("duration_too_short", lambda: ai_input(make_frames(0, n=20, span_ms=700))),
    ("non_monotonic_timestamps", lambda: ai_input(_bad_timestamps(make_frames(0)))),
    ("non_monotonic_timestamps", lambda: ai_input(_shuffled_timestamps(make_frames(0)))),
    ("missing_camera_size", lambda: ai_input(make_frames(0), cam={"width": 720})),
    ("malformed_landmarks", lambda: ai_input(_bad_shape(make_frames(0)))),
    ("malformed_landmarks", lambda: ai_input(_nan(make_frames(0)))),
]


@pytest.mark.parametrize(
    "reason,build", REJECTIONS, ids=[f"{r}-{i}" for i, (r, _) in enumerate(REJECTIONS)]
)
@pytest.mark.parametrize("fn", [embed_both, lambda p: embed_both_batch([p])], ids=["single", "batch"])
def test_rejections(reason, build, fn):
    with pytest.raises(InvalidSequenceError) as exc:
        fn(build())
    assert reason_of(exc.value) == reason


def test_left_hand_is_mirrored_not_rejected():
    """v1.0.0 mobile은 왼손을 거절하지 않고 오른손으로 미러링한다."""
    right = embed_both(ai_input(make_frames(0)))
    left = embed_both(ai_input(left_hand(make_frames(0))))
    assert not np.allclose(right[0], left[0], atol=1e-4)


def test_batch_rejects_if_any_invalid():
    with pytest.raises(InvalidSequenceError):
        embed_both_batch([ai_input(make_frames(0)), ai_input(make_frames(1, n=3))])
