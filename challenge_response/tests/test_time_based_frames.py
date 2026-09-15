"""프레임 수 기반 값을 관측 시각으로 판정하는지 검증한다 (2026-09-16).

config의 shape_hold_frames·escape_frames·max_lost_frames와 이동 윈도우는 파일럿 영상
(frame_reference_fps, 약 30fps)에서 센 프레임 수다. 웹캠은 약 20fps로 돌았고, 프레임
수로 세면 같은 값이 1.5배 긴 시간이 됐다. 기준 fps로 들어오면 예전과 같고, 다른 fps로
들어오면 같은 '시간'이 걸려야 한다.
"""
from __future__ import annotations

import numpy as np
import pytest

from core.challenge_state_machine import FailReason, FrameSpan, State, TimeWindow
from tests.test_state_machine import CONFIG, build, obs, shape_hand

REFERENCE_FPS = 30.0
TIME_CONFIG = {**CONFIG, "frame_reference_fps": REFERENCE_FPS}


# ---------------------------------------------------------------- FrameSpan / TimeWindow


@pytest.mark.parametrize("frames", range(1, 21))
def test_frame_span_matches_frame_count_at_reference_fps(frames):
    """기준 fps에서는 N번째 프레임에서 정확히 완료된다 (타임스탬프 ±5ms 흔들림 포함)."""
    rng = np.random.default_rng(frames)
    span = FrameSpan(frames, REFERENCE_FPS)
    done_at = None
    for i in range(frames + 5):
        t = i * 1000.0 / REFERENCE_FPS + (rng.uniform(-5, 5) if i else 0.0)
        if span.hit(t):
            done_at = i + 1
            break
    assert done_at == frames


def test_frame_span_uses_time_not_frame_count_at_lower_fps():
    """20fps에서는 프레임 수가 아니라 같은 시간에서 완료된다."""
    span = FrameSpan(7, REFERENCE_FPS)            # 30fps에서 7프레임 = 첫~끝 간격 200ms
    frames = 0
    t = 0.0
    while not span.hit(t):
        frames += 1
        t += 50.0                                  # 20fps
    assert t <= 200.0 + 50.0
    assert frames + 1 < 7


def test_frame_span_progress_and_reset():
    span = FrameSpan(7, REFERENCE_FPS)
    span.hit(0.0)
    span.hit(100.0)
    assert 0.0 < span.progress < 1.0
    span.reset()
    assert not span.active and span.progress == 0.0


def test_time_window_holds_reference_frame_count_at_reference_fps():
    window = TimeWindow(18, REFERENCE_FPS)
    for i in range(40):
        window.add(i * 1000.0 / REFERENCE_FPS, np.zeros(3), 1.0)
    assert len(window) == 18
    assert window.ready


def test_time_window_is_ready_after_the_same_time_at_lower_fps():
    window = TimeWindow(18, REFERENCE_FPS)       # 30fps 18프레임 = 첫~끝 약 567ms
    t = 0.0
    while True:
        window.add(t, np.zeros(3), 1.0)
        if window.ready:
            break
        t += 50.0
    assert 500.0 <= t <= 600.0
    assert len(window) < 18


# ---------------------------------------------------------------- 상태 머신


def _feed(sm, frame_ms, frames, **kwargs):
    status = None
    for i in range(frames):
        status = sm.update(obs(i * frame_ms, **kwargs))
        if status.finished:
            break
    return status


def test_shape_hold_takes_the_same_time_at_20fps():
    at30 = build(["OPEN_PALM", "FIST", "MOVE_RIGHT"], TIME_CONFIG)
    at20 = build(["OPEN_PALM", "FIST", "MOVE_RIGHT"], TIME_CONFIG)
    _feed(at30, 1000.0 / 30.0, 60, hand=shape_hand("OPEN_PALM"))
    _feed(at20, 50.0, 40, hand=shape_hand("OPEN_PALM"))
    assert at30.steps[0].passed and at20.steps[0].passed
    assert abs(at30.steps[0].elapsed_ms - at20.steps[0].elapsed_ms) <= 50.0


def test_hand_lost_takes_the_same_time_at_20fps():
    lost_ms = {}
    for fps in (30.0, 20.0):
        sm = build(["OPEN_PALM", "FIST", "MOVE_RIGHT"], TIME_CONFIG)
        sm.update(obs(0.0, shape_hand("OPEN_PALM")))
        frame_ms = 1000.0 / fps
        t, status = 0.0, None
        while status is None or not status.finished:
            t += frame_ms
            status = sm.update(obs(t, found=False))
        assert status.fail_reason == FailReason.HAND_LOST
        lost_ms[fps] = t
    assert abs(lost_ms[30.0] - lost_ms[20.0]) <= 50.0


def test_move_step_passes_in_the_same_time_at_20fps():
    """같은 속도로 움직이면 20fps에서도 30fps와 같은 시간에 이동이 판정된다.

    프레임 수로 세면 20fps에서는 윈도우가 차는 데 1.5배 오래 걸린다.
    """
    passed_ms = {}
    for fps in (30.0, 20.0):
        sm = build(["MOVE_RIGHT", "OPEN_PALM", "FIST"], TIME_CONFIG)
        frame_ms = 1000.0 / fps
        for i in range(int(3000 / frame_ms)):
            t = i * frame_ms
            sm.update(obs(t, center=(0.006 * t, 0.0, 0.0)))   # 손 크기/초 속도가 fps와 무관
            if sm.step_index > 0:
                break
        assert sm.steps[0].passed
        passed_ms[fps] = sm.steps[0].elapsed_ms
    assert abs(passed_ms[30.0] - passed_ms[20.0]) <= 50.0


def test_reference_fps_falls_back_to_constructor_fps():
    sm = build(["OPEN_PALM", "FIST", "MOVE_RIGHT"])      # frame_reference_fps 없음
    assert sm.reference_fps == pytest.approx(30.0)
    sm2 = build(["OPEN_PALM", "FIST", "MOVE_RIGHT"], TIME_CONFIG)
    assert sm2.reference_fps == pytest.approx(REFERENCE_FPS)
    assert sm2.state == State.IDLE
