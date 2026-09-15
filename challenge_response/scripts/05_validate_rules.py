"""규칙 검증 (SPEC 4.11).

실시간 촬영 없이 파일럿 영상만으로 판정기가 제대로 동작하는지 확인한다.
도출된 challenge_config.json을 그대로 쓴다.

  손 모양 영상 -> 판정이 파일명 동작과 일치하는 프레임 비율
  MOVE 영상    -> 편도 1회(정지 -> 한 방향 -> 제자리 정지)마다 처음 검출된 방향이
                  라벨과 같은지. 튕기는 방식으로 찍은 영상만 평가한다.
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
from core.challenge_state_machine import Observation  # noqa: E402
from core.naming import MOVE_ACTIONS, SHAPE_ACTIONS  # noqa: E402
from core.negative_eval import diagonal_request_target, request_passes  # noqa: E402

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


def trimmed_tracks(clip, movement: MovementDetector, trim_windows: int):
    """진입·이탈 구간을 자른 손바닥 궤적. (centers, scales, 시작 프레임, 윈도우 프레임 수)"""
    centers, scales = F.frame_palm_tracks(clip)
    wf = movement.window_frames(clip.fps)
    start, stop = F.stable_span(np.isfinite(scales), wf * trim_windows)
    return centers[start:stop], scales[start:stop], start, wf


def detect_move_events(clip, movement: MovementDetector, trim_windows: int) -> list[dict]:
    """영상을 훑으며 이동 검출 '사건'을 뽑는다.

    연속으로 같은 방향이 검출되면 한 사건으로 묶는다.
    """
    centers, scales, start, wf = trimmed_tracks(clip, movement, trim_windows)

    events: list[dict] = []
    previous = NONE
    for i in range(0, max(len(scales) - wf + 1, 0)):
        result = movement.detect_from_tracks(centers[i:i + wf], scales[i:i + wf])
        if result.label != NONE and result.label != previous:
            events.append({"frame": start + i, "window": i, "label": result.label,
                           "displacement": result.displacement_ratio,
                           "axis_ratio": result.axis_ratio})
        previous = result.label
    return events


def evaluate_one_way(clip, events: list[dict], movement: MovementDetector,
                     config: dict, trim_windows: int) -> dict:
    """편도 1회 기준 검증 (2026-09-16, README 4장).

    실시간 이동 단계는 정지 상태에서 요청 방향으로 한 번 움직이는 것을 판정한다.
    튕기는 방식 영상을 '정지 -> 한 방향 이동 -> 제자리 정지' 구간으로 나누고,
    각 구간에서 **처음 검출된 방향**이 라벨과 같아야 성공으로 센다. 구간 안에서
    아무것도 검출되지 않으면 실패다. 판별 규칙은 04와 같은 F.move_style이다.
    """
    move_cfg = config["movement"]
    centers, scales, _, wf = trimmed_tracks(clip, movement, trim_windows)
    rest = move_cfg.get("rest_displacement_ratio")
    if rest is None:
        return {"style": "판별 불가(rest_displacement_ratio 없음)", "one_way_trials": 0,
                "one_way_correct": 0, "one_way_firsts": ""}
    style = F.move_style(centers, scales, wf, float(rest),
                         float(move_cfg["min_displacement_ratio"]))
    if not style.is_flick:
        return {"style": style.reason, "one_way_trials": 0, "one_way_correct": 0,
                "one_way_firsts": ""}
    firsts = []
    previous_end = 0
    for _, end in style.one_way_bouts():
        # 직전 복귀 정지부터 센다. 획을 처음 잡는 윈도우는 '이탈'로 판정된 윈도우보다
        # 조금 앞에서 시작할 수 있다. 그 사이 손은 출발점에 멈춰 있으므로 다른 획이 없다.
        inside = [e for e in events if previous_end <= e["window"] < end]
        firsts.append(inside[0]["label"] if inside else NONE)
        previous_end = end
    return {"style": "튕기는 방식", "one_way_trials": len(firsts),
            "one_way_correct": sum(f == clip.meta.action for f in firsts),
            "one_way_firsts": ", ".join(f.replace("MOVE_", "") for f in firsts)}


def clip_observations(clip) -> list:
    """캐시된 영상 전체를 실시간 입력처럼 Observation으로 (진입·이탈 구간도 그대로 둔다)."""
    angle = F.angle_source(clip, "image_iso")
    screen = F.screen_coords(clip)
    out = []
    for i in range(clip.num_frames):
        t = i * 1000.0 / clip.fps
        if clip.valid_mask[i]:
            out.append(Observation(t, True, float(clip.detection_score[i]), angle[i], screen[i]))
        else:
            out.append(Observation(t, False))
    return out


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
        row = {
            "stem": clip.meta.stem, "action": clip.meta.action,
            "condition": clip.meta.condition or "none",
            "events_total": len(events),
            "events_correct": int(counts.get(clip.meta.action, 0)),
            "events_wrong": int(len(events) - counts.get(clip.meta.action, 0)),
            "labels": ", ".join(f"{k}×{v}" for k, v in counts.items()) or "(없음)",
        }
        if clip.meta.action in MOVE_ACTIONS:
            row.update(evaluate_one_way(clip, events, movement, config, trim))
        move_rows.append(row)
    moves = pd.DataFrame(move_rows)
    moves.to_csv(report_dir / "validate_movement.csv", index=False, encoding="utf-8-sig")

    move_only = moves[moves.action.isin(MOVE_ACTIONS)].astype(
        {"one_way_trials": int, "one_way_correct": int})
    print()
    print("=" * 78)
    print("이동 검출 — 편도 (튕기는 방식 영상의 '정지 -> 이동 -> 제자리 정지'마다 첫 검출 방향)")
    print("=" * 78)
    print(move_only[["stem", "style", "one_way_trials", "one_way_correct",
                     "one_way_firsts"]].to_string(index=False))
    print()
    print("참고: 검출 사건 전체 (파일럿 촬영의 왕복 횟수 기준, 목표 아님)")
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

    flick_clips = move_only[move_only.style == "튕기는 방식"]
    trials = int(flick_clips.one_way_trials.sum()) if not flick_clips.empty else 0
    correct = int(flick_clips.one_way_correct.sum()) if not flick_clips.empty else 0
    share = correct / trials if trials else float("nan")
    minimum = targets["move_one_way_correct_min"]
    results.append((f"MOVE_* 편도 첫 검출 방향 ({correct}/{trials}회, "
                    f"튕기는 방식 {len(flick_clips)}/{len(move_only)}영상)",
                    f"{share * 100:.1f}%", f">= {minimum * 100:.0f}%",
                    bool(trials) and share >= minimum))

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
    # 요청 1회 기준 (2026-09-16): 영상 x 요청 방향마다 실제 상태 머신(제한 시간·재시도 포함)으로
    # 통과 여부를 잰다. 파일럿 캐시는 원본 좌표계라 raw로 판정한다. 채점은 이 항목으로 한다.
    raw_config = {**config, "coordinate_frame": "raw"}
    request_hits = request_pairs = 0
    request_rows = []
    for clip in diag_clips:
        passes = request_passes(raw_config, clip_observations(clip), clip.fps)
        request_hits += sum(v is not None for v in passes.values())
        request_pairs += len(passes)
        request_rows.append({"stem": clip.meta.stem,
                             **{a: ("" if v is None else round(v)) for a, v in passes.items()}})
    request_rate = request_hits / request_pairs if request_pairs else float("nan")
    request_limit = diagonal_request_target(targets, config)
    if request_rows:
        pd.DataFrame(request_rows).to_csv(report_dir / "validate_diagonal_requests.csv",
                                          index=False, encoding="utf-8-sig")
    results.append((f"NEG_diagonal 요청 1회 통과율 ({request_hits}/{request_pairs}쌍)",
                    f"{request_rate * 100:.1f}%", f"<= {request_limit * 100:.0f}%",
                    request_rate <= request_limit))
    # 정상 MOVE 영상에 같은 축 반대 방향을 요청했을 때 통과율 (README 5.10). 되돌아오는 획
    # 때문에 생기는 약점이라 목표는 없고 참고로 추적한다(passed=None).
    opposite = {"MOVE_LEFT": "MOVE_RIGHT", "MOVE_RIGHT": "MOVE_LEFT",
                "MOVE_UP": "MOVE_DOWN", "MOVE_DOWN": "MOVE_UP"}
    opp_hits = opp_total = 0
    for clip in clips:
        if clip.meta.action not in MOVE_ACTIONS:
            continue
        passes = request_passes(raw_config, clip_observations(clip), clip.fps,
                                directions=(opposite[clip.meta.action],))
        opp_hits += sum(v is not None for v in passes.values())
        opp_total += 1
    if opp_total:
        results.append((f"(참고) MOVE 영상에 반대 방향 요청 시 통과율 ({opp_hits}/{opp_total})",
                        f"{opp_hits / opp_total * 100:.1f}%", "-", None))
    # 윈도우 비율은 '한 번만 걸리면 통과'를 반영하지 못해 참고로만 남긴다(passed=None).
    results.append(("(참고) NEG_diagonal 단일 방향 확정 윈도우 비율", f"{diagonal_share * 100:.1f}%",
                    f"< {targets['diagonal_confirmed_max'] * 100:.0f}%", None))

    print()
    print("=" * 78)
    print("SPEC 4.11 목표 대비")
    print("=" * 78)
    width = max(len(r[0]) for r in results)
    def mark(passed):
        return "참고" if passed is None else ("달성" if passed else "미달")

    for name, value, target, passed in results:
        print(f"  {name:<{width}}  {value:>10}  (목표 {target:>7})  {mark(passed)}")

    summary = pd.DataFrame([(n, v, t, mark(p)) for n, v, t, p in results],
                           columns=["항목", "측정값", "목표", "달성"])
    summary.to_csv(report_dir / "validate_targets.csv", index=False, encoding="utf-8-sig")

    failed = [r[0] for r in results if r[3] is False]
    if failed:
        print(f"\n미달 항목 {len(failed)}개: {', '.join(failed)}", file=sys.stderr)
    print(f"\n리포트: {report_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
