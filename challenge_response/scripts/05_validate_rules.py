"""규칙 검증 (SPEC 4.11).

실시간 촬영 없이 파일럿 영상만으로 판정기가 제대로 동작하는지 확인한다.
도출된 challenge_config.json을 그대로 쓴다.

  손 모양 영상 -> 판정이 파일명 동작과 일치하는 프레임 비율
  MOVE 영상    -> 왕복 3회가 모두 올바른 방향으로 검출되는지
  NEG 영상     -> UNKNOWN / NONE으로 나오는 프레임 비율

결과를 혼동 행렬로 출력하고 SPEC 4.11 목표 대비 달성 여부를 표기한다.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

import _bootstrap  # noqa: F401

from core import features as F  # noqa: E402
from core.hand_action_detector import SHAPE_PATTERNS, UNKNOWN, HandActionDetector  # noqa: E402
from core.landmark_io import HERE, load_all_clips, load_json, load_paths  # noqa: E402
from core.movement_detector import NONE, MovementDetector  # noqa: E402
from core.naming import MOVE_ACTIONS, SHAPE_ACTIONS  # noqa: E402

SHAPE_LABELS = list(SHAPE_PATTERNS) + [UNKNOWN, "NO_HAND"]
MOVE_LABELS = list(MOVE_ACTIONS) + [NONE]


def classify_shapes(clip, detector: HandActionDetector) -> list[str]:
    coords = F.angle_source(clip, detector.angle_space)
    gate = detector_confidence_gate(detector)
    labels = []
    for i in range(clip.num_frames):
        if not clip.valid_mask[i]:
            labels.append("NO_HAND")
            continue
        result = detector.detect(coords[i])
        labels.append(result.label if result.confidence >= gate else UNKNOWN)
    return labels


def detector_confidence_gate(detector: HandActionDetector) -> float:
    return getattr(detector, "confidence_min", 0.0)


def detect_move_events(clip, movement: MovementDetector, trim_windows: int) -> list[dict]:
    """영상을 훑으며 이동 검출 '사건'을 뽑는다.

    연속으로 같은 방향이 검출되면 한 사건으로 묶는다. 왕복 3회면 라벨 방향으로
    3번 검출되어야 한다.
    """
    centers, scales = F.frame_palm_tracks(clip)
    wf = movement.window_frames(clip.fps)
    start, stop = F.stable_span(np.isfinite(scales), wf * trim_windows)
    centers, scales = centers[start:stop], scales[start:stop]

    events: list[dict] = []
    previous = NONE
    for i in range(0, max(len(scales) - wf + 1, 0)):
        result = movement.detect_from_tracks(centers[i:i + wf], scales[i:i + wf])
        if result.label != NONE and result.label != previous:
            events.append({"frame": start + i, "label": result.label,
                           "displacement": result.displacement_ratio,
                           "axis_ratio": result.axis_ratio})
        previous = result.label
    return events


def main() -> int:
    paths = load_paths()
    config_path = HERE / "configs" / "challenge_config.json"
    if not config_path.exists():
        print("04_derive_thresholds.py를 먼저 실행할 것.", file=sys.stderr)
        return 1
    config = load_json(config_path)
    policy = load_json(HERE / "configs" / "derivation_policy.json")
    targets = policy["targets"]
    trim = int(policy["motion_edge_trim_windows"])

    if config.get("finger_extended_angle", {}).get("others") is None:
        print("손 모양 임계값이 도출되지 않았다. 검증할 수 없다.", file=sys.stderr)
        return 1

    shape_detector = HandActionDetector(config)
    confidence_min = config.get("shape_confidence_min")
    shape_detector.confidence_min = float(confidence_min) if confidence_min else 0.0

    # 파일럿 영상은 원본 좌표계다. 화면 기준 반전은 실시간 프로토타입에서만 적용한다.
    movement = MovementDetector({**config, "coordinate_frame": "raw"})

    clips = load_all_clips(paths["landmark_cache"], paths.get("mirror_flip") or {})
    report_dir = Path(paths["report_out"])
    report_dir.mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------- 손 모양
    shape_rows = []
    for clip in clips:
        labels = classify_shapes(clip, shape_detector)
        for label in labels:
            shape_rows.append({"action": clip.meta.action, "stem": clip.meta.stem,
                               "condition": clip.meta.condition or "none",
                               "predicted": label})
    shapes = pd.DataFrame(shape_rows)
    detected = shapes[shapes.predicted != "NO_HAND"]

    confusion = pd.crosstab(detected.action, detected.predicted,
                            normalize="index").reindex(columns=SHAPE_LABELS[:-1], fill_value=0.0)
    confusion.to_csv(report_dir / "confusion_shape.csv", encoding="utf-8-sig")

    print("=" * 78)
    print("손 모양 혼동 행렬 (검출된 프레임 기준, 행 합계 100%)")
    print("=" * 78)
    print((confusion * 100).round(1).to_string())

    # ---------------------------------------------------------- 이동
    move_rows = []
    for clip in clips:
        if clip.meta.action not in MOVE_ACTIONS and not clip.meta.is_negative:
            continue
        events = detect_move_events(clip, movement, trim)
        counts = pd.Series([e["label"] for e in events]).value_counts()
        move_rows.append({
            "stem": clip.meta.stem, "action": clip.meta.action,
            "condition": clip.meta.condition or "none",
            "events_total": len(events),
            "events_correct": int(counts.get(clip.meta.action, 0)),
            "events_wrong": int(len(events) - counts.get(clip.meta.action, 0)),
            "labels": ", ".join(f"{k}×{v}" for k, v in counts.items()) or "(없음)",
        })
    moves = pd.DataFrame(move_rows)
    moves.to_csv(report_dir / "validate_movement.csv", index=False, encoding="utf-8-sig")

    print()
    print("=" * 78)
    print("이동 검출 (왕복 3회 = 라벨 방향으로 3회 검출되어야 함)")
    print("=" * 78)
    print(moves[["stem", "events_total", "events_correct", "labels"]].to_string(index=False))

    # ---------------------------------------------------------- 목표 대비
    def shape_correct(action: str) -> float:
        row = confusion.loc[action] if action in confusion.index else None
        return float(row[action]) if row is not None and action in row else float("nan")

    def shape_leak(action: str, into) -> float:
        if action not in confusion.index:
            return float("nan")
        return float(sum(confusion.loc[action].get(t, 0.0) for t in into))

    results = []
    for action in SHAPE_ACTIONS:
        value = shape_correct(action)
        results.append((f"{action} 정확 판정 프레임", f"{value * 100:.1f}%",
                        f">= {targets['shape_correct_min'] * 100:.0f}%",
                        value >= targets["shape_correct_min"]))

    leak = shape_leak("NEG_halffist", ("OPEN_PALM", "FIST"))
    results.append(("NEG_halffist -> OPEN_PALM/FIST", f"{leak * 100:.1f}%",
                    f"< {targets['halffist_false_accept_max'] * 100:.0f}%",
                    leak < targets["halffist_false_accept_max"]))
    for action in ("NEG_threefingers", "NEG_indexring"):
        leak = shape_leak(action, ("TWO_FINGERS",))
        results.append((f"{action} -> TWO_FINGERS", f"{leak * 100:.1f}%",
                        f"< {targets['twofingers_false_accept_max'] * 100:.0f}%",
                        leak < targets["twofingers_false_accept_max"]))

    move_clips = moves[moves.action.isin(MOVE_ACTIONS)]
    worst = int(move_clips.events_correct.min()) if not move_clips.empty else 0
    ok_clips = int((move_clips.events_correct >= targets["move_strokes_required"]).sum())
    results.append((f"MOVE_* 왕복 3회 검출 ({ok_clips}/{len(move_clips)}영상)",
                    f"최소 {worst}회", f">= {targets['move_strokes_required']}회",
                    ok_clips == len(move_clips)))

    shake = moves[moves.action == "NEG_shake"]
    shake_events = int(shake.events_total.sum()) if not shake.empty else 0
    results.append(("NEG_shake 이동 검출", f"{shake_events}회",
                    f"<= {targets['shake_detections_max']}회",
                    shake_events <= targets["shake_detections_max"]))

    diagonal_share = float("nan")
    diag_clips = [c for c in clips if c.meta.action == "NEG_diagonal"]
    if diag_clips:
        confirmed = total = 0
        for clip in diag_clips:
            centers, scales = F.frame_palm_tracks(clip)
            wf = movement.window_frames(clip.fps)
            start, stop = F.stable_span(np.isfinite(scales), wf * trim)
            centers, scales = centers[start:stop], scales[start:stop]
            for i in range(0, max(len(scales) - wf + 1, 0)):
                result = movement.detect_from_tracks(centers[i:i + wf], scales[i:i + wf])
                total += 1
                confirmed += result.label != NONE
        diagonal_share = confirmed / total if total else float("nan")
    results.append(("NEG_diagonal 단일 방향 확정 비율", f"{diagonal_share * 100:.1f}%",
                    f"< {targets['diagonal_confirmed_max'] * 100:.0f}%",
                    diagonal_share < targets["diagonal_confirmed_max"]))

    print()
    print("=" * 78)
    print("SPEC 4.11 목표 대비")
    print("=" * 78)
    width = max(len(r[0]) for r in results)
    for name, value, target, passed in results:
        print(f"  {name:<{width}}  {value:>10}  (목표 {target:>7})  "
              f"{'달성' if passed else '미달'}")

    summary = pd.DataFrame(results, columns=["항목", "측정값", "목표", "달성"])
    summary.to_csv(report_dir / "validate_targets.csv", index=False, encoding="utf-8-sig")

    failed = [r[0] for r in results if not r[3]]
    if failed:
        print(f"\n미달 항목 {len(failed)}개: {', '.join(failed)}", file=sys.stderr)
    print(f"\n리포트: {report_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
