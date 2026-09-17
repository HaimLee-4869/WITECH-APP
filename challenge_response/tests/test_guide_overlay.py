"""안내 패널이 가리키는 방향과 판정기가 인정하는 방향이 같은지 검증한다.

화면을 거울로 뒤집어 보여주기 때문에 좌우 반전이 두 번 적용되기 쉽다.
실제로 그 버그가 있었고, 상하 이동만으로는 드러나지 않았다. 여기서 막는다.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

# 그리기 모듈이라 OpenCV가 있어야 한다. 백엔드 전용 환경에는 없다.
pytest.importorskip("cv2", reason="guide_overlay는 OpenCV가 필요하다")

import guide_overlay as G  # noqa: E402
import hand_sketch  # noqa: E402

from core.hand_action_detector import SHAPE_PATTERNS  # noqa: E402
from core.movement_detector import MIRRORED, RAW, MovementDetector  # noqa: E402
from core.naming import MOVE_ACTIONS  # noqa: E402
from tests.synth import make_sequence  # noqa: E402

BASE_CONFIG = {
    "coordinate_frame": MIRRORED,
    "movement": {
        "window_ms": 500,
        "min_displacement_ratio": 1.0,
        "axis_dominance_ratio": 2.0,
        "max_duration_ms": 2000,
        "direction_map": {"MOVE_LEFT": ["x", -1], "MOVE_RIGHT": ["x", 1],
                          "MOVE_UP": ["y", -1], "MOVE_DOWN": ["y", 1]},
    },
}
RAW_CONFIG = {**BASE_CONFIG, "coordinate_frame": RAW}


def judge(config, screen_dx, screen_dy):
    """화면에서 (dx,dy)로 움직였을 때 판정기가 내놓는 라벨.

    화면은 거울이므로 원본 좌표의 x는 화면과 반대다. y는 그대로.
    """
    raw_dx = -screen_dx if config["coordinate_frame"] == MIRRORED else screen_dx
    sequence = make_sequence((0.0, 0.0, 0.0), (raw_dx * 3.0, screen_dy * 3.0, 0.0), 20)
    return MovementDetector(config).detect(sequence).label


@pytest.mark.parametrize("action", MOVE_ACTIONS)
def test_arrow_direction_is_accepted_by_the_detector(action):
    """화살표가 가리키는 대로 움직이면 그 동작으로 판정되어야 한다."""
    dx, dy = G.screen_direction(action, BASE_CONFIG)
    assert (dx, dy) != (0, 0)
    assert judge(BASE_CONFIG, dx, dy) == action


@pytest.mark.parametrize("action", MOVE_ACTIONS)
def test_arrow_direction_holds_in_raw_frame_too(action):
    dx, dy = G.screen_direction(action, RAW_CONFIG)
    assert judge(RAW_CONFIG, dx, dy) == action


def test_left_and_right_arrows_are_opposite():
    left = G.screen_direction("MOVE_LEFT", BASE_CONFIG)
    right = G.screen_direction("MOVE_RIGHT", BASE_CONFIG)
    assert left == (-right[0], -right[1])


def test_left_arrow_points_screen_left():
    """텍스트가 LEFT인데 화살표가 오른쪽을 가리키면 사용자가 혼란스럽다."""
    assert G.screen_direction("MOVE_LEFT", BASE_CONFIG) == (-1, 0)
    assert G.screen_direction("MOVE_RIGHT", BASE_CONFIG) == (1, 0)


def test_vertical_arrows_are_not_affected_by_mirroring():
    for action in ("MOVE_UP", "MOVE_DOWN"):
        assert (G.screen_direction(action, BASE_CONFIG)
                == G.screen_direction(action, RAW_CONFIG))
    assert G.screen_direction("MOVE_UP", BASE_CONFIG) == (0, -1)


def test_arrow_is_screen_relative_regardless_of_coordinate_frame():
    """화살표는 화면 기준 방향이므로 좌표계 설정이 바뀌어도 같아야 한다.

    좌표계 차이는 screen_direction 안에서 흡수되고, 판정과의 일치는 위의
    test_arrow_direction_* 이 확인한다.
    """
    for action in MOVE_ACTIONS:
        assert (G.screen_direction(action, BASE_CONFIG)
                == G.screen_direction(action, RAW_CONFIG))


def test_unknown_action_has_no_direction():
    assert G.screen_direction("OPEN_PALM", BASE_CONFIG) == (0, 0)


@pytest.mark.parametrize("action", list(SHAPE_PATTERNS))
def test_shape_guide_draws_without_error(action):
    canvas = np.zeros((480, 640, 3), np.uint8)
    G.draw_guide(canvas, action, BASE_CONFIG)
    assert canvas.any()


@pytest.mark.parametrize("action", MOVE_ACTIONS)
def test_move_guide_draws_without_error(action):
    canvas = np.zeros((480, 640, 3), np.uint8)
    G.draw_guide(canvas, action, BASE_CONFIG)
    assert canvas.any()


def test_guide_is_skipped_when_it_would_not_fit():
    canvas = np.zeros((60, 60, 3), np.uint8)
    G.draw_guide(canvas, "FIST", BASE_CONFIG)  # 예외 없이 그냥 넘어가야 한다


def test_extended_fingers_are_drawn_taller_than_curled():
    """아이콘이 펴짐/굽힘을 실제로 구분해 그리는지."""
    def finger_pixels(action):
        canvas = np.zeros((480, 640, 3), np.uint8)
        G.draw_guide(canvas, action, BASE_CONFIG)
        return int(np.count_nonzero(
            np.all(canvas == hand_sketch.EXTENDED_COLOUR, axis=2)))

    assert finger_pixels("OPEN_PALM") > finger_pixels("TWO_FINGERS")
    assert finger_pixels("TWO_FINGERS") > finger_pixels("INDEX")
    assert finger_pixels("FIST") == 0


def test_next_actions_strip_marks_the_current_step():
    actions = ["OPEN_PALM", "MOVE_LEFT", "FIST"]
    canvas = np.zeros((480, 640, 3), np.uint8)
    G.draw_next_actions(canvas, actions, 1, BASE_CONFIG)
    assert np.any(np.all(canvas == (60, 200, 240), axis=2))


# ---------------------------------------------------------------- 가장자리 경고

def _hand_at(cx, cy, size=0.1):
    """정규화 좌표 (cx, cy) 근처에 손목(0)과 중지 MCP(9)를 둔 21점 손."""
    lm = np.zeros((21, 3))
    lm[:, 0], lm[:, 1] = cx, cy
    lm[0, 1] = cy + size / 2      # 손목
    lm[9, 1] = cy - size / 2      # 중지 MCP
    return lm


def test_centred_hand_has_no_edge_warning():
    assert G.edge_sides(_hand_at(0.5, 0.5), 640, 480) == []


def test_hand_near_top_and_bottom():
    assert G.edge_sides(_hand_at(0.5, 0.04), 640, 480) == ["top"]
    assert G.edge_sides(_hand_at(0.5, 0.96), 640, 480) == ["bottom"]


def test_left_right_follow_the_mirrored_screen():
    """원본 x가 작으면(카메라 기준 왼쪽) 거울 화면에서는 오른쪽이다."""
    assert G.edge_sides(_hand_at(0.005, 0.5), 640, 480) == ["right"]
    assert G.edge_sides(_hand_at(0.995, 0.5), 640, 480) == ["left"]


def test_default_margin_is_a_quarter_hand():
    """손 크기 1/4보다 멀면 경고하지 않는다 (1.0이면 이동 프레임 93%에서 켜졌다)."""
    size = 0.1                                     # 손 크기 48px @ 480
    half_hand_away = 0.5 * size * 480 / 480 + size / 2   # 윤곽 위끝이 손 크기 절반만큼 떨어짐
    assert G.edge_sides(_hand_at(0.5, half_hand_away, size), 640, 480) == []
    tenth_hand_away = 0.1 * size + size / 2
    assert G.edge_sides(_hand_at(0.5, tenth_hand_away, size), 640, 480) == ["top"]


def test_margin_scales_with_hand_size():
    """같은 위치라도 손이 크게(가깝게) 찍히면 여유가 더 필요하다."""
    assert G.edge_sides(_hand_at(0.5, 0.2, size=0.05), 640, 480) == []
    assert G.edge_sides(_hand_at(0.5, 0.2, size=0.3), 640, 480) == ["top"]


def test_missing_landmarks_give_no_warning():
    assert G.edge_sides(np.full((21, 3), np.nan), 640, 480) == []
