"""movement_detector.py 검증 (SPEC 4.7)."""
from __future__ import annotations

import numpy as np
import pytest

from core import features as F
from core.movement_detector import NONE, MovementDetector
from tests.synth import make_sequence

FRAMES = 20
HAND_SCALE = 1.0  # synth의 손목(0)-중지MCP(9) 거리는 scale과 같다

TEST_CONFIG = {
    "coordinate_frame": "raw",
    "movement": {
        "window_ms": 1000,
        "min_displacement_ratio": 1.2,
        "axis_dominance_ratio": 2.0,
        "max_duration_ms": 2500,
        # 화면 좌표: x는 오른쪽이 +, y는 아래쪽이 +
        "direction_map": {"MOVE_LEFT": ["x", -1], "MOVE_RIGHT": ["x", 1],
                          "MOVE_UP": ["y", -1], "MOVE_DOWN": ["y", 1]},
    },
}
MIRRORED_CONFIG = {**TEST_CONFIG, "coordinate_frame": "mirrored"}


@pytest.fixture
def detector():
    return MovementDetector(TEST_CONFIG)


def move(dx: float, dy: float, scale: float = 1.0, frames: int = FRAMES) -> np.ndarray:
    """손 크기 배수로 (dx, dy)만큼 이동하는 시퀀스."""
    return make_sequence((0.0, 0.0, 0.0), (dx * scale, dy * scale, 0.0),
                         frames, scale=scale)


@pytest.mark.parametrize("dx,dy,expected", [
    (3.0, 0.0, "MOVE_RIGHT"),
    (-3.0, 0.0, "MOVE_LEFT"),
    (0.0, -3.0, "MOVE_UP"),
    (0.0, 3.0, "MOVE_DOWN"),
])
def test_pure_axis_movement_is_detected(detector, dx, dy, expected):
    assert detector.detect(move(dx, dy)).label == expected


def test_45_degree_diagonal_is_none(detector):
    result = detector.detect(move(3.0, 3.0))
    assert result.label == NONE
    assert result.reason == "NOT_AXIS_DOMINANT"


def test_diagonal_just_under_dominance_is_none(detector):
    ratio = TEST_CONFIG["movement"]["axis_dominance_ratio"]
    result = detector.detect(move(3.0, 3.0 / (ratio - 0.2)))
    assert result.label == NONE


def test_movement_above_dominance_is_accepted(detector):
    ratio = TEST_CONFIG["movement"]["axis_dominance_ratio"]
    assert detector.detect(move(3.0, 3.0 / (ratio + 1.0))).label == "MOVE_RIGHT"


def test_small_shake_is_none(detector):
    """min_displacement_ratio 미만은 이동으로 치지 않는다 (NEG_shake 방어)."""
    limit = TEST_CONFIG["movement"]["min_displacement_ratio"]
    result = detector.detect(move(limit * 0.5, 0.0))
    assert result.label == NONE
    assert result.reason == "TOO_SMALL"


def test_oscillation_without_net_travel_is_none(detector):
    """제자리에서 떠는 손은 이동이 아니다."""
    limit = TEST_CONFIG["movement"]["min_displacement_ratio"]
    amp = limit * 0.3
    seq = np.stack([make_sequence((0.0, 0.0, 0.0),
                                  (amp * (1 if i % 2 else -1), 0.0, 0.0), 2)[1]
                    for i in range(FRAMES)])
    assert detector.detect(seq).label == NONE


@pytest.mark.parametrize("scale", [0.25, 1.0, 4.0])
def test_result_is_invariant_to_hand_size(detector, scale):
    """손이 2배, 4배 커져도 정규화 후 결과는 같아야 한다 (near/far 불변)."""
    result = detector.detect(move(3.0, 0.0, scale=scale))
    assert result.label == "MOVE_RIGHT"
    assert result.displacement_ratio == pytest.approx(3.0)


def test_displacement_ratio_is_measured_in_hand_scales(detector):
    assert detector.detect(move(2.5, 0.0)).displacement_ratio == pytest.approx(2.5)


def test_mirrored_frame_swaps_left_and_right():
    mirrored = MovementDetector(MIRRORED_CONFIG)
    assert mirrored.detect(move(3.0, 0.0)).label == "MOVE_LEFT"
    assert mirrored.detect(move(-3.0, 0.0)).label == "MOVE_RIGHT"


def test_mirrored_frame_leaves_up_and_down_alone():
    mirrored = MovementDetector(MIRRORED_CONFIG)
    assert mirrored.detect(move(0.0, -3.0)).label == "MOVE_UP"
    assert mirrored.detect(move(0.0, 3.0)).label == "MOVE_DOWN"


def test_direction_map_is_taken_from_config_not_assumed():
    """축→방향 대응은 실측에서 오므로, config를 바꾸면 결과도 바뀌어야 한다."""
    swapped = {**TEST_CONFIG, "movement": {
        **TEST_CONFIG["movement"],
        "direction_map": {"MOVE_LEFT": ["x", 1], "MOVE_RIGHT": ["x", -1],
                          "MOVE_UP": ["y", 1], "MOVE_DOWN": ["y", -1]}}}
    assert MovementDetector(swapped).detect(move(3.0, 0.0)).label == "MOVE_LEFT"


def test_unmapped_axis_returns_none():
    partial = {**TEST_CONFIG, "movement": {
        **TEST_CONFIG["movement"],
        "direction_map": {"MOVE_LEFT": ["x", -1], "MOVE_RIGHT": ["x", 1]}}}
    result = MovementDetector(partial).detect(move(0.0, 3.0))
    assert result.label == NONE
    assert result.reason == "UNMAPPED_AXIS"


def test_all_invalid_frames_return_none(detector):
    result = detector.detect(np.full((FRAMES, 21, 3), np.nan))
    assert result.label == NONE
    assert result.reason == "NO_TRACK"


def test_window_frames_scales_with_fps(detector):
    assert detector.window_frames(30.0) == 30
    assert detector.window_frames(60.0) == 60


def test_invalid_coordinate_frame_is_rejected():
    with pytest.raises(ValueError):
        MovementDetector({**TEST_CONFIG, "coordinate_frame": "screen"})


# ---------------------------------------------------------------- 촬영 방식 판별 (04 direction_map, 05 편도 검증)

_WF = 10          # 윈도우 프레임 수
_REST = 0.05      # 정지로 보는 윈도우 변위 상한 (실제로는 NEG_shake p95)
_MIN_DISP = 0.2   # 판정기가 이동으로 보는 최소 변위


def _track(xs):
    """x 궤적(손 크기 1 기준) -> (centers, scales)."""
    xs = np.asarray(xs, dtype=float)
    centers = np.zeros((len(xs), 3))
    centers[:, 0] = xs
    return centers, np.ones(len(xs))


def _flick(direction=-1, strokes=3, rest=25, out=8):
    xs = [0.0] * rest
    for _ in range(strokes):
        xs += list(direction * np.linspace(0, 1, out)) + list(direction * np.linspace(1, 0, out))
        xs += [0.0] * rest
    return xs


def test_flick_style_is_detected_with_one_bout_per_stroke():
    style = F.move_style(*_track(_flick(strokes=3)), _WF, _REST, _MIN_DISP)
    assert style.is_flick
    assert len(style.one_way_bouts()) == 3
    assert style.opposite_excursion < _MIN_DISP


def test_continuous_back_and_forth_is_not_flick():
    xs = np.sin(np.linspace(0, 6 * np.pi, 180))
    style = F.move_style(*_track(xs), _WF, _REST, _MIN_DISP)
    assert not style.is_flick


def test_clip_that_starts_moving_is_not_flick():
    xs = list(np.linspace(0, -1, 8)) + _flick(strokes=2)
    style = F.move_style(*_track(xs), _WF, _REST, _MIN_DISP)
    assert not style.starts_at_rest
    assert not style.is_flick


def test_moving_to_both_sides_of_the_start_is_not_flick():
    xs = _flick(direction=-1, strokes=1) + _flick(direction=+1, strokes=1)
    style = F.move_style(*_track(xs), _WF, _REST, _MIN_DISP)
    assert not style.one_sided
    assert not style.is_flick


def test_flick_without_return_to_rest_is_not_flick():
    xs = [0.0] * 25 + list(np.linspace(0, -1, 8)) + [-1.0] * 25
    style = F.move_style(*_track(xs), _WF, _REST, _MIN_DISP)
    assert style.ends_away
    assert not style.is_flick


def test_flick_is_direction_agnostic():
    left = F.move_style(*_track(_flick(direction=-1)), _WF, _REST, _MIN_DISP)
    right = F.move_style(*_track(_flick(direction=+1)), _WF, _REST, _MIN_DISP)
    assert left.is_flick and right.is_flick
