"""실시간 세션 집계 — 어느 관문이 병목인지, 파일럿과 실사용 사이에 갭이 있는지.

    python scripts/06_analyze_sessions.py [--csv 경로] [--participant P01]

파일럿 영상은 폰을 거치하고 의식적으로 반듯하게 찍은 것이라 실시간 사용 조건과
다를 수 있다. 이 스크립트는 **같은 계산식**으로 두 쪽을 재서 그 갭이 실제로
있는지 숫자로 보여준다. 임계값을 바꾸지는 않는다.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

import _bootstrap  # noqa: F401

from core import features as F  # noqa: E402
from core.landmark_io import HERE, load_all_clips, load_json, load_paths  # noqa: E402
from core.naming import MOVE_ACTIONS  # noqa: E402

PCTS = (5, 25, 50, 75, 95)


def load_sessions(csv_path: Path, participant: str | None) -> pd.DataFrame:
    sessions = pd.read_csv(csv_path)
    if participant:
        sessions = sessions[sessions["participant"] == participant]
    return sessions


def report_versions(sessions: pd.DataFrame) -> None:
    """규칙 버전별로 갈라서 본다. 변경 전후 비교가 이 표에서 시작된다."""
    if "rule_version" not in sessions.columns:
        print("[주의] rule_version 칼럼이 없는 옛 기록이다. 버전별 비교는 건너뛴다.")
        return
    print(chr(10) + "=" * 74)
    print("규칙 버전별 결과")
    print("=" * 74)
    print(f"{'rule_version':<32}{'escape':>7}{'시도':>6}{'통과':>6}{'통과율':>8}")
    for version, group in sessions.groupby(sessions["rule_version"].fillna("(없음)")):
        passed = int((group["result"] == "PASS").sum())
        escape = group["escape_frames"].dropna()
        escape_text = f"{escape.iloc[0]:.0f}" if len(escape) else "-"
        print(f"{str(version):<32}{escape_text:>7}{len(group):>6}{passed:>6}"
              f"{passed / len(group) * 100:>7.1f}%")


def report_outcomes(sessions: pd.DataFrame) -> None:
    total = len(sessions)
    passed = int((sessions["result"] == "PASS").sum())
    print("=" * 74)
    print(f"세션 {total}회, 통과 {passed}회 ({passed / total * 100:.1f}%)"
          if total else "세션 없음")
    print("=" * 74)
    if not total:
        return

    failures = sessions[sessions["result"] == "FAIL"]
    if failures.empty:
        print("실패 없음")
        return

    print(f"\n{'실패 사유':<20}{'횟수':>6}{'비중':>8}   막힌 단계")
    for reason, group in sorted(failures.groupby("fail_reason"),
                                key=lambda kv: -len(kv[1])):
        steps = []
        for i in (1, 2, 3):
            blocked = group[f"passed_{i}"] == 0
            if i > 1:
                blocked &= group[f"passed_{i - 1}"] == 1
            count = int(blocked.sum())
            if count:
                steps.append(f"{i}단계 {count}회")
        print(f"{reason:<20}{len(group):>6}{len(group) / total * 100:>7.1f}%   "
              f"{', '.join(steps)}")

    print(f"\n{'요청 동작':<16}{'등장':>6}{'통과':>6}{'통과율':>8}")
    for i in (1, 2, 3):
        pass
    counts: dict[str, list[int]] = {}
    for i in (1, 2, 3):
        for action, group in sessions.groupby(f"action_{i}"):
            entry = counts.setdefault(action, [0, 0])
            entry[0] += len(group)
            entry[1] += int((group[f"passed_{i}"] == 1).sum())
    for action, (seen, ok) in sorted(counts.items(), key=lambda kv: kv[1][1] / max(kv[1][0], 1)):
        print(f"{action:<16}{seen:>6}{ok:>6}{ok / seen * 100:>7.1f}%")


def report_move_gates(sessions: pd.DataFrame) -> pd.DataFrame:
    moves = sessions[sessions["move_windows"].notna() & (sessions["move_windows"] > 0)]
    print("\n" + "=" * 74)
    print("이동 단계 관문 분석")
    print("=" * 74)
    if moves.empty:
        print("이동 단계 기록이 없다. run_challenge.py를 최신 버전으로 다시 돌릴 것.")
        return moves

    thresholds = moves[["move_min_disp_threshold", "move_axis_threshold",
                        "move_window_ms"]].drop_duplicates()
    print("기록 당시 임계값:")
    for _, row in thresholds.iterrows():
        print(f"  min_displacement_ratio={row['move_min_disp_threshold']}  "
              f"axis_dominance_ratio={row['move_axis_threshold']}  "
              f"window_ms={row['move_window_ms']}")

    windows = moves["move_windows"].sum()
    disp_pass = moves["move_disp_pass"].sum()
    axis_pass = moves["move_axis_pass"].sum()
    print(f"\n평가된 윈도우 {int(windows)}개")
    print(f"  1번 관문(변위 크기) 통과 {int(disp_pass)}개 "
          f"({disp_pass / windows * 100:.1f}%)")
    print(f"  2번 관문(주축 지배) 통과 {int(axis_pass)}개 "
          f"({axis_pass / windows * 100:.1f}%, "
          f"1번 통과분의 {axis_pass / disp_pass * 100:.1f}%)"
          if disp_pass else "  2번 관문: 1번을 통과한 윈도우가 없음")

    blocked_at_1 = int((moves["move_disp_pass"] == 0).sum())
    blocked_at_2 = int(((moves["move_disp_pass"] > 0) & (moves["move_axis_pass"] == 0)).sum())
    reached = int((moves["move_axis_pass"] > 0).sum())
    print(f"\n시도 {len(moves)}회 기준 병목:")
    print(f"  1번 관문에서 한 번도 못 넘음: {blocked_at_1}회")
    print(f"  1번은 넘었지만 2번에서 막힘:  {blocked_at_2}회")
    print(f"  두 관문 모두 통과한 적 있음:  {reached}회 "
          f"(그중 단계 통과 {int((moves['move_passed'] == 1).sum())}회)")

    print(f"\n{'요청':<12}{'시도':>5}{'통과':>5}{'최대 변위비':>12}{'최대 주축비':>12}{'주축':>6}")
    for action, group in moves.groupby("move_action"):
        print(f"{action:<12}{len(group):>5}"
              f"{int((group['move_passed'] == 1).sum()):>5}"
              f"{group['move_max_disp_ratio'].median():>12.3f}"
              f"{group['move_max_axis_ratio'].median():>12.2f}"
              f"{group['move_dominant_axis'].mode().iat[0] if len(group['move_dominant_axis'].mode()) else '-':>6}")
    return moves


def pilot_move_maxima(config: dict, policy: dict) -> pd.DataFrame:
    """파일럿 영상에서 실시간과 **같은 방식**으로 잰 최대 변위비/주축비.

    실시간은 각 시도에서 윈도우별 최대치를 남긴다. 비교가 성립하려면 파일럿도
    영상별 최대치를 같은 윈도우 길이로 재야 한다.
    """
    paths = load_paths()
    clips = load_all_clips(paths["landmark_cache"], paths.get("mirror_flip") or {})
    window_ms = float(config["movement"]["window_ms"])
    trim = int(policy["motion_edge_trim_windows"])

    rows = []
    for clip in clips:
        if clip.meta.action not in MOVE_ACTIONS:
            continue
        centers, scales = F.frame_palm_tracks(clip)
        wf = max(int(round(window_ms / 1000.0 * clip.fps)), 2)
        start, stop = F.stable_span(np.isfinite(scales), wf * trim)
        motions = [m for m in F.sliding_window_motions(centers[start:stop],
                                                       scales[start:stop], wf)
                   if m.valid]
        if not motions:
            continue
        min_disp = float(config["movement"]["min_displacement_ratio"])
        disps = [m.displacement_ratio for m in motions]
        # 실시간과 같은 규칙: 주축비는 변위 관문을 통과한 윈도우에서만 모은다.
        axes = [m.axis_ratio for m in motions
                if m.displacement_ratio >= min_disp and np.isfinite(m.axis_ratio)]
        rows.append({"stem": clip.meta.stem, "action": clip.meta.action,
                     "condition": clip.meta.condition or "none",
                     "max_disp_ratio": float(np.max(disps)),
                     "med_disp_ratio": float(np.median(disps)),
                     "max_axis_ratio": float(np.max(axes)) if axes else np.nan,
                     "med_axis_ratio": float(np.median(axes)) if axes else np.nan})
    return pd.DataFrame(rows)


def report_gap(moves: pd.DataFrame, pilot: pd.DataFrame, config: dict) -> None:
    print("\n" + "=" * 74)
    print("파일럿 촬영 vs 실시간 사용 — 같은 계산식으로 잰 최대치 비교")
    print("=" * 74)
    if moves.empty or pilot.empty:
        print("비교할 데이터가 부족하다.")
        return

    min_disp = config["movement"]["min_displacement_ratio"]
    axis_min = config["movement"]["axis_dominance_ratio"]

    def describe(values, label, threshold):
        arr = np.asarray(pd.to_numeric(values, errors="coerce"), dtype=float)
        arr = arr[np.isfinite(arr)]
        if arr.size == 0:
            print(f"  {label:<14} 데이터 없음")
            return
        qs = np.percentile(arr, PCTS)
        below = float((arr < threshold).mean() * 100.0)
        print(f"  {label:<14} n={arr.size:<4}"
              + "".join(f" p{p}={q:8.3f}" for p, q in zip(PCTS, qs))
              + f"   임계값 미만 {below:.0f}%")

    print(f"\n[정규화 변위] 임계값 min_displacement_ratio={min_disp}")
    describe(pilot["max_disp_ratio"], "파일럿 최대", min_disp)
    describe(moves["move_max_disp_ratio"], "실시간 최대", min_disp)
    describe(pilot["med_disp_ratio"], "파일럿 중앙", min_disp)
    describe(moves["move_med_disp_ratio"], "실시간 중앙", min_disp)

    print(f"\n[주축비 — 변위 관문을 통과한 윈도우만] "
          f"임계값 axis_dominance_ratio={axis_min}")
    print("  최대치는 부축 변위가 0에 가까운 윈도우 하나에 좌우되므로 "
          "중앙값을 같이 본다.")
    describe(pilot["max_axis_ratio"], "파일럿 최대", axis_min)
    describe(moves["move_max_axis_ratio"], "실시간 최대", axis_min)
    describe(pilot["med_axis_ratio"], "파일럿 중앙", axis_min)
    describe(moves["move_med_axis_ratio"], "실시간 중앙", axis_min)

    print("\n[방향별 비교 — 각 그룹의 중앙값]")
    header = (f"  {'동작':<12}{'변위 파일럿':>12}{'변위 실시간':>12}{'비율':>8}"
              f"{'주축 파일럿':>12}{'주축 실시간':>12}{'비율':>8}")
    print(header)
    for action in MOVE_ACTIONS:
        pilot_rows = pilot[pilot["action"] == action]
        live_rows = moves[moves["move_action"] == action]

        def pair(pilot_col, live_col):
            p = pd.to_numeric(pilot_rows[pilot_col], errors="coerce").dropna()
            r = pd.to_numeric(live_rows[live_col], errors="coerce").dropna()
            if p.empty or r.empty:
                return "-", "-", "-"
            return (f"{p.median():.3f}", f"{r.median():.3f}",
                    f"{r.median() / p.median():.2f}x")

        d = pair("max_disp_ratio", "move_max_disp_ratio")
        a = pair("med_axis_ratio", "move_med_axis_ratio")
        print(f"  {action:<12}{d[0]:>12}{d[1]:>12}{d[2]:>8}"
              f"{a[0]:>12}{a[1]:>12}{a[2]:>8}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=None, help="results.csv 경로")
    ap.add_argument("--participant", default=None)
    ap.add_argument("--rule-version", default=None,
                    help="특정 규칙 버전만 집계 (변경 전후 비교용)")
    args = ap.parse_args()

    paths = load_paths()
    config = load_json(HERE / "configs" / "challenge_config.json")
    policy = load_json(HERE / "configs" / "derivation_policy.json")

    csv_path = Path(args.csv) if args.csv else Path(paths["session_out"]) / "results.csv"
    if not csv_path.exists():
        print(f"세션 기록이 없다: {csv_path}", file=sys.stderr)
        print("run_challenge.py를 먼저 돌릴 것.", file=sys.stderr)
        return 1

    sessions = load_sessions(csv_path, args.participant)
    if args.rule_version and "rule_version" in sessions.columns:
        sessions = sessions[sessions["rule_version"] == args.rule_version]
    if sessions.empty:
        print("조건에 맞는 세션이 없다.", file=sys.stderr)
        return 1

    report_versions(sessions)
    report_outcomes(sessions)
    moves = report_move_gates(sessions)
    if not moves.empty:
        report_gap(moves, pilot_move_maxima(config, policy), config)

    out = Path(paths["report_out"]) / "session_summary.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    sessions.to_csv(out, index=False, encoding="utf-8-sig")
    print(f"\n집계에 쓴 세션: {csv_path}\n요약 복사본: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
