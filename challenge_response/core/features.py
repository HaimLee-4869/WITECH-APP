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


def frame_tip_wrist_ratios(clip, space: str) -> np.ndarray:
    """(F,) 손끝-손목 거리 / 손 크기. 검출 실패 프레임은 nan."""
    coords = angle_source(clip, space)
    out = np.full(coords.shape[0], np.nan, dtype=np.float64)
    for i in range(coords.shape[0]):
        if clip.valid_mask[i]:
            out[i] = g.fingertip_wrist_ratio(coords[i])
    return out


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


@dataclass(frozen=True)
class MoveStyle:
    """MOVE 영상의 촬영 방식. 방향 판정(04)과 편도 검증(05)이 같은 규칙을 쓴다.

    인덱스는 모두 슬라이딩 윈도우의 시작 프레임이다.
    """
    starts_at_rest: bool              # 첫 윈도우가 정지인가
    opposite_excursion: float         # 주축에서 출발점 반대편으로 넘어간 최대 거리 / 손 크기
    one_sided: bool                   # opposite_excursion < min_displacement_ratio
    bouts: tuple[tuple[int, int], ...]  # 출발점을 떠났다가 돌아와 멈춘 구간 [떠난 윈도우, 복귀 정지 윈도우)
    ends_away: bool                   # 마지막 이탈 뒤 돌아와 멈추기 전에 영상이 끝났는가

    @property
    def is_flick(self) -> bool:
        """출발점에서 멈췄다가 한 방향으로 튕기고 돌아와 멈추는 방식인가.

        1. 정지 상태로 시작한다. 첫 획이 라벨 방향이라는 가정(first_stroke_sign)이
           여기서 성립한다.
        2. 주축에서 출발점 반대편으로는 판정기가 이동으로 볼 만큼 넘어가지 않는다.
        3. 출발점을 떠났다가 돌아와 멈춘 적이 한 번 이상 있다.
        멈춤 없는 왕복은 대개 출발점 양쪽으로 넘어가거나(2) 정지로 시작하지 않는다(1).
        """
        return self.starts_at_rest and self.one_sided and bool(self.bouts)

    @property
    def reason(self) -> str:
        if self.is_flick:
            return "튕기는 방식"
        if not self.starts_at_rest:
            return "정지 상태로 시작하지 않음"
        if not self.one_sided:
            return f"출발점 양쪽으로 이동(반대편 {self.opposite_excursion:.2f})"
        return "출발점으로 돌아와 멈춘 적 없음"

    def one_way_bouts(self) -> list[tuple[int, int]]:
        """'정지 -> 한 방향 이동 -> 제자리 정지' 한 번씩 (편도 1회 시도)."""
        return list(self.bouts)


def move_style(centers: np.ndarray, scales: np.ndarray, window_frames: int,
               rest_displacement_ratio: float, min_displacement_ratio: float) -> MoveStyle:
    """촬영 방식을 판별한다. 새 임계값 없이 04가 도출한 값만 쓴다.

    - 정지 윈도우: 윈도우 변위가 rest_displacement_ratio(NEG_shake 윈도우 p95,
      제자리 흔들림 수준) 미만. 윈도우 자체가 window_ms 길이이므로 정지 윈도우
      하나 = window_ms 동안 제자리.
    - 출발점: 첫 윈도우가 덮는 프레임의 평균 손바닥 위치.
    - 이탈/복귀는 주축(영상 전체에서 이동 범위가 큰 축) 방향으로만 잰다. 출발점에서
      min_displacement_ratio(판정기가 이동으로 보는 최소 변위) 이상 떨어지면 이탈,
      이탈 뒤 정지 윈도우의 모든 프레임이 그 거리 안으로 들어오면 복귀.
    """
    wf = int(window_frames)
    motions = sliding_window_motions(centers, scales, wf)
    empty = MoveStyle(False, float("nan"), False, (), False)
    if not motions:
        return empty
    still = np.array([m.valid and m.displacement_ratio < rest_displacement_ratio
                      for m in motions], dtype=bool)
    pts = np.asarray(centers, dtype=np.float64)[:, :2]
    scale = float(np.nanmedian(scales))
    if not np.isfinite(scale) or scale <= 0:
        return empty

    axis, _, _ = primary_axis(centers, scales)
    home = float(np.nanmean(pts[:wf, axis]))
    along = (pts[:, axis] - home) / scale
    distance = np.abs(along)

    leaving = np.flatnonzero(distance >= min_displacement_ratio)
    if leaving.size:
        sign = np.sign(along[leaving[0]])
        opposite = float(np.nanmax(np.concatenate([[0.0], -sign * along[np.isfinite(along)]])))
    else:
        opposite = 0.0

    bouts: list[tuple[int, int]] = []
    away_since = None
    for i in range(len(still)):
        window = distance[i:i + wf]
        if not np.isfinite(window).any():
            continue
        if away_since is None:
            if np.nanmax(window) >= min_displacement_ratio:
                away_since = i
        elif still[i] and np.nanmax(window) < min_displacement_ratio:
            bouts.append((away_since, i))
            away_since = None

    return MoveStyle(starts_at_rest=bool(still[0]), opposite_excursion=opposite,
                     one_sided=opposite < min_displacement_ratio, bouts=tuple(bouts),
                     ends_away=away_since is not None)


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


def stable_span(valid: np.ndarray, trim_frames: int) -> tuple[int, int]:
    """손이 안정적으로 잡혀 있는 구간 [start, stop).

    영상 앞뒤에는 손이 화면으로 들어오고 나가는 동작이 들어 있다. 그건 제스처가
    아니고, 실시간에서도 WAIT_HAND 이전·HAND_LOST 이후는 판정하지 않는다.
    첫/마지막 검출에서 trim_frames만큼 잘라낸 구간을 돌려준다.
    """
    ok = np.asarray(valid, dtype=bool)
    if not ok.any():
        return 0, 0
    first = int(np.argmax(ok))
    last = len(ok) - 1 - int(np.argmax(ok[::-1]))
    return first + trim_frames, last - trim_frames + 1


def interior_gap_lengths(valid: np.ndarray) -> list[int]:
    """첫 검출과 마지막 검출 '사이'의 미검출 구간 길이들.

    앞뒤 미검출(손이 아직 안 들어왔거나 이미 나간 상태)은 세지 않는다.
    """
    ok = np.asarray(valid, dtype=bool)
    if not ok.any():
        return []
    first = int(np.argmax(ok))
    last = len(ok) - 1 - int(np.argmax(ok[::-1]))
    gaps, current = [], 0
    for value in ok[first:last + 1]:
        if not value:
            current += 1
        elif current:
            gaps.append(current)
            current = 0
    return gaps


def primary_axis(centers: np.ndarray, scales: np.ndarray) -> tuple[int, float, float]:
    """이동 범위가 큰 축과 (주축 범위, 축비)를 돌려준다. 손 크기로 정규화."""
    pts = np.asarray(centers, dtype=np.float64)[:, :2]
    ok = np.isfinite(pts[:, 0])
    scale = float(np.nanmedian(scales))
    if ok.sum() < 2 or not np.isfinite(scale) or scale <= 0:
        return 0, float("nan"), float("nan")
    norm = pts[ok] / scale
    spans = norm.max(axis=0) - norm.min(axis=0)
    axis = int(np.argmax(spans))
    minor = max(float(spans[1 - axis]), _EPS)
    return axis, float(spans[axis]), float(spans[axis] / minor)


def first_stroke_sign(centers: np.ndarray, scales: np.ndarray, axis: int,
                      fraction: float) -> int:
    """정지 상태에서 처음 움직인 방향의 부호.

    왕복 운동은 양방향이 같은 횟수로 나타나므로 슬라이딩 윈도우 다수결로는
    좌/우를 가릴 수 없다. 촬영은 정지 상태에서 시작하므로 첫 획이 라벨 방향이다.
    """
    pts = np.asarray(centers, dtype=np.float64)[:, axis]
    scale = float(np.nanmedian(scales))
    ok = np.isfinite(pts)
    if ok.sum() < 2 or not np.isfinite(scale) or scale <= 0:
        return 0
    track = pts[ok] / scale
    offset = track - track[0]
    span = float(track.max() - track.min())
    threshold = fraction * span
    hits = np.flatnonzero(np.abs(offset) >= threshold)
    return int(np.sign(offset[hits[0]])) if hits.size else 0


def stroke_duration_ms(centers: np.ndarray, scales: np.ndarray, axis: int,
                       fps: float) -> float:
    """획 1회 소요시간. 주축 궤적이 자기 평균선을 가로지른 횟수로 잰다.

    진폭 임계값이 필요 없으므로 임계값 도출에 순환 참조가 생기지 않는다.
    """
    pts = np.asarray(centers, dtype=np.float64)[:, axis]
    ok = np.isfinite(pts)
    if ok.sum() < 3 or fps <= 0:
        return float("nan")
    track = pts[ok]
    centered = track - track.mean()
    crossings = int(np.sum(np.diff(np.sign(centered)) != 0))
    if crossings == 0:
        return float("nan")
    return float(len(track) / fps * 1000.0 / crossings)
