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
from .movement_detector import NONE, OPPOSITE_DIRECTION, MovementDetector


# 판정 규칙이 바뀌면 올린다. results.csv에 같이 적어 변경 전후를 비교한다.
RULE_VERSION = "2026-09-18.continuous-session"


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
    # 판정을 멈춘 구간(결과 표시·다음 단계 준비)에서 손이 사라졌다.
    # Challenge와 제스처 인증을 한 번의 촬영으로 묶었기 때문에, 이 구간이 비면
    # "Challenge는 본인 손, 인증은 영상 재생"을 막지 못한다.
    SESSION_BROKEN = "SESSION_BROKEN"


# 재시도로 회복할 수 있는 사유. 손이 사라지거나 순서를 어긴 건 재시도 대상이 아니다.
RETRYABLE = frozenset({FailReason.WRONG_SHAPE, FailReason.WRONG_DIRECTION,
                       FailReason.ACTION_TIMEOUT})


class FrameSpan:
    """'N프레임 연속'을 프레임 수가 아니라 관측 시각으로 잰다.

    config의 프레임 수(shape_hold_frames 등)는 파일럿 영상(frame_reference_fps)에서 센
    값이다. 실시간 fps가 다르면 같은 프레임 수가 다른 시간이 된다(웹캠 20fps에서 7프레임은
    233ms가 아니라 350ms). 도출과 같은 기준이 되도록 기준 fps에서의 시간으로 비교한다.

    N프레임 연속 = 첫 프레임과 지금 프레임의 간격이 (N-1)프레임 간격 이상.
    타임스탬프 흔들림에 대비해 반 프레임 여유를 둔다. 기준 fps로 들어오면 프레임 수로
    센 것과 결과가 같다.
    """

    def __init__(self, frames: int, reference_fps: float):
        self.frames = int(frames)
        frame_ms = 1000.0 / float(reference_fps)
        self.required_ms = max(self.frames - 1.5, 0.0) * frame_ms
        self.start_ms: Optional[float] = None
        self.last_ms: Optional[float] = None

    def hit(self, timestamp_ms: float) -> bool:
        """조건을 만족한 프레임 하나. 연속 구간이 요구 길이에 닿았으면 True."""
        if self.start_ms is None:
            self.start_ms = timestamp_ms
        self.last_ms = timestamp_ms
        return self.done

    def reset(self) -> None:
        self.start_ms = self.last_ms = None

    @property
    def active(self) -> bool:
        return self.start_ms is not None

    @property
    def elapsed_ms(self) -> float:
        return 0.0 if self.start_ms is None else self.last_ms - self.start_ms

    @property
    def done(self) -> bool:
        return self.frames > 0 and self.active and self.elapsed_ms >= self.required_ms

    @property
    def progress(self) -> float:
        if not self.active:
            return 0.0
        if self.required_ms <= 0:
            return 1.0
        return min(self.elapsed_ms / self.required_ms, 1.0)


class MsSpan:
    """"이만큼 연속으로" 를 ms로 직접 잰다.

    FrameSpan과 달리 기준 fps 환산을 하지 않는다. 파일럿 영상에서 도출한 임계값이
    아니라 화면 흐름을 위한 대기 시간이기 때문이다.
    """

    def __init__(self, required_ms: float):
        self.required_ms = float(required_ms)
        self.start_ms: Optional[float] = None
        self.last_ms: Optional[float] = None

    def hit(self, timestamp_ms: float) -> bool:
        if self.start_ms is None:
            self.start_ms = timestamp_ms
        self.last_ms = timestamp_ms
        return self.done

    def reset(self) -> None:
        self.start_ms = self.last_ms = None

    @property
    def active(self) -> bool:
        return self.start_ms is not None

    @property
    def elapsed_ms(self) -> float:
        return 0.0 if self.start_ms is None else self.last_ms - self.start_ms

    @property
    def done(self) -> bool:
        return self.active and self.elapsed_ms >= self.required_ms

    @property
    def progress(self) -> float:
        if not self.active:
            return 0.0
        if self.required_ms <= 0:
            return 1.0
        return min(self.elapsed_ms / self.required_ms, 1.0)


class TimeWindow:
    """이동 판정 윈도우. 기준 fps에서 window_frames 프레임이 차지하는 시간만큼 담는다."""

    def __init__(self, window_frames: int, reference_fps: float):
        frame_ms = 1000.0 / float(reference_fps)
        self.window_frames = int(window_frames)
        self.keep_ms = (self.window_frames - 0.5) * frame_ms    # 이보다 오래된 프레임은 버린다
        self.required_ms = (self.window_frames - 1.5) * frame_ms  # 이만큼 차면 판정
        self._t: deque = deque()
        self.centers: deque = deque()
        self.scales: deque = deque()

    def add(self, timestamp_ms: float, center, scale) -> None:
        self._t.append(timestamp_ms)
        self.centers.append(center)
        self.scales.append(scale)
        while self._t and timestamp_ms - self._t[0] > self.keep_ms:
            self._t.popleft()
            self.centers.popleft()
            self.scales.popleft()

    def clear(self) -> None:
        self._t.clear()
        self.centers.clear()
        self.scales.clear()

    @property
    def span_ms(self) -> float:
        return self._t[-1] - self._t[0] if len(self._t) >= 2 else 0.0

    @property
    def ready(self) -> bool:
        return len(self._t) >= 2 and self.span_ms >= self.required_ms

    def __len__(self) -> int:
        return len(self._t)


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
    span_ms: float = 0.0          # 윈도우에 담긴 시간
    span_needed_ms: float = 0.0   # 판정에 필요한 시간
    ready: Optional[bool] = None  # 시간 기준 판정 준비 여부. None이면 프레임 수로 본다

    @property
    def window_ready(self) -> bool:
        if self.ready is not None:
            return self.ready
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
    escape_from: Optional[str] = None        # 벗어나야 하는 이전 손 모양
    escape_progress: float = 1.0             # 0.0~1.0, 1.0이면 관문 열림
    hand_ready_progress: float = 0.0         # WAIT_HAND에서 손이 연속으로 잡힌 정도
    step_result: Optional[str] = None        # "PASS" | "FAIL" 표시 중
    step_result_remaining_ms: float = 0.0
    step_result_reason: Optional[FailReason] = None
    preparing: bool = False                  # 다음 단계 준비 시간 중인지
    prepare_remaining_ms: float = 0.0        # 준비 시간이 얼마나 남았는지
    just_passed_step: Optional[int] = None   # 방금 통과한 단계 번호(0-based)

    @property
    def awaiting_escape(self) -> bool:
        return self.escape_from is not None and self.escape_progress < 1.0

    @property
    def awaiting_hand(self) -> bool:
        """손을 들기를 기다리는 중인지. 이 동안에는 제한 시간이 흐르지 않는다."""
        return self.state == State.WAIT_HAND

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
        # 손이 이만큼 연속으로 잡혀야 1단계를 시작한다. 그 전에는 제한 시간이 흐르지
        # 않고 재시도도 차감되지 않는다. 화면이 뜨자마자 판정이 시작되면 손을 들기도
        # 전에 시간이 지나간다(실기기에서 겪었다). 0이면 첫 프레임에 바로 시작한다.
        self.wait_hand_ready_ms = float(timing.get("wait_hand_ready_ms", 0.0))
        # 손을 아예 들지 않을 때 대기를 끝내는 안전장치. 판정 제한이 아니다.
        self.wait_hand_timeout_ms = float(timing.get("wait_hand_timeout_ms", 15000.0))
        # 단계가 넘어간 뒤 다음 판정을 시작하기까지 주는 시간. 요청 동작을 보고
        # 손을 준비할 시간이라, 이 동안에는 per_action_timeout_ms가 흐르지 않는다.
        self.step_prepare_ms = float(timing.get("step_prepare_ms", 0.0))
        # 단계 결과(PASS/FAIL)를 보여주는 시간. 맞게 했는지 인지할 틈을 준다.
        # 이 동안에는 제한 시간이 흐르지 않는다.
        self.step_result_hold_ms = float(timing.get("step_result_hold_ms", 0.0))

        tracking = config["tracking"]
        self.max_lost_frames = int(tracking["max_lost_frames"])
        self.min_detection_score = float(tracking["min_detection_score"])

        # 프레임 수 기반 값들을 시간으로 바꿀 기준 fps. 04가 파일럿 영상에서 기록한다.
        # 없으면(옛 config, 테스트) 생성자에 받은 fps를 기준으로 쓴다.
        reference = config.get("frame_reference_fps")
        self.reference_fps = float(reference) if reference else self.fps

        self.hold_frames = int(config["shape_hold_frames"])
        # 이전 단계 종료 시점의 손 모양에서 벗어나야 다음 판정을 시작한다.
        # None이면 관문을 끈다(도출 실패 시).
        escape = config.get("escape_frames")
        self.escape_frames = int(escape) if escape else 0
        # null이면 신뢰도 게이트를 끈다. 04에서 '신뢰도로는 더 못 거른다'가 측정으로
        # 확인된 경우이므로, 임의의 값을 넣는 대신 조건을 걸지 않는다.
        confidence_min = config.get("shape_confidence_min")
        self.shape_confidence_min = (float(confidence_min)
                                     if confidence_min is not None else 0.0)

        window = self.movement_detector.window_frames(self.reference_fps)
        self._window = TimeWindow(window, self.reference_fps)

        self.state = State.IDLE
        self.step_index = 0
        self.fail_reason: Optional[FailReason] = None
        self.steps: list[StepResult] = [StepResult(a) for a in challenge.actions]

        # 1단계가 **시작된** 시각. 대기 중에는 None이고 전체 제한도 흐르지 않는다.
        self._started_ms: Optional[float] = None
        # 화면에 들어온 시각. 대기 제한(안전장치)만 여기서 잰다.
        self._wait_started_ms: Optional[float] = None
        self._step_started_ms: Optional[float] = None
        self._now_ms: float = 0.0
        self._frame_delta_ms: float = 0.0
        self._hand_ready = MsSpan(self.wait_hand_ready_ms)
        # 다음 단계 준비 시간이 끝나는 시각. None이면 준비 중이 아니다.
        self._prepare_until_ms: Optional[float] = None
        # 단계 결과 표시가 끝나는 시각과 그 내용. None이면 표시 중이 아니다.
        self._result_until_ms: Optional[float] = None
        self._result_kind: Optional[str] = None      # "PASS" | "FAIL"
        self._result_reason: Optional[FailReason] = None
        self._hold = FrameSpan(self.hold_frames, self.reference_fps)
        self._wrong_label: Optional[str] = None
        self._wrong = FrameSpan(self.hold_frames, self.reference_fps)
        # 제한 시간 동안 사용자가 '확실히' 수행한 다른 동작. 타임아웃 때 사유를 정한다.
        self._sustained_wrong: Optional[str] = None
        self._just_passed_step: Optional[int] = None  # 방금 통과한 단계(화면 표시용)
        self._last_shape: Optional[str] = None    # 마지막으로 검출된 손 모양
        self._escape_from: Optional[str] = None   # 벗어나야 하는 모양
        self._escape = FrameSpan(self.escape_frames, self.reference_fps)
        # 기존 규칙은 '연속 N프레임 초과'에서 실패였다 = N+1프레임 연속
        self._lost = FrameSpan(self.max_lost_frames + 1, self.reference_fps)
        self._unstable = FrameSpan(self.max_lost_frames + 1, self.reference_fps)
        self._retries_left = self.max_retries

    # ------------------------------------------------------------ 진행

    @property
    def current_action(self) -> Optional[str]:
        if self.step_index < len(self.challenge.actions):
            return self.challenge.actions[self.step_index]
        return None

    def start(self, timestamp_ms: float) -> None:
        self.state = State.WAIT_HAND
        # ⚠️ _started_ms는 여기서 정하지 않는다. 손을 들기 전까지 전체 제한 시간이
        # 흐르면 안 된다. 1단계가 시작될 때 정한다.
        self._wait_started_ms = timestamp_ms
        self._step_started_ms = None
        self._now_ms = timestamp_ms

    def update(self, obs: Observation) -> Status:
        if self.state in (State.PASS, State.FAIL):
            return self._status()
        if self.state == State.IDLE:
            self.start(obs.timestamp_ms)
        # 이탈 관문이 닫혀 있는 동안 시계를 멈추려면 프레임 간격이 필요하다.
        self._frame_delta_ms = max(obs.timestamp_ms - self._now_ms, 0.0)
        self._now_ms = obs.timestamp_ms

        # 손을 들기를 기다리는 동안은 아무 시계도 흐르지 않는다.
        # None을 돌려주면 이 프레임부터 바로 판정에 들어간다.
        if self.state == State.WAIT_HAND:
            waiting = self._update_wait(obs)
            if waiting is not None:
                return waiting

        # 단계 결과(PASS/FAIL) 표시. 맞게 했는지 인지할 틈을 준다.
        # 준비 시간과 마찬가지로 이 동안에는 아무 시계도 흐르지 않는다.
        if self._result_until_ms is not None:
            broken = self._update_continuity(obs)
            if broken is not None:
                return broken
            if obs.timestamp_ms < self._result_until_ms:
                self._step_started_ms = obs.timestamp_ms
                if self._started_ms is not None:
                    self._started_ms += self._frame_delta_ms
                return self._status()
            return self._resolve_result(obs.timestamp_ms)

        # 다음 단계 준비 시간. 요청 동작을 보고 손을 만들 시간을 준다.
        # 이 동안에는 단계 제한도 전체 제한도 흐르지 않는다.
        if self._prepare_until_ms is not None:
            broken = self._update_continuity(obs)
            if broken is not None:
                return broken
            if obs.timestamp_ms < self._prepare_until_ms:
                self._step_started_ms = obs.timestamp_ms
                if self._started_ms is not None:
                    self._started_ms += self._frame_delta_ms
                return self._status()
            self._prepare_until_ms = None
            self._step_started_ms = obs.timestamp_ms

        if obs.timestamp_ms - self._started_ms > self.total_timeout_ms:
            return self._fail(FailReason.TOTAL_TIMEOUT, obs.timestamp_ms)

        tracking_status = self._update_tracking(obs)
        if tracking_status is not None:
            return tracking_status

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

    def _update_wait(self, obs: Observation) -> Optional[Status]:
        """손이 원 안에 들어오기를 기다린다.

        **제한 시간을 소모하지 않고 재시도도 차감하지 않는다.** 이 단계가 없으면
        화면이 뜨자마자 판정이 시작되고, 손 소실 관문까지 돌아 1.25초 만에
        HAND_NOT_FOUND로 끝난다(실기기에서 실제로 그랬다).
        """
        if not obs.hand_found:
            self._hand_ready.reset()
            # 손을 아예 들지 않으면 세션이 멈춰 있게 된다. 안전장치로만 끝낸다.
            if obs.timestamp_ms - self._wait_started_ms > self.wait_hand_timeout_ms:
                return self._fail(FailReason.HAND_NOT_FOUND, obs.timestamp_ms)
            return self._status()

        if not self._hand_ready.hit(obs.timestamp_ms):
            return self._status()

        # 여기서부터 제한 시간이 흐른다. 이 프레임도 판정에 쓴다(None을 돌려준다).
        self.state = State.ACTION
        self._started_ms = obs.timestamp_ms
        self._step_started_ms = obs.timestamp_ms
        self._hold.reset()
        self._lost.reset()
        self._unstable.reset()
        return None

    def _update_continuity(self, obs: Observation) -> Optional[Status]:
        """판정을 멈춘 구간에서도 손이 계속 잡히는지 본다.

        결과 표시(PASS/FAIL)와 다음 단계 준비 시간에는 판정을 하지 않지만
        **추적은 유지해야 한다.** 이 구간이 비어 있으면 통과 표시를 본 사용자가
        손을 내리고 다른 것을 들이밀 수 있고, 그게 이 세션 구조로 막으려는 공격이다.

        허용 길이는 판정 중과 같다(max_lost_frames). 한 프레임 끊김으로 실패시키면
        정상 사용자가 죽는다.
        """
        if obs.hand_found:
            self._lost.reset()
            return None
        if self._lost.hit(obs.timestamp_ms):
            return self._fail(FailReason.SESSION_BROKEN, obs.timestamp_ms)
        return self._status()

    def _update_tracking(self, obs: Observation) -> Optional[Status]:
        """손 소실/추적 불안정을 처리한다. 실패면 Status, 아니면 None."""
        if not obs.hand_found:
            self._hold.reset()
            self._window.clear()
            if self._lost.hit(obs.timestamp_ms):
                reason = (FailReason.HAND_NOT_FOUND if self.state == State.WAIT_HAND
                          else FailReason.HAND_LOST)
                return self._fail(reason, obs.timestamp_ms)
            return self._status()

        self._lost.reset()
        score = obs.detection_score
        if np.isfinite(score) and score < self.min_detection_score:
            self._hold.reset()
            if self._unstable.hit(obs.timestamp_ms):
                return self._fail(FailReason.TRACKING_UNSTABLE, obs.timestamp_ms)
            return self._status()

        self._unstable.reset()
        return None

    def _update_shape(self, obs: Observation, action: str) -> Status:
        result = self.shape_detector.detect(obs.angle_coords)
        confident = result.confidence >= self.shape_confidence_min
        self._last_shape = result.label

        # --- 이전 손 모양 이탈 관문 ---
        # 이동은 손바닥을 편 채로 하므로, 이동 다음 단계가 OPEN_PALM이면 손이 이미
        # 그 모양이라 아무것도 안 해도 통과된다. 요청에 반응했는지를 확인하지
        # 못하게 되므로 보안 문제다. 이전 모양에서 실제로 벗어난 뒤에 판정한다.
        if self._escape_pending():
            if result.label != self._escape_from:
                self._escape.hit(obs.timestamp_ms)
            else:
                self._escape.reset()
            # 관문이 닫혀 있는 동안은 제한 시간을 소모하지 않는다.
            # 단계 제한과 전체 제한을 같이 미뤄야 한다. 전체 제한만 흐르게 두면
            # 마지막 단계에 관문이 걸릴 때 TOTAL_TIMEOUT으로 죽는다.
            self._step_started_ms = obs.timestamp_ms
            if self._started_ms is not None:
                self._started_ms += self._frame_delta_ms
            if self._escape_pending():
                return self._status(result.label, result.confidence)
            self._escape_from = None

        if result.label == action and confident:
            self._wrong_label = None
            self._wrong.reset()
            if self._hold.hit(obs.timestamp_ms):
                return self._advance(obs.timestamp_ms)
            return self._status(result.label, result.confidence)

        self._hold.reset()
        if not confident or result.label == UNKNOWN:
            self._wrong_label = None
            self._wrong.reset()
            return self._status(result.label, result.confidence)

        # 틀린 모양도 유지 조건을 채워야 실패로 본다. 한 프레임 오검출로 세션을
        # 끝내면, 측정상 최대 8프레임까지 나오는 순간 오검출에 정상 시도가 죽는다.
        if result.label != self._wrong_label:
            self._wrong_label = result.label
            self._wrong.reset()
        if not self._wrong.hit(obs.timestamp_ms):
            return self._status(result.label, result.confidence)

        # 여기서 바로 실패시키면 사용자가 화면의 요청을 읽고 손 모양을 바꿀 시간이
        # 없다. 손을 든 순간의 모양이 요청과 다르다는 이유로 0.3초 만에 끝나버린다.
        # 무엇을 하고 있었는지만 기록하고, 제한 시간까지 기다린다.
        self._sustained_wrong = result.label
        return self._status(result.label, result.confidence)

    def _update_move(self, obs: Observation, action: str) -> Status:
        from . import geometry as g

        # 이동 중의 손 모양을 계속 기억해 둔다. 이동이 끝난 시점의 이 값이
        # 다음 단계의 escape_from이 된다.
        if obs.angle_coords is not None:
            self._last_shape = self.shape_detector.detect(obs.angle_coords).label

        coords = obs.screen_coords
        window = self._window
        window.add(obs.timestamp_ms, g.palm_center(coords), g.hand_scale(coords))

        base = dict(frames_filled=len(window), frames_needed=window.window_frames,
                    span_ms=window.span_ms, span_needed_ms=window.required_ms,
                    ready=window.ready)
        if not window.ready:
            return self._status(move_probe=MoveProbe(**base))

        result = self.movement_detector.detect_from_tracks(
            np.array(window.centers), np.array(window.scales))
        probe = MoveProbe(
            **base,
            displacement_ratio=result.displacement_ratio,
            axis_ratio=result.axis_ratio, axis=result.axis, sign=result.sign,
            label=result.label, reason=result.reason)
        self._move_stats().record(probe)

        if result.label == action:
            return self._advance(obs.timestamp_ms)
        if result.label == OPPOSITE_DIRECTION.get(action):
            # 요청과 같은 축의 반대 방향이 먼저 확정되면 즉시 실패시킨다 (재시도는 허용).
            # 그대로 두면 이동 영상 하나의 '되돌아오는 획'이 반대 방향 요청을 통과시킨다
            # (정상 MOVE 파일럿 영상에 반대 방향 요청 시 80% 통과 -> 이 규칙으로 30%).
            # 실시간 33개 이동 단계 중 반대 방향이 먼저 나온 3건은 모두 재시도로 회복됐다.
            # 요청 방향이 먼저 잡히면 그 순간 통과하므로 그 뒤의 되돌아오는 획은 상관없다.
            return self._fail_step(FailReason.WRONG_DIRECTION, obs.timestamp_ms)
        if result.label != NONE:
            # 수직 방향은 즉시 실패시키지 않고 제한 시간까지 기다린다. 사유만 기억한다.
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

    def _escape_pending(self) -> bool:
        return self._escape_from is not None and not self._escape.done

    def _escape_progress(self) -> float:
        if not self._escape_pending():
            return 1.0
        return self._escape.progress

    def _arm_escape_gate(self) -> None:
        """다음 단계가 손 모양이면, 방금 끝난 시점의 손 모양에서 벗어나게 한다.

        이동 단계에는 걸지 않는다. 이동은 단계 전환 때 윈도우를 비우므로 정지한
        손으로는 변위가 나오지 않고, Challenge에 이동은 하나뿐이라 '이전 단계가
        이미 이동을 만족시키는' 경우 자체가 생기지 않는다.
        """
        action = self.current_action
        self._escape.reset()
        if (self.escape_frames > 0 and action is not None
                and is_shape_action(action) and self._last_shape is not None):
            self._escape_from = self._last_shape
        else:
            self._escape_from = None

    def _future_actions(self) -> set[str]:
        return set(self.challenge.actions[self.step_index + 1:])

    def _advance(self, timestamp_ms: float) -> Status:
        step_index = self.step_index
        step = self.steps[self.step_index]
        step.passed = True
        step.elapsed_ms = timestamp_ms - self._step_started_ms
        self.step_index += 1
        self._hold.reset()
        self._wrong_label = None
        self._wrong.reset()
        self._sustained_wrong = None
        self._window.clear()
        self._retries_left = self.max_retries
        self._just_passed_step = step_index

        # PASS를 먼저 보여준다. 다음 단계로 갈지 끝낼지는 표시가 끝난 뒤 정한다.
        if self.step_result_hold_ms > 0:
            self._result_kind = "PASS"
            self._result_reason = None
            self._result_until_ms = timestamp_ms + self.step_result_hold_ms
            return self._status()
        return self._finish_advance(timestamp_ms)

    def _finish_advance(self, timestamp_ms: float) -> Status:
        """PASS 표시가 끝난 뒤(또는 표시가 없을 때) 다음 단계로 넘어간다."""
        if self.step_index >= len(self.challenge.actions):
            self.state = State.PASS
            return self._status()
        self._step_started_ms = timestamp_ms
        self._arm_escape_gate()
        if self.step_prepare_ms > 0:
            self._prepare_until_ms = timestamp_ms + self.step_prepare_ms
        return self._status()

    def _resolve_result(self, timestamp_ms: float) -> Status:
        """결과 표시 시간이 끝났다. PASS면 다음 단계로, FAIL이면 그 단계를 다시."""
        kind = self._result_kind
        self._result_until_ms = None
        self._result_kind = None
        self._result_reason = None
        if kind == "PASS":
            return self._finish_advance(timestamp_ms)
        # FAIL(재시도): 같은 단계를 다시 준비한다.
        self._step_started_ms = timestamp_ms
        if self.step_prepare_ms > 0:
            self._prepare_until_ms = timestamp_ms + self.step_prepare_ms
        return self._status()

    def _fail_step(self, reason: FailReason, timestamp_ms: float) -> Status:
        """재시도가 남아 있으면 현재 단계를 다시 시작한다."""
        if reason in RETRYABLE and self._retries_left > 0:
            self._retries_left -= 1
            self.steps[self.step_index].retries_used += 1
            self._step_started_ms = timestamp_ms
            self._hold.reset()
            self._wrong_label = None
            self._wrong.reset()
            self._sustained_wrong = None
            self._window.clear()
            self._prepare_until_ms = None
            if self.step_result_hold_ms > 0:
                self._result_kind = "FAIL"
                self._result_reason = reason
                self._result_until_ms = timestamp_ms + self.step_result_hold_ms
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
            hold_progress=self._hold.progress,
            remaining_ms=remaining,
            fail_reason=self.fail_reason,
            steps=list(self.steps),
            move_probe=move_probe,
            escape_from=self._escape_from if self._escape_pending() else None,
            escape_progress=self._escape_progress(),
            hand_ready_progress=self._hand_ready.progress,
            step_result=self._result_kind,
            step_result_remaining_ms=(
                max(self._result_until_ms - self._now_ms, 0.0)
                if self._result_until_ms is not None else 0.0
            ),
            step_result_reason=self._result_reason,
            preparing=self._prepare_until_ms is not None,
            prepare_remaining_ms=(
                max(self._prepare_until_ms - self._now_ms, 0.0)
                if self._prepare_until_ms is not None else 0.0
            ),
            just_passed_step=self._just_passed_step,
        )
