"""RunStats 검증 — 20회쯤 돌린 뒤 무엇이 문제인지 바로 보이는지."""
from __future__ import annotations

import pytest

from core.challenge_logger import RunStats
from core.challenge_state_machine import FailReason, State, StepResult, Status

ACTIONS = ["OPEN_PALM", "MOVE_LEFT", "FIST"]


def status_for(state, reason=None, step_index=0, retries=0):
    steps = [StepResult(a) for a in ACTIONS]
    steps[step_index].retries_used = retries
    return Status(state=state, step_index=step_index, current_action=None,
                  fail_reason=reason, steps=steps)


def passing(step_index=2):
    return status_for(State.PASS, None, step_index)


def failing(reason, step_index=0, retries=0):
    return status_for(State.FAIL, reason, step_index, retries)


def test_empty_stats_are_safe():
    stats = RunStats()
    assert stats.attempts == 0
    assert stats.pass_rate == 0.0
    assert stats.summary_lines() == ["run: 0/0 pass (0%)"]
    assert "실패 없음" in stats.console_report()


def test_counts_attempts_and_passes():
    stats = RunStats()
    stats.record(passing(), 3000.0)
    stats.record(failing(FailReason.WRONG_SHAPE), 2500.0)
    assert stats.attempts == 2
    assert stats.passes == 1
    assert stats.failures == 1
    assert stats.pass_rate == pytest.approx(0.5)


def test_groups_by_reason():
    stats = RunStats()
    for _ in range(3):
        stats.record(failing(FailReason.WRONG_SHAPE), 1000.0)
    stats.record(failing(FailReason.HAND_LOST), 1000.0)
    assert stats.reasons["WRONG_SHAPE"] == 3
    assert stats.reasons["HAND_LOST"] == 1


def test_ranked_puts_the_worst_reason_first():
    stats = RunStats()
    stats.record(failing(FailReason.HAND_LOST), 1000.0)
    for _ in range(4):
        stats.record(failing(FailReason.ACTION_TIMEOUT), 1000.0)
    assert stats.ranked()[0][0] == "ACTION_TIMEOUT"
    assert stats.ranked()[0][1] == 4


def test_tracks_which_step_failed():
    """같은 사유라도 1단계와 3단계에서 막히는 건 원인이 다르다."""
    stats = RunStats()
    stats.record(failing(FailReason.WRONG_SHAPE, step_index=0), 1000.0)
    stats.record(failing(FailReason.WRONG_SHAPE, step_index=0), 1000.0)
    stats.record(failing(FailReason.WRONG_SHAPE, step_index=2), 1000.0)
    steps = stats.reason_steps["WRONG_SHAPE"]
    assert steps[1] == 2
    assert steps[3] == 1


def test_passes_do_not_add_a_reason():
    stats = RunStats()
    stats.record(passing(), 3000.0)
    assert stats.reasons == {}
    assert stats.ranked() == []


def test_counts_retries_across_steps():
    stats = RunStats()
    stats.record(failing(FailReason.WRONG_SHAPE, step_index=0, retries=1), 1000.0)
    stats.record(passing(), 3000.0)
    stats.record(failing(FailReason.HAND_LOST, step_index=1, retries=2), 1000.0)
    assert stats.retries == 3


def test_median_duration():
    stats = RunStats()
    for ms in (1000.0, 3000.0, 2000.0):
        stats.record(passing(), ms)
    assert stats.median_ms == pytest.approx(2000.0)


def test_median_of_even_count_averages_the_middle():
    stats = RunStats()
    for ms in (1000.0, 2000.0, 3000.0, 4000.0):
        stats.record(passing(), ms)
    assert stats.median_ms == pytest.approx(2500.0)


def test_summary_lines_lead_with_the_pass_rate():
    stats = RunStats()
    for _ in range(3):
        stats.record(passing(), 3000.0)
    for _ in range(7):
        stats.record(failing(FailReason.WRONG_SHAPE), 1000.0)
    assert stats.summary_lines()[0] == "run: 3/10 pass (30%)"


def test_summary_lines_are_ascii_for_opencv():
    """OpenCV는 한글을 못 그린다. 화면용 줄에 한글이 섞이면 네모로 나온다."""
    stats = RunStats()
    stats.record(failing(FailReason.TRACKING_UNSTABLE, step_index=1), 1000.0)
    stats.record(passing(), 3000.0)
    for line in stats.summary_lines():
        line.encode("ascii")


def test_summary_lines_are_capped():
    stats = RunStats()
    for reason in FailReason:
        stats.record(failing(reason), 1000.0)
    assert len(stats.summary_lines(limit=3)) == 4  # 머리줄 + 3


def test_console_report_lists_every_reason_with_steps():
    stats = RunStats()
    stats.record(failing(FailReason.WRONG_ORDER, step_index=1), 1200.0)
    stats.record(failing(FailReason.HAND_LOST, step_index=2), 900.0)
    report = stats.console_report()
    assert "WRONG_ORDER" in report
    assert "HAND_LOST" in report
    assert "2단계 1회" in report
    assert "3단계 1회" in report


@pytest.mark.parametrize("reason", list(FailReason))
def test_every_fail_reason_is_countable(reason):
    stats = RunStats()
    stats.record(failing(reason), 1000.0)
    assert stats.reasons[reason.value] == 1
    assert reason.value in stats.console_report()
