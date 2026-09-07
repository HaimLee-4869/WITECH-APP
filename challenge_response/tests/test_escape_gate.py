"""단계 전환 시 이전 손 모양 이탈 관문 검증.

MOVE_*는 손바닥을 편 채로 수행한다. 이동이 끝난 시점의 손은 이미 OPEN_PALM이라,
다음 단계가 OPEN_PALM이면 사용자가 아무것도 안 해도 통과된다. 공격자도 손바닥
편 영상 하나로 그 단계를 넘길 수 있으므로 UX가 아니라 보안 문제다.
"""
from __future__ import annotations

import numpy as np
import pytest

from core.challenge_generator import Challenge
from core.challenge_state_machine import (RULE_VERSION, ChallengeStateMachine,
                                          Observation, State)
from core.hand_action_detector import SHAPE_PATTERNS, HandActionDetector
from core.movement_detector import MovementDetector
from tests.synth import make_hand, make_pattern_hand

EXTENDED_ANGLE = 175.0
CURLED_ANGLE = 60.0
FPS = 30.0
FRAME_MS = 1000.0 / FPS
ESCAPE = 4

CONFIG = {
    "angle_space": "world",
    "finger_extended_angle": {"thumb": 150.0, "others": 160.0},
    "shape_confidence_margin_deg": 10.0,
    "shape_confidence_min": 0.5,
    "shape_hold_frames": 5,
    "escape_frames": ESCAPE,
    "coordinate_frame": "raw",
    "movement": {
        "window_ms": 400,
        "min_displacement_ratio": 1.2,
        "axis_dominance_ratio": 2.0,
        "max_duration_ms": 2500,
        "direction_map": {"MOVE_LEFT": ["x", -1], "MOVE_RIGHT": ["x", 1],
                          "MOVE_UP": ["y", -1], "MOVE_DOWN": ["y", 1]},
    },
    "timing": {"per_action_timeout_ms": 2000, "total_timeout_ms": 20000,
               "max_retries": 0},
    "tracking": {"max_lost_frames": 5, "min_detection_score": 0.5},
}


def shape_hand(label):
    pattern = dict(zip(("index", "middle", "ring", "pinky"), SHAPE_PATTERNS[label]))
    return make_pattern_hand({**pattern, "thumb": True}, EXTENDED_ANGLE, CURLED_ANGLE)


def build(actions, config=CONFIG):
    challenge = Challenge(challenge_id="t", actions=list(actions), created_at="now")
    return ChallengeStateMachine(config, challenge, HandActionDetector(config),
                                 MovementDetector(config), FPS)


class Clock:
    """프레임을 흘려보내며 시각을 관리한다."""

    def __init__(self, machine):
        self.machine = machine
        self.t = 0.0

    def shape(self, label, frames):
        status = None
        for _ in range(frames):
            hand = shape_hand(label)
            status = self.machine.update(
                Observation(self.t, True, 1.0, hand, hand))
            self.t += FRAME_MS
            if status.finished:
                break
        return status

    def move(self, dx, dy, frames):
        status = None
        for i in range(frames):
            hand = make_hand(180.0, center=(dx * i * 0.4, dy * i * 0.4, 0.0))
            status = self.machine.update(
                Observation(self.t, True, 1.0, hand, hand))
            self.t += FRAME_MS
            if status.finished:
                break
        return status


def move_then_shape(actions=("MOVE_RIGHT", "OPEN_PALM", "FIST")):
    machine = build(list(actions))
    clock = Clock(machine)
    window = machine.movement_detector.window_frames(FPS)
    clock.move(1.0, 0.0, window + 2)
    assert machine.steps[0].passed, "이동 단계가 먼저 통과해야 시나리오가 성립한다"
    return machine, clock


# ------------------------------------------------------------------ 핵심


def test_move_then_open_palm_does_not_pass_for_free():
    """보고된 문제 그대로: 이동 후 손을 그대로 두면 통과되면 안 된다."""
    machine, clock = move_then_shape()
    clock.shape("OPEN_PALM", CONFIG["shape_hold_frames"] * 3)
    assert not machine.steps[1].passed
    assert machine.step_index == 1


def test_escape_then_perform_passes():
    """손을 한 번 바꿨다가 다시 하면 통과한다."""
    machine, clock = move_then_shape()
    clock.shape("FIST", ESCAPE)          # 이전 모양에서 벗어남
    clock.shape("OPEN_PALM", CONFIG["shape_hold_frames"])
    assert machine.steps[1].passed


def test_gate_needs_the_full_escape_frames():
    machine, clock = move_then_shape()
    clock.shape("FIST", ESCAPE - 1)      # 한 프레임 모자람
    clock.shape("OPEN_PALM", CONFIG["shape_hold_frames"] * 2)
    assert not machine.steps[1].passed


def test_escape_streak_resets_when_returning_early():
    """잠깐 벗어났다가 되돌아오면 처음부터 다시 세야 한다."""
    machine, clock = move_then_shape()
    for _ in range(3):
        clock.shape("FIST", ESCAPE - 1)
        clock.shape("OPEN_PALM", 1)      # 되돌아옴 -> 연속 카운트 초기화
    clock.shape("OPEN_PALM", CONFIG["shape_hold_frames"] * 2)
    assert not machine.steps[1].passed


def test_timeout_does_not_run_while_gate_is_closed():
    """관문이 닫혀 있는 동안은 제한 시간을 소모하지 않는다."""
    machine, clock = move_then_shape()
    long_wait = int(CONFIG["timing"]["per_action_timeout_ms"] / FRAME_MS) * 3
    status = clock.shape("OPEN_PALM", long_wait)
    assert status.state is not State.FAIL
    clock.shape("FIST", ESCAPE)
    clock.shape("OPEN_PALM", CONFIG["shape_hold_frames"])
    assert machine.steps[1].passed


# ------------------------------------------------------------------ 범위


def test_gate_is_not_applied_to_movement_steps():
    """이동은 단계 전환 때 윈도우를 비우므로 정지한 손으로 통과할 수 없다.

    이동 앞에 관문을 걸면 편 손으로 하는 이동을 하려고 주먹을 쥐었다 펴야 한다.
    """
    machine = build(["OPEN_PALM", "MOVE_RIGHT", "FIST"])
    clock = Clock(machine)
    clock.shape("OPEN_PALM", CONFIG["shape_hold_frames"])
    assert machine.steps[0].passed
    window = machine.movement_detector.window_frames(FPS)
    clock.move(1.0, 0.0, window + 2)
    assert machine.steps[1].passed


def test_first_step_has_no_gate():
    machine = build(["OPEN_PALM", "FIST", "MOVE_RIGHT"])
    clock = Clock(machine)
    clock.shape("OPEN_PALM", CONFIG["shape_hold_frames"])
    assert machine.steps[0].passed


def test_shape_to_shape_transition_is_not_burdened():
    """다른 모양을 요청받으면 그 모양을 만드는 동안 자연히 벗어난다."""
    machine = build(["OPEN_PALM", "FIST", "MOVE_RIGHT"])
    clock = Clock(machine)
    clock.shape("OPEN_PALM", CONFIG["shape_hold_frames"])
    clock.shape("FIST", ESCAPE + CONFIG["shape_hold_frames"])
    assert machine.steps[1].passed


def test_gate_is_off_when_escape_frames_missing():
    config = {k: v for k, v in CONFIG.items() if k != "escape_frames"}
    machine = build(["MOVE_RIGHT", "OPEN_PALM", "FIST"], config)
    clock = Clock(machine)
    window = machine.movement_detector.window_frames(FPS)
    clock.move(1.0, 0.0, window + 2)
    clock.shape("OPEN_PALM", config["shape_hold_frames"])
    assert machine.steps[1].passed


# ------------------------------------------------------------------ 보고


def test_status_reports_the_shape_to_escape_from():
    machine, clock = move_then_shape()
    status = clock.shape("OPEN_PALM", 1)
    assert status.awaiting_escape
    assert status.escape_from == "OPEN_PALM"
    assert 0.0 <= status.escape_progress < 1.0


def test_escape_progress_grows_and_clears():
    machine, clock = move_then_shape()
    first = clock.shape("FIST", 1)
    second = clock.shape("FIST", 1)
    assert second.escape_progress > first.escape_progress
    done = clock.shape("FIST", ESCAPE)
    assert not done.awaiting_escape
    assert done.escape_from is None


def test_rule_version_is_declared():
    assert isinstance(RULE_VERSION, str) and RULE_VERSION
