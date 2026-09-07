"""Challenge 순서·시간 관리 상태 머신 (SPEC 4.9).

    IDLE -> WAIT_HAND -> ACTION_1 -> ACTION_2 -> ACTION_3 -> PASS
                              |          |          |
                              +----------+----------+--> FAIL(사유)

Riverpod이나 UI 프레임워크에 의존하지 않는 순수 파이썬이다.
나중에 Flutter로 옮길 때 이 클래스가 명세 역할을 한다.

실패 사유는 문자열이 아니라 enum이다. 어떤 공격이 어느 단계에서 막혔는지
나중에 집계해야 하기 때문이다.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import numpy as np

from .challenge_generator import Challenge, is_move_action, is_shape_action
from .hand_action_detector import UNKNOWN, HandActionDetector
from .movement_detector import NONE, MovementDetector


class State(Enum):
    IDLE = "IDLE"
    WAIT_HAND = "WAIT_HAND"
    ACTION = "ACTION"
    PASS = "PASS"
    FAIL = "FAIL"


class FailReason(Enum):
    HAND_NOT_FOUND = "HAND_NOT_FOUND"
    WRONG_SHAPE = "WRONG_SHAPE"
    WRONG_DIRECTION = "WRONG_DIRECTION"
    WRONG_ORDER = "WRONG_ORDER"
    ACTION_TIMEOUT = "ACTION_TIMEOUT"
    TOTAL_TIMEOUT = "TOTAL_TIMEOUT"
    HAND_LOST = "HAND_LOST"
    TRACKING_UNSTABLE = "TRACKING_UNSTABLE"


# 재시도로 회복할 수 있는 사유. 손이 사라지거나 순서를 어긴 건 재시도 대상이 아니다.
RETRYABLE = frozenset({FailReason.WRONG_SHAPE, FailReason.WRONG_DIRECTION,
                       FailReason.ACTION_TIMEOUT})


@dataclass(frozen=True)
class Observation:
    """프레임 1개의 관측값. 좌표계 변환은 호출자가 끝내서 넘긴다."""
    timestamp_ms: float
    hand_found: bool
    detection_score: float = float("nan")
    angle_coords: Optional[np.ndarray] = None   # config의 angle_space 좌표
    screen_coords: Optional[np.ndarray] = None  # 종횡비 보정된 화면 좌표


@dataclass
class MoveProbe:
    """이동 판정 한 번의 중간값. 어느 관문에서 막혔는지 보려고 남긴다."""
    frames_filled: int = 0
    frames_needed: int = 0
    displacement_ratio: float = float("nan")
    axis_ratio: float = float("nan")
    axis: str = "none"
    sign: int = 0
    label: str = NONE
    reason: str = "NO_DATA"

    @property
    def window_ready(self) -> bool:
        return self.frames_needed > 0 and self.frames_filled >= self.frames_needed

    @property
    def displacement_ok(self) -> bool:
        """1번 관문(변위 크기)을 통과했는지."""
        return self.reason in ("NOT_AXIS_DOMINANT", "UNMAPPED_AXIS", "OK")

    @property
    def axis_ok(self) -> bool:
        """2번 관문(주축 지배력)을 통과했는지."""
        return self.reason in ("UNMAPPED_AXIS", "OK")


@dataclass
class MoveStats:
    """한 이동 단계 동안 관문별로 몇 번 통과했는지, 값은 어디까지 갔는지.

    최대치와 중앙값을 같이 남긴다. 최대 주축비는 부축 변위가 0에 가까운 윈도우
    하나에 좌우돼 분포 비교에 못 쓰기 때문이다.
    """
    windows: int = 0
    displacement_pass: int = 0
    axis_pass: int = 0
    axis_counts: dict = field(default_factory=dict)
    displacements: list = field(default_factory=list)
    # 주축비는 변위 관문을 통과한 윈도우에서만 의미가 있다. 손이 거의 안 움직인
    # 윈도우의 주축비는 잡음이다.
    axis_ratios: list = field(default_factory=list)

    def record(self, probe: MoveProbe) -> None:
        if not probe.window_ready or probe.reason == "NO_TRACK":
            return
        self.windows += 1
        self.displacement_pass += int(probe.displacement_ok)
        self.axis_pass += int(probe.axis_ok)
        if np.isfinite(probe.displacement_ratio):
            self.displacements.append(float(probe.displacement_ratio))
        if probe.displacement_ok and np.isfinite(probe.axis_ratio):
            self.axis_ratios.append(float(probe.axis_ratio))
        if probe.axis in ("x", "y"):
            self.axis_counts[probe.axis] = self.axis_counts.get(probe.axis, 0) + 1

    @staticmethod
    def _stat(values: list, function) -> float:
        return float(function(values)) if values else float("nan")

    @property
    def max_displacement_ratio(self) -> float:
        return self._stat(self.displacements, np.max)

    @property
    def median_displacement_ratio(self) -> float:
        return self._stat(self.displacements, np.median)

    @property
    def max_axis_ratio(self) -> float:
        return self._stat(self.axis_ratios, np.max)

    @property
    def median_axis_ratio(self) -> float:
        return self._stat(self.axis_ratios, np.median)

    @property
    def dominant_axis(self) -> str:
        if not self.axis_counts:
            return ""
        return max(self.axis_counts, key=self.axis_counts.get)


@dataclass
class StepResult:
    action: str
    passed: bool = False
    fail_reason: Optional[FailReason] = None
    elapsed_ms: float = 0.0
    retries_used: int = 0
    move: Optional[MoveStats] = None


@dataclass
class Status:
    """update()가 돌려주는 현재 상태 스냅샷."""
    state: State
    step_index: int
    current_action: Optional[str]
    detected_shape: str = UNKNOWN
    detected_move: str = NONE
    shape_confidence: float = 0.0
    hold_progress: float = 0.0        # 0.0~1.0
    remaining_ms: float = 0.0
    fail_reason: Optional[FailReason] = None
    steps: list[StepResult] = field(default_factory=list)
    move_probe: Optional[MoveProbe] = None   # 이동 단계에서만 채워진다

    @property
    def finished(self) -> bool:
        return self.state in (State.PASS, State.FAIL)


class ChallengeStateMachine:
    def __init__(self, config: dict, challenge: Challenge,
                 shape_detector: HandActionDetector,
                 movement_detector: MovementDetector,
                 fps: float):
        self.config = config
        self.challenge = challenge
        self.shape_detector = shape_detector
        self.movement_detector = movement_detector
        self.fps = float(fps)

        timing = config["timing"]
        self.per_action_timeout_ms = float(timing["per_action_timeout_ms"])
        self.total_timeout_ms = float(timing["total_timeout_ms"])
        self.max_retries = int(timing["max_retries"])

        tracking = config["tracking"]
        self.max_lost_frames = int(tracking["max_lost_frames"])
        self.min_detection_score = float(tracking["min_detection_score"])

        self.hold_frames = int(config["shape_hold_frames"])
        # null이면 신뢰도 게이트를 끈다. 04에서 '신뢰도로는 더 못 거른다'가 측정으로
        # 확인된 경우이므로, 임의의 값을 넣는 대신 조건을 걸지 않는다.
        confidence_min = config.get("shape_confidence_min")
        self.shape_confidence_min = (float(confidence_min)
                                     if confidence_min is not None else 0.0)

        window = self.movement_detector.window_frames(self.fps)
        self._centers: deque = deque(maxlen=window)
        self._scales: deque = deque(maxlen=window)

        self.state = State.IDLE
        self.step_index = 0
        self.fail_reason: Optional[FailReason] = None
        self.steps: list[StepResult] = [StepResult(a) for a in challenge.actions]

        self._started_ms: Optional[float] = None
        self._step_started_ms: Optional[float] = None
        self._now_ms: float = 0.0
        self._hold_streak = 0
        self._wrong_label: Optional[str] = None
        self._wrong_streak = 0
        # 제한 시간 동안 사용자가 '확실히' 수행한 다른 동작. 타임아웃 때 사유를 정한다.
        self._sustained_wrong: Optional[str] = None
        self._lost_streak = 0
        self._unstable_streak = 0
        self._retries_left = self.max_retries

    # ------------------------------------------------------------ 진행

    @property
    def current_action(self) -> Optional[str]:
        if self.step_index < len(self.challenge.actions):
            return self.challenge.actions[self.step_index]
        return None

    def start(self, timestamp_ms: float) -> None:
        self.state = State.WAIT_HAND
        self._started_ms = timestamp_ms
        self._step_started_ms = timestamp_ms
        self._now_ms = timestamp_ms

    def update(self, obs: Observation) -> Status:
        if self.state in (State.PASS, State.FAIL):
            return self._status()
        if self.state == State.IDLE:
            self.start(obs.timestamp_ms)
        self._now_ms = obs.timestamp_ms

        if obs.timestamp_ms - self._started_ms > self.total_timeout_ms:
            return self._fail(FailReason.TOTAL_TIMEOUT, obs.timestamp_ms)

        tracking_status = self._update_tracking(obs)
        if tracking_status is not None:
            return tracking_status

        if self.state == State.WAIT_HAND:
            self.state = State.ACTION
            self._step_started_ms = obs.timestamp_ms
            self._hold_streak = 0

        action = self.current_action
        if action is None:
            return self._status()

        if is_shape_action(action):
            status = self._update_shape(obs, action)
        else:
            status = self._update_move(obs, action)

        if not status.finished and self.state == State.ACTION:
            elapsed = obs.timestamp_ms - self._step_started_ms
            if elapsed > self.per_action_timeout_ms:
                return self._fail_step(self._timeout_reason(action), obs.timestamp_ms)
        return status

    # ------------------------------------------------------------ 내부

    def _update_tracking(self, obs: Observation) -> Optional[Status]:
        """손 소실/추적 불안정을 처리한다. 실패면 Status, 아니면 None."""
        if not obs.hand_found:
            self._lost_streak += 1
            self._hold_streak = 0
            self._centers.clear()
            self._scales.clear()
            if self._lost_streak > self.max_lost_frames:
                reason = (FailReason.HAND_NOT_FOUND if self.state == State.WAIT_HAND
                          else FailReason.HAND_LOST)
                return self._fail(reason, obs.timestamp_ms)
            return self._status()

        self._lost_streak = 0
        score = obs.detection_score
        if np.isfinite(score) and score < self.min_detection_score:
            self._unstable_streak += 1
            self._hold_streak = 0
            if self._unstable_streak > self.max_lost_frames:
                return self._fail(FailReason.TRACKING_UNSTABLE, obs.timestamp_ms)
            return self._status()

        self._unstable_streak = 0
        return None

    def _update_shape(self, obs: Observation, action: str) -> Status:
        result = self.shape_detector.detect(obs.angle_coords)
        confident = result.confidence >= self.shape_confidence_min

        if result.label == action and confident:
            self._wrong_label, self._wrong_streak = None, 0
            self._hold_streak += 1
            if self._hold_streak >= self.hold_frames:
                return self._advance(obs.timestamp_ms)
            return self._status(result.label, result.confidence)

        self._hold_streak = 0
        if not confident or result.label == UNKNOWN:
            self._wrong_label, self._wrong_streak = None, 0
            return self._status(result.label, result.confidence)

        # 틀린 모양도 유지 조건을 채워야 실패로 본다. 한 프레임 오검출로 세션을
        # 끝내면, 측정상 최대 8프레임까지 나오는 순간 오검출에 정상 시도가 죽는다.
        if result.label == self._wrong_label:
            self._wrong_streak += 1
        else:
            self._wrong_label, self._wrong_streak = result.label, 1
        if self._wrong_streak < self.hold_frames:
            return self._status(result.label, result.confidence)

        # 여기서 바로 실패시키면 사용자가 화면의 요청을 읽고 손 모양을 바꿀 시간이
        # 없다. 손을 든 순간의 모양이 요청과 다르다는 이유로 0.3초 만에 끝나버린다.
        # 무엇을 하고 있었는지만 기록하고, 제한 시간까지 기다린다.
        self._sustained_wrong = result.label
        return self._status(result.label, result.confidence)

    def _update_move(self, obs: Observation, action: str) -> Status:
        from . import geometry as g

        coords = obs.screen_coords
        self._centers.append(g.palm_center(coords))
        self._scales.append(g.hand_scale(coords))

        needed = self._scales.maxlen
        probe = MoveProbe(frames_filled=len(self._scales), frames_needed=needed)
        if len(self._scales) < needed:
            return self._status(move_probe=probe)

        result = self.movement_detector.detect_from_tracks(
            np.array(self._centers), np.array(self._scales))
        probe = MoveProbe(
            frames_filled=len(self._scales), frames_needed=needed,
            displacement_ratio=result.displacement_ratio,
            axis_ratio=result.axis_ratio, axis=result.axis, sign=result.sign,
            label=result.label, reason=result.reason)
        self._move_stats().record(probe)

        if result.label == action:
            return self._advance(obs.timestamp_ms)
        if result.label != NONE:
            # 손 모양과 마찬가지로 즉시 실패시키지 않는다. 왕복 동작 중에는
            # 반대 방향 획도 반드시 지나가기 때문이다.
            self._sustained_wrong = result.label
        return self._status(detected_move=result.label, move_probe=probe)

    def _move_stats(self) -> MoveStats:
        step = self.steps[self.step_index]
        if step.move is None:
            step.move = MoveStats()
        return step.move

    def _timeout_reason(self, action: str) -> FailReason:
        """제한 시간이 지났을 때, 그동안 한 동작으로 실패 사유를 정한다."""
        wrong = self._sustained_wrong
        if wrong is None:
            return FailReason.ACTION_TIMEOUT
        if wrong in self._future_actions():
            return FailReason.WRONG_ORDER
        return (FailReason.WRONG_SHAPE if is_shape_action(action)
                else FailReason.WRONG_DIRECTION)

    def _future_actions(self) -> set[str]:
        return set(self.challenge.actions[self.step_index + 1:])

    def _advance(self, timestamp_ms: float) -> Status:
        step = self.steps[self.step_index]
        step.passed = True
        step.elapsed_ms = timestamp_ms - self._step_started_ms
        self.step_index += 1
        self._hold_streak = 0
        self._wrong_label, self._wrong_streak = None, 0
        self._sustained_wrong = None
        self._centers.clear()
        self._scales.clear()
        self._retries_left = self.max_retries
        if self.step_index >= len(self.challenge.actions):
            self.state = State.PASS
        else:
            self._step_started_ms = timestamp_ms
        return self._status()

    def _fail_step(self, reason: FailReason, timestamp_ms: float) -> Status:
        """재시도가 남아 있으면 현재 단계를 다시 시작한다."""
        if reason in RETRYABLE and self._retries_left > 0:
            self._retries_left -= 1
            self.steps[self.step_index].retries_used += 1
            self._step_started_ms = timestamp_ms
            self._hold_streak = 0
            self._wrong_label, self._wrong_streak = None, 0
            self._sustained_wrong = None
            self._centers.clear()
            self._scales.clear()
            return self._status()
        return self._fail(reason, timestamp_ms)

    def _fail(self, reason: FailReason, timestamp_ms: float) -> Status:
        self.state = State.FAIL
        self.fail_reason = reason
        if self.step_index < len(self.steps):
            step = self.steps[self.step_index]
            step.passed = False
            step.fail_reason = reason
            if self._step_started_ms is not None:
                step.elapsed_ms = timestamp_ms - self._step_started_ms
        return self._status()

    def _status(self, detected_shape: str = UNKNOWN, confidence: float = 0.0,
                detected_move: str = NONE,
                move_probe: Optional[MoveProbe] = None) -> Status:
        remaining = 0.0
        if self._step_started_ms is not None and self.state == State.ACTION:
            remaining = max(self.per_action_timeout_ms -
                            (self._now_ms - self._step_started_ms), 0.0)
        return Status(
            state=self.state,
            step_index=self.step_index,
            current_action=self.current_action,
            detected_shape=detected_shape,
            detected_move=detected_move,
            shape_confidence=confidence,
            hold_progress=min(self._hold_streak / self.hold_frames, 1.0),
            remaining_ms=remaining,
            fail_reason=self.fail_reason,
            steps=list(self.steps),
            move_probe=move_probe,
        )
