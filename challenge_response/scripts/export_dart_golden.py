"""Dart 이식본과 대조할 기대값을 뽑는다.

    cd challenge_response
    python scripts/export_dart_golden.py

앱은 Challenge 판정을 Dart로 다시 구현했다(lib/challenge/). 두 구현이 갈라지면
안티스푸핑 규칙이 조용히 달라지므로, **파이썬 실행 결과**를 파일로 남기고 Dart
테스트가 그 파일을 읽어 비교한다. 손으로 옮긴 기대값이 아니라 실행 결과가 근거다.

입력은 파라미터로 적고 양쪽이 각자 합성한다. 그래야 합성기(synth.py / synth.dart)가
갈라진 것도 같이 잡힌다. 합성기 자체는 synthSamples의 좌표로 직접 대조한다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from core import geometry as g  # noqa: E402
from core.challenge_generator import Challenge  # noqa: E402
from core.challenge_state_machine import (RULE_VERSION,  # noqa: E402
                                          ChallengeStateMachine, Observation)
from core.hand_action_detector import SHAPE_PATTERNS, HandActionDetector  # noqa: E402
from core.movement_detector import MovementDetector  # noqa: E402
from tests.synth import make_hand, make_pattern_hand  # noqa: E402

OUT = ROOT.parent / "test" / "challenge" / "golden" / "cross_impl.json"

EXTENDED_ANGLE = 175.0
CURLED_ANGLE = 60.0
FPS = 30.0
FRAME_MS = 1000.0 / FPS
ESCAPE = 4

# 대조용 설정. 합성 손의 각도 범위에 맞춰 관문 경계를 볼 수 있게 잡았다.
CONFIG = {
    "angle_space": "world",
    "coordinate_frame": "raw",
    "finger_extended_angle": {"thumb": 150.0, "others": 160.0},
    "fist_max_tip_wrist_ratio": None,
    "shape_confidence_margin_deg": 20.0,
    "shape_confidence_min": 0.5,
    "shape_hold_frames": 5,
    "escape_frames": ESCAPE,
    "frame_reference_fps": FPS,
    "movement": {
        "window_ms": 400,
        "min_displacement_ratio": 1.2,
        "axis_dominance_ratio": 2.0,
        "max_duration_ms": 2500,
        "rest_displacement_ratio": 0.086,
        "direction_map": {"MOVE_LEFT": ["x", -1], "MOVE_RIGHT": ["x", 1],
                          "MOVE_UP": ["y", -1], "MOVE_DOWN": ["y", 1]},
    },
    "timing": {"per_action_timeout_ms": 2000, "total_timeout_ms": 20000,
               "max_retries": 0},
    "tracking": {"max_lost_frames": 5, "min_detection_score": 0.5},
}

# Dart(ChallengeConfig)가 그대로 읽을 수 있는 형태.
CAMEL_CONFIG = {
    "ruleVersion": RULE_VERSION,
    "angleSpace": CONFIG["angle_space"],
    "coordinateFrame": CONFIG["coordinate_frame"],
    "frameReferenceFps": CONFIG["frame_reference_fps"],
    "fingerExtendedAngle": CONFIG["finger_extended_angle"],
    "fistMaxTipWristRatio": CONFIG["fist_max_tip_wrist_ratio"],
    "shapeHoldFrames": CONFIG["shape_hold_frames"],
    "shapeConfidenceMarginDeg": CONFIG["shape_confidence_margin_deg"],
    "shapeConfidenceMin": CONFIG["shape_confidence_min"],
    "escapeFrames": CONFIG["escape_frames"],
    "movement": {
        "windowMs": CONFIG["movement"]["window_ms"],
        "minDisplacementRatio": CONFIG["movement"]["min_displacement_ratio"],
        "axisDominanceRatio": CONFIG["movement"]["axis_dominance_ratio"],
        "maxDurationMs": CONFIG["movement"]["max_duration_ms"],
        "restDisplacementRatio": CONFIG["movement"]["rest_displacement_ratio"],
        "directionMap": CONFIG["movement"]["direction_map"],
    },
    "timing": {
        "perActionTimeoutMs": CONFIG["timing"]["per_action_timeout_ms"],
        "totalTimeoutMs": CONFIG["timing"]["total_timeout_ms"],
        "maxRetries": CONFIG["timing"]["max_retries"],
    },
    "tracking": {
        "maxLostFrames": CONFIG["tracking"]["max_lost_frames"],
        "minDetectionScore": CONFIG["tracking"]["min_detection_score"],
    },
    "steps": {"numShapes": 2, "numMoves": 1},
    "shapePool": list(SHAPE_PATTERNS),
    "movePool": list(CONFIG["movement"]["direction_map"]),
}

NON_THUMB = ("index", "middle", "ring", "pinky")


def num(value) -> float | None:
    """NaN/Inf는 JSON에 없다. 문자열로 남겨 Dart가 되살린다."""
    v = float(value)
    if np.isnan(v):
        return "NaN"
    if np.isinf(v):
        return "Infinity" if v > 0 else "-Infinity"
    return round(v, 9)


def pattern_hand(flags, thumb=True, **kwargs):
    pattern = dict(zip(NON_THUMB, flags))
    return make_pattern_hand({**pattern, "thumb": thumb},
                             EXTENDED_ANGLE, CURLED_ANGLE, **kwargs)


def move_sequence(dx, dy, frames, scale=1.0):
    return np.stack([
        make_hand(180.0, scale=scale,
                  center=(dx * scale * i / (frames - 1),
                          dy * scale * i / (frames - 1), 0.0))
        for i in range(frames)
    ])


# ------------------------------------------------------------------ 합성기 대조

def synth_samples():
    """합성기가 양쪽에서 같은 좌표를 내는지 확인할 표본."""
    cases = [
        {"name": "open_180", "params": {"uniformAngle": 180.0}},
        {"name": "curled_60", "params": {"uniformAngle": 60.0}},
        {"name": "scaled_shifted",
         "params": {"uniformAngle": 150.0, "scale": 0.3, "center": [0.4, 0.7, 0.1]}},
        {"name": "mixed", "params": {"angles": {"thumb": 100.0, "index": 180.0,
                                                "middle": 170.0, "ring": 60.0,
                                                "pinky": 50.0}}},
    ]
    out = []
    for case in cases:
        p = case["params"]
        hand = make_hand(p.get("angles", p.get("uniformAngle", 180.0)),
                         scale=p.get("scale", 1.0),
                         center=tuple(p.get("center", (0.0, 0.0, 0.0))))
        out.append({**case,
                    "landmarks": [[num(v) for v in point] for point in hand]})
    return out


# ------------------------------------------------------------------ 손 모양

def shape_cases(detector):
    cases = []
    for label, flags in SHAPE_PATTERNS.items():
        cases.append({"name": f"pattern_{label}", "flags": list(flags),
                      "thumb": True, "scale": 1.0, "center": [0.0, 0.0, 0.0]})
    undeclared = [(True, True, True, False), (True, False, True, False),
                  (True, False, False, True), (False, True, False, False),
                  (False, False, True, True), (False, True, True, True)]
    for flags in undeclared:
        cases.append({"name": "undeclared_" + "".join("T" if f else "F" for f in flags),
                      "flags": list(flags), "thumb": True, "scale": 1.0,
                      "center": [0.0, 0.0, 0.0]})
    cases.append({"name": "thumb_curled_two_fingers",
                  "flags": list(SHAPE_PATTERNS["TWO_FINGERS"]), "thumb": False,
                  "scale": 1.0, "center": [0.0, 0.0, 0.0]})
    cases.append({"name": "far_small_index", "flags": list(SHAPE_PATTERNS["INDEX"]),
                  "thumb": True, "scale": 0.25, "center": [0.8, 0.6, 0.2]})

    out = []
    for case in cases:
        hand = pattern_hand(case["flags"], case["thumb"],
                            scale=case["scale"], center=tuple(case["center"]))
        result = detector.detect(hand)
        out.append({**case,
                    "label": result.label,
                    "confidence": num(result.confidence),
                    "tipWristRatio": num(result.tip_wrist_ratio),
                    "flagsOut": [bool(f) for f in result.flags],
                    "angles": [num(a) for a in result.angles]})
    return out


# ------------------------------------------------------------------ 이동

def move_cases(detector):
    cases = [
        {"name": "right", "dx": 3.0, "dy": 0.0},
        {"name": "left", "dx": -3.0, "dy": 0.0},
        {"name": "up", "dx": 0.0, "dy": -3.0},
        {"name": "down", "dx": 0.0, "dy": 3.0},
        {"name": "diagonal_45", "dx": 3.0, "dy": 3.0},
        {"name": "diagonal_just_under", "dx": 3.0, "dy": 3.0 / 1.8},
        {"name": "diagonal_just_over", "dx": 3.0, "dy": 3.0 / 3.0},
        {"name": "too_small", "dx": 0.6, "dy": 0.0},
        {"name": "far_hand", "dx": 3.0, "dy": 0.0, "scale": 0.25},
    ]
    out = []
    for case in cases:
        scale = case.get("scale", 1.0)
        seq = move_sequence(case["dx"], case["dy"], 20, scale)
        result = detector.detect(seq)
        out.append({**case, "scale": scale, "frames": 20,
                    "label": result.label,
                    "reason": result.reason,
                    "displacementRatio": num(result.displacement_ratio),
                    "axisRatio": num(result.axis_ratio),
                    "axis": result.axis,
                    "sign": int(result.sign)})
    return out


def mirrored_move_cases():
    """좌표는 원본, 라벨만 뒤집는 규칙을 대조한다."""
    mirrored = MovementDetector({**CONFIG, "coordinate_frame": "mirrored"})
    out = []
    for name, dx, dy in [("right_raw", 3.0, 0.0), ("left_raw", -3.0, 0.0),
                         ("up_raw", 0.0, -3.0), ("down_raw", 0.0, 3.0)]:
        result = mirrored.detect(move_sequence(dx, dy, 20))
        out.append({"name": name, "dx": dx, "dy": dy, "frames": 20,
                    "label": result.label})
    return out


# ------------------------------------------------------------------ 상태 머신

def run_script(actions, script, config=None):
    """script를 순서대로 흘려보내고 최종 상태를 돌려준다."""
    cfg = config or CONFIG
    machine = ChallengeStateMachine(
        cfg, Challenge(challenge_id="golden", actions=list(actions), created_at="now"),
        HandActionDetector(cfg), MovementDetector(cfg), FPS)
    t = 0.0
    status = None
    for step in script:
        for i in range(step["frames"]):
            kind = step["kind"]
            if kind == "shape":
                hand = pattern_hand(SHAPE_PATTERNS[step["label"]])
                obs = Observation(t, True, 1.0, hand, hand)
            elif kind == "move":
                hand = make_hand(180.0, center=(step["dx"] * i * 0.4,
                                                step["dy"] * i * 0.4, 0.0))
                obs = Observation(t, True, 1.0, hand, hand)
            else:  # lost
                obs = Observation(t, False)
            status = machine.update(obs)
            t += FRAME_MS
            if status.finished:
                break
        if status is not None and status.finished:
            break
    return machine, status


def sequence_cases():
    hold = CONFIG["shape_hold_frames"]
    window = MovementDetector(CONFIG).window_frames(FPS)

    cases = [
        {"name": "full_pass",
         "actions": ["OPEN_PALM", "FIST", "MOVE_RIGHT"],
         "script": [{"kind": "shape", "label": "OPEN_PALM", "frames": hold},
                    {"kind": "shape", "label": "FIST", "frames": ESCAPE + hold},
                    {"kind": "move", "dx": 1.0, "dy": 0.0, "frames": window + 2}]},
        {"name": "wrong_shape_timeout",
         "actions": ["OPEN_PALM", "INDEX", "MOVE_RIGHT"],
         "script": [{"kind": "shape", "label": "FIST", "frames": 70}]},
        {"name": "wrong_order",
         "actions": ["OPEN_PALM", "MOVE_RIGHT", "FIST"],
         "script": [{"kind": "shape", "label": "FIST", "frames": 70}]},
        {"name": "opposite_direction_fails_immediately",
         "actions": ["MOVE_RIGHT", "OPEN_PALM", "FIST"],
         "script": [{"kind": "move", "dx": -1.0, "dy": 0.0, "frames": window}]},
        {"name": "perpendicular_waits",
         "actions": ["MOVE_RIGHT", "OPEN_PALM", "FIST"],
         "script": [{"kind": "move", "dx": 0.0, "dy": -1.0, "frames": window}]},
        {"name": "escape_gate_blocks_free_pass",
         "actions": ["MOVE_RIGHT", "OPEN_PALM", "FIST"],
         "script": [{"kind": "move", "dx": 1.0, "dy": 0.0, "frames": window + 2},
                    {"kind": "shape", "label": "OPEN_PALM", "frames": hold * 3}]},
        {"name": "escape_then_pass",
         "actions": ["MOVE_RIGHT", "OPEN_PALM", "FIST"],
         "script": [{"kind": "move", "dx": 1.0, "dy": 0.0, "frames": window + 2},
                    {"kind": "shape", "label": "FIST", "frames": ESCAPE},
                    {"kind": "shape", "label": "OPEN_PALM", "frames": hold}]},
        {"name": "hand_never_found",
         "actions": ["OPEN_PALM", "FIST", "MOVE_RIGHT"],
         "script": [{"kind": "lost", "frames": 20}]},
        {"name": "hand_lost_mid_action",
         "actions": ["OPEN_PALM", "FIST", "MOVE_RIGHT"],
         "script": [{"kind": "shape", "label": "OPEN_PALM", "frames": 2},
                    {"kind": "lost", "frames": 20}]},
    ]

    out = []
    for case in cases:
        machine, status = run_script(case["actions"], case["script"])
        out.append({**case,
                    "state": status.state.value,
                    "failReason": status.fail_reason.value if status.fail_reason else None,
                    "stepIndex": machine.step_index,
                    "stepsPassed": [bool(s.passed) for s in machine.steps]})
    return out


def main() -> int:
    detector = HandActionDetector(CONFIG)
    movement = MovementDetector(CONFIG)

    payload = {
        "_note": "scripts/export_dart_golden.py가 만든 파이썬 실행 결과. 손으로 고치지 말 것.",
        "ruleVersion": RULE_VERSION,
        "fps": FPS,
        "escapeFrames": ESCAPE,
        "extendedAngle": EXTENDED_ANGLE,
        "curledAngle": CURLED_ANGLE,
        "config": CAMEL_CONFIG,
        "synthSamples": synth_samples(),
        "shapeCases": shape_cases(detector),
        "moveCases": move_cases(movement),
        "mirroredMoveCases": mirrored_move_cases(),
        "sequenceCases": sequence_cases(),
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"{OUT.relative_to(ROOT.parent)} 생성")
    for key in ("synthSamples", "shapeCases", "moveCases",
                "mirroredMoveCases", "sequenceCases"):
        print(f"  {key}: {len(payload[key])}건")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
