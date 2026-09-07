"""이동 판정 계측 검증 (MoveProbe / MoveStats).

임계값을 바꾸기 전에 어느 관문이 막고 있는지 볼 수 있어야 한다.
"""
from __future__ import annotations

import numpy as np
import pytest

from core.challenge_state_machine import MoveProbe, MoveStats

READY = {"frames_filled": 15, "frames_needed": 15}


def probe(reason, disp=0.5, axis_ratio=6.0, axis="x", **kwargs):
    return MoveProbe(displacement_ratio=disp, axis_ratio=axis_ratio, axis=axis,
                     reason=reason, **{**READY, **kwargs})


def test_window_not_ready_while_filling():
    assert not MoveProbe(frames_filled=7, frames_needed=15).window_ready
    assert MoveProbe(frames_filled=15, frames_needed=15).window_ready


@pytest.mark.parametrize("reason,disp_ok,axis_ok", [
    ("NO_TRACK", False, False),
    ("TOO_SMALL", False, False),
    ("NOT_AXIS_DOMINANT", True, False),
    ("UNMAPPED_AXIS", True, True),
    ("OK", True, True),
])
def test_gate_flags_follow_the_reason(reason, disp_ok, axis_ok):
    """어느 단계에서 멈췄는지가 reason 하나로 결정된다."""
    p = probe(reason)
    assert p.displacement_ok is disp_ok
    assert p.axis_ok is axis_ok


def test_stats_ignore_windows_that_never_filled():
    stats = MoveStats()
    stats.record(MoveProbe(frames_filled=3, frames_needed=15))
    assert stats.windows == 0


def test_stats_ignore_untracked_windows():
    stats = MoveStats()
    stats.record(probe("NO_TRACK", disp=float("nan"), axis_ratio=float("nan")))
    assert stats.windows == 0


def test_stats_count_each_gate_separately():
    stats = MoveStats()
    for _ in range(5):
        stats.record(probe("TOO_SMALL", disp=0.05))
    for _ in range(3):
        stats.record(probe("NOT_AXIS_DOMINANT", disp=0.4, axis_ratio=2.0))
    for _ in range(2):
        stats.record(probe("OK", disp=0.6, axis_ratio=9.0))
    assert stats.windows == 10
    assert stats.displacement_pass == 5
    assert stats.axis_pass == 2


def test_max_and_median_displacement():
    stats = MoveStats()
    for value in (0.1, 0.2, 0.9):
        stats.record(probe("OK", disp=value))
    assert stats.max_displacement_ratio == pytest.approx(0.9)
    assert stats.median_displacement_ratio == pytest.approx(0.2)


def test_axis_ratio_only_counts_windows_past_the_first_gate():
    """손이 거의 안 움직인 윈도우의 주축비는 잡음이라 섞으면 안 된다."""
    stats = MoveStats()
    stats.record(probe("TOO_SMALL", disp=0.01, axis_ratio=99.0))
    stats.record(probe("OK", disp=0.6, axis_ratio=5.0))
    assert stats.max_axis_ratio == pytest.approx(5.0)
    assert stats.median_axis_ratio == pytest.approx(5.0)


def test_infinite_axis_ratio_is_not_recorded():
    """부축 변위가 0이면 주축비가 inf다. 통계에 넣으면 전부 오염된다."""
    stats = MoveStats()
    stats.record(probe("OK", disp=0.5, axis_ratio=float("inf")))
    stats.record(probe("OK", disp=0.5, axis_ratio=4.0))
    assert stats.max_axis_ratio == pytest.approx(4.0)
    assert np.isfinite(stats.median_axis_ratio)


def test_empty_stats_report_nan_not_zero():
    stats = MoveStats()
    for value in (stats.max_displacement_ratio, stats.median_displacement_ratio,
                  stats.max_axis_ratio, stats.median_axis_ratio):
        assert np.isnan(value)


def test_dominant_axis_is_the_most_observed():
    stats = MoveStats()
    for _ in range(4):
        stats.record(probe("OK", axis="y"))
    for _ in range(2):
        stats.record(probe("OK", axis="x"))
    assert stats.dominant_axis == "y"


def test_dominant_axis_is_blank_without_data():
    assert MoveStats().dominant_axis == ""
