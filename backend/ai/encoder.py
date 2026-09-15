"""
⚠️ 스텁 구현. AI팀의 ai_release/encoder.py로 교체될 예정.
시그니처와 반환 형태는 실제와 동일하게 유지한다. (명세 1장, 5장)

같은 입력에는 항상 같은 벡터를 돌려준다. 그래야 등록 → 인증 → 재색인
흐름을 진짜처럼 검증할 수 있다.
"""

from __future__ import annotations

import hashlib

import numpy as np

from ai.features import InvalidSequenceError, validate_sequence

__all__ = [
    "MODEL_VERSION",
    "GESTURE_MODEL_VERSION",
    "EMBEDDING_DIM",
    "InvalidSequenceError",
    "load_model",
    "embed",
    "embed_batch",
    "classify_gesture",
]

MODEL_VERSION = "stub-v0"
GESTURE_MODEL_VERSION = "stub-gesture-v0"
EMBEDDING_DIM = 128

_loaded = False


def load_model(device: str = "cpu") -> None:
    global _loaded
    _loaded = True


def _validate(frames) -> None:
    validate_sequence(frames)


def _deterministic_vector(frames) -> np.ndarray:
    """같은 입력 → 항상 같은 벡터. 테스트 재현성에 필수.

    hash()가 아니라 hashlib을 쓴다. hash()는 PYTHONHASHSEED에 따라 실행마다 달라진다.
    """
    key = repr(frames).encode()
    seed = int(hashlib.sha256(key).hexdigest()[:8], 16)
    v = np.random.RandomState(seed).randn(EMBEDDING_DIM).astype(np.float32)
    return v / (np.linalg.norm(v) + 1e-12)


def embed(frames) -> np.ndarray:
    _validate(frames)
    return _deterministic_vector(frames)


def embed_batch(list_of_frames) -> np.ndarray:
    if not list_of_frames:
        return np.zeros((0, EMBEDDING_DIM), dtype=np.float32)
    return np.stack([embed(f) for f in list_of_frames])


def classify_gesture(frames) -> tuple[str, float]:
    _validate(frames)
    v = _deterministic_vector(frames)
    idx = int(abs(v[0]) * 1000) % 5
    return (f"G{idx + 1}", 0.90)
