"""negative_eval.py 검증 — 웹캠 반례를 실시간과 같은 판정 경로로 평가하는지."""
from __future__ import annotations

import numpy as np
import pytest

from core.challenge_state_machine import Observation, State
from core.negative_eval import (NegativeProbe, diagonal_request_target, evaluate_observations,
                                request_passes)
from tests.synth import make_hand
from tests.test_state_machine import CONFIG

FPS = 30.0
FRAME_MS = 1000.0 / FPS
TARGETS = {"shake_detections_max": 0, "diagonal_confirmed_max": 0.2,
           "diagonal_request_pass_basis": "chance"}


def _obs(i, center, found=True, score=1.0):
    if not found:
        return Observation(i * FRAME_MS, False)
    hand = make_hand(180.0, center=center)
    return Observation(i * FRAME_MS, True, score, hand, hand)


def _run(kind, centers, found=None):
    found = found or [True] * len(centers)
    return evaluate_observations(CONFIG, kind,
                                 [_obs(i, c, f) for i, (c, f) in enumerate(zip(centers, found))], FPS)


def test_small_shake_is_not_accepted():
    """변위 하한(1.2 손 크기)보다 작게 흔들면 이동으로 인정하지 않는다."""
    xs = 0.3 * np.sin(np.linspace(0, 12 * np.pi, 90))
    result = _run("shake", [(x, 0.0, 0.0) for x in xs])
    ok, text = result.verdict(TARGETS)
    assert ok, text
    assert result.events == []
    assert result.evaluated_windows > 0


def test_large_straight_motion_counts_as_a_shake_false_accept():
    xs = list(np.linspace(0, 4.0, 15)) + [4.0] * 30
    result = _run("shake", [(x, 0.0, 0.0) for x in xs])
    ok, _ = result.verdict(TARGETS)
    assert not ok
    assert result.first_accept_ms()["MOVE_RIGHT"] is not None


def test_diagonal_motion_is_not_confirmed():
    ts = list(np.linspace(0, 3.0, 20)) + [3.0] * 20
    result = _run("diagonal", [(t, t, 0.0) for t in ts])
    ok, text = result.verdict(TARGETS, CONFIG)
    assert ok, text
    assert result.confirmed_windows == 0


def test_exit_records_tracking_end_and_prior_motion():
    xs = list(np.linspace(0, 4.0, 15))
    centers = [(x, 0.0, 0.0) for x in xs] + [(0, 0, 0)] * 20
    found = [True] * 15 + [False] * 20
    result = _run("exit", centers, found)
    assert result.tracking_end == "HAND_LOST"
    ok, text = result.verdict(TARGETS)
    assert not ok and "이동 인정" in text


def test_frames_before_the_hand_appears_do_not_end_evaluation():
    centers = [(0, 0, 0)] * 60 + [(0.0, 0.0, 0.0)] * 30
    found = [False] * 60 + [True] * 30
    result = _run("shake", centers, found)
    assert result.tracking_end is None
    assert result.evaluated_windows > 0


def test_probe_request_never_passes_and_timeouts_are_disabled():
    probe = NegativeProbe(CONFIG, "shake", FPS)
    status = None
    for i in range(int(20000 / FRAME_MS)):          # 제한 시간(9초)보다 길게
        status = probe.update(_obs(i, (0.0, 0.0, 0.0)))
    assert status.state is State.ACTION
    assert probe.result.tracking_end is None


def test_unknown_kind_is_rejected():
    with pytest.raises(ValueError):
        NegativeProbe(CONFIG, "wave", FPS)


# ---------------------------------------------------------------- 요청 1회 기준


def _observations(centers):
    return [_obs(i, c) for i, c in enumerate(centers)]


def test_straight_move_passes_only_its_own_direction_request():
    xs = list(np.linspace(0, 4.0, 15)) + [4.0] * 30
    passes = request_passes(CONFIG, _observations([(x, 0.0, 0.0) for x in xs]), FPS)
    assert passes["MOVE_RIGHT"] is not None
    assert passes["MOVE_LEFT"] is None and passes["MOVE_UP"] is None and passes["MOVE_DOWN"] is None


def test_request_window_follows_real_timeout_and_retry():
    """손이 잡힌 뒤 단계 제한 x (1+재시도)가 지나서 움직이면 요청은 이미 실패했다."""
    timing = CONFIG["timing"]
    budget = timing["per_action_timeout_ms"] * (1 + timing["max_retries"])
    still = int((budget + 500) / FRAME_MS)
    xs = [0.0] * still + list(np.linspace(0, 4.0, 15)) + [4.0] * 30
    passes = request_passes(CONFIG, _observations([(x, 0.0, 0.0) for x in xs]), FPS)
    assert passes["MOVE_RIGHT"] is None


def test_diagonal_verdict_uses_request_rate_and_keeps_window_share_as_reference():
    ts = list(np.linspace(0, 3.0, 20)) + [3.0] * 20
    result = _run("diagonal", [(t, t, 0.0) for t in ts])
    assert result.request_passes is not None and result.request_pass_count == 0
    ok, text = result.verdict(TARGETS, CONFIG)
    assert ok and "요청 1회 통과 0/4" in text and "참고" in text


def test_chance_target_is_one_over_direction_count():
    assert diagonal_request_target(TARGETS, CONFIG) == pytest.approx(0.25)
    assert diagonal_request_target({"diagonal_request_pass_max": 0.1}, CONFIG) == pytest.approx(0.1)
