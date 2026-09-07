"""손 모양 판정 (SPEC 4.6).

패턴 매칭이 핵심이다. 손가락 4개(엄지 제외)의 펴짐/굽힘 조합이 정확히
일치할 때만 라벨을 준다. 단일 임계값으로 뭉뚱그리지 않기 때문에
NEG_threefingers([T,T,T,F])나 NEG_indexring([T,F,T,F])이 자연히 걸러진다.

임계값 리터럴은 없다. 전부 challenge_config.json에서 온다.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import features as F
from . import geometry as g

UNKNOWN = "UNKNOWN"

# [index, middle, ring, pinky] 조합 → 라벨. 임계값이 아니라 프로토콜 정의다.
SHAPE_PATTERNS: dict[str, tuple[bool, bool, bool, bool]] = {
    "OPEN_PALM": (True, True, True, True),
    "FIST": (False, False, False, False),
    "INDEX": (True, False, False, False),
    "TWO_FINGERS": (True, True, False, False),
}


@dataclass(frozen=True)
class ShapeResult:
    label: str
    confidence: float
    flags: tuple[bool, ...]      # FINGER_NAMES 순서 (엄지 포함)
    angles: tuple[float, ...]    # FINGER_NAMES 순서
    margins: tuple[float, ...]   # 임계값과의 여유(도)


class HandActionDetector:
    """프레임 1개의 랜드마크 → (라벨, 신뢰도)."""

    def __init__(self, config: dict):
        angle_cfg = config["finger_extended_angle"]
        self.thumb_threshold = float(angle_cfg["thumb"])
        self.other_threshold = float(angle_cfg["others"])
        self.angle_space = str(config["angle_space"])
        self.confidence_margin_deg = float(config["shape_confidence_margin_deg"])

    def prepare(self, landmarks: np.ndarray, width: int | None = None,
                height: int | None = None) -> np.ndarray:
        """정규화 좌표를 설정된 angle_space로 옮긴다.

        angle_space가 "world"이면 MediaPipe world landmarks를 그대로 넘겨야 한다.
        """
        if self.angle_space == "world":
            return np.asarray(landmarks, dtype=np.float64)
        if width is None or height is None:
            raise ValueError("image_iso 좌표계는 width/height가 필요하다")
        return g.to_isotropic(landmarks, width, height)

    def detect(self, coords: np.ndarray) -> ShapeResult:
        """coords는 이미 self.angle_space 좌표계여야 한다 (prepare 참고)."""
        angles = g.finger_angle_array(coords)
        flags, margins = g.extension_flags(angles, self.thumb_threshold, self.other_threshold)

        idx = [g.FINGER_NAMES.index(n) for n in g.NON_THUMB_FINGERS]

        # 각도를 못 구한 손가락이 하나라도 있으면 판정하지 않는다.
        # 이게 없으면 랜드마크가 전부 nan인 프레임의 flags가 모두 False가 되어
        # FIST([F,F,F,F])로 오인된다.
        if not all(np.isfinite(angles[i]) for i in idx):
            return ShapeResult(UNKNOWN, 0.0, tuple(flags),
                               tuple(float(a) for a in angles), tuple(margins))

        pattern = tuple(flags[i] for i in idx)
        label = next((name for name, p in SHAPE_PATTERNS.items() if p == pattern), UNKNOWN)

        # 신뢰도: 판정에 쓰인 4손가락이 임계값에서 얼마나 확실히 떨어져 있는지.
        # 가장 아슬아슬한 손가락이 전체 신뢰도를 결정한다.
        scale = self.confidence_margin_deg
        decisiveness = [min(abs(margins[i]) / scale, 1.0) if np.isfinite(margins[i]) else 0.0
                        for i in idx]
        confidence = float(min(decisiveness)) if decisiveness else 0.0

        return ShapeResult(label=label, confidence=confidence,
                           flags=tuple(flags), angles=tuple(float(a) for a in angles),
                           margins=tuple(margins))

    def detect_from_clip(self, clip, frame_index: int) -> ShapeResult:
        """캐시된 영상의 한 프레임을 판정한다 (05_validate_rules.py용)."""
        coords = F.angle_source(clip, self.angle_space)[frame_index]
        return self.detect(coords)
