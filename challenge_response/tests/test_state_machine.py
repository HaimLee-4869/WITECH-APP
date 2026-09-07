"""challenge_state_machine.py 검증 (SPEC 4.9).

순서 위반·타임아웃·손 소실이 각각 올바른 FailReason을 내는지 본다.
임계값은 테스트용 합성 config로 주입한다.
"""
from __future__ import annotations

import numpy as np
import pytest

from core.challenge_generator import Challenge
from core.challenge_state_machine import (ChallengeStateMachine, FailReason,
                                          Observation, State)
from core.hand_action_detector import SHAPE_PATTERNS, HandActionDetector
from core.movement_detector import MovementDetector
from tests.synth import make_hand, make_pattern_hand

EXTENDED_ANGLE = 175.0
CURLED_ANGLE = 60.0
FPS = 30.0
FRAME_MS = 1000.0 / FPS

CONFIG = {
    "angle_space": "world",
    "finger_extended_angle": {"thumb": 150.0, "others": 160.0},
    "shape_confidence_margin_deg": 10.0,
    "shape_confidence_min": 0.5,
    "shape_hold_frames": 5,
    "coordinate_frame": "raw",
    "movement": {
        "window_ms": 400,          # 12프레임
        "min_displacement_ratio": 1.2,
        "axis_dominance_ratio": 2.0,
        "max_duration_ms": 2500,
        "direction_map": {"MOVE_LEFT": ["x", -1], "MOVE_RIGHT": ["x", 1],
                          "MOVE_UP": ["y", -1], "MOVE_DOWN": ["y", 1]},
    },
    "timing": {"per_action_timeout_ms": 2000, "total_timeout_ms": 9000,
               "max_retries": 0},
    "tracking": {"max_lost_frames": 5, "min_detection_score": 0.5},
}


def shape_hand(label: str) -> np.ndarray:
    pattern = dict(zip(("index", "middle", "ring", "pinky"), SHAPE_PATTERNS[label]))
    return make_pattern_hand({**pattern, "thumb": True}, EXTENDED_ANGLE, CURLED_ANGLE)


def build(actions, config=CONFIG) -> ChallengeStateMachine:
    challenge = Challenge(challenge_id="test", actions=list(actions), created_at="now")
    return ChallengeStateMachine(config, challenge,
                                 HandActionDetector(config),
                                 MovementDetector(config), FPS)


def obs(t_ms: float, hand=None, found=True, score=1.0, center=(0.0, 0.0, 0.0)):
    coords = hand if hand is not None else make_hand(180.0, center=center)
    return Observation(timestamp_ms=t_ms, hand_found=found, detection_score=score,
                       angle_coords=coords, screen_coords=coords)


def feed_shape(sm, label, frames, start_ms=0.0):
    status = None
    for i in range(frames):
        status = sm.update(obs(start_ms + i * FRAME_MS, shape_hand(label)))
        if status.finished:
            break
    return status


# ------------------------------------------------------------------ 정상 흐름


def test_holding_the_requested_shape_passes_the_step():
    sm = build(["OPEN_PALM", "FIST", "MOVE_RIGHT"])
    feed_shape(sm, "OPEN_PALM", CONFIG["shape_hold_frames"])
    assert sm.step_index == 1
    assert sm.steps[0].passed


def test_shape_must_be_held_for_the_full_hold_frames():
    sm = build(["OPEN_PALM", "FIST", "MOVE_RIGHT"])
    feed_shape(sm, "OPEN_PALM", CONFIG["shape_hold_frames"] - 1)
    assert sm.step_index == 0
    assert not sm.steps[0].passed


def test_full_challenge_can_pass():
    sm = build(["OPEN_PALM", "FIST", "MOVE_RIGHT"])
    hold = CONFIG["shape_hold_frames"]
    t = 0.0
    feed_shape(sm, "OPEN_PALM", hold, t)
    t += hold * FRAME_MS
    feed_shape(sm, "FIST", hold, t)
    t += hold * FRAME_MS
    window = sm.movement_detector.window_frames(FPS)
    status = None
    for i in range(window):
        center = (3.0 * i / (window - 1), 0.0, 0.0)
        status = sm.update(obs(t + i * FRAME_MS, center=center))
    assert status.state == State.PASS
    assert all(step.passed for step in status.steps)


def test_hold_progress_is_reported():
    sm = build(["OPEN_PALM", "FIST", "MOVE_RIGHT"])
    status = feed_shape(sm, "OPEN_PALM", CONFIG["shape_hold_frames"] - 2)
    assert 0.0 < status.hold_progress < 1.0


# ------------------------------------------------------------------ 실패 사유


def test_wrong_shape_gives_wrong_shape():
    sm = build(["OPEN_PALM", "INDEX", "MOVE_RIGHT"])
    status = feed_shape(sm, "FIST", CONFIG["shape_hold_frames"])
    assert status.state == State.FAIL
    assert status.fail_reason is FailReason.WRONG_SHAPE


def test_brief_wrong_shape_blip_does_not_fail():
    """오검출은 측정상 최대 8프레임까지 연속으로 나온다. 한 프레임에 죽으면 안 된다."""
    sm = build(["OPEN_PALM", "INDEX", "MOVE_RIGHT"])
    status = feed_shape(sm, "FIST", CONFIG["shape_hold_frames"] - 1)
    assert status.state != State.FAIL
    status = feed_shape(sm, "OPEN_PALM", CONFIG["shape_hold_frames"],
                        CONFIG["shape_hold_frames"] * FRAME_MS)
    assert sm.steps[0].passed


def test_alternating_wrong_shapes_do_not_accumulate():
    """서로 다른 오검출이 번갈아 나오는 건 '한 모양을 유지'한 게 아니다."""
    sm = build(["OPEN_PALM", "MOVE_RIGHT", "MOVE_UP"])
    for i in range(CONFIG["shape_hold_frames"] * 3):
        label = "FIST" if i % 2 else "INDEX"
        status = sm.update(obs(i * FRAME_MS, shape_hand(label)))
        if status.finished:
            break
    assert status.fail_reason is not FailReason.WRONG_SHAPE


def test_performing_a_later_action_first_gives_wrong_order():
    """3단계 동작을 1단계에서 하면 순서 위반이다."""
    sm = build(["OPEN_PALM", "MOVE_RIGHT", "FIST"])
    status = feed_shape(sm, "FIST", CONFIG["shape_hold_frames"])
    assert status.state == State.FAIL
    assert status.fail_reason is FailReason.WRONG_ORDER


def test_wrong_direction_gives_wrong_direction():
    sm = build(["MOVE_RIGHT", "OPEN_PALM", "FIST"])
    window = sm.movement_detector.window_frames(FPS)
    status = None
    for i in range(window):
        status = sm.update(obs(i * FRAME_MS, center=(-3.0 * i / (window - 1), 0.0, 0.0)))
    assert status.state == State.FAIL
    assert status.fail_reason is FailReason.WRONG_DIRECTION


def test_action_timeout_when_nothing_recognisable_happens():
    sm = build(["OPEN_PALM", "FIST", "MOVE_RIGHT"])
    ambiguous = make_hand({"thumb": 180.0, "index": 180.0, "middle": 180.0,
                           "ring": 180.0, "pinky": CONFIG["finger_extended_angle"]["others"]})
    status = None
    t = 0.0
    while t <= CONFIG["timing"]["per_action_timeout_ms"] + FRAME_MS:
        status = sm.update(obs(t, ambiguous))
        if status.finished:
            break
        t += FRAME_MS
    assert status.state == State.FAIL
    assert status.fail_reason is FailReason.ACTION_TIMEOUT


def test_total_timeout_beats_per_action_timeout():
    config = {**CONFIG, "timing": {**CONFIG["timing"],
                                   "per_action_timeout_ms": 100000,
                                   "total_timeout_ms": 500}}
    sm = build(["OPEN_PALM", "FIST", "MOVE_RIGHT"], config)
    sm.update(obs(0.0, shape_hand("OPEN_PALM")))
    status = sm.update(obs(600.0, shape_hand("OPEN_PALM")))
    assert status.state == State.FAIL
    assert status.fail_reason is FailReason.TOTAL_TIMEOUT


def test_hand_never_appearing_gives_hand_not_found():
    sm = build(["OPEN_PALM", "FIST", "MOVE_RIGHT"])
    status = None
    for i in range(CONFIG["tracking"]["max_lost_frames"] + 2):
        status = sm.update(Observation(i * FRAME_MS, hand_found=False))
    assert status.state == State.FAIL
    assert status.fail_reason is FailReason.HAND_NOT_FOUND


def test_hand_disappearing_mid_action_gives_hand_lost():
    sm = build(["OPEN_PALM", "FIST", "MOVE_RIGHT"])
    feed_shape(sm, "OPEN_PALM", 2)
    status = None
    t = 3 * FRAME_MS
    for i in range(CONFIG["tracking"]["max_lost_frames"] + 2):
        status = sm.update(Observation(t + i * FRAME_MS, hand_found=False))
    assert status.state == State.FAIL
    assert status.fail_reason is FailReason.HAND_LOST


def test_brief_dropout_is_tolerated():
    sm = build(["OPEN_PALM", "FIST", "MOVE_RIGHT"])
    feed_shape(sm, "OPEN_PALM", 2)
    t = 3 * FRAME_MS
    for i in range(CONFIG["tracking"]["max_lost_frames"]):
        status = sm.update(Observation(t + i * FRAME_MS, hand_found=False))
        assert status.state != State.FAIL
    assert sm.state is not State.FAIL


def test_low_detection_score_gives_tracking_unstable():
    sm = build(["OPEN_PALM", "FIST", "MOVE_RIGHT"])
    low = CONFIG["tracking"]["min_detection_score"] - 0.1
    status = None
    for i in range(CONFIG["tracking"]["max_lost_frames"] + 2):
        status = sm.update(obs(i * FRAME_MS, shape_hand("OPEN_PALM"), score=low))
    assert status.state == State.FAIL
    assert status.fail_reason is FailReason.TRACKING_UNSTABLE


def test_fail_reason_is_an_enum_not_a_string():
    sm = build(["OPEN_PALM", "INDEX", "MOVE_RIGHT"])
    status = feed_shape(sm, "FIST", CONFIG["shape_hold_frames"])
    assert isinstance(status.fail_reason, FailReason)


def test_failed_step_records_its_reason():
    sm = build(["OPEN_PALM", "INDEX", "MOVE_RIGHT"])
    status = feed_shape(sm, "FIST", CONFIG["shape_hold_frames"])
    assert status.steps[0].fail_reason is FailReason.WRONG_SHAPE
    assert not status.steps[0].passed


# ------------------------------------------------------------------ 재시도


def test_retry_gives_the_step_another_chance():
    config = {**CONFIG, "timing": {**CONFIG["timing"], "max_retries": 1}}
    sm = build(["OPEN_PALM", "INDEX", "MOVE_RIGHT"], config)
    hold = config["shape_hold_frames"]
    status = feed_shape(sm, "FIST", hold)
    assert status.state != State.FAIL
    assert sm.steps[0].retries_used == 1
    feed_shape(sm, "OPEN_PALM", hold, hold * FRAME_MS)
    assert sm.steps[0].passed


def test_retries_run_out():
    config = {**CONFIG, "timing": {**CONFIG["timing"], "max_retries": 1}}
    sm = build(["OPEN_PALM", "INDEX", "MOVE_RIGHT"], config)
    hold = config["shape_hold_frames"]
    feed_shape(sm, "FIST", hold)
    status = feed_shape(sm, "FIST", hold, hold * FRAME_MS)
    assert status.state == State.FAIL
    assert status.fail_reason is FailReason.WRONG_SHAPE


def test_hand_lost_is_not_retryable():
    config = {**CONFIG, "timing": {**CONFIG["timing"], "max_retries": 5}}
    sm = build(["OPEN_PALM", "FIST", "MOVE_RIGHT"], config)
    feed_shape(sm, "OPEN_PALM", 2)
    status = None
    t = 3 * FRAME_MS
    for i in range(config["tracking"]["max_lost_frames"] + 2):
        status = sm.update(Observation(t + i * FRAME_MS, hand_found=False))
    assert status.fail_reason is FailReason.HAND_LOST


# ------------------------------------------------------------------ 상태 전이


def test_starts_in_idle_and_moves_to_action():
    sm = build(["OPEN_PALM", "FIST", "MOVE_RIGHT"])
    assert sm.state is State.IDLE
    sm.update(obs(0.0, shape_hand("OPEN_PALM")))
    assert sm.state is State.ACTION


def test_finished_machine_ignores_further_frames():
    sm = build(["OPEN_PALM", "INDEX", "MOVE_RIGHT"])
    feed_shape(sm, "FIST", CONFIG["shape_hold_frames"])
    before = sm.step_index
    status = sm.update(obs(999.0, shape_hand("OPEN_PALM")))
    assert status.state == State.FAIL
    assert sm.step_index == before


def test_state_machine_has_no_ui_dependency():
    """Flutter 이식 시 이 로직이 명세가 되므로 순수 파이썬이어야 한다."""
    import ast
    import core.challenge_state_machine as mod

    tree = ast.parse(open(mod.__file__, encoding="utf-8").read())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported <= {"__future__", "collections", "dataclasses", "enum",
                        "typing", "numpy", "challenge_generator",
                        "hand_action_detector", "movement_detector", ""}, imported
