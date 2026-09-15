"""실시간 반례(흔들기·대각선·손 이탈) 평가 (2026-09-16).

파일럿 반례 영상은 폰으로 찍은 30fps 영상이라 웹캠 실사용 조건과 다르다. 여기서는
웹캠으로 직접 찍은 반례를 **실시간 challenge와 같은 판정 경로**에 흘린다.

방법: 상태 머신에 어떤 판정 라벨과도 일치하지 않는 이동 요청(PROBE_ACTION) 하나를 주고
녹화 전체를 넣는다. 요청이 영원히 만족되지 않으므로 끝까지 판정이 돌고, 추적 규칙
(점수 게이트, 손 놓침, 시간 기준 윈도우)은 실사용과 똑같이 적용된다. 윈도우마다 나온
이동 라벨이 곧 "그 방향을 요청받았다면 통과했을" 순간이다.

임계값은 하나도 새로 만들지 않는다. 판정 목표는 derivation_policy.json의 targets를 쓴다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from . import geometry as g
from .challenge_generator import Challenge
from .challenge_state_machine import ChallengeStateMachine, MoveProbe, Observation, State
from .hand_action_detector import HandActionDetector
from .movement_detector import NONE, MovementDetector
from .naming import MOVE_ACTIONS

NEGATIVE_KINDS = ("shake", "diagonal", "exit")
# 상태 머신에 주는 가짜 이동 요청. 이동 판정기가 내는 라벨과 절대 같지 않다.
PROBE_ACTION = "MOVE_PROBE"


@dataclass
class WindowRecord:
    t_ms: float
    displacement_ratio: float
    axis_ratio: float
    label: str
    reason: str


@dataclass
class NegativeResult:
    kind: str
    frames: int = 0
    hand_frames: int = 0
    windows: list[WindowRecord] = field(default_factory=list)
    events: list[tuple[float, str]] = field(default_factory=list)  # 라벨이 새로 나온 순간
    tracking_end: Optional[str] = None      # HAND_LOST 등으로 판정이 끝났으면 사유
    tracking_end_ms: Optional[float] = None
    # 요청 1회 기준: 방향 -> 통과까지 걸린 시간(ms) 또는 None. request_passes()로 채운다.
    request_passes: Optional[dict] = None

    @property
    def request_pass_count(self) -> int:
        return sum(v is not None for v in (self.request_passes or {}).values())

    @property
    def evaluated_windows(self) -> int:
        return len(self.windows)

    @property
    def confirmed_windows(self) -> int:
        return sum(w.label != NONE for w in self.windows)

    @property
    def confirmed_share(self) -> float:
        return self.confirmed_windows / self.evaluated_windows if self.windows else 0.0

    @property
    def max_displacement_ratio(self) -> float:
        values = [w.displacement_ratio for w in self.windows if np.isfinite(w.displacement_ratio)]
        return float(max(values)) if values else float("nan")

    def first_accept_ms(self) -> dict[str, Optional[float]]:
        """방향별로 처음 인정된 시각. 없으면 None."""
        out: dict[str, Optional[float]] = {a: None for a in MOVE_ACTIONS}
        for t, label in self.events:
            if label in out and out[label] is None:
                out[label] = t
        return out

    def verdict(self, targets: dict, config: Optional[dict] = None) -> tuple[bool, str]:
        """(오검출 없음 여부, 설명). 목표는 derivation_policy.targets에서 온다."""
        accepted = [a.replace("MOVE_", "") for a, t in self.first_accept_ms().items() if t is not None]
        if self.kind == "shake":
            limit = int(targets["shake_detections_max"])
            ok = len(self.events) <= limit
            return ok, (f"이동 인정 {len(self.events)}회 (목표 <= {limit})"
                        + (f", 인정된 방향 {'/'.join(accepted)}" if accepted else ""))
        if self.kind == "diagonal":
            reference = (f"참고: 방향 확정 윈도우 {self.confirmed_windows}/{self.evaluated_windows} "
                         f"({self.confirmed_share * 100:.1f}%)")
            if self.request_passes is None:
                limit = float(targets["diagonal_confirmed_max"])
                return self.confirmed_share < limit, reference + f" (요청 기준 미계산)"
            limit = diagonal_request_target(targets, config)
            total = len(self.request_passes)
            rate = self.request_pass_count / total if total else 0.0
            passed = [a.replace("MOVE_", "") for a, v in self.request_passes.items() if v is not None]
            ok = rate <= limit
            return ok, (f"요청 1회 통과 {self.request_pass_count}/{total}방향 ({rate * 100:.0f}%, "
                        f"목표 <= {limit * 100:.0f}%)" + (f" {'/'.join(passed)}" if passed else "")
                        + f"; {reference}")
        # exit: SPEC 목표는 없다. 손이 사라지기 전 움직임이 이동 단계를 통과시키는지 본다(README 5.9).
        ok = not self.events
        end = (f", 추적 종료 {self.tracking_end} @ {self.tracking_end_ms:.0f}ms"
               if self.tracking_end else ", 추적 종료 없음")
        return ok, (f"손이 사라지기 전 이동 인정 {len(self.events)}회"
                    + (f"({'/'.join(accepted)})" if accepted else "") + end)


class NegativeProbe:
    """프레임을 받아 실시간과 같은 규칙으로 반례를 평가한다."""

    def __init__(self, config: dict, kind: str, fps: float):
        if kind not in NEGATIVE_KINDS:
            raise ValueError(f"알 수 없는 반례 종류: {kind!r}")
        # 요청이 만족될 수 없으므로 제한 시간이 끝나면 판정이 멈춘다. 녹화 전체를 보려고
        # 시간 제한만 끈다. 추적 규칙과 임계값은 그대로다.
        probe_config = {**config, "timing": {**config["timing"],
                                              "per_action_timeout_ms": float("inf"),
                                              "total_timeout_ms": float("inf"),
                                              "max_retries": 0}}
        challenge = Challenge(challenge_id=f"negative-{kind}", actions=[PROBE_ACTION],
                              created_at="probe")
        self.machine = ChallengeStateMachine(probe_config, challenge,
                                             HandActionDetector(probe_config),
                                             MovementDetector(probe_config), fps)
        self.result = NegativeResult(kind=kind)
        self._previous = NONE
        self.last_status = None

    @property
    def finished(self) -> bool:
        return self.result.tracking_end is not None

    def update(self, obs: Observation):
        self.result.frames += 1
        self.result.hand_frames += int(obs.hand_found)
        if self.finished:
            return self.last_status
        # 손이 처음 잡히기 전 프레임은 넣지 않는다. 녹화 시작 때 손이 아직 없으면
        # HAND_NOT_FOUND로 평가가 끝나 버리는데, 그건 반례와 무관하다.
        if not obs.hand_found and self.machine.state is State.IDLE:
            return self.last_status
        status = self.machine.update(obs)
        self.last_status = status
        probe: Optional[MoveProbe] = status.move_probe
        if probe is not None and probe.window_ready:
            self.result.windows.append(WindowRecord(obs.timestamp_ms, probe.displacement_ratio,
                                                    probe.axis_ratio, probe.label, probe.reason))
        label = status.detected_move
        if label != NONE and label != self._previous:
            self.result.events.append((obs.timestamp_ms, label))
        self._previous = label
        if status.state is State.FAIL:
            self.result.tracking_end = status.fail_reason.value if status.fail_reason else "FAIL"
            self.result.tracking_end_ms = obs.timestamp_ms
        return status


def observations_from_npz(data) -> list[Observation]:
    """record_negatives.py가 저장한 npz -> Observation 목록 (다시 평가할 때)."""
    width, height = int(data["width"]), int(data["height"])
    out = []
    for i, t in enumerate(data["timestamp_ms"]):
        if data["valid_mask"][i]:
            coords = g.to_isotropic(data["landmarks"][i], width, height)
            out.append(Observation(float(t), True, float(data["detection_score"][i]), coords, coords))
        else:
            out.append(Observation(float(t), False))
    return out


def diagonal_request_target(targets: dict, config: Optional[dict]) -> float:
    """NEG_diagonal 요청 1회 통과율 목표. basis=chance면 1/방향 수 (derivation_policy 참고)."""
    if targets.get("diagonal_request_pass_basis") == "chance":
        directions = (config or {}).get("movement", {}).get("direction_map") or MOVE_ACTIONS
        return 1.0 / len(directions)
    return float(targets["diagonal_request_pass_max"])


def request_passes(config: dict, observations, fps: float,
                   directions=MOVE_ACTIONS) -> dict[str, Optional[float]]:
    """요청 1회 기준: 이 영상을 보여줬을 때 각 방향 요청이 통과되는가 (2026-09-16).

    방향마다 그 이동 하나만 요청하는 Challenge를 만들어 **실제 제한 시간·재시도·추적 규칙
    그대로** 상태 머신에 넣는다. 요청은 손이 처음 잡힌 순간 시작한다(실시간 WAIT_HAND 종료와
    같다). 통과했으면 손이 잡힌 뒤 경과 시간, 아니면 None.

    윈도우 비율(확정 윈도우 / 전체 윈도우)은 "한 번만 걸리면 통과"라는 인증 구조를 반영하지
    못한다. 대각선 영상의 윈도우 비율이 20% 미만이어도 요청 방향이 한 번 잡히면 뚫린다.
    """
    observations = list(observations)
    out: dict[str, Optional[float]] = {}
    for direction in directions:
        challenge = Challenge(challenge_id=f"request-{direction}", actions=[direction],
                              created_at="probe")
        machine = ChallengeStateMachine(config, challenge, HandActionDetector(config),
                                        MovementDetector(config), fps)
        passed_at = None
        started = None
        for obs in observations:
            if machine.state is State.IDLE and not obs.hand_found:
                continue                       # 손이 잡히기 전은 WAIT_HAND 이전과 같다
            if started is None:
                started = obs.timestamp_ms
            status = machine.update(obs)
            if status.state is State.PASS:
                passed_at = obs.timestamp_ms - started
                break
            if status.finished:
                break
        out[direction] = passed_at
    return out


def evaluate_observations(config: dict, kind: str, observations, fps: float) -> NegativeResult:
    observations = list(observations)
    probe = NegativeProbe(config, kind, fps)
    for obs in observations:
        probe.update(obs)
    if kind == "diagonal":
        probe.result.request_passes = request_passes(config, observations, fps)
    return probe.result
