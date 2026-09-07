"""이동 방향 판정 (SPEC 4.7).

    1. palm_center와 hand_scale 계산
    2. 시작점 대비 최대 변위 벡터
    3. 손 크기로 정규화
    4. 변위가 min_displacement_ratio 미만이면 NONE      <- NEG_shake 거름
    5. |주축|/|부축|가 axis_dominance_ratio 미만이면 NONE <- NEG_diagonal 거름
    6. 주축 부호로 방향 결정
    7. coordinate_frame이 "mirrored"면 좌우를 뒤집어 반환

임계값 리터럴은 없다. 전부 challenge_config.json에서 온다.
(축→방향 대응표도 추측하지 않고 04_derive_thresholds.py가 실제 영상에서 뽑는다.)
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import features as F
from . import geometry as g

NONE = "NONE"
MIRRORED = "mirrored"
RAW = "raw"

# 좌우가 뒤집혔을 때 서로 바뀌는 라벨 쌍. 상하는 거울에 영향받지 않는다.
_LEFT_RIGHT = {"MOVE_LEFT": "MOVE_RIGHT", "MOVE_RIGHT": "MOVE_LEFT"}


@dataclass(frozen=True)
class MoveResult:
    label: str
    confidence: float
    displacement_ratio: float
    axis_ratio: float
    axis: str
    sign: int
    reason: str  # NONE일 때 어느 단계에서 걸렸는지


class MovementDetector:
    """최근 N프레임의 랜드마크 시퀀스 → (방향, 신뢰도)."""

    def __init__(self, config: dict):
        move = config["movement"]
        self.min_displacement_ratio = float(move["min_displacement_ratio"])
        self.axis_dominance_ratio = float(move["axis_dominance_ratio"])
        self.window_ms = float(move["window_ms"])
        self.max_duration_ms = float(move["max_duration_ms"])
        # {"MOVE_LEFT": ["x", -1], ...} -> {("x", -1): "MOVE_LEFT", ...}
        self.direction_map = {(str(a), int(s)): label
                              for label, (a, s) in move["direction_map"].items()}
        self.coordinate_frame = str(config["coordinate_frame"])
        if self.coordinate_frame not in (RAW, MIRRORED):
            raise ValueError(f"coordinate_frame은 {RAW} 또는 {MIRRORED}: "
                             f"{self.coordinate_frame!r}")

    def window_frames(self, fps: float) -> int:
        """fps에 맞는 판정 윈도우 길이(프레임)."""
        return max(int(round(self.window_ms / 1000.0 * fps)), 2)

    def detect_from_tracks(self, centers: np.ndarray, scales: np.ndarray) -> MoveResult:
        """이미 계산된 손바닥 중심/손 크기 궤적으로 판정한다."""
        motion = F.window_motion(centers, scales, 0, len(scales))

        if not motion.valid:
            return MoveResult(NONE, 0.0, motion.displacement_ratio, motion.axis_ratio,
                              motion.axis, motion.sign, "NO_TRACK")

        if motion.displacement_ratio < self.min_displacement_ratio:
            return MoveResult(NONE, 0.0, motion.displacement_ratio, motion.axis_ratio,
                              motion.axis, motion.sign, "TOO_SMALL")

        if motion.axis_ratio < self.axis_dominance_ratio:
            return MoveResult(NONE, 0.0, motion.displacement_ratio, motion.axis_ratio,
                              motion.axis, motion.sign, "NOT_AXIS_DOMINANT")

        label = self.direction_map.get((motion.axis, motion.sign))
        if label is None:
            return MoveResult(NONE, 0.0, motion.displacement_ratio, motion.axis_ratio,
                              motion.axis, motion.sign, "UNMAPPED_AXIS")

        if self.coordinate_frame == MIRRORED:
            label = _LEFT_RIGHT.get(label, label)

        disp_excess = motion.displacement_ratio / self.min_displacement_ratio
        axis_excess = (motion.axis_ratio / self.axis_dominance_ratio
                       if np.isfinite(motion.axis_ratio) else float("inf"))
        confidence = float(min(disp_excess, axis_excess, 1.0)) if np.isfinite(
            min(disp_excess, axis_excess)) else 1.0

        return MoveResult(label, confidence, motion.displacement_ratio, motion.axis_ratio,
                          motion.axis, motion.sign, "OK")

    def detect(self, sequence: np.ndarray) -> MoveResult:
        """sequence는 (F,21,3) 화면 좌표(종횡비 보정 완료)."""
        seq = np.asarray(sequence, dtype=np.float64)
        centers = g.sequence_palm_centers(seq)
        scales = g.sequence_hand_scales(seq)
        return self.detect_from_tracks(centers, scales)
