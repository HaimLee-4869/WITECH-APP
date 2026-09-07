"""임계값 도출 (SPEC 4.5) → configs/challenge_config.json 생성.

도출 원칙 (SPEC 4.5):
  - 정상 동작의 p5를 통과시키고 경계 케이스의 p95를 걸러내는 지점을 찾는다.
  - 그런 지점이 없으면(두 분포가 겹치면) **자동으로 중간값을 넣지 않는다.**
    해당 임계값을 null로 두고 unresolved에 사유를 적은 뒤 크게 경고한다.
  - 모든 값에 _source로 근거 분포를 남긴다.

측정으로 정할 수 없는 항목(재시도 횟수, 화면/원본 좌표계 선택)은
derivation_policy.json에서 가져오고 _source에 '측정값 아님'을 명시한다.
"""
from __future__ import annotations

import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

import _bootstrap  # noqa: F401

from core import features as F  # noqa: E402
from core.geometry import FINGER_NAMES, NON_THUMB_FINGERS  # noqa: E402
from core.hand_action_detector import SHAPE_PATTERNS, UNKNOWN  # noqa: E402
from core.landmark_io import HERE, load_all_clips, load_json, load_paths, save_json  # noqa: E402
from core.naming import MOVE_ACTIONS, SHAPE_ACTIONS  # noqa: E402

WARNINGS: list[str] = []
UNRESOLVED: dict[str, str] = {}


def warn(message: str) -> None:
    WARNINGS.append(message)
    print(f"[경고] {message}", file=sys.stderr)


def unresolved(key: str, message: str) -> None:
    UNRESOLVED[key] = message
    warn(f"{key}: {message}")


def gap_threshold(positive_p5: float, negative_p95: float, margin_ratio: float):
    """정상 p5와 경계 p95 사이에 틈이 있으면 그 안에 임계값을 놓는다.

    틈이 없으면 (None, 겹침폭)을 돌려준다. 임의의 중간값을 만들지 않는다.
    """
    gap = float(positive_p5 - negative_p95)
    if gap <= 0:
        return None, gap
    return float(negative_p95 + margin_ratio * gap), gap


def run_lengths(mask: np.ndarray) -> list[int]:
    """True가 연속된 구간의 길이 목록."""
    runs, current = [], 0
    for value in np.asarray(mask, dtype=bool):
        if value:
            current += 1
        elif current:
            runs.append(current)
            current = 0
    if current:
        runs.append(current)
    return runs


# ------------------------------------------------------------------ 손 모양


def choose_angle_space(roles: pd.DataFrame, spaces) -> tuple[str, dict]:
    """extended와 curled 분포가 가장 넓게 벌어지는 좌표계를 고른다."""
    scores = {}
    for space in spaces:
        sub = roles[(roles.angle_space == space) & (roles.finger_group == "others")]
        ext = sub[sub.role == "extended"]
        cur = sub[sub.role == "curled"]
        if ext.empty or cur.empty:
            continue
        scores[space] = {
            "extended_p5": float(ext.p5.iloc[0]),
            "curled_p95": float(cur.p95.iloc[0]),
            "gap": float(ext.p5.iloc[0] - cur.p95.iloc[0]),
        }
    if not scores:
        raise RuntimeError("손가락 역할 분포가 비어 있다. 03을 먼저 실행할 것.")
    best = max(scores, key=lambda s: scores[s]["gap"])
    return best, scores


def derive_finger_thresholds(roles: pd.DataFrame, space: str, margin_ratio: float):
    out: dict = {}
    detail: dict = {}
    for group, key in (("others", "others"), ("thumb", "thumb")):
        sub = roles[(roles.angle_space == space) & (roles.finger_group == group)]
        ext = sub[sub.role == "extended"]
        cur = sub[sub.role == "curled"]
        if ext.empty or cur.empty:
            unresolved(f"finger_extended_angle.{key}", f"{group} 분포가 없다")
            out[key] = None
            continue
        p5, p95 = float(ext.p5.iloc[0]), float(cur.p95.iloc[0])
        threshold, gap = gap_threshold(p5, p95, margin_ratio)
        detail[key] = {"extended_p5": p5, "curled_p95": p95, "gap": gap}
        if threshold is None:
            unresolved(
                f"finger_extended_angle.{key}",
                f"펴짐 p5={p5:.1f}도가 접힘 p95={p95:.1f}도보다 낮다(겹침 {-gap:.1f}도). "
                "규칙만으로 두 상태를 가를 수 없다.")
            out[key] = None
        else:
            out[key] = round(threshold, 1)
    return out, detail


def label_frames(frames: pd.DataFrame, space: str, thumb_th, other_th) -> pd.Series:
    """도출된 임계값으로 전 프레임에 손 모양 라벨을 붙인다."""
    cols = {n: frames[f"angle_{space}_{n}"].to_numpy() for n in FINGER_NAMES}
    flags = {n: cols[n] >= other_th for n in NON_THUMB_FINGERS}
    labels = np.full(len(frames), UNKNOWN, dtype=object)
    for name, pattern in SHAPE_PATTERNS.items():
        match = np.ones(len(frames), dtype=bool)
        for finger, want in zip(NON_THUMB_FINGERS, pattern):
            match &= (flags[finger] == want)
        labels[match] = name
    labels[~frames["valid"].to_numpy()] = "NO_HAND"
    for name in NON_THUMB_FINGERS:  # 각도가 nan이면 판정 불가
        labels[~np.isfinite(cols[name])] = "NO_HAND"
    return pd.Series(labels, index=frames.index)


def evaluate_shape_targets(frames: pd.DataFrame, labels: pd.Series) -> pd.DataFrame:
    rows = []
    frames = frames.assign(label=labels)
    detected = frames[frames.label != "NO_HAND"]
    for action, grp in detected.groupby("action", sort=True):
        counts = Counter(grp.label)
        total = len(grp)
        row = {"action": action, "detected_frames": total}
        for name in list(SHAPE_PATTERNS) + [UNKNOWN]:
            row[name] = counts.get(name, 0) / total if total else float("nan")
        rows.append(row)
    return pd.DataFrame(rows)


def frame_confidences(frames: pd.DataFrame, space: str, other_th: float,
                      margin_deg: float) -> np.ndarray:
    """판정에 쓰는 4손가락 중 가장 아슬아슬한 손가락의 정규화 여유."""
    stack = np.stack([frames[f"angle_{space}_{n}"].to_numpy() for n in NON_THUMB_FINGERS])
    normalized = np.minimum(np.abs(stack - other_th) / margin_deg, 1.0)
    return np.min(normalized, axis=0)


def derive_confidence_min(frames: pd.DataFrame, labels: pd.Series, space: str,
                          other_th: float, margin_deg: float, policy):
    """정답 프레임은 통과시키고 NEG 오검출 프레임은 걸러내는 신뢰도 하한."""
    conf = frame_confidences(frames, space, other_th, margin_deg)
    work = frames.assign(label=labels, confidence=conf)
    detected = work[work.label != "NO_HAND"]

    correct = detected[(detected.action.isin(SHAPE_ACTIONS)) &
                       (detected.label == detected.action)].confidence.to_numpy()
    false_accept = detected[(detected.action.str.startswith("NEG_")) &
                            (detected.label.isin(SHAPE_PATTERNS))].confidence.to_numpy()

    if correct.size == 0:
        unresolved("shape_confidence_min", "정답으로 판정된 프레임이 없다")
        return None, "정답 프레임 없음"
    pos_p5 = float(np.percentile(correct, policy["positive_percentile"]))
    if false_accept.size == 0:
        return round(pos_p5, 3), (f"정상 영상 정답 프레임 신뢰도 "
                                  f"p{policy['positive_percentile']}={pos_p5:.3f} "
                                  f"(NEG 오검출 프레임 0개라 상한 제약 없음)")

    neg_p95 = float(np.percentile(false_accept, policy["negative_percentile"]))
    source = (f"정상 영상 정답 프레임 신뢰도 p{policy['positive_percentile']}={pos_p5:.3f} / "
              f"NEG 오검출 프레임 신뢰도 p{policy['negative_percentile']}={neg_p95:.3f} "
              f"({false_accept.size}프레임)")
    if neg_p95 >= pos_p5:
        unresolved("shape_confidence_min",
                   f"NEG 오검출 프레임의 신뢰도 p{policy['negative_percentile']}={neg_p95:.3f}가 "
                   f"정답 프레임 p{policy['positive_percentile']}={pos_p5:.3f} 이상이다. "
                   "신뢰도로 경계 케이스를 더 걸러낼 수 없다.")
        return None, source
    threshold, _ = gap_threshold(pos_p5, neg_p95, policy["separation_margin_ratio"])
    return round(threshold, 3), source


def derive_hold_frames(frames: pd.DataFrame, labels: pd.Series, policy) -> tuple[int, str]:
    """NEG 영상에서 잘못된 라벨이 연속으로 유지되는 최대 길이보다 길게 잡는다."""
    frames = frames.assign(label=labels)
    false_runs: list[int] = []
    for stem, grp in frames[frames.action.str.startswith("NEG_")].groupby("stem"):
        grp = grp.sort_values("frame")
        false_runs += run_lengths(grp.label.isin(SHAPE_PATTERNS).to_numpy())

    true_runs: list[int] = []
    for stem, grp in frames[frames.action.isin(SHAPE_ACTIONS)].groupby("stem"):
        grp = grp.sort_values("frame")
        true_runs += run_lengths((grp.label == grp.action).to_numpy())

    neg_p = float(np.percentile(false_runs, policy["negative_percentile"])) if false_runs else 0.0
    hold = max(int(np.ceil(neg_p)) + 1, int(policy["hold_frames_min"]))
    pos_p5 = float(np.percentile(true_runs, policy["positive_percentile"])) if true_runs else 0.0
    source = (f"NEG 영상 오검출 연속길이 p{policy['negative_percentile']}={neg_p:.1f}프레임 +1, "
              f"하한 {policy['hold_frames_min']} / "
              f"정상 영상 정답 연속길이 p{policy['positive_percentile']}={pos_p5:.1f}프레임")
    if pos_p5 < hold:
        warn(f"shape_hold_frames={hold}이 정상 영상의 정답 연속길이 p5={pos_p5:.1f}보다 길다. "
             "정상 사용자가 유지 조건을 못 채울 수 있다.")
    return hold, source


# ------------------------------------------------------------------ 이동


def collect_window_table(clips, window_ms: float) -> pd.DataFrame:
    rows = []
    for clip in clips:
        centers, scales = F.frame_palm_tracks(clip)
        wf = int(round(window_ms / 1000.0 * clip.fps)) if clip.fps > 0 else 0
        for m in F.sliding_window_motions(centers, scales, wf):
            if m.valid:
                rows.append({"stem": clip.meta.stem, "action": clip.meta.action,
                             "condition": clip.meta.condition or "none",
                             "displacement_ratio": m.displacement_ratio,
                             "axis_ratio": m.axis_ratio, "axis": m.axis, "sign": m.sign})
    return pd.DataFrame(rows)


def positive_move_pool(windows: pd.DataFrame, within_pct: float) -> np.ndarray:
    """MOVE 영상별 '움직이는 중' 변위를 대표하는 값들.

    한 영상에는 왕복 3회가 들어 있어 방향이 바뀌는 순간의 윈도우는 변위가 작다.
    그래서 전체 윈도우의 p5가 아니라 영상 안에서의 상위 백분위를 쓴다.
    """
    move = windows[windows.action.isin(MOVE_ACTIONS)]
    return np.array([np.percentile(g.displacement_ratio, within_pct)
                     for _, g in move.groupby("stem")])


def derive_movement(clips, policy) -> tuple[dict, dict]:
    within = policy["motion_positive_within_clip_percentile"]
    pos_pct, neg_pct = policy["positive_percentile"], policy["negative_percentile"]
    margin = policy["separation_margin_ratio"]

    # 1) 윈도우 길이: MOVE와 NEG_shake가 가장 크게 벌어지는 값을 고른다.
    scan = []
    cache: dict[float, pd.DataFrame] = {}
    for window_ms in policy["motion_window_ms_grid"]:
        windows = collect_window_table(clips, window_ms)
        if windows.empty:
            continue
        cache[window_ms] = windows
        pos = positive_move_pool(windows, within)
        shake = windows.loc[windows.action == "NEG_shake", "displacement_ratio"].to_numpy()
        if pos.size == 0 or shake.size == 0:
            continue
        p5, p95 = float(np.percentile(pos, pos_pct)), float(np.percentile(shake, neg_pct))
        scan.append({"window_ms": window_ms, "move_p5": p5, "shake_p95": p95,
                     "gap": p5 - p95})
    if not scan:
        raise RuntimeError("이동 윈도우를 하나도 만들지 못했다.")
    scan_df = pd.DataFrame(scan)
    best = scan_df.loc[scan_df.gap.idxmax()]
    window_ms = float(best.window_ms)
    windows = cache[window_ms]

    detail = {"window_scan": scan_df.to_dict("records"),
              "chosen_window_ms": window_ms,
              "move_p5": float(best.move_p5), "shake_p95": float(best.shake_p95)}

    # 2) min_displacement_ratio
    min_disp, gap = gap_threshold(float(best.move_p5), float(best.shake_p95), margin)
    disp_source = (f"MOVE_* 영상내 p{within} 변위의 p{pos_pct}={best.move_p5:.2f} / "
                   f"NEG_shake 윈도우 p{neg_pct}={best.shake_p95:.2f} "
                   f"(window={window_ms:.0f}ms, 틈={gap:.2f})")
    if min_disp is None:
        unresolved("movement.min_displacement_ratio",
                   f"MOVE p{pos_pct}={best.move_p5:.2f}가 NEG_shake p{neg_pct}="
                   f"{best.shake_p95:.2f}보다 작다(겹침 {-gap:.2f}). "
                   "흔들기와 이동을 변위 크기만으로 가를 수 없다.")

    # 3) axis_dominance_ratio — 변위 조건을 통과한 윈도우끼리 비교한다.
    axis_source = "min_displacement_ratio가 정해지지 않아 계산하지 못함"
    axis_ratio_th = None
    axis_detail = {}
    if min_disp is not None:
        passing = windows[windows.displacement_ratio >= min_disp]
        move_axis = passing.loc[passing.action.isin(MOVE_ACTIONS), "axis_ratio"]
        diag_axis = passing.loc[passing.action == "NEG_diagonal", "axis_ratio"]
        move_axis = move_axis.replace([np.inf], np.nan).dropna().to_numpy()
        diag_axis = diag_axis.replace([np.inf], np.nan).dropna().to_numpy()
        if move_axis.size and diag_axis.size:
            mp5 = float(np.percentile(move_axis, pos_pct))
            dp95 = float(np.percentile(diag_axis, neg_pct))
            axis_detail = {"move_p5": mp5, "diagonal_p95": dp95,
                           "move_n": int(move_axis.size), "diagonal_n": int(diag_axis.size)}
            axis_ratio_th, agap = gap_threshold(mp5, dp95, margin)
            axis_source = (f"MOVE_* 주축비 p{pos_pct}={mp5:.2f} / "
                           f"NEG_diagonal 주축비 p{neg_pct}={dp95:.2f} (틈={agap:.2f})")
            if axis_ratio_th is None:
                unresolved("movement.axis_dominance_ratio",
                           f"MOVE 주축비 p{pos_pct}={mp5:.2f}가 NEG_diagonal p{neg_pct}="
                           f"{dp95:.2f}보다 낮다(겹침 {-agap:.2f}). 대각선을 가를 수 없다.")
        else:
            unresolved("movement.axis_dominance_ratio", "비교할 윈도우가 없다")

    # 4) 축→방향 대응표: 실제 영상에서 관측된 다수 축/부호를 쓴다 (추측하지 않음).
    direction_map: dict[str, list] = {}
    direction_detail: dict[str, dict] = {}
    threshold_for_map = min_disp if min_disp is not None else 0.0
    for action in MOVE_ACTIONS:
        sub = windows[(windows.action == action) &
                      (windows.displacement_ratio >= threshold_for_map)]
        if axis_ratio_th is not None:
            sub = sub[sub.axis_ratio >= axis_ratio_th]
        if sub.empty:
            unresolved(f"movement.direction_map.{action}", "조건을 통과한 윈도우가 없다")
            continue
        votes = Counter(zip(sub.axis, sub.sign))
        (axis, sign), n = votes.most_common(1)[0]
        share = n / len(sub)
        direction_map[action] = [axis, int(sign)]
        direction_detail[action] = {"axis": axis, "sign": int(sign),
                                    "share": round(share, 3), "windows": len(sub)}
        if share < 0.5:
            warn(f"{action}의 주축/부호 다수결 비율이 {share:.1%}밖에 안 된다. 방향이 불안정하다.")

    used = defaultdict(list)
    for action, (axis, sign) in direction_map.items():
        used[(axis, sign)].append(action)
    for key, actions in used.items():
        if len(actions) > 1:
            unresolved("movement.direction_map",
                       f"{actions}가 같은 축/부호 {key}로 관측됐다. 서로 구분할 수 없다.")

    # 5) 획 1회에 걸리는 시간 → max_duration_ms
    stroke_source = "min_displacement_ratio 미정으로 계산하지 못함"
    max_duration_ms = None
    if min_disp is not None:
        durations = []
        for clip in clips:
            if clip.meta.action not in MOVE_ACTIONS:
                continue
            centers, scales = F.frame_palm_tracks(clip)
            axis_idx = 0 if direction_map.get(clip.meta.action, ["x"])[0] == "x" else 1
            strokes = F.count_strokes(centers, axis_idx, scales, min_disp)
            if strokes > 0 and clip.fps > 0:
                durations.append(clip.num_frames / clip.fps * 1000.0 / strokes)
        if durations:
            p = float(np.percentile(durations, policy["timeout_percentile"]))
            step = policy["timeout_round_ms"]
            max_duration_ms = int(np.ceil(p / step) * step)
            stroke_source = (f"MOVE_* 영상 획 1회 소요시간 "
                             f"p{policy['timeout_percentile']}={p:.0f}ms "
                             f"({len(durations)}개 영상, {step}ms 단위 올림)")
        else:
            unresolved("movement.max_duration_ms", "획을 하나도 검출하지 못했다")

    movement = {
        "window_ms": int(window_ms),
        "min_displacement_ratio": round(min_disp, 3) if min_disp is not None else None,
        "axis_dominance_ratio": round(axis_ratio_th, 3) if axis_ratio_th is not None else None,
        "max_duration_ms": max_duration_ms,
        "direction_map": direction_map,
        "_source": {
            "window_ms": (f"MOVE와 NEG_shake의 분리폭이 최대인 윈도우 "
                          f"({policy['motion_window_ms_grid'][0]}~"
                          f"{policy['motion_window_ms_grid'][-1]}ms 중 {window_ms:.0f}ms)"),
            "min_displacement_ratio": disp_source,
            "axis_dominance_ratio": axis_source,
            "max_duration_ms": stroke_source,
            "direction_map": ("MOVE_* 영상에서 조건을 통과한 윈도우의 주축/부호 다수결: "
                              + ", ".join(f"{a}→{d['axis']}{d['sign']:+d}({d['share']:.0%})"
                                          for a, d in direction_detail.items())),
        },
    }
    detail["axis"] = axis_detail
    detail["direction"] = direction_detail
    return movement, detail


# ------------------------------------------------------------------ 추적/타이밍


def derive_tracking(frames: pd.DataFrame, policy) -> tuple[dict, dict]:
    pos = frames[~frames.action.str.startswith("NEG_")]
    lost_runs: list[int] = []
    for stem, grp in pos.groupby("stem"):
        lost_runs += run_lengths(~grp.sort_values("frame").valid.to_numpy())
    exit_runs: list[int] = []
    for stem, grp in frames[frames.action == "NEG_exit"].groupby("stem"):
        exit_runs += run_lengths(~grp.sort_values("frame").valid.to_numpy())

    p = (float(np.percentile(lost_runs, policy["lost_frames_percentile"]))
         if lost_runs else 0.0)
    max_lost = max(int(np.ceil(p)), 1)
    exit_max = max(exit_runs) if exit_runs else 0
    if exit_max <= max_lost:
        warn(f"NEG_exit의 최대 연속 미검출 {exit_max}프레임이 max_lost_frames={max_lost} "
             "이하다. 손이 사라지는 공격을 못 잡는다.")

    scores = pos.loc[pos.valid, "detection_score"].to_numpy()
    min_score = float(np.percentile(scores, policy["positive_percentile"])) if scores.size else None

    tracking = {
        "max_lost_frames": max_lost,
        "min_detection_score": round(min_score, 3) if min_score is not None else None,
        "_source": {
            "max_lost_frames": (f"정상 영상 연속 미검출 길이 "
                                f"p{policy['lost_frames_percentile']}={p:.1f}프레임 "
                                f"/ NEG_exit 최대 연속 미검출 {exit_max}프레임"),
            "min_detection_score": (f"정상 영상 검출 프레임 detection_score "
                                    f"p{policy['positive_percentile']}={min_score:.3f}"
                                    if min_score is not None else "데이터 없음"),
        },
    }
    return tracking, {"lost_p": p, "exit_max": exit_max}


def derive_timing(frames: pd.DataFrame, labels: pd.Series, hold_frames: int,
                  movement: dict, policy, num_actions: int) -> dict:
    """단계별 제한 시간을 파일럿 영상의 소요 시간에서 뽑는다."""
    frames = frames.assign(label=labels)
    times_ms: list[float] = []
    for stem, grp in frames[frames.action.isin(SHAPE_ACTIONS)].groupby("stem"):
        grp = grp.sort_values("frame")
        correct = (grp.label == grp.action).to_numpy()
        fps = float(grp.fps.iloc[0]) or 1.0
        streak, first = 0, None
        for i, ok in enumerate(correct):
            streak = streak + 1 if ok else 0
            if streak >= hold_frames:
                first = i
                break
        if first is not None:
            times_ms.append((first + 1) / fps * 1000.0)
    move_ms = movement.get("max_duration_ms")
    if move_ms:
        times_ms.append(float(move_ms))

    step = policy["timeout_round_ms"]
    if times_ms:
        p = float(np.percentile(times_ms, policy["timeout_percentile"]))
        per_action = int(np.ceil(p / step) * step)
        source = (f"손 모양 영상에서 {hold_frames}프레임 연속 정답까지 걸린 시간과 "
                  f"이동 획 1회 시간의 p{policy['timeout_percentile']}={p:.0f}ms "
                  f"({len(times_ms)}건, {step}ms 단위 올림)")
    else:
        per_action, source = None, "측정 데이터 없음"
        unresolved("timing.per_action_timeout_ms", "정답 유지 구간을 찾지 못했다")

    return {
        "per_action_timeout_ms": per_action,
        "total_timeout_ms": per_action * num_actions if per_action else None,
        "max_retries": policy["max_retries"],
        "_source": {
            "per_action_timeout_ms": source,
            "total_timeout_ms": (f"per_action_timeout_ms × 단계 수 {num_actions}"
                                 if per_action else "미정"),
            "max_retries": "측정값 아님. " + policy["max_retries_note"],
        },
    }


# ------------------------------------------------------------------ main


def main() -> int:
    paths = load_paths()
    policy = load_json(HERE / "configs" / "derivation_policy.json")
    report_dir = Path(paths["report_out"])

    roles_path = report_dir / "summary_finger_roles.csv"
    frames_path = report_dir / "frame_features.csv"
    if not roles_path.exists() or not frames_path.exists():
        print("03_analyze_distributions.py를 먼저 실행할 것.", file=sys.stderr)
        return 1

    roles = pd.read_csv(roles_path)
    frames = pd.read_csv(frames_path)
    clips = load_all_clips(paths["landmark_cache"], paths.get("mirror_flip") or {})

    space, space_scores = choose_angle_space(roles, policy["angle_spaces_considered"])
    print("=== 좌표계 선택 ===")
    for name, s in space_scores.items():
        mark = " <= 선택" if name == space else ""
        print(f"  {name:10} extended_p5={s['extended_p5']:7.2f}  "
              f"curled_p95={s['curled_p95']:7.2f}  틈={s['gap']:7.2f}{mark}")

    finger, finger_detail = derive_finger_thresholds(roles, space,
                                                     policy["separation_margin_ratio"])
    others_th, thumb_th = finger.get("others"), finger.get("thumb")

    shape_targets = pd.DataFrame()
    hold_frames, hold_source = None, "임계값 미정으로 계산하지 못함"
    labels = None
    confidence_margin = None
    confidence_min, confidence_min_source = None, "임계값 미정으로 계산하지 못함"
    if others_th is not None:
        labels = label_frames(frames, space, thumb_th, others_th)
        shape_targets = evaluate_shape_targets(frames, labels)
        shape_targets.to_csv(report_dir / "shape_label_distribution.csv",
                             index=False, encoding="utf-8-sig")
        hold_frames, hold_source = derive_hold_frames(frames, labels, policy)
        confidence_margin = round(finger_detail["others"]["gap"] / 2.0, 1)
        confidence_min, confidence_min_source = derive_confidence_min(
            frames, labels, space, others_th, confidence_margin, policy)

    movement, movement_detail = derive_movement(clips, policy)
    tracking, _ = derive_tracking(frames, policy)
    num_actions = 3
    timing = (derive_timing(frames, labels, hold_frames, movement, policy, num_actions)
              if labels is not None else
              {"per_action_timeout_ms": None, "total_timeout_ms": None,
               "max_retries": policy["max_retries"],
               "_source": {"per_action_timeout_ms": "손 모양 임계값 미정으로 계산 못함"}})

    fd = finger_detail
    config = {
        "_generated_by": "scripts/04_derive_thresholds.py",
        "_note": ("모든 임계값은 촬영 영상의 실측 분포에서 나왔다. "
                  "_source가 없는 값은 없다. null은 분포가 겹쳐 도출하지 못한 값이다."),
        "angle_space": space,
        "_source_angle_space": (
            "extended/curled 분리폭 비교: " +
            ", ".join(f"{k}={v['gap']:.1f}도" for k, v in space_scores.items())),
        "finger_extended_angle": {
            "thumb": finger.get("thumb"),
            "others": finger.get("others"),
            "_source": {
                "others": (f"OPEN_PALM/INDEX/TWO_FINGERS의 펴야 하는 손가락 p5="
                           f"{fd['others']['extended_p5']:.1f}도 / "
                           f"FIST 등 접어야 하는 손가락 p95={fd['others']['curled_p95']:.1f}도 "
                           f"(틈={fd['others']['gap']:.1f}도)" if "others" in fd else "도출 실패"),
                "thumb": (f"OPEN_PALM 엄지 p5={fd['thumb']['extended_p5']:.1f}도 / "
                          f"FIST 엄지 p95={fd['thumb']['curled_p95']:.1f}도 "
                          f"(틈={fd['thumb']['gap']:.1f}도)" if "thumb" in fd else "도출 실패"),
            },
        },
        "shape_hold_frames": hold_frames,
        "_source_shape_hold_frames": hold_source,
        "shape_confidence_margin_deg": confidence_margin,
        "_source_shape_confidence_margin_deg": (
            f"펴짐/접힘 분포 틈 {fd['others']['gap']:.1f}도의 절반"
            if "others" in fd else "도출 실패"),
        "shape_confidence_min": confidence_min,
        "_source_shape_confidence_min": confidence_min_source,
        "movement": movement,
        "timing": timing,
        "tracking": tracking,
        "coordinate_frame": policy["coordinate_frame"],
        "_source_coordinate_frame": "측정값 아님. " + policy["coordinate_frame_note"],
        "_unresolved": UNRESOLVED,
        "_warnings": WARNINGS,
    }

    out_path = HERE / "configs" / "challenge_config.json"
    save_json(out_path, config)

    print("\n=== 손 모양 임계값 ===")
    for key, value in (("others", others_th), ("thumb", thumb_th)):
        d = finger_detail.get(key, {})
        print(f"  {key:7} = {value}   (extended_p5={d.get('extended_p5', float('nan')):.1f}, "
              f"curled_p95={d.get('curled_p95', float('nan')):.1f}, "
              f"틈={d.get('gap', float('nan')):.1f}도)")

    if not shape_targets.empty:
        print("\n=== 도출된 임계값으로 라벨링한 프레임 비율 (검출된 프레임 기준) ===")
        cols = ["action", "detected_frames"] + list(SHAPE_PATTERNS) + [UNKNOWN]
        with pd.option_context("display.width", 200, "display.max_columns", 20):
            print(shape_targets[cols].to_string(
                index=False, float_format=lambda v: f"{v * 100:6.1f}%"))

    print("\n=== 이동 임계값 ===")
    print(f"  window_ms              = {movement['window_ms']}")
    print(f"  min_displacement_ratio = {movement['min_displacement_ratio']}")
    print(f"  axis_dominance_ratio   = {movement['axis_dominance_ratio']}")
    print(f"  max_duration_ms        = {movement['max_duration_ms']}")
    print(f"  direction_map          = {movement['direction_map']}")
    print(f"\n  추적: {tracking['max_lost_frames']}프레임, "
          f"최소 점수 {tracking['min_detection_score']}")
    print(f"  타이밍: 단계 {timing['per_action_timeout_ms']}ms / "
          f"전체 {timing['total_timeout_ms']}ms")

    if UNRESOLVED:
        print("\n" + "!" * 74, file=sys.stderr)
        print("!! 분포가 겹쳐 도출하지 못한 임계값이 있다. 임의 값으로 채우지 않았다.",
              file=sys.stderr)
        for key, message in UNRESOLVED.items():
            print(f"!!  {key}: {message}", file=sys.stderr)
        print("!" * 74, file=sys.stderr)

    print(f"\nconfig 저장: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
