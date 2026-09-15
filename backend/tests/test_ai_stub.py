"""3단계: 스텁 AI 모듈 단위 테스트.

실제 ai_release로 교체한 뒤에도 시그니처·반환 형태 테스트는 통과해야 한다.
결정성(같은 입력 → 같은 벡터)과 사유 코드 테스트는 스텁 전용이다.
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
from tests.payloads import ai_input, make_frames

BACKEND_DIR = Path(__file__).resolve().parent.parent


def test_public_signature():
    assert isinstance(encoder.MODEL_VERSION, str)
    assert isinstance(encoder.GESTURE_MODEL_VERSION, str)
    assert issubclass(encoder.InvalidSequenceError, ValueError)
    assert list(inspect.signature(encoder.load_model).parameters) == ["device"]
    assert inspect.signature(encoder.load_model).parameters["device"].default == "cpu"
    for fn in (encoder.embed, encoder.embed_batch, encoder.classify_gesture):
        assert len(inspect.signature(fn).parameters) == 1


def test_embed_shape_dtype_norm():
    v = encoder.embed(ai_input(make_frames(0)))
    assert v.shape == (128,)
    assert v.dtype == np.float32
    assert np.linalg.norm(v) == pytest.approx(1.0, abs=1e-5)


def test_embed_is_deterministic():
    a = encoder.embed(ai_input(make_frames(0)))
    b = encoder.embed(ai_input(make_frames(0)))
    assert np.array_equal(a, b)


def test_embed_deterministic_across_processes():
    """PYTHONHASHSEED가 달라도 같은 벡터여야 한다 (hash() 대신 hashlib)."""
    code = (
        "from ai import encoder; from tests.payloads import ai_input, make_frames;"
        "print(encoder.embed(ai_input(make_frames(0)))[:4].tolist())"
    )
    outputs = set()
    for hashseed in ("1", "2"):
        env = {**os.environ, "PYTHONHASHSEED": hashseed}
        out = subprocess.run(
            [sys.executable, "-c", code], cwd=BACKEND_DIR, env=env,
            capture_output=True, text=True, check=True,
        )
        outputs.add(out.stdout.strip())
    assert len(outputs) == 1


def test_different_input_low_similarity():
    a = encoder.embed(ai_input(make_frames(0)))
    b = encoder.embed(ai_input(make_frames(1)))
    assert float(a @ b) < 0.5


def test_embed_batch():
    batch = encoder.embed_batch([ai_input(make_frames(s)) for s in range(3)])
    assert batch.shape == (3, 128)
    assert batch.dtype == np.float32
    assert np.array_equal(batch[1], encoder.embed(ai_input(make_frames(1))))
    empty = encoder.embed_batch([])
    assert empty.shape == (0, 128)


def test_classify_gesture():
    label, conf = encoder.classify_gesture(ai_input(make_frames(0)))
    assert label in {"G1", "G2", "G3", "G4", "G5"}
    assert isinstance(conf, float) and 0.0 <= conf <= 1.0
    assert encoder.classify_gesture(ai_input(make_frames(0))) == (label, conf)


def test_load_model_accepts_device():
    encoder.load_model(device="cpu")


def test_build_features_shape():
    feats = features.build_features(ai_input(make_frames(0)))
    assert feats.shape == (features.SEQ_LEN, features.FEATURE_DIM) == (32, 127)


def test_eight_frames_accepted_without_padding():
    """8~31프레임은 AI 모듈이 보간한다. 최소 조건(8프레임, 750ms)은 통과해야 한다."""
    encoder.embed(ai_input(make_frames(0, n=8, span_ms=750)))


# --- 거절 조건 6종 (명세 1장) ---------------------------------------------------

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
    ("duration_too_short", lambda: ai_input(make_frames(0, n=20, span_ms=749))),
    ("non_monotonic_timestamps", lambda: ai_input(_bad_timestamps(make_frames(0)))),
    ("missing_camera_size", lambda: ai_input(make_frames(0), cam={"width": 720})),
    ("malformed_landmarks", lambda: ai_input(_bad_shape(make_frames(0)))),
    ("malformed_landmarks", lambda: ai_input(_nan(make_frames(0)))),
]


@pytest.mark.parametrize("reason,build", REJECTIONS, ids=[f"{r}-{i}" for i, (r, _) in enumerate(REJECTIONS)])
@pytest.mark.parametrize("fn", [encoder.embed, encoder.classify_gesture])
def test_rejections(reason, build, fn):
    with pytest.raises(encoder.InvalidSequenceError) as exc:
        fn(build())
    assert exc.value.reason == reason


def test_embed_batch_rejects_if_any_invalid():
    with pytest.raises(encoder.InvalidSequenceError):
        encoder.embed_batch([ai_input(make_frames(0)), ai_input(make_frames(1, n=3))])
