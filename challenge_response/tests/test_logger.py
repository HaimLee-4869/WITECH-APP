"""challenge_logger.py 검증 (SPEC 4.10).

성공·실패 영상을 모두 남겨야 하므로, 실패한 세션도 빠짐없이 기록되는지 본다.
"""
from __future__ import annotations

import csv

import numpy as np
import pytest

from core.challenge_generator import Challenge
from core.challenge_logger import CSV_FIELDS, SessionRecorder, append_result
from core.challenge_state_machine import FailReason, State, StepResult, Status


@pytest.fixture
def recorder(tmp_path):
    challenge = Challenge(challenge_id="abc-123",
                          actions=["OPEN_PALM", "MOVE_LEFT", "FIST"],
                          created_at="2026-09-07T00:00:00+00:00")
    return SessionRecorder(challenge=challenge, participant="P01",
                           started_at="2026-09-07T00:00:00+00:00",
                           session_dir=tmp_path)


def pass_status(challenge):
    steps = [StepResult(a, passed=True, elapsed_ms=100.0 * (i + 1))
             for i, a in enumerate(challenge.actions)]
    return Status(state=State.PASS, step_index=3, current_action=None, steps=steps)


def fail_status(challenge, reason=FailReason.ACTION_TIMEOUT):
    steps = [StepResult(challenge.actions[0], passed=True, elapsed_ms=120.0),
             StepResult(challenge.actions[1], passed=False, fail_reason=reason,
                        elapsed_ms=2500.0, retries_used=1),
             StepResult(challenge.actions[2])]
    return Status(state=State.FAIL, step_index=1, current_action=challenge.actions[1],
                  fail_reason=reason, steps=steps)


def read_rows(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def test_missing_frames_are_kept_as_invalid(recorder):
    recorder.add_frame(np.zeros((21, 3)), True, 0.9, "Right", 0.0)
    recorder.add_frame(None, False, float("nan"), "", 33.0)
    assert recorder.valid == [True, False]
    assert len(recorder.landmarks) == 2
    assert np.isnan(recorder.landmarks[1]).all()


def test_landmarks_are_saved_with_metadata(recorder):
    for i in range(4):
        recorder.add_frame(np.full((21, 3), float(i)), True, 0.9, "Right", i * 33.0)
    path = recorder.save_landmarks(fps=30.0, width=640, height=480)
    data = np.load(path, allow_pickle=False)
    assert data["landmarks"].shape == (4, 21, 3)
    assert data["valid_mask"].shape == (4,)
    assert str(data["challenge_id"]) == "abc-123"
    assert list(data["actions"]) == ["OPEN_PALM", "MOVE_LEFT", "FIST"]
    assert int(data["width"]) == 640


def test_empty_session_still_saves(recorder):
    path = recorder.save_landmarks(fps=30.0, width=640, height=480)
    assert np.load(path, allow_pickle=False)["landmarks"].shape == (0, 21, 3)


def test_pass_row_records_every_step(recorder, tmp_path):
    recorder.add_frame(np.zeros((21, 3)), True, 0.9, "Right", 0.0)
    csv_path = tmp_path / "results.csv"
    append_result(csv_path, recorder, pass_status(recorder.challenge), 3000.0)
    row = read_rows(csv_path)[0]
    assert row["result"] == "PASS"
    assert row["fail_reason"] == ""
    assert [row["action_1"], row["action_2"], row["action_3"]] == \
        ["OPEN_PALM", "MOVE_LEFT", "FIST"]
    assert [row["passed_1"], row["passed_2"], row["passed_3"]] == ["1", "1", "1"]


def test_fail_row_records_structured_reason(recorder, tmp_path):
    csv_path = tmp_path / "results.csv"
    append_result(csv_path, recorder, fail_status(recorder.challenge), 5000.0)
    row = read_rows(csv_path)[0]
    assert row["result"] == "FAIL"
    assert row["fail_reason"] == FailReason.ACTION_TIMEOUT.value
    assert row["passed_2"] == "0"
    assert row["retries_2"] == "1"


@pytest.mark.parametrize("reason", list(FailReason))
def test_every_fail_reason_round_trips(recorder, tmp_path, reason):
    csv_path = tmp_path / f"{reason.name}.csv"
    append_result(csv_path, recorder, fail_status(recorder.challenge, reason), 1000.0)
    assert read_rows(csv_path)[0]["fail_reason"] == reason.value


def test_results_accumulate_with_one_header(recorder, tmp_path):
    csv_path = tmp_path / "results.csv"
    append_result(csv_path, recorder, pass_status(recorder.challenge), 3000.0)
    append_result(csv_path, recorder, fail_status(recorder.challenge), 5000.0)
    rows = read_rows(csv_path)
    assert len(rows) == 2
    assert [r["result"] for r in rows] == ["PASS", "FAIL"]
    assert list(rows[0]) == CSV_FIELDS


def test_row_points_at_the_saved_media(recorder, tmp_path):
    csv_path = tmp_path / "results.csv"
    append_result(csv_path, recorder, pass_status(recorder.challenge), 3000.0)
    row = read_rows(csv_path)[0]
    assert row["landmark_path"].endswith("abc-123.npz")
    assert row["video_path"].endswith("abc-123.mp4")


def test_frame_counts_are_recorded(recorder, tmp_path):
    for detected in (True, True, False):
        recorder.add_frame(np.zeros((21, 3)) if detected else None,
                           detected, 0.9, "Right", 0.0)
    csv_path = tmp_path / "results.csv"
    append_result(csv_path, recorder, pass_status(recorder.challenge), 3000.0)
    row = read_rows(csv_path)[0]
    assert row["frames"] == "3"
    assert row["detected_frames"] == "2"
