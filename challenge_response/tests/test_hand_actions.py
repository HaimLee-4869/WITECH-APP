"""hand_action_detector.py 검증 (SPEC 4.6).

임계값은 테스트용 합성 config로 주입한다. 실제 영상이 없어도 패턴 매칭 규칙을
검증할 수 있어야 한다.
"""
from __future__ import annotations

import numpy as np
import pytest

from core.geometry import FINGER_NAMES, NON_THUMB_FINGERS
from core.hand_action_detector import SHAPE_PATTERNS, UNKNOWN, HandActionDetector
from tests.synth import make_pattern_hand

EXTENDED_ANGLE = 175.0
CURLED_ANGLE = 60.0

TEST_CONFIG = {
    "angle_space": "world",
    "finger_extended_angle": {"thumb": 150.0, "others": 160.0},
    "shape_confidence_margin_deg": 20.0,
}


@pytest.fixture
def detector():
    return HandActionDetector(TEST_CONFIG)


def hand_for(pattern: dict, thumb_extended: bool = True, **kwargs) -> np.ndarray:
    return make_pattern_hand({**pattern, "thumb": thumb_extended},
                             EXTENDED_ANGLE, CURLED_ANGLE, **kwargs)


def pattern_dict(flags) -> dict:
    return dict(zip(NON_THUMB_FINGERS, flags))


@pytest.mark.parametrize("label,flags", list(SHAPE_PATTERNS.items()))
def test_each_declared_pattern_gets_its_label(detector, label, flags):
    result = detector.detect(hand_for(pattern_dict(flags)))
    assert result.label == label


@pytest.mark.parametrize("flags", [
    (True, True, True, False),    # NEG_threefingers
    (True, False, True, False),   # NEG_indexring
    (True, False, False, True),   # NEG_indexpinky
    (False, True, False, False),
    (False, False, True, True),
    (False, True, True, True),
])
def test_undeclared_patterns_are_unknown(detector, flags):
    assert detector.detect(hand_for(pattern_dict(flags))).label == UNKNOWN


def test_threefingers_is_unknown_not_open_palm(detector):
    """[T,T,T,F]가 OPEN_PALM으로 새면 경계 케이스 방어가 무너진다."""
    result = detector.detect(hand_for(pattern_dict((True, True, True, False))))
    assert result.label == UNKNOWN
    assert result.label != "OPEN_PALM"


def test_indexring_is_unknown_not_two_fingers(detector):
    result = detector.detect(hand_for(pattern_dict((True, False, True, False))))
    assert result.label == UNKNOWN


@pytest.mark.parametrize("thumb_extended", [True, False])
def test_thumb_does_not_change_the_label(detector, thumb_extended):
    """엄지는 사람마다 편차가 커서 판정에서 뺀다 (SPEC 4.6)."""
    pattern = pattern_dict(SHAPE_PATTERNS["TWO_FINGERS"])
    assert detector.detect(hand_for(pattern, thumb_extended)).label == "TWO_FINGERS"


def test_labels_are_invariant_to_hand_size_and_position(detector):
    pattern = pattern_dict(SHAPE_PATTERNS["INDEX"])
    near = detector.detect(hand_for(pattern, scale=1.0, center=(0.0, 0.0, 0.0)))
    far = detector.detect(hand_for(pattern, scale=0.25, center=(0.8, 0.6, 0.2)))
    assert near.label == far.label == "INDEX"
    assert near.confidence == pytest.approx(far.confidence)


def test_confidence_is_high_when_far_from_threshold(detector):
    result = detector.detect(hand_for(pattern_dict(SHAPE_PATTERNS["OPEN_PALM"])))
    margin = EXTENDED_ANGLE - TEST_CONFIG["finger_extended_angle"]["others"]
    expected = min(margin / TEST_CONFIG["shape_confidence_margin_deg"], 1.0)
    assert result.confidence == pytest.approx(expected)
    assert result.confidence > 0.5


def test_confidence_saturates_at_one(detector):
    from tests.synth import make_hand
    assert detector.detect(make_hand(180.0)).confidence == pytest.approx(1.0)


def test_confidence_drops_at_the_boundary(detector):
    """임계값 바로 위에 걸친 손가락은 신뢰도를 끌어내려야 한다."""
    from tests.synth import make_hand
    threshold = TEST_CONFIG["finger_extended_angle"]["others"]
    angles = {name: EXTENDED_ANGLE for name in FINGER_NAMES}
    angles["pinky"] = threshold + 1.0
    result = detector.detect(make_hand(angles))
    assert result.label == "OPEN_PALM"
    assert result.confidence < 0.2


def test_confidence_is_the_weakest_finger(detector):
    from tests.synth import make_hand
    margin = TEST_CONFIG["shape_confidence_margin_deg"]
    threshold = TEST_CONFIG["finger_extended_angle"]["others"]
    angles = {n: threshold + margin for n in FINGER_NAMES}
    angles["ring"] = threshold + margin / 2.0
    result = detector.detect(make_hand(angles))
    assert result.confidence == pytest.approx(0.5)


def test_missing_landmarks_give_unknown_with_zero_confidence(detector):
    """랜드마크가 없으면 flags가 전부 False가 되어 FIST로 새기 쉽다. 막아야 한다."""
    result = detector.detect(np.full((21, 3), np.nan))
    assert result.label == UNKNOWN
    assert result.confidence == pytest.approx(0.0)


def test_single_missing_finger_gives_unknown(detector):
    """한 손가락만 못 읽어도 패턴을 확정하면 안 된다."""
    hand = hand_for(pattern_dict(SHAPE_PATTERNS["OPEN_PALM"]))
    hand[8] = np.nan  # 검지 TIP
    assert detector.detect(hand).label == UNKNOWN


def test_flags_and_angles_are_reported_for_debugging(detector):
    result = detector.detect(hand_for(pattern_dict(SHAPE_PATTERNS["FIST"])))
    assert len(result.flags) == len(FINGER_NAMES)
    assert len(result.angles) == len(FINGER_NAMES)
    assert all(not f for f in result.flags[1:])


def test_prepare_requires_frame_size_for_image_space():
    detector = HandActionDetector({**TEST_CONFIG, "angle_space": "image_iso"})
    with pytest.raises(ValueError):
        detector.prepare(np.zeros((21, 3)))


def test_prepare_applies_aspect_correction_for_image_space():
    detector = HandActionDetector({**TEST_CONFIG, "angle_space": "image_iso"})
    lm = np.zeros((21, 3))
    lm[0] = [0.5, 0.5, 0.0]
    assert detector.prepare(lm, 1920, 1080)[0] == pytest.approx([960.0, 540.0, 0.0])


def test_every_declared_pattern_is_distinct():
    assert len(set(SHAPE_PATTERNS.values())) == len(SHAPE_PATTERNS)
