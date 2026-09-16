"""AI 모듈 계약 테스트 (dual-head v1.1.1 + 명세 1장).

ai_release를 교체해도 이 파일은 그대로 통과해야 한다.
입력은 백엔드와 같은 경로(ai_gateway.to_ai_input)로 만든다.
"""

from __future__ import annotations

import inspect
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from ai import encoder, features
from app.services.ai_gateway import (
    InvalidSequenceError,
    embed_both,
    embed_both_batch,
    reason_of,
)
from tests.payloads import ai_input, left_hand, make_frames

BACKEND_DIR = Path(__file__).resolve().parent.parent


def test_public_signature():
    assert isinstance(encoder.MODEL_VERSION, str)
    assert encoder.EMBEDDING_DIM == 128
    assert issubclass(InvalidSequenceError, ValueError)
    assert list(inspect.signature(encoder.load_model).parameters) == ["device"]
    assert inspect.signature(encoder.load_model).parameters["device"].default == "cpu"
    for fn in (encoder.embed_user, encoder.embed_gesture, encoder.embed_both):
        assert len(inspect.signature(fn).parameters) == 1


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


def test_embed_both_matches_single_calls():
    payload = ai_input(make_frames(0))
    user, gesture = embed_both(payload)
    assert np.allclose(user, encoder.embed_user(payload), atol=1e-6)
    assert np.allclose(gesture, encoder.embed_gesture(payload), atol=1e-6)


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
        "print(encoder.embed_user(ai_input(make_frames(0)))[:4].tolist())"
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
    assert float(a_user @ b_user) < 0.9
    assert float(a_gesture @ b_gesture) < 0.99


def test_batch():
    payloads = [ai_input(make_frames(s)) for s in range(3)]
    users, gestures = embed_both_batch(payloads)
    assert users.shape == gestures.shape == (3, 128)
    assert np.allclose(np.linalg.norm(users, axis=1), 1.0, atol=1e-5)
    assert np.allclose(np.linalg.norm(gestures, axis=1), 1.0, atol=1e-5)
    single_user, single_gesture = embed_both(payloads[1])
    assert np.allclose(users[1], single_user, atol=1e-5)
    assert np.allclose(gestures[1], single_gesture, atol=1e-5)


def test_thresholds_file_has_two_gates():
    thresholds = encoder.get_thresholds()
    points = thresholds["operating_points"]
    assert "default" in points
    for point in points.values():
        assert "user_threshold" in point and "gesture_threshold" in point
    assert thresholds["selected_operating_point"] == "default"


def test_load_model_accepts_device():
    assert encoder.load_model(device="cpu")["embedding_dim"] == 128


def test_build_features_shape():
    feats, duration = features.build_hand_features(ai_input(make_frames(0)))
    assert feats.shape == (features.T_OUT, features.FEATURE_DIM) == (32, 127)
    assert feats.dtype == np.float32
    assert duration > 0


def test_eight_frames_accepted_without_padding():
    """8~31프레임은 AI 모듈이 보간한다. 최소 조건(8프레임, 750ms)은 통과해야 한다."""
    embed_both(ai_input(make_frames(0, n=8, span_ms=750)))


# --- 거절 조건 (명세 1장 + 실제 모듈의 오른손 조건) ---------------------------------

def _no_hand(frames, count):
    for f in frames[:count]:
        f["lm"] = None
    return frames


def _bad_timestamps(frames):
    frames[5]["tMs"] = frames[4]["tMs"]
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
    ("missing_camera_size", lambda: ai_input(make_frames(0), cam={"width": 720})),
    ("malformed_landmarks", lambda: ai_input(_bad_shape(make_frames(0)))),
    ("malformed_landmarks", lambda: ai_input(_nan(make_frames(0)))),
    ("wrong_hand", lambda: ai_input(left_hand(make_frames(0)))),
]


@pytest.mark.parametrize(
    "reason,build", REJECTIONS, ids=[f"{r}-{i}" for i, (r, _) in enumerate(REJECTIONS)]
)
@pytest.mark.parametrize("fn", [encoder.embed_user, encoder.embed_gesture, encoder.embed_both])
def test_rejections(reason, build, fn):
    with pytest.raises(InvalidSequenceError) as exc:
        fn(build())
    assert reason_of(exc.value) == reason


def test_batch_rejects_if_any_invalid():
    with pytest.raises(InvalidSequenceError):
        embed_both_batch([ai_input(make_frames(0)), ai_input(make_frames(1, n=3))])
