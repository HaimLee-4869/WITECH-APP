"""
⚠️ 스텁 구현. AI팀의 ai_release/features.py로 교체될 예정.

실제 모듈은 여기서 좌표 정규화·리샘플링(T=32)·feature 생성(D=127)을 한다.
백엔드는 이 전처리를 직접 구현하지 않는다 (명세 13장).

스텁은 명세 1장의 거절 조건만 실제와 같게 구현한다. 백엔드의 422 변환과
재촬영 안내 흐름을 AI 모듈 없이 검증하기 위해서다.

입력 형태 (백엔드 app/services/ai_gateway.py 가 만든다):

    {
      "camera": {"width": 720, "height": 1280},
      "frames": [{"tMs": 0, "lm": [[x, y, z], ... 21개] | None, ...}, ...]
    }

lm이 None 또는 빈 리스트인 프레임은 "손이 검출되지 않은 프레임"으로 본다.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

import numpy as np

SEQ_LEN = 32        # T
FEATURE_DIM = 127   # D (hand only)
NUM_LANDMARKS = 21
MIN_FRAMES = 8
MIN_VALID_FRAMES = 8
MIN_SPAN_MS = 750


class InvalidSequenceError(ValueError):
    """AI 모듈이 입력을 거절할 때. 실제 모듈과 같은 타입 (ValueError 하위).

    `reason`은 스텁이 붙이는 사유 코드다. 실제 모듈에 없으면 백엔드가
    메시지로 추정한다 (app/services/ai_gateway.py).
    """

    def __init__(self, message: str, reason: str = "invalid_sequence"):
        super().__init__(message)
        self.reason = reason


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _has_hand(frame: Mapping) -> bool:
    lm = frame.get("lm")
    return lm is not None and len(lm) > 0


def _check_landmarks(lm) -> None:
    if not isinstance(lm, Sequence) or len(lm) != NUM_LANDMARKS:
        raise InvalidSequenceError(
            f"landmarks must be {NUM_LANDMARKS}x3", reason="malformed_landmarks"
        )
    for point in lm:
        if not isinstance(point, Sequence) or len(point) != 3:
            raise InvalidSequenceError(
                f"landmarks must be {NUM_LANDMARKS}x3", reason="malformed_landmarks"
            )
        for v in point:
            if not _is_number(v) or not math.isfinite(v):
                raise InvalidSequenceError(
                    "landmarks contain NaN/Inf or non-numeric values",
                    reason="malformed_landmarks",
                )


def validate_sequence(payload) -> None:
    """명세 1장 거절 조건. 실패하면 InvalidSequenceError."""
    if not isinstance(payload, Mapping):
        raise InvalidSequenceError("sequence payload must be a mapping", reason="malformed_landmarks")

    camera = payload.get("camera") or {}
    width, height = camera.get("width"), camera.get("height")
    if not (_is_number(width) and width > 0 and _is_number(height) and height > 0):
        raise InvalidSequenceError("camera width/height missing", reason="missing_camera_size")

    frames = payload.get("frames") or []
    if len(frames) < MIN_FRAMES:
        raise InvalidSequenceError(
            f"too few frames: {len(frames)} < {MIN_FRAMES}", reason="too_few_frames"
        )

    t_values = [f.get("tMs") for f in frames]
    if not all(_is_number(t) and math.isfinite(t) for t in t_values) or any(
        b <= a for a, b in zip(t_values, t_values[1:])
    ):
        raise InvalidSequenceError("tMs must be strictly increasing", reason="non_monotonic_timestamps")

    valid = 0
    for f in frames:
        if _has_hand(f):
            _check_landmarks(f["lm"])
            valid += 1
    if valid < MIN_VALID_FRAMES:
        raise InvalidSequenceError(
            f"too few valid hand frames: {valid} < {MIN_VALID_FRAMES}",
            reason="insufficient_valid_frames",
        )

    span = t_values[-1] - t_values[0]
    if span < MIN_SPAN_MS:
        raise InvalidSequenceError(
            f"sequence too short: {span}ms < {MIN_SPAN_MS}ms", reason="duration_too_short"
        )


def build_features(payload) -> np.ndarray:
    """스텁: [T=32, D=127] 형태만 맞춘다. 값은 의미 없다.

    손이 있는 프레임의 좌표 63개를 tMs 기준으로 32점 선형 보간하고 나머지 차원은 0.
    """
    validate_sequence(payload)
    frames = [f for f in payload["frames"] if _has_hand(f)]
    t = np.asarray([f["tMs"] for f in frames], dtype=np.float64)
    coords = np.asarray([np.asarray(f["lm"], dtype=np.float64).reshape(-1) for f in frames])
    grid = np.linspace(t[0], t[-1], SEQ_LEN)
    out = np.zeros((SEQ_LEN, FEATURE_DIM), dtype=np.float32)
    for d in range(coords.shape[1]):
        out[:, d] = np.interp(grid, t, coords[:, d])
    return out
