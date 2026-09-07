"""분석과 판정이 공유하는 프레임/윈도우 특징 계산.

여기에도 임계값은 없다. 03_analyze_distributions.py(분포 측정)와
hand_action_detector / movement_detector(판정)가 **같은 수식**을 쓰도록
계산을 한 곳에 모아둔 것이다.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import geometry as g

# 각도를 재는 좌표계 선택지.
#   image_iso : 정규화 좌표를 화면 종횡비로 보정한 2.5D 좌표
#   world     : MediaPipe world landmarks (미터 단위 3D)
ANGLE_SPACES = ("image_iso", "world")

_EPS = np.finfo(np.float64).eps


def angle_source(clip, space: str) -> np.ndarray:
    """각도 계산에 쓸 (F,21,3) 좌표를 고른다."""
    if space == "world":
        return np.asarray(clip.world_landmarks, dtype=np.float64)
    if space == "image_iso":
        return g.to_isotropic(clip.landmarks, clip.width, clip.height)
    raise ValueError(f"알 수 없는 angle_space: {space!r}")


def screen_coords(clip) -> np.ndarray:
    """이동 판정에 쓸 화면 좌표 (F,21,3). 종횡비 보정된 픽셀 단위."""
    return g.to_isotropic(clip.landmarks, clip.width, clip.height)


def frame_angles(clip, space: str) -> np.ndarray:
    """(F,5) 손가락 관절 각도. 검출 실패 프레임은 nan."""
    coords = angle_source(clip, space)
    n = coords.shape[0]
    out = np.full((n, len(g.FINGER_NAMES)), np.nan, dtype=np.float64)
    for i in range(n):
        if clip.valid_mask[i]:
            out[i] = g.finger_angle_array(coords[i])
    return out


def frame_palm_tracks(clip) -> tuple[np.ndarray, np.ndarray]:
    """(F,3) 손바닥 중심과 (F,) 손 크기. 검출 실패 프레임은 nan."""
    coords = screen_coords(clip)
    centers = np.full((coords.shape[0], 3), np.nan)
    scales = np.full(coords.shape[0], np.nan)
    valid = clip.valid_mask
    if valid.any():
        centers[valid] = g.sequence_palm_centers(coords[valid])
        scales[valid] = g.sequence_hand_scales(coords[valid])
    return centers, scales


@dataclass(frozen=True)
class WindowMotion:
    """한 윈도우 안에서 측정한 이동량."""
    displacement_ratio: float   # 최대 변위 크기 / 손 크기
    dx_ratio: float             # 주축이 x일 때 부호 있는 값 (오른쪽 +)
    dy_ratio: float             # 화면 아래쪽 +
    axis_ratio: float           # |주축| / |부축|
    axis: str                   # "x" | "y" | "none"
    sign: int                   # +1 / -1 / 0
    coverage: float             # 윈도우 내 손 검출 비율

    @property
    def valid(self) -> bool:
        return np.isfinite(self.displacement_ratio)


def window_motion(centers: np.ndarray, scales: np.ndarray,
                  start: int, stop: int) -> WindowMotion:
    """centers[start:stop] 구간의 이동량을 계산한다 (SPEC 4.7의 1~3단계).

    시작점 대비 가장 멀리 간 지점까지의 변위를 손 크기로 나눈다.
    """
    seg_c = np.asarray(centers[start:stop], dtype=np.float64)
    seg_s = np.asarray(scales[start:stop], dtype=np.float64)
    ok = np.isfinite(seg_c[:, 0]) & np.isfinite(seg_s) & (seg_s > 0)
    coverage = float(ok.mean()) if ok.size else 0.0

    nan_motion = WindowMotion(np.nan, np.nan, np.nan, np.nan, "none", 0, coverage)
    if ok.sum() < 2:
        return nan_motion

    pts = seg_c[ok][:, :2]
    scale = float(np.median(seg_s[ok]))
    if not np.isfinite(scale) or scale <= 0:
        return nan_motion

    deltas = pts - pts[0]
    magnitudes = np.linalg.norm(deltas, axis=1)
    peak = deltas[int(np.argmax(magnitudes))]

    dx, dy = float(peak[0]) / scale, float(peak[1]) / scale
    displacement = float(np.hypot(dx, dy))

    if abs(dx) >= abs(dy):
        axis, primary, secondary, sign = "x", abs(dx), abs(dy), (1 if dx >= 0 else -1)
    else:
        axis, primary, secondary, sign = "y", abs(dy), abs(dx), (1 if dy >= 0 else -1)
    axis_ratio = float(primary / secondary) if secondary > _EPS else float("inf")

    return WindowMotion(displacement, dx, dy, axis_ratio, axis, sign, coverage)


def sliding_window_motions(centers: np.ndarray, scales: np.ndarray,
                           window_frames: int, step: int = 1) -> list[WindowMotion]:
    """프레임을 window_frames 길이로 훑으며 이동량을 모은다."""
    n = len(scales)
    if window_frames <= 1 or n < window_frames:
        return []
    return [window_motion(centers, scales, i, i + window_frames)
            for i in range(0, n - window_frames + 1, step)]


def count_strokes(centers: np.ndarray, axis: int, scales: np.ndarray,
                  min_amplitude_ratio: float) -> int:
    """주축 궤적에서 방향이 바뀌는 '왕복 획'의 수를 센다.

    min_amplitude_ratio(손 크기 배수)보다 작은 흔들림은 획으로 세지 않는다.
    임계값은 호출자가 config에서 넘긴다.
    """
    pos = np.asarray(centers, dtype=np.float64)[:, axis]
    scale = float(np.nanmedian(scales))
    ok = np.isfinite(pos)
    if not np.isfinite(scale) or scale <= 0 or ok.sum() < 2:
        return 0
    track = pos[ok] / scale

    threshold = float(min_amplitude_ratio)
    strokes = 0
    anchor = track[0]
    direction = 0
    for value in track[1:]:
        delta = value - anchor
        if abs(delta) < threshold:
            continue
        new_direction = 1 if delta > 0 else -1
        if new_direction != direction:
            strokes += 1
            direction = new_direction
        anchor = value
    return strokes


def percentile_summary(values: np.ndarray, percentiles=(5, 25, 50, 75, 95)) -> dict:
    """평균·표준편차·백분위 요약. nan은 제외한다."""
    arr = np.asarray(values, dtype=np.float64)
    arr = arr[np.isfinite(arr)]
    out: dict[str, float] = {"n": int(arr.size)}
    if arr.size == 0:
        out["mean"] = out["std"] = float("nan")
        for p in percentiles:
            out[f"p{p}"] = float("nan")
        return out
    out["mean"] = float(arr.mean())
    out["std"] = float(arr.std(ddof=1)) if arr.size > 1 else 0.0
    for p in percentiles:
        out[f"p{p}"] = float(np.percentile(arr, p))
    return out
