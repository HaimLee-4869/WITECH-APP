"""Challenge 세션 결과 저장 (SPEC 4.10).

성공·실패 영상을 모두 남긴다. 실패 영상이 규칙 개선의 재료다.
"""
from __future__ import annotations

import csv
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np

from .challenge_generator import Challenge
from .challenge_state_machine import RULE_VERSION, FailReason, State, Status

@dataclass
class RunStats:
    """이번 실행에서 시도한 결과를 사유별로 모은다.

    20회쯤 돌린 뒤 무엇이 문제인지 바로 보려는 용도다. 사유뿐 아니라 몇 단계에서
    막혔는지도 같이 센다. 같은 WRONG_SHAPE라도 1단계에서 막히는 것과 3단계에서
    막히는 것은 원인이 다르다.
    """
    attempts: int = 0
    passes: int = 0
    reasons: Counter = field(default_factory=Counter)
    reason_steps: dict = field(default_factory=dict)
    retries: int = 0
    durations: list = field(default_factory=list)

    @property
    def failures(self) -> int:
        return self.attempts - self.passes

    @property
    def pass_rate(self) -> float:
        return self.passes / self.attempts if self.attempts else 0.0

    @property
    def median_ms(self) -> float:
        if not self.durations:
            return float("nan")
        ordered = sorted(self.durations)
        middle = len(ordered) // 2
        if len(ordered) % 2:
            return ordered[middle]
        return (ordered[middle - 1] + ordered[middle]) / 2.0

    def record(self, status: Status, elapsed_ms: float) -> None:
        self.attempts += 1
        self.durations.append(float(elapsed_ms))
        self.retries += sum(step.retries_used for step in status.steps)
        if status.state is State.PASS:
            self.passes += 1
            return
        reason = status.fail_reason
        key = reason.value if reason else "UNKNOWN"
        self.reasons[key] += 1
        # 사람이 세는 단계 번호는 1부터
        step_no = min(status.step_index + 1, len(status.steps)) if status.steps else 0
        self.reason_steps.setdefault(key, Counter())[step_no] += 1

    def ranked(self) -> list[tuple[str, int, Counter]]:
        """많이 나온 사유부터 (사유, 횟수, 단계별 분포)."""
        return [(key, count, self.reason_steps.get(key, Counter()))
                for key, count in self.reasons.most_common()]

    def headline(self) -> str:
        return (f"이번 실행 {self.attempts}회 중 통과 {self.passes}회 "
                f"({self.pass_rate * 100:.0f}%)")

    def summary_lines(self, limit: int = 6) -> list[str]:
        """화면에 띄울 짧은 요약 (영문/숫자만 — OpenCV가 한글을 못 그린다)."""
        lines = [f"run: {self.passes}/{self.attempts} pass "
                 f"({self.pass_rate * 100:.0f}%)"]
        for key, count, steps in self.ranked()[:limit]:
            spread = " ".join(f"s{step}:{n}" for step, n in sorted(steps.items()))
            lines.append(f"{key:<18}{count:>3}  {spread}")
        return lines

    def console_report(self) -> str:
        """콘솔에 출력할 표."""
        rows = [self.headline()]
        if self.attempts:
            rows.append(f"  중앙 소요시간 {self.median_ms:.0f}ms, "
                        f"재시도 사용 {self.retries}회")
        if not self.reasons:
            rows.append("  실패 없음")
            return "\n".join(rows)
        rows.append(f"  {'실패 사유':<20}{'횟수':>5}   단계별")
        for key, count, steps in self.ranked():
            spread = ", ".join(f"{step}단계 {n}회" for step, n in sorted(steps.items()))
            rows.append(f"  {key:<20}{count:>5}   {spread}")
        return "\n".join(rows)


CSV_FIELDS = [
    # 판정 규칙이 바뀌면 rule_version이 올라간다. 변경 전후를 갈라서 비교할 때 쓴다.
    "rule_version", "escape_frames",
    "challenge_id", "participant", "started_at", "elapsed_ms", "result",
    "fail_reason", "action_1", "action_2", "action_3",
    "passed_1", "passed_2", "passed_3",
    "elapsed_1_ms", "elapsed_2_ms", "elapsed_3_ms",
    "retries_1", "retries_2", "retries_3",
    "frames", "detected_frames", "video_path", "landmark_path",
    # 이동 단계 진단. 어느 관문이 병목인지 나중에 집계하려고 남긴다.
    "move_action", "move_step", "move_passed", "move_windows",
    "move_disp_pass", "move_axis_pass",
    "move_max_disp_ratio", "move_med_disp_ratio",
    "move_max_axis_ratio", "move_med_axis_ratio", "move_dominant_axis",
    # 임계값이 바뀌어도 과거 기록을 해석할 수 있도록 당시 값을 같이 적는다.
    "move_min_disp_threshold", "move_axis_threshold", "move_window_ms",
]


@dataclass
class SessionRecorder:
    """한 번의 Challenge 동안 프레임과 결과를 모은다."""
    challenge: Challenge
    participant: str
    started_at: str
    session_dir: Path
    landmarks: list = field(default_factory=list)
    valid: list = field(default_factory=list)
    scores: list = field(default_factory=list)
    handedness: list = field(default_factory=list)
    timestamps: list = field(default_factory=list)

    def add_frame(self, landmarks: Optional[np.ndarray], detected: bool,
                  score: float, hand_label: str, timestamp_ms: float) -> None:
        empty = np.full((21, 3), np.nan, dtype=np.float32)
        self.landmarks.append(empty if landmarks is None
                              else np.asarray(landmarks, dtype=np.float32))
        self.valid.append(bool(detected))
        self.scores.append(float(score))
        self.handedness.append(str(hand_label))
        self.timestamps.append(float(timestamp_ms))

    @property
    def landmark_path(self) -> Path:
        return self.session_dir / f"{self.challenge.challenge_id}.npz"

    @property
    def video_path(self) -> Path:
        return self.session_dir / f"{self.challenge.challenge_id}.mp4"

    def save_landmarks(self, fps: float, width: int, height: int) -> Path:
        self.session_dir.mkdir(parents=True, exist_ok=True)
        n = len(self.landmarks)
        np.savez_compressed(
            self.landmark_path,
            landmarks=(np.stack(self.landmarks) if n
                       else np.zeros((0, 21, 3), dtype=np.float32)),
            valid_mask=np.array(self.valid, dtype=bool),
            detection_score=np.array(self.scores, dtype=np.float32),
            handedness=np.array(self.handedness, dtype="<U8"),
            timestamp_ms=np.array(self.timestamps, dtype=np.float64),
            fps=np.float32(fps), width=np.int32(width), height=np.int32(height),
            challenge_id=self.challenge.challenge_id,
            participant=self.participant,
            actions=np.array(self.challenge.actions, dtype="<U16"),
            created_at=self.challenge.created_at,
        )
        return self.landmark_path


def _movement_columns(status: Status, config: Optional[dict]) -> dict:
    """이동 단계의 관문별 통과 횟수와 최대치."""
    blank = {key: "" for key in (
        "move_action", "move_step", "move_passed", "move_windows",
        "move_disp_pass", "move_axis_pass",
        "move_max_disp_ratio", "move_med_disp_ratio",
        "move_max_axis_ratio", "move_med_axis_ratio", "move_dominant_axis",
        "move_min_disp_threshold", "move_axis_threshold", "move_window_ms")}

    movement = (config or {}).get("movement", {})
    blank["move_min_disp_threshold"] = movement.get("min_displacement_ratio", "")
    blank["move_axis_threshold"] = movement.get("axis_dominance_ratio", "")
    blank["move_window_ms"] = movement.get("window_ms", "")

    for index, step in enumerate(status.steps, start=1):
        if step.move is None:
            continue
        stats = step.move
        blank.update({
            "move_action": step.action,
            "move_step": index,
            "move_passed": int(step.passed),
            "move_windows": stats.windows,
            "move_disp_pass": stats.displacement_pass,
            "move_axis_pass": stats.axis_pass,
            "move_max_disp_ratio": _fmt(stats.max_displacement_ratio),
            "move_med_disp_ratio": _fmt(stats.median_displacement_ratio),
            "move_max_axis_ratio": _fmt(stats.max_axis_ratio),
            "move_med_axis_ratio": _fmt(stats.median_axis_ratio),
            "move_dominant_axis": stats.dominant_axis,
        })
        break
    return blank


def _fmt(value: float) -> str:
    if value is None or not np.isfinite(value):
        return ""
    return f"{value:.4f}"


# ---------------------------------------------------------------- 실행 로그 (텍스트)

def threshold_report_lines(config: dict, shape_detector, movement_detector,
                           machine) -> list[str]:
    """지금 **실제로 적용된** 임계값. config 파일이 아니라 판정기 객체에서 읽는다.

    config를 고쳤는데 판정기가 옛 값을 쓰는 사고를 실행 시작 때 바로 잡으려는 것이다.
    """
    move = config.get("movement", {})
    gate = shape_detector.fist_max_tip_wrist_ratio
    lines = [
        f"rule_version            {RULE_VERSION}",
        f"timing                  단계 {machine.per_action_timeout_ms:.0f}ms / "
        f"전체 {machine.total_timeout_ms:.0f}ms / 재시도 {machine.max_retries}회",
        f"shape                   others {shape_detector.other_threshold:.1f}° / "
        f"thumb {shape_detector.thumb_threshold:.1f}° ({shape_detector.angle_space})",
        f"fist_max_tip_wrist      {'꺼짐(null)' if gate is None else f'{gate:.3f}'}",
        f"frame_reference_fps     {machine.reference_fps:.2f} "
        f"(프레임 수 값은 이 fps 기준 시간으로 판정)",
        f"shape_hold_frames       {machine.hold_frames} = 첫~끝 {machine._hold.required_ms:.0f}ms 이상",
        f"escape_frames           {machine.escape_frames} = 첫~끝 {machine._escape.required_ms:.0f}ms 이상",
        f"shape_confidence_min    {machine.shape_confidence_min:.3f}"
        f"{' (null -> 게이트 없음)' if config.get('shape_confidence_min') is None else ''}",
        f"move window             {movement_detector.window_ms:.0f}ms "
        f"(기준 {machine._window.window_frames}프레임, 첫~끝 {machine._window.required_ms:.0f}ms 이상이면 판정)",
        f"move min_displacement   {movement_detector.min_displacement_ratio:.3f}",
        f"move axis_dominance     {movement_detector.axis_dominance_ratio:.3f}",
        f"move direction_map      {move.get('direction_map')}",
        f"coordinate_frame        {movement_detector.coordinate_frame}",
        f"tracking                max_lost {machine.max_lost_frames}프레임"
        f"(연속 {machine._lost.required_ms:.0f}ms 넘으면 실패) / "
        f"min_score {machine.min_detection_score:.3f}",
    ]
    unresolved = config.get("_unresolved") or {}
    if unresolved:
        lines.append(f"_unresolved             {', '.join(unresolved)}")
    return lines


def attempt_report_lines(recorder: SessionRecorder, status: Status,
                         elapsed_ms: float, attempt_no: int) -> list[str]:
    """시도 1회의 상세 기록. 콘솔에는 요약만 띄우고 이 내용은 파일에 남긴다."""
    result = "PASS" if status.state is State.PASS else "FAIL"
    reason = status.fail_reason.value if status.fail_reason else "-"
    lines = [
        f"[시도 {attempt_no}] {result}  사유={reason}  총 {elapsed_ms:.0f}ms  "
        f"challenge={recorder.challenge.challenge_id}  참가자={recorder.participant}",
        f"  요청 동작: {' -> '.join(recorder.challenge.actions)}",
        f"  프레임 {len(recorder.valid)} / 손 검출 {int(sum(recorder.valid))}",
    ]
    for index, step in enumerate(status.steps, start=1):
        reached = index - 1 <= status.step_index
        if step.passed:
            outcome = "통과"
        elif step.fail_reason is not None:
            outcome = f"실패({step.fail_reason.value})"
        else:
            outcome = "미도달" if not reached else "진행 중 종료"
        lines.append(f"  {index}단계 {step.action:<12} {outcome:<22} "
                     f"{step.elapsed_ms:7.0f}ms  재시도 {step.retries_used}")
        if step.move is not None:
            m = step.move
            lines.append(
                f"      이동 진단: 윈도우 {m.windows}, 변위 관문 통과 {m.displacement_pass}, "
                f"축비 관문 통과 {m.axis_pass}, 주축 {m.dominant_axis or '-'}")
            lines.append(
                f"      변위비 최대 {_fmt(m.max_displacement_ratio) or '-'} / "
                f"중앙 {_fmt(m.median_displacement_ratio) or '-'}   "
                f"축비 최대 {_fmt(m.max_axis_ratio) or '-'} / "
                f"중앙 {_fmt(m.median_axis_ratio) or '-'}")
    return lines


def append_result(csv_path: Path, recorder: SessionRecorder, status: Status,
                  elapsed_ms: float, config: Optional[dict] = None) -> None:
    """결과 CSV에 한 줄 추가한다. 파일이 없으면 헤더부터 쓴다."""
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not csv_path.exists()

    steps = list(status.steps)
    while len(steps) < 3:
        steps.append(None)

    fail: Optional[FailReason] = status.fail_reason
    row = {
        "rule_version": RULE_VERSION,
        "escape_frames": (config or {}).get("escape_frames", ""),
        "challenge_id": recorder.challenge.challenge_id,
        "participant": recorder.participant,
        "started_at": recorder.started_at,
        "elapsed_ms": round(elapsed_ms, 1),
        "result": "PASS" if status.state is State.PASS else "FAIL",
        "fail_reason": fail.value if fail else "",
        "frames": len(recorder.valid),
        "detected_frames": int(sum(recorder.valid)),
        "video_path": str(recorder.video_path),
        "landmark_path": str(recorder.landmark_path),
    }
    for i, step in enumerate(steps[:3], start=1):
        row[f"action_{i}"] = step.action if step else ""
        row[f"passed_{i}"] = int(step.passed) if step else ""
        row[f"elapsed_{i}_ms"] = round(step.elapsed_ms, 1) if step else ""
        row[f"retries_{i}"] = step.retries_used if step else ""
    row.update(_movement_columns(status, config))

    with open(csv_path, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if is_new:
            writer.writeheader()
        writer.writerow(row)
