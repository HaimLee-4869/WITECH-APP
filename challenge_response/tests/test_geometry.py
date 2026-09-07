"""geometry.py 검증 - 알려진 좌표에서 각도가 맞는지, 정규화가 거리 변화에 불변인지."""
from __future__ import annotations

import numpy as np
import pytest

from core import geometry as g
from tests.synth import make_hand


def test_angle_at_right_angle():
    assert g.angle_at([1, 0, 0], [0, 0, 0], [0, 1, 0]) == pytest.approx(90.0)


def test_angle_at_straight_line():
    assert g.angle_at([-1, 0, 0], [0, 0, 0], [1, 0, 0]) == pytest.approx(180.0)


def test_angle_at_zero_when_folded_back():
    assert g.angle_at([1, 0, 0], [0, 0, 0], [2, 0, 0]) == pytest.approx(0.0, abs=1e-6)


def test_angle_at_known_60_degrees():
    a = [np.cos(np.radians(60.0)), np.sin(np.radians(60.0)), 0.0]
    assert g.angle_at(a, [0, 0, 0], [1, 0, 0]) == pytest.approx(60.0)


def test_angle_at_degenerate_returns_nan():
    assert np.isnan(g.angle_at([0, 0, 0], [0, 0, 0], [1, 0, 0]))


@pytest.mark.parametrize("target", [180.0, 160.0, 120.0, 90.0, 40.0])
def test_finger_angles_match_synthetic_target(target):
    angles = g.finger_angles(make_hand(target))
    for name in g.FINGER_NAMES:
        assert angles[name] == pytest.approx(target, abs=1e-6)


def test_finger_angle_array_order_matches_names():
    hand = make_hand({"thumb": 100.0, "index": 180.0, "middle": 170.0,
                      "ring": 60.0, "pinky": 50.0})
    assert list(g.FINGER_NAMES) == ["thumb", "index", "middle", "ring", "pinky"]
    assert g.finger_angle_array(hand) == pytest.approx(
        [100.0, 180.0, 170.0, 60.0, 50.0], abs=1e-6)


def test_finger_angles_invariant_to_scale_and_translation():
    near = make_hand(150.0, scale=1.0, center=(0.0, 0.0, 0.0))
    far = make_hand(150.0, scale=0.3, center=(0.4, 0.7, 0.1))
    assert g.finger_angle_array(near) == pytest.approx(
        g.finger_angle_array(far), abs=1e-6)


def test_hand_scale_is_wrist_to_middle_mcp():
    hand = make_hand(180.0, scale=2.0)
    expected = float(np.linalg.norm(hand[g.MIDDLE_MCP] - hand[g.WRIST]))
    assert g.hand_scale(hand) == pytest.approx(expected)


def test_hand_scale_proportional_to_size():
    small, big = make_hand(180.0, scale=1.0), make_hand(180.0, scale=3.0)
    assert g.hand_scale(big) == pytest.approx(3.0 * g.hand_scale(small))


def test_displacement_over_hand_scale_is_distance_invariant():
    """카메라가 멀어져 손이 작아져도 (변위/손크기) 비율은 같아야 한다."""
    ratios = []
    for scale in (1.0, 0.4):
        a = make_hand(180.0, scale=scale, center=(0.0, 0.0, 0.0))
        b = make_hand(180.0, scale=scale, center=(2.0 * scale, 0.0, 0.0))
        disp = float(np.linalg.norm(g.palm_center(b) - g.palm_center(a)))
        ratios.append(disp / g.hand_scale(a))
    assert ratios[0] == pytest.approx(ratios[1])


def test_palm_center_uses_only_palm_points():
    hand = make_hand(180.0)
    expected = hand[list(g.PALM_POINTS)].mean(axis=0)
    assert g.palm_center(hand) == pytest.approx(expected)


def test_palm_center_unaffected_by_fingertip_movement():
    assert g.palm_center(make_hand(180.0)) == pytest.approx(g.palm_center(make_hand(30.0)))


def test_sequence_helpers_match_per_frame_calls():
    seq = np.stack([make_hand(180.0, center=(x, 0.0, 0.0)) for x in (0.0, 0.5, 1.0)])
    centers, scales = g.sequence_palm_centers(seq), g.sequence_hand_scales(seq)
    for i in range(seq.shape[0]):
        assert centers[i] == pytest.approx(g.palm_center(seq[i]))
        assert scales[i] == pytest.approx(g.hand_scale(seq[i]))


def test_to_isotropic_applies_aspect_ratio():
    lm = np.zeros((21, 3))
    lm[0] = [0.5, 0.5, 0.1]
    assert g.to_isotropic(lm, width=1920, height=1080)[0] == pytest.approx(
        [960.0, 540.0, 192.0])


def test_to_isotropic_fixes_angle_distortion_on_wide_frames():
    """정규화 좌표 그대로 각도를 재면 16:9 영상에서 왜곡된다. 보정하면 45도가 나온다."""
    normalized = np.zeros((21, 3))
    mcp, pip, tip = g.FINGER_JOINTS["index"]
    # 픽셀 기준으로 정확히 45도가 되도록 배치한 뒤 정규화한 값
    normalized[pip] = [0.5, 0.5, 0.0]
    normalized[mcp] = [0.5 + 100.0 / 1920.0, 0.5, 0.0]
    normalized[tip] = [0.5 + 100.0 / 1920.0, 0.5 + 100.0 / 1080.0, 0.0]
    raw = g.finger_angles(normalized)["index"]
    fixed = g.finger_angles(g.to_isotropic(normalized, 1920, 1080))["index"]
    assert fixed == pytest.approx(45.0)
    assert abs(raw - 45.0) > 1.0


def test_to_isotropic_does_not_mutate_input():
    lm = np.zeros((21, 3))
    lm[0] = [0.5, 0.5, 0.5]
    g.to_isotropic(lm, 100, 200)
    assert lm[0] == pytest.approx([0.5, 0.5, 0.5])


def test_extension_flags_uses_separate_thumb_threshold():
    angles = {"thumb": 155.0, "index": 155.0, "middle": 170.0,
              "ring": 90.0, "pinky": 90.0}
    flags, margins = g.extension_flags(angles, thumb_threshold=150.0, other_threshold=160.0)
    assert flags == [True, False, True, False, False]
    assert margins[0] == pytest.approx(5.0)
    assert margins[1] == pytest.approx(-5.0)


def test_extension_flags_nan_angle_is_not_extended():
    angles = {"thumb": float("nan"), "index": 180.0, "middle": 180.0,
              "ring": 180.0, "pinky": 180.0}
    flags, margins = g.extension_flags(angles, 150.0, 160.0)
    assert flags[0] is False
    assert np.isnan(margins[0])
