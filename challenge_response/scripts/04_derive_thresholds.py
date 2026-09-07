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
from core.naming import (MOVE_ACTIONS, SHAPE_ACTIONS,  # noqa: E402
                         SHAPE_NEG_ACTIONS)

WARNINGS: list[str] = []
UNRESOLVED: dict[str, str] = {}


def warn(message: str) -> None:
    WARNINGS.append(message)
    print(f"[경고] {message}", file=sys.stderr)


def unresolved(key: str, message: str) -> None:
    UNRESOLVED[key] = message
    warn(f"{key}: {message}")


def derivable_shape_negatives(policy) -> tuple[str, ...]:
    """임계값 도출 근거로 쓸 손 모양 반례.

    이미 '규칙으로 분리 불가'로 확정된 반례를 근거에 넣으면, 그 반례를 못 막는
    대신 다른 임계값이 통째로 망가진다. 제외하고 미해결 항목으로 따로 보고한다.
    """
    excluded = set(policy.get("unresolvable_shape_negatives", []))
    return tuple(a for a in SHAPE_NEG_ACTIONS if a not in excluded)


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
    # NEG_shake / NEG_diagonal / NEG_exit은 손 모양이 정상(편 손)인 채로 움직이는
    # 영상이라 OPEN_PALM 판정이 '오검출'이 아니다. 손 모양 반례만 넣는다.
    usable_negatives = derivable_shape_negatives(policy)
    false_accept = detected[(detected.action.isin(usable_negatives)) &
                            (detected.label.isin(SHAPE_PATTERNS))].confidence.to_numpy()

    if correct.size == 0:
        unresolved("shape_confidence_min", "정답으로 판정된 프레임이 없다")
        return None, "정답 프레임 없음"
    pos_p5 = float(np.percentile(correct, policy["positive_percentile"]))
    if false_accept.size == 0:
        return round(pos_p5, 3), (
            f"정상 영상 정답 프레임 신뢰도 p{policy['positive_percentile']}={pos_p5:.3f}, "
            f"{', '.join(usable_negatives)}에서 오검출 프레임 0개라 상한 제약 없음")

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


def derive_escape_frames(frames: pd.DataFrame, labels: pd.Series,
                         policy) -> tuple[int, str]:
    """이전 손 모양에서 '벗어났다'고 인정할 연속 프레임 수.

    단계가 바뀔 때 이전 동작의 손 모양이 그대로 다음 요청을 만족하면, 사용자가
    아무것도 하지 않아도 통과된다. MOVE_*는 손바닥을 편 채로 수행하므로 이동
    다음 단계가 OPEN_PALM이면 공짜로 넘어간다. 공격자도 손바닥 편 영상 하나로
    그 단계를 통과할 수 있다는 뜻이라 UX가 아니라 보안 문제다.

    그래서 이전 모양에서 벗어난 프레임을 일정 수 관측한 뒤에야 판정을 시작한다.
    이 값이 너무 작으면 순간 오검출만으로 관문이 열려 방어가 무력해지므로,
    **손 모양을 유지하는 동안 생기는 오검출 구간**보다 길어야 한다.
    그 분포를 파일럿 영상에서 잰다.
    """
    work = frames.assign(label=labels)
    noise_runs: list[int] = []
    for stem, grp in work[work.action.isin(SHAPE_ACTIONS)].groupby("stem"):
        grp = grp.sort_values("frame")
        grp = grp[grp.label != "NO_HAND"]
        noise_runs += run_lengths((grp.label != grp.action).to_numpy())

    minimum = int(policy["escape_frames_min"])
    if not noise_runs:
        return minimum, "오검출 구간이 하나도 없어 하한값을 그대로 씀"

    array = np.asarray(noise_runs, dtype=float)
    basis = policy.get("escape_frames_basis", "percentile")
    percentile = float(np.percentile(array, policy["negative_percentile"]))
    observed_max = float(array.max())

    if basis == "max":
        escape = max(int(np.ceil(observed_max)) + 1, minimum)
        rule = (f"관측된 최대치 {observed_max:.0f}프레임 +1")
        why = ("다른 임계값과 달리 negative_percentile을 쓰지 않는다. 이탈 관문은 "
               "보안 관문이라 잡음 구간 하나만 관문을 열어도 그 시도의 방어가 "
               f"무력해진다. p{policy['negative_percentile']}={percentile:.1f}로 잡으면 "
               f"관측된 {int((array > np.ceil(percentile) + 1).sum())}개 구간이 "
               "관문을 열 수 있다.")
    else:
        escape = max(int(np.ceil(percentile)) + 1, minimum)
        rule = f"p{policy['negative_percentile']}={percentile:.1f}프레임 +1"
        why = ""

    source = (f"손 모양 영상에서 라벨이 정답과 다른 구간(오검출 잡음)의 길이 "
              f"{rule}, 하한 {minimum} "
              f"(구간 {array.size:.0f}개, p50={np.median(array):.0f}, "
              f"p{policy['negative_percentile']}={percentile:.1f}, "
              f"최대 {observed_max:.0f}프레임). "
              + (why + " " if why else "")
              + "정상적인 손 모양 변경에 걸리는 시간은 파일럿 영상으로 잴 수 없어 "
                "근거에 넣지 못했다.")

    if observed_max >= escape:
        warn(f"escape_frames={escape}인데 오검출 구간 최대치가 "
             f"{observed_max:.0f}프레임이다. 드물게 잡음만으로 관문이 열릴 수 있다.")
    if array.size < 30:
        warn(f"escape_frames 근거 표본이 {array.size:.0f}개뿐이다. "
             "실사용 세션이 쌓이면 다시 재야 한다.")
    return escape, source


def derive_hold_frames(frames: pd.DataFrame, labels: pd.Series, policy) -> tuple[int, str]:
    """NEG 영상에서 잘못된 라벨이 연속으로 유지되는 최대 길이보다 길게 잡는다."""
    frames = frames.assign(label=labels)
    false_runs: list[int] = []
    # 손 모양 반례 영상에서만 센다. 이동 반례는 편 손을 유지한 채 움직이는
    # 영상이라 OPEN_PALM이 오래 유지되는 게 정상이다.
    for stem, grp in frames[frames.action.isin(
            derivable_shape_negatives(policy))].groupby("stem"):
        grp = grp.sort_values("frame")
        false_runs += run_lengths(grp.label.isin(SHAPE_PATTERNS).to_numpy())

    true_runs: list[int] = []
    for stem, grp in frames[frames.action.isin(SHAPE_ACTIONS)].groupby("stem"):
        grp = grp.sort_values("frame")
        true_runs += run_lengths((grp.label == grp.action).to_numpy())

    neg_p = float(np.percentile(false_runs, policy["negative_percentile"])) if false_runs else 0.0
    hold = max(int(np.ceil(neg_p)) + 1, int(policy["hold_frames_min"]))
    pos_p5 = float(np.percentile(true_runs, policy["positive_percentile"])) if true_runs else 0.0
    source = (f"{', '.join(derivable_shape_negatives(policy))} 영상의 오검출 연속길이 "
              f"p{policy['negative_percentile']}={neg_p:.1f}프레임 +1, "
              f"하한 {policy['hold_frames_min']} / "
              f"정상 영상 정답 연속길이 p{policy['positive_percentile']}={pos_p5:.1f}프레임 "
              f"(제외: {', '.join(policy['unresolvable_shape_negatives']) or '없음'})")
    if pos_p5 < hold:
        warn(f"shape_hold_frames={hold}이 정상 영상의 정답 연속길이 p5={pos_p5:.1f}보다 길다. "
             "정상 사용자가 유지 조건을 못 채울 수 있다.")
    return hold, source


# ------------------------------------------------------------------ 이동


def clip_motion_profile(clip, window_ms: float, trim_windows: int) -> dict:
    """영상 1개의 이동 특성. 앞뒤 진입/이탈 구간은 잘라낸다."""
    centers, scales = F.frame_palm_tracks(clip)
    wf = max(int(round(window_ms / 1000.0 * clip.fps)), 2) if clip.fps > 0 else 0
    start, stop = F.stable_span(np.isfinite(scales), wf * trim_windows)
    centers, scales = centers[start:stop], scales[start:stop]

    axis, span, axis_ratio = F.primary_axis(centers, scales)
    return {
        "stem": clip.meta.stem, "action": clip.meta.action,
        "condition": clip.meta.condition or "none",
        "centers": centers, "scales": scales, "window_frames": wf, "fps": clip.fps,
        "axis": axis, "span": span, "clip_axis_ratio": axis_ratio,
        "motions": [m for m in F.sliding_window_motions(centers, scales, wf) if m.valid],
    }


def usable_move_clips(profiles):
    """이동 임계값 도출에 쓸 수 있는 MOVE 영상을 고른다.

    기준은 데이터에서 나온다: 일부러 대각선으로 찍은 NEG_diagonal 영상보다도
    축 지배력이 낮은 MOVE 영상은 '한 축으로 움직인 촬영'이라고 볼 수 없다.
    그런 영상까지 넣으면 축 임계값으로 대각선과 정상 이동을 가를 수 없게 된다.
    """
    diagonal = [p["clip_axis_ratio"] for p in profiles
                if p["action"] == "NEG_diagonal" and np.isfinite(p["clip_axis_ratio"])]
    ceiling = float(max(diagonal)) if diagonal else 0.0

    usable, rejected = [], []
    for p in profiles:
        if p["action"] not in MOVE_ACTIONS:
            continue
        expected = "x" if p["action"] in ("MOVE_LEFT", "MOVE_RIGHT") else "y"
        observed = "x" if p["axis"] == 0 else "y"
        if p["clip_axis_ratio"] <= ceiling or observed != expected:
            rejected.append({"stem": p["stem"], "axis_ratio": round(p["clip_axis_ratio"], 2),
                             "observed_axis": observed, "expected_axis": expected})
        else:
            usable.append(p)
    return usable, rejected, ceiling


def derive_movement(clips, policy):
    trim = int(policy["motion_edge_trim_windows"])
    pos_pct, neg_pct = policy["positive_percentile"], policy["negative_percentile"]
    within = policy["motion_positive_within_clip_percentile"]
    margin = policy["separation_margin_ratio"]
    grid = policy["motion_window_ms_grid"]

    # 1) 획 1회 소요시간부터 잰다. 평균선 교차 횟수로 재므로 임계값이 필요 없다.
    probe = [clip_motion_profile(c, float(np.median(grid)), trim) for c in clips]
    usable, rejected, ceiling = usable_move_clips(probe)
    if not usable:
        unresolved("movement", "쓸 수 있는 MOVE 영상이 없다")
        return {"_source": {}}, {"rejected": rejected}
    for r in rejected:
        warn(f"MOVE 영상 제외: {r['stem']} — 영상 축비 {r['axis_ratio']}"
             f"(NEG_diagonal 최대 {ceiling:.2f} 이하), "
             f"관측 주축 {r['observed_axis']} / 기대 {r['expected_axis']}")

    durations = np.array([d for d in
                          (F.stroke_duration_ms(p["centers"], p["scales"], p["axis"], p["fps"])
                           for p in usable) if np.isfinite(d)])
    if durations.size == 0:
        unresolved("movement.window_ms", "획 소요시간을 재지 못했다")
        return {"_source": {}}, {"rejected": rejected}

    fastest = float(np.percentile(durations, policy["stroke_window_percentile"]))
    slowest = float(np.percentile(durations, policy["stroke_timeout_percentile"]))
    window_ms = float(min(grid, key=lambda w: abs(w - fastest)))
    step = policy["timeout_round_ms"]
    max_duration_ms = int(np.ceil(slowest / step) * step)

    # 2) 정한 윈도우로 다시 훑는다.
    profiles = [clip_motion_profile(c, window_ms, trim) for c in clips]
    usable, rejected, ceiling = usable_move_clips(profiles)
    usable_stems = {p["stem"] for p in usable}

    def frame(pred):
        rows = []
        for p in profiles:
            if not pred(p):
                continue
            for m in p["motions"]:
                rows.append({"stem": p["stem"], "action": p["action"],
                             "displacement_ratio": m.displacement_ratio,
                             "axis_ratio": m.axis_ratio, "axis": m.axis, "sign": m.sign})
        return pd.DataFrame(rows)

    move = frame(lambda p: p["stem"] in usable_stems)
    shake = frame(lambda p: p["action"] == "NEG_shake")
    diagonal = frame(lambda p: p["action"] == "NEG_diagonal")

    # 3) min_displacement_ratio. 왕복 영상은 방향이 바뀌는 순간의 윈도우 변위가 작으므로
    #    전체 p5가 아니라 '움직이는 중'을 대표하는 영상 내 상위 백분위를 쓴다.
    per_clip = np.array([np.percentile(g.displacement_ratio, within)
                         for _, g in move.groupby("stem")])
    move_p5 = float(np.percentile(per_clip, pos_pct))
    shake_p95 = float(np.percentile(shake.displacement_ratio, neg_pct))
    min_disp, disp_gap = gap_threshold(move_p5, shake_p95, margin)
    disp_source = (f"MOVE 영상별 p{within} 변위의 p{pos_pct}={move_p5:.3f} / "
                   f"NEG_shake 윈도우 p{neg_pct}={shake_p95:.3f} "
                   f"(window={window_ms:.0f}ms, 진입·이탈 {trim}윈도우 제외, "
                   f"틈={disp_gap:.3f})")
    if min_disp is None:
        unresolved("movement.min_displacement_ratio",
                   f"MOVE p{pos_pct}={move_p5:.3f}가 NEG_shake p{neg_pct}="
                   f"{shake_p95:.3f}보다 작다(겹침 {-disp_gap:.3f}).")

    # 4) axis_dominance_ratio. 양쪽 다 '획 구간' 윈도우끼리 비교한다.
    def stroke_axis_ratios(df):
        pools = []
        for _, g in df.groupby("stem"):
            cut = np.percentile(g.displacement_ratio, within)
            values = g.loc[g.displacement_ratio >= cut, "axis_ratio"]
            pools.append(values.replace([np.inf, -np.inf], np.nan).dropna().to_numpy())
        return np.concatenate(pools) if pools else np.array([])

    move_axis = stroke_axis_ratios(move)
    diag_axis = stroke_axis_ratios(diagonal)
    axis_th, axis_gap = None, float("nan")
    axis_p5 = axis_p95 = None
    if move_axis.size and diag_axis.size:
        axis_p5 = float(np.percentile(move_axis, pos_pct))
        axis_p95 = float(np.percentile(diag_axis, neg_pct))
        axis_th, axis_gap = gap_threshold(axis_p5, axis_p95, margin)
        axis_source = (f"MOVE 획 구간 주축비 p{pos_pct}={axis_p5:.2f} / "
                       f"NEG_diagonal 획 구간 주축비 p{neg_pct}={axis_p95:.2f} "
                       f"(틈={axis_gap:.2f})")
        if axis_th is None:
            unresolved("movement.axis_dominance_ratio",
                       f"MOVE p{pos_pct}={axis_p5:.2f}가 NEG_diagonal p{neg_pct}="
                       f"{axis_p95:.2f}보다 낮다(겹침 {-axis_gap:.2f}).")
    else:
        axis_source = "비교할 윈도우가 없다"
        unresolved("movement.axis_dominance_ratio", axis_source)

    # 5) 축→방향 대응표. 왕복 운동은 양방향이 같은 횟수로 나오므로 다수결로는
    #    좌/우를 가릴 수 없다. 각 영상의 '첫 획' 방향을 모아 만장일치를 확인한다.
    direction_map = {}
    direction_detail = {}
    for action in MOVE_ACTIONS:
        votes = []
        for p in usable:
            if p["action"] != action:
                continue
            sign = F.first_stroke_sign(p["centers"], p["scales"], p["axis"],
                                       policy["first_stroke_fraction"])
            if sign:
                votes.append((("x" if p["axis"] == 0 else "y"), sign))
        if not votes:
            unresolved(f"movement.direction_map.{action}",
                       "쓸 수 있는 영상이 없어 방향을 정하지 못했다")
            continue
        (axis, sign), agree = Counter(votes).most_common(1)[0]
        direction_map[action] = [axis, int(sign)]
        direction_detail[action] = {"axis": axis, "sign": int(sign),
                                    "clips": len(votes), "agree": agree}
        if agree < len(votes):
            unresolved(f"movement.direction_map.{action}",
                       f"영상 {len(votes)}개 중 {agree}개만 같은 방향을 가리킨다")

    collisions = defaultdict(list)
    for action, (axis, sign) in direction_map.items():
        collisions[(axis, sign)].append(action)
    for key, actions in collisions.items():
        if len(actions) > 1:
            unresolved("movement.direction_map",
                       f"{actions}가 같은 축/부호 {key}로 관측됐다. 서로 구분할 수 없다.")

    excluded_note = (
        f"NEG_diagonal 최대 축비 {ceiling:.2f} 이하이거나 기대 축과 다른 MOVE 영상 "
        f"{len(rejected)}개 제외: "
        + ", ".join(f"{r['stem']}(축비 {r['axis_ratio']}, 관측 {r['observed_axis']}축)"
                    for r in rejected)) if rejected else "제외한 영상 없음"

    movement = {
        "window_ms": int(window_ms),
        "min_displacement_ratio": round(min_disp, 3) if min_disp is not None else None,
        "axis_dominance_ratio": round(axis_th, 3) if axis_th is not None else None,
        "max_duration_ms": max_duration_ms,
        "direction_map": direction_map,
        "_source": {
            "window_ms": (f"MOVE 영상 획 1회 소요시간(주축 궤적의 평균선 교차 횟수로 측정) "
                          f"p{policy['stroke_window_percentile']}={fastest:.0f}ms에 가장 "
                          f"가까운 격자값. 가장 빠른 획 안에 윈도우가 들어가야 한다."),
            "min_displacement_ratio": disp_source,
            "axis_dominance_ratio": axis_source,
            "max_duration_ms": (f"획 1회 소요시간 p{policy['stroke_timeout_percentile']}="
                                f"{slowest:.0f}ms ({durations.size}개 영상, "
                                f"{step}ms 단위 올림)"),
            "direction_map": ("각 영상의 첫 획 방향: " + ", ".join(
                f"{a}->{d['axis']}{d['sign']:+d}({d['agree']}/{d['clips']}영상 일치)"
                for a, d in direction_detail.items())),
            "excluded_clips": excluded_note,
        },
    }
    detail = {
        "rejected": rejected, "diagonal_ceiling": ceiling,
        "stroke_ms": {"p5": float(np.percentile(durations, 5)),
                      "p50": float(np.percentile(durations, 50)),
                      "p95": float(np.percentile(durations, 95))},
        "move_p5": move_p5, "shake_p95": shake_p95,
        "axis": {"move_p5": axis_p5, "diagonal_p95": axis_p95},
        "direction": direction_detail,
    }
    return movement, detail


# ------------------------------------------------------------------ 추적/타이밍


def derive_tracking(frames: pd.DataFrame, policy) -> tuple[dict, dict]:
    """중간 끊김은 견디고, 손이 실제로 사라지는 건 잡아내는 지점.

    영상 앞뒤의 미검출은 손이 아직 화면에 들어오지 않았거나 이미 나간 구간이다.
    실시간에서는 WAIT_HAND / 종료가 담당하므로 max_lost_frames의 근거가 아니다.
    첫 검출과 마지막 검출 '사이'의 끊김만 센다.
    """
    positive_gaps: list[int] = []
    for stem, grp in frames[~frames.action.str.startswith("NEG_")].groupby("stem"):
        positive_gaps += F.interior_gap_lengths(grp.sort_values("frame").valid.to_numpy())
    exit_gaps: list[int] = []
    for stem, grp in frames[frames.action == "NEG_exit"].groupby("stem"):
        exit_gaps += F.interior_gap_lengths(grp.sort_values("frame").valid.to_numpy())

    pos_p95 = (float(np.percentile(positive_gaps, policy["negative_percentile"]))
               if positive_gaps else 0.0)
    exit_p5 = (float(np.percentile(exit_gaps, policy["positive_percentile"]))
               if exit_gaps else float("inf"))

    max_lost, gap = gap_threshold(exit_p5, pos_p95, policy["separation_margin_ratio"])
    lost_source = (f"정상 영상 중간 끊김 p{policy['negative_percentile']}={pos_p95:.1f}프레임 "
                   f"({len(positive_gaps)}건) / NEG_exit 중간 끊김 "
                   f"p{policy['positive_percentile']}={exit_p5:.1f}프레임 "
                   f"({len(exit_gaps)}건, 틈={gap:.1f}프레임)")
    if max_lost is None:
        unresolved("tracking.max_lost_frames",
                   f"정상 영상 끊김 p{policy['negative_percentile']}={pos_p95:.1f}가 "
                   f"NEG_exit 끊김 p{policy['positive_percentile']}={exit_p5:.1f} 이상이다. "
                   "일시적 끊김과 손이 사라진 것을 가를 수 없다.")
        max_lost_frames = None
    else:
        max_lost_frames = max(int(round(max_lost)), 1)

    scores = frames.loc[~frames.action.str.startswith("NEG_") & frames.valid,
                        "detection_score"].to_numpy()
    min_score = (float(np.percentile(scores, policy["positive_percentile"]))
                 if scores.size else None)

    tracking = {
        "max_lost_frames": max_lost_frames,
        "min_detection_score": round(min_score, 3) if min_score is not None else None,
        "_source": {
            "max_lost_frames": lost_source,
            "min_detection_score": (
                f"정상 영상 검출 프레임 detection_score "
                f"p{policy['positive_percentile']}={min_score:.3f} ({scores.size}프레임)"
                if min_score is not None else "데이터 없음"),
        },
    }
    return tracking, {"positive_p95": pos_p95, "exit_p5": exit_p5,
                      "positive_gaps": len(positive_gaps), "exit_gaps": len(exit_gaps)}


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
    escape_frames, escape_source = None, "임계값 미정으로 계산하지 못함"
    labels = None
    confidence_margin = None
    confidence_min, confidence_min_source = None, "임계값 미정으로 계산하지 못함"
    if others_th is not None:
        labels = label_frames(frames, space, thumb_th, others_th)
        shape_targets = evaluate_shape_targets(frames, labels)
        shape_targets.to_csv(report_dir / "shape_label_distribution.csv",
                             index=False, encoding="utf-8-sig")
        hold_frames, hold_source = derive_hold_frames(frames, labels, policy)
        escape_frames, escape_source = derive_escape_frames(frames, labels, policy)
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
        "escape_frames": escape_frames,
        "_source_escape_frames": escape_source,
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

    print(f"  신뢰도 하한 = {confidence_min}, "
          f"이전 모양 이탈 = {escape_frames}프레임")

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
