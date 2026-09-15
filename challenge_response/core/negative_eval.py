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

    def verdict(self, targets: dict) -> tuple[bool, str]:
        """(오검출 없음 여부, 설명). 목표는 derivation_policy.targets에서 온다."""
        accepted = [a.replace("MOVE_", "") for a, t in self.first_accept_ms().items() if t is not None]
        if self.kind == "shake":
            limit = int(targets["shake_detections_max"])
            ok = len(self.events) <= limit
            return ok, (f"이동 인정 {len(self.events)}회 (목표 <= {limit})"
                        + (f", 인정된 방향 {'/'.join(accepted)}" if accepted else ""))
        if self.kind == "diagonal":
            limit = float(targets["diagonal_confirmed_max"])
            ok = self.confirmed_share < limit
            return ok, (f"방향 확정 윈도우 {self.confirmed_windows}/{self.evaluated_windows} "
                        f"({self.confirmed_share * 100:.1f}%, 목표 < {limit * 100:.0f}%)"
                        + (f", 인정된 방향 {'/'.join(accepted)}" if accepted else ""))
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


def evaluate_observations(config: dict, kind: str, observations, fps: float) -> NegativeResult:
    probe = NegativeProbe(config, kind, fps)
    for obs in observations:
        probe.update(obs)
    return probe.result
